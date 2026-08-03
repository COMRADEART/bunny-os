# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""CPU topology, instruction sets, imposed quota and current load."""

from __future__ import annotations

import os
from pathlib import Path
import re

from ..model import CpuFacts, absent, measured, unknown
from .sources import Deadline, iter_directory, read_first_line, read_int, read_text, sanitize

__all__ = ["INTERESTING_FLAGS", "probe", "quota_cores"]

#: Flags that change what Bunny OS can run, not every flag the CPU reports.
#: Recording all 200-odd x86 flags would make the inventory a fingerprint, and
#: §14 requires that it not become one. These are the ones a scoring or
#: implementation-selection decision actually reads.
INTERESTING_FLAGS = frozenset({
    # x86_64
    "sse4_2", "avx", "avx2", "avx512f", "avx512bw", "avx512vnni", "amx_bf16", "amx_int8",
    "aes", "fma", "f16c", "vmx", "svm",
    # aarch64
    "asimd", "asimdhp", "asimddp", "sve", "sve2", "i8mm", "bf16", "aes",
})

_VENDOR_KEYS = ("vendor_id", "CPU implementer")
_MODEL_KEYS = ("model name", "Model", "Processor", "CPU part")
_FLAG_KEYS = ("flags", "Features")


def _cpuinfo_fields(text: str) -> tuple[dict[str, str], set[str], int]:
    """Parse ``/proc/cpuinfo`` into first-seen scalars, flags and a core count.

    Physical cores are counted as distinct ``(physical id, core id)`` pairs.
    On ARM, where those keys are usually absent, the caller falls back to the
    sysfs topology and then to the logical count.
    """
    scalars: dict[str, str] = {}
    flags: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    physical_id = ""
    core_id = ""
    for line in text.splitlines():
        if ":" not in line:
            if physical_id or core_id:
                pairs.add((physical_id, core_id))
            physical_id = core_id = ""
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        value = raw.strip()
        if key in _FLAG_KEYS:
            flags.update(value.split())
        elif key == "physical id":
            physical_id = value
        elif key == "core id":
            core_id = value
        elif key not in scalars:
            scalars[key] = value
    if physical_id or core_id:
        pairs.add((physical_id, core_id))
    return scalars, flags, len(pairs)


def _sysfs_physical_cores() -> int:
    """Distinct core identities from ``/sys/devices/system/cpu/*/topology``."""
    identities: set[tuple[int, int]] = set()
    for entry in iter_directory("/sys/devices/system/cpu", limit=4096):
        if not re.fullmatch(r"cpu\d+", entry.name):
            continue
        package = read_int(entry / "topology/physical_package_id")
        core = read_int(entry / "topology/core_id")
        if package is not None and core is not None:
            identities.add((package, core))
    return len(identities)


def _logical_threads() -> int | None:
    """Threads this process may actually be scheduled on.

    ``sched_getaffinity`` rather than ``cpu_count`` because a systemd unit with
    ``CPUAffinity=`` or a container pinned to two CPUs on a 96-thread host has
    two threads available to it, and budgeting against 96 would oversubscribe
    the machine by a factor of 48.
    """
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count()


def quota_cores() -> tuple[float | None, str]:
    """Fractional cores permitted by the cgroup, and where that came from.

    cgroup v2 states this as ``"<quota> <period>"`` in ``cpu.max``, with the
    literal ``max`` meaning unrestricted. v1 splits it across two files and
    signals unrestricted with ``-1``. Both are read because Bunny OS images use
    v2 while a container on someone else's host may still be v1.
    """
    text = read_first_line("/sys/fs/cgroup/cpu.max")
    if text:
        parts = text.split()
        if parts and parts[0] == "max":
            return None, "cgroup2 cpu.max unrestricted"
        if len(parts) == 2:
            try:
                quota, period = int(parts[0]), int(parts[1])
            except ValueError:
                return None, "cgroup2 cpu.max unparseable"
            if quota > 0 and period > 0:
                return quota / period, "cgroup2 cpu.max"

    quota = read_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period = read_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota is not None and period:
        if quota < 0:
            return None, "cgroup1 cfs quota unrestricted"
        if quota > 0 and period > 0:
            return quota / period, "cgroup1 cfs quota"
    return None, "no cgroup cpu quota observed"


