# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""GPUs and accelerators: presence, driver readiness, VRAM and runtimes.

The rule this module exists to enforce is that **a detected device is not a
usable device**. A PCI function with a vendor ID of ``0x10de`` proves an NVIDIA
card is bolted to the board. It does not prove a kernel driver bound to it,
that a render node was created, that anything can be opened without root, or
that CUDA is installed. Bunny OS has to distinguish these because starting a
GPU-backed renderer on a machine whose driver never loaded is a boot failure
that looks like a hardware fault.

So there are three separate things here, and they are never collapsed:

* **presence**   — the device exists (sysfs enumeration)
* **driver**     — a driver is bound and a render node exists
* **runtime**    — CUDA / ROCm / Vulkan / OpenCL can actually be used

``docs/phase-1/BUNNY_OS_PHASE_1.md`` §13.4 additionally requires that VRAM come
from vendor tools, never from a generic reported adapter memory field, which is
"a well-known wrong number". So VRAM is read from ``amdgpu``'s sysfs counters
and from ``nvidia-smi``, and is ``unknown`` when neither is available.
"""

from __future__ import annotations

from pathlib import Path
import re

from ..model import AcceleratorFacts, GpuFacts, Observation, absent, measured, unknown
from .sources import Deadline, iter_directory, read_first_line, read_int, sanitize, run, which_allowed

__all__ = ["PCI_VENDORS", "probe", "probe_accelerators"]

PCI_VENDORS = {
    "0x8086": "intel",
    "0x1002": "amd",
    "0x1022": "amd",
    "0x10de": "nvidia",
    "0x1af4": "virtio",
    "0x1234": "qemu",
    "0x15ad": "vmware",
    "0x1414": "microsoft",
}

#: Drivers whose devices share system memory rather than owning a VRAM pool.
#: For these, "no dedicated VRAM" is a fact about the design, so the field is
#: ``absent`` — meaning *known to have none* — rather than ``unknown``.
_SHARED_MEMORY_DRIVERS = frozenset({"i915", "xe", "v3d", "vc4", "panfrost", "lima", "msm", "etnaviv"})
_VIRTUAL_DRIVERS = frozenset({"virtio_gpu", "virtio-gpu", "vmwgfx", "qxl", "bochs-drm", "simpledrm", "hyperv_drm"})
_DISCRETE_DRIVERS = frozenset({"nvidia", "nouveau", "amdgpu", "radeon"})

#: A discrete part with less than this is almost certainly a display adapter
#: rather than a compute device. Used only to label ``kind``; it never gates
#: usability, which is decided by driver and runtime readiness.
_DISCRETE_VRAM_FLOOR = 512 * 1024 * 1024


def _render_nodes() -> set[str]:
    return {entry.name for entry in iter_directory("/dev/dri") if entry.name.startswith("renderD")}


def _card_render_node(device: Path, available: set[str]) -> str | None:
    """The render node belonging to this card, if one was created.

    Matched through the card's own ``device/drm`` directory rather than by index
    arithmetic, because card and render-node numbering diverge as soon as a
    display-only device is present.
    """
    for entry in iter_directory(device / "drm", limit=32):
        if entry.name.startswith("renderD") and entry.name in available:
            return entry.name
    return None


def _amd_vram(device: Path) -> tuple[Observation, Observation]:
    total = read_int(device / "mem_info_vram_total")
    used = read_int(device / "mem_info_vram_used")
    if total is None or total <= 0:
        return unknown("amdgpu sysfs"), unknown("amdgpu sysfs")
    total_observation = measured(total, "amdgpu mem_info_vram_total")
    if used is None or used < 0:
        return total_observation, unknown("amdgpu mem_info_vram_used")
    return total_observation, measured(max(0, total - used), "amdgpu mem_info_vram_used")


def _nvidia_smi(deadline: Deadline) -> dict[int, dict[str, int | str]]:
    """Per-index VRAM and driver facts from ``nvidia-smi``.

    Fixed query, CSV without headers or units, so the parse is positional and
    total. If the tool is missing, refuses, or times out, the caller is left
    with ``unknown`` VRAM — which is the correct outcome, since no other source
    for it is trustworthy.
    """
    if which_allowed("/usr/bin/nvidia-smi") is None:
        return {}
    result = run(
        [
            "/usr/bin/nvidia-smi",
            "--query-gpu=index,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ],
        deadline=deadline,
        timeout=3.0,
    )
    if not result.ok:
        return {}
    devices: dict[int, dict[str, int | str]] = {}
    for line in result.stdout.splitlines()[:64]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            index = int(parts[0])
            total_mib = int(parts[1])
            free_mib = int(parts[2])
        except ValueError:
            continue
        devices[index] = {
            "totalBytes": total_mib * 1024 * 1024,
            "freeBytes": free_mib * 1024 * 1024,
            "driverVersion": sanitize(parts[3], limit=32),
        }
    return devices


def _classify(driver: str, vram_total: Observation) -> Observation:
    if driver in _VIRTUAL_DRIVERS:
        return measured("virtual", "driver name")
    if driver in _SHARED_MEMORY_DRIVERS:
        return measured("integrated", "driver name")
    if driver in _DISCRETE_DRIVERS:
        total = vram_total.get(0)
        if isinstance(total, int) and total >= _DISCRETE_VRAM_FLOOR:
            return measured("discrete", "driver name and VRAM size")
        if vram_total.is_measured:
            return measured("integrated", "driver name with small VRAM pool")
        return measured("discrete", "driver name", "VRAM unknown; classification from driver alone")
    return unknown("driver name", f"driver {driver!r} is not in the classification table" if driver else "no driver bound")


def _runtimes(vendor: str, driver: str, deadline: Deadline, *, probe_runtimes: bool) -> dict[str, Observation]:
    """Whether each compute/graphics runtime is genuinely usable.

    Every entry answers the same question — *could work be submitted through
    this API right now* — and a `False` here is as informative as a `True`. A
    machine with an NVIDIA card and no ``/dev/nvidiactl`` gets
    ``cuda: measured(False)``, which is what stops a plan proposing local GPU
    inference on it.
    """
    values: dict[str, Observation] = {}

    if vendor == "nvidia":
        control = Path("/dev/nvidiactl").exists()
        smi = which_allowed("/usr/bin/nvidia-smi") is not None
        values["cuda"] = measured(
            control and smi,
            "/dev/nvidiactl and nvidia-smi",
            "device node and vendor tool both required",
        )
    else:
        values["cuda"] = absent("nvidia runtime", "not an NVIDIA device")

    if vendor == "amd":
        values["rocm"] = measured(
            Path("/dev/kfd").exists(),
            "/dev/kfd",
            "ROCm compute requires the KFD device node",
        )
    else:
        values["rocm"] = absent("rocm", "not an AMD device")

    if not probe_runtimes:
        values["vulkan"] = unknown("vulkaninfo", "runtime probing disabled for this pass")
        values["opencl"] = unknown("clinfo", "runtime probing disabled for this pass")
        return values

    if which_allowed("/usr/bin/vulkaninfo") is None:
        values["vulkan"] = unknown("vulkaninfo", "tool not installed; presence of a driver is not a Vulkan claim")
    else:
        result = run(["/usr/bin/vulkaninfo", "--summary"], deadline=deadline, timeout=3.0)
        values["vulkan"] = measured(result.ok, "vulkaninfo --summary", result.detail or "loader reported a device")

    if which_allowed("/usr/bin/clinfo") is None:
        values["opencl"] = unknown("clinfo", "tool not installed")
    else:
        result = run(["/usr/bin/clinfo", "--list"], deadline=deadline, timeout=3.0)
        values["opencl"] = measured(
            result.ok and bool(result.stdout.strip()),
            "clinfo --list",
            result.detail or "at least one platform enumerated",
        )

    return values


def probe(deadline: Deadline, *, probe_runtimes: bool = True) -> list[GpuFacts]:
    cards = [
        entry for entry in iter_directory("/sys/class/drm", limit=64)
        if re.fullmatch(r"card\d+", entry.name)
    ]
    if not cards:
        return []

    nvidia = _nvidia_smi(deadline)
    render_nodes = _render_nodes()
    devices: list[GpuFacts] = []

    for index, card in enumerate(cards):
        device = card / "device"
        vendor_id = (read_first_line(device / "vendor") or "").lower()
        vendor_name = PCI_VENDORS.get(vendor_id, "")
        device_id = (read_first_line(device / "device") or "").lower()

        driver_name = ""
        try:
            driver_name = (device / "driver").resolve(strict=True).name
        except OSError:
            pass

        render_node = _card_render_node(device, render_nodes)

        if vendor_name == "amd":
            vram_total, vram_available = _amd_vram(device)
        elif vendor_name == "nvidia" and index in nvidia:
            entry = nvidia[index]
            vram_total = measured(entry["totalBytes"], "nvidia-smi memory.total")
            vram_available = measured(entry["freeBytes"], "nvidia-smi memory.free")
        elif driver_name in _SHARED_MEMORY_DRIVERS:
            vram_total = absent("driver design", "shares system memory; there is no dedicated pool")
            vram_available = absent("driver design", "shares system memory; there is no dedicated pool")
        else:
            vram_total = unknown("vendor tools", "no trustworthy VRAM source; generic adapter memory is not read")
            vram_available = unknown("vendor tools")

        runtimes = _runtimes(vendor_name, driver_name, deadline, probe_runtimes=probe_runtimes)

        devices.append(GpuFacts(
            index=index,
            vendor=measured(vendor_name, "pci vendor id") if vendor_name else unknown("pci vendor id", f"unrecognised vendor {vendor_id!r}"),
            device_id=measured(sanitize(device_id, limit=16), "pci device id") if device_id else unknown("pci device id"),
            description=measured(f"{vendor_name or 'unknown'}:{device_id or 'unknown'}", "sysfs"),
            kind=_classify(driver_name, vram_total),
            driver=measured(sanitize(driver_name, limit=32), "sysfs driver link") if driver_name else absent("sysfs driver link", "no driver is bound to this device"),
            render_node=measured(render_node, "/dev/dri") if render_node else absent("/dev/dri", "no render node was created for this card"),
            vram_total_bytes=vram_total,
            vram_available_bytes=vram_available,
            runtimes=runtimes,
        ))

    return devices


def probe_accelerators(deadline: Deadline) -> list[AcceleratorFacts]:
    """Non-GPU accelerators: NPUs and anything on the kernel accel subsystem.

    Deliberately shallow. The kernel exposes these devices long before a usable
    userspace runtime exists for them, so presence is recorded and usability is
    reported as unknown rather than guessed. §13.4's amendment treats an NPU as
    a detectable accelerator, not as a substrate anything may be scheduled on.
    """
    found: list[AcceleratorFacts] = []
    for entry in iter_directory("/sys/class/accel", limit=32):
        driver = ""
        try:
            driver = (entry / "device/driver").resolve(strict=True).name
        except OSError:
            pass
        found.append(AcceleratorFacts(
            kind="npu" if "vpu" in driver or "npu" in driver else "accel",
            description=measured(sanitize(driver or entry.name, limit=48), "/sys/class/accel"),
            driver_ready=unknown(
                "/sys/class/accel",
                "device is bound, but no userspace runtime was probed; offload is not claimed",
            ),
        ))
    return found
