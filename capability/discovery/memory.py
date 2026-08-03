# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Memory capacity, availability, cgroup ceilings, pressure and reservation."""

from __future__ import annotations

from ..model import MemoryFacts, absent, measured, unknown
from .sources import Deadline, read_first_line, read_int, read_text

__all__ = ["cgroup_limit", "meminfo", "probe"]

#: cgroup v1 spells "no limit" as a number close to 2**63. Anything at or above
#: this is a sentinel, not a ceiling, and treating it as one would tell the
#: budget engine the machine has eight exabytes of RAM.
_V1_UNLIMITED = 1 << 62


def meminfo() -> dict[str, int]:
    """``/proc/meminfo`` as bytes, keyed by its own field names."""
    text = read_text("/proc/meminfo", limit=64 * 1024)
    if text is None:
        return {}
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, raw = line.partition(":")
        parts = raw.split()
        if not parts or not parts[0].isdigit():
            continue
        amount = int(parts[0])
        # Every numeric field in /proc/meminfo is in kB except the HugePages_*
        # counters, which are counts. Only the kB-suffixed fields are converted.
        values[key.strip()] = amount * 1024 if len(parts) > 1 and parts[1] == "kB" else amount
    return values


def cgroup_limit() -> tuple[int | None, str]:
    """The memory ceiling this process is actually held to, if any.

    This is the single most important number in the whole inventory on a
    constrained deployment. A 512 MB container on a 256 GB host has 512 MB, and
    a budget engine that reads ``MemTotal`` will size a service for the host and
    watch the kernel kill it.
    """
    text = read_first_line("/sys/fs/cgroup/memory.max")
    if text:
        if text == "max":
            return None, "cgroup2 memory.max unrestricted"
        try:
            value = int(text)
        except ValueError:
            return None, "cgroup2 memory.max unparseable"
        if value > 0:
            return value, "cgroup2 memory.max"

    value = read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if value is not None:
        if value >= _V1_UNLIMITED:
            return None, "cgroup1 memory.limit_in_bytes unrestricted"
        if value > 0:
            return value, "cgroup1 memory.limit_in_bytes"
    return None, "no cgroup memory limit observed"


def _cgroup_usage() -> tuple[int | None, str]:
    value = read_int("/sys/fs/cgroup/memory.current")
    if value is not None and value >= 0:
        return value, "cgroup2 memory.current"
    value = read_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if value is not None and value >= 0:
        return value, "cgroup1 memory.usage_in_bytes"
    return None, "no cgroup memory usage observed"


def pressure(resource: str) -> tuple[float | None, str]:
    """The ``some avg10`` share from a PSI file, as a percentage 0..100.

    PSI is the honest signal for "is this machine in trouble right now".
    Free-memory headroom is not: a machine can have gigabytes free and still be
    stalling on reclaim, and can have almost nothing free and be perfectly
    healthy because the page cache is doing its job.
    """
    text = read_text(f"/proc/pressure/{resource}", limit=4096)
    if text is None:
        return None, f"/proc/pressure/{resource} unavailable"
    for line in text.splitlines():
        if not line.startswith("some "):
            continue
        for field in line.split():
            name, _, raw = field.partition("=")
            if name == "avg10":
                try:
                    return float(raw), f"/proc/pressure/{resource}"
                except ValueError:
                    return None, f"/proc/pressure/{resource} unparseable"
    return None, f"/proc/pressure/{resource} has no 'some' line"


def _reserved_bytes(values: dict[str, int]) -> tuple[int | None, str]:
    """Firmware/kernel-reserved RAM that userspace will never see.

    Read from ``/proc/iomem``, which an unprivileged reader gets as all-zero
    ranges. That zeroing is detected and reported as unknown rather than as
    "nothing is reserved", because on the small ARM boards this subsystem has to
    serve, reserved carve-outs are a large share of installed RAM and claiming
    zero would overstate what is available.
    """
    text = read_text("/proc/iomem", limit=256 * 1024)
    if text is None:
        return None, "/proc/iomem unavailable"
    total = 0
    nonzero_seen = False
    for line in text.splitlines():
        span, _, label = line.partition(":")
        start_text, _, end_text = span.strip().partition("-")
        try:
            start = int(start_text, 16)
            end = int(end_text, 16)
        except ValueError:
            continue
        if end > 0:
            nonzero_seen = True
        if label.strip().lower() == "reserved":
            total += end - start + 1
    if not nonzero_seen:
        return None, "/proc/iomem is zeroed for unprivileged readers"
    return total, "/proc/iomem reserved ranges"


def probe(deadline: Deadline) -> MemoryFacts:
    values = meminfo()

    if "MemTotal" in values:
        physical = measured(values["MemTotal"], "/proc/meminfo MemTotal")
    else:
        physical = unknown("/proc/meminfo", "unreadable")

    if "MemAvailable" in values:
        available = measured(values["MemAvailable"], "/proc/meminfo MemAvailable")
    elif "MemFree" in values:
        # Older kernels lack MemAvailable. MemFree understates what is reclaimable
        # and is recorded as such rather than presented as an equivalent.
        available = measured(values["MemFree"], "/proc/meminfo MemFree", "MemAvailable absent; MemFree understates reclaimable memory")
    else:
        available = unknown("/proc/meminfo", "unreadable")

    limit, limit_source = cgroup_limit()
    cgroup_limit_observation = (
        measured(limit, "cgroup", limit_source) if limit is not None else absent("cgroup", limit_source)
    )

    usage, usage_source = _cgroup_usage()
    cgroup_usage_observation = (
        measured(usage, "cgroup", usage_source) if usage is not None else absent("cgroup", usage_source)
    )

    if "SwapTotal" in values:
        swap_total = measured(values["SwapTotal"], "/proc/meminfo SwapTotal")
        swap_free = measured(values.get("SwapFree", 0), "/proc/meminfo SwapFree")
    else:
        swap_total = unknown("/proc/meminfo")
        swap_free = unknown("/proc/meminfo")

    share, share_source = pressure("memory")
    pressure_observation = (
        measured(share, share_source) if share is not None else absent("psi", share_source)
    )

    reserved, reserved_source = _reserved_bytes(values)
    reserved_observation = (
        measured(reserved, "/proc/iomem", reserved_source)
        if reserved is not None
        else unknown("/proc/iomem", reserved_source)
    )

    return MemoryFacts(
        physical_bytes=physical,
        available_bytes=available,
        cgroup_limit_bytes=cgroup_limit_observation,
        cgroup_usage_bytes=cgroup_usage_observation,
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        pressure_some_avg10=pressure_observation,
        reserved_bytes=reserved_observation,
    )