def _frequency_capped() -> tuple[bool | None, str]:
    """Whether the frequency *policy* is currently capped below the hardware max.

    This deliberately compares ``scaling_max_freq`` against ``cpuinfo_max_freq``
    rather than comparing the current frequency against the maximum. A CPU
    sitting at 800 MHz because nothing is running is idle, not throttled, and a
    probe that confused the two would report constant thermal distress on a
    healthy laptop. A reduced *ceiling*, by contrast, is a live constraint:
    firmware, a thermal daemon or a power profile has taken headroom away.
    """
    policy = Path("/sys/devices/system/cpu/cpu0/cpufreq")
    hardware_max = read_int(policy / "cpuinfo_max_freq")
    scaling_max = read_int(policy / "scaling_max_freq")
    if hardware_max is None or scaling_max is None or hardware_max <= 0:
        return None, "cpufreq policy not exposed"
    capped = scaling_max < int(hardware_max * 0.95)
    return capped, f"scaling_max_freq={scaling_max}kHz cpuinfo_max_freq={hardware_max}kHz"


def probe(deadline: Deadline) -> CpuFacts:
    text = read_text("/proc/cpuinfo", limit=256 * 1024)
    scalars: dict[str, str] = {}
    flags: set[str] = set()
    cpuinfo_cores = 0
    if text:
        scalars, flags, cpuinfo_cores = _cpuinfo_fields(text)

    vendor = unknown("/proc/cpuinfo")
    for key in _VENDOR_KEYS:
        if key in scalars:
            vendor = measured(sanitize(scalars[key], limit=32), "/proc/cpuinfo")
            break

    model = unknown("/proc/cpuinfo")
    for key in _MODEL_KEYS:
        if key in scalars:
            model = measured(sanitize(scalars[key], limit=96), "/proc/cpuinfo")
            break

    threads = _logical_threads()
    logical = measured(threads, "sched_getaffinity") if threads else unknown("sched_getaffinity")

    physical_count = cpuinfo_cores or _sysfs_physical_cores()
    if physical_count:
        physical = measured(physical_count, "/proc/cpuinfo" if cpuinfo_cores else "sysfs topology")
    elif threads:
        # Not a measurement of physical cores. Reported as unknown with the
        # reason, so a consumer that needs true core count does not read a
        # thread count that happens to look plausible.
        physical = unknown("sysfs topology", "topology not exposed; only logical threads are known")
    else:
        physical = unknown("sysfs topology")

    if text:
        selected = sorted(flags.intersection(INTERESTING_FLAGS))
        instruction_sets = measured(selected, "/proc/cpuinfo")
        virtualization = measured(bool(flags.intersection({"vmx", "svm"})), "/proc/cpuinfo")
    else:
        instruction_sets = unknown("/proc/cpuinfo", "unreadable")
        virtualization = unknown("/proc/cpuinfo", "unreadable")

    max_khz = read_int("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    if max_khz and max_khz > 0:
        frequency = measured(max_khz * 1000, "cpufreq/cpuinfo_max_freq")
    else:
        frequency = absent("cpufreq", "no cpufreq driver; frequency is not exposed")

    cores, quota_source = quota_cores()
    quota = measured(cores, "cgroup", quota_source) if cores is not None else absent("cgroup", quota_source)

    load_line = read_first_line("/proc/loadavg")
    load = unknown("/proc/loadavg")
    if load_line:
        try:
            load = measured(float(load_line.split()[0]), "/proc/loadavg")
        except (IndexError, ValueError):
            load = unknown("/proc/loadavg", "unparseable")

    capped, capped_detail = _frequency_capped()
    throttled = (
        measured(capped, "cpufreq", capped_detail) if capped is not None else absent("cpufreq", capped_detail)
    )

    return CpuFacts(
        vendor=vendor,
        model=model,
        physical_cores=physical,
        logical_threads=logical,
        instruction_sets=instruction_sets,
        max_frequency_hz=frequency,
        virtualization_supported=virtualization,
        quota_cores=quota,
        load_average_1m=load,
        frequency_throttled=throttled,
    )
