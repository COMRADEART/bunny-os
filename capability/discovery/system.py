# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Architecture, kernel, virtualization and containment."""

from __future__ import annotations

from pathlib import Path
import platform

from ..model import SystemFacts, absent, measured, unknown
from .sources import Deadline, read_text, run, sanitize

__all__ = ["ARCHITECTURES", "normalize_architecture", "probe"]

#: Architectures Bunny OS has an execution story for. Anything else is reported
#: verbatim rather than coerced, so a port shows up as an unrecognised value
#: instead of being silently mislabelled as one of these.
ARCHITECTURES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}

_CONTAINER_MARKERS = (
    ("/run/.containerenv", "podman"),
    ("/.dockerenv", "docker"),
)


def normalize_architecture(value: str) -> str:
    return ARCHITECTURES.get(value.lower(), value.lower())


def _containment() -> tuple[bool | None, str]:
    """Whether this is a container, and which runtime if it says so.

    Marker files first because they are free and unambiguous. ``/proc/1/cgroup``
    second, because a cgroup path naming a container runtime is strong evidence
    even when no marker file was mounted.
    """
    for path, runtime in _CONTAINER_MARKERS:
        if Path(path).exists():
            return True, runtime
    cgroup = read_text("/proc/1/cgroup", limit=8192)
    if cgroup is None:
        return None, ""
    lowered = cgroup.lower()
    for runtime in ("docker", "podman", "containerd", "lxc", "kubepods"):
        if runtime in lowered:
            return True, runtime
    # A readable /proc/1/cgroup with no container marker is evidence of *not* a
    # container, which is a measurement rather than an absence of one.
    return False, ""


def probe(deadline: Deadline) -> SystemFacts:
    machine = platform.machine()
    architecture = (
        measured(normalize_architecture(machine), "platform.machine")
        if machine
        else unknown("platform.machine", "empty")
    )

    release = platform.release()
    kernel = measured(sanitize(release, limit=64), "platform.release") if release else unknown("platform.release")

    contained, runtime = _containment()
    if contained is None:
        containerized = unknown("/proc/1/cgroup", "unreadable")
        container_runtime = unknown("/proc/1/cgroup")
    else:
        containerized = measured(contained, "/proc/1/cgroup")
        container_runtime = measured(runtime, "/proc/1/cgroup") if runtime else absent("/proc/1/cgroup")

    virtualized = unknown("systemd-detect-virt")
    result = run(["/usr/bin/systemd-detect-virt", "--vm", "--quiet"], deadline=deadline, timeout=1.0)
    if result.detail.startswith("exit status"):
        # systemd-detect-virt exits non-zero to mean "not virtualized", which is
        # a measurement, not a failure. Only a genuinely absent or timed-out
        # tool leaves this unknown.
        virtualized = measured(False, "systemd-detect-virt")
    elif result.ok:
        virtualized = measured(True, "systemd-detect-virt")
    else:
        cpuinfo = read_text("/proc/cpuinfo", limit=32 * 1024) or ""
        if "hypervisor" in cpuinfo:
            virtualized = measured(True, "/proc/cpuinfo", "hypervisor flag")
        elif cpuinfo:
            virtualized = measured(False, "/proc/cpuinfo", "no hypervisor flag")

    return SystemFacts(
        architecture=architecture,
        kernel_release=kernel,
        virtualized=virtualized,
        containerized=containerized,
        container_runtime=container_runtime,
        # Recorded as a boolean, never as the value. The boot id is a machine
        # identifier and §14 forbids collecting one; that it exists is enough to
        # tell a caller that this is a booted Linux system.
        boot_id_present=measured(Path("/proc/sys/kernel/random/boot_id").exists(), "/proc/sys/kernel"),
    )
