# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What this machine is, measured, with ``UNKNOWN`` as a first-class answer.

Every field here is either a number that was read from somewhere, or ``None``
meaning it could not be. There is no default, no "assume 8 GB", no
``vram or 4096``. That discipline costs a little at the call site — every
consumer has to handle ``None`` — and it buys the property the whole subsystem
rests on: a plan that says "estimated VRAM 2.1 GB" was computed from measured
inputs, and one that could not be is refused rather than guessed.

Capability is a tri-state for the same reason. ``bf16`` is not ``False`` when we
could not ask; it is ``UNKNOWN``, and :func:`~model_studio.hardware.precision.
select_precision` treats those two differently. Collapsing them loses exactly
the distinction that decides whether a run is safe.

Two independent views of the GPU, deliberately:

``accelerator``
    what the *training backend* can use. If torch is not installed, or is a CPU
    build, this is ``cpu`` — because that is what training would actually run
    on, whatever is in the machine.
``observed_gpus``
    what the *machine* has, from ``nvidia-smi`` and sysfs, asked without torch.

Keeping them apart is what lets the CLI say the true and useful thing: "this
machine has an RTX 4050 with 6 GB, and the installed torch is a CPU build, so
training would run on the CPU". One field could only have said one of those, and
whichever it said would have been the misleading half.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

__all__ = [
    "SUPPORTED",
    "UNKNOWN",
    "UNSUPPORTED",
    "Accelerator",
    "HardwareReport",
    "ObservedGpu",
    "cpu_accelerator",
    "probe_hardware",
]

#: Capability tri-state. ``UNKNOWN`` never resolves upward into ``SUPPORTED``.
SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"

#: PCI vendor identifiers, for the sysfs path where there is no vendor tool.
_PCI_VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}

#: "Not passed", which is not the same as "there is no torch". See
#: :func:`probe_hardware`.
_UNSET: Any = object()

#: The first compute capability with hardware bfloat16 (Ampere, sm_80). Used
#: only as a *fallback* when torch cannot be asked directly — the direct query
#: is always preferred, because it also accounts for the torch build and driver.
_BF16_MINIMUM_CAPABILITY = (8, 0)


@dataclass(frozen=True)
class ObservedGpu:
    """A GPU the machine has, seen without asking a training framework."""

    name: str
    vendor: str
    vram_bytes: int | None = None
    source: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vendor": self.vendor,
            "vramBytes": self.vram_bytes,
            "source": self.source,
        }


@dataclass(frozen=True)
class Accelerator:
    """The device the training backend would actually use."""

    kind: str = "cpu"
    name: str = "cpu"
    vendor: str = ""
    vram_bytes: int | None = None
    vram_free_bytes: int | None = None
    compute_capability: tuple[int, int] | None = None
    bf16: str = UNKNOWN
    fp16: str = UNKNOWN
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "vendor": self.vendor,
            "vramBytes": self.vram_bytes,
            "vramFreeBytes": self.vram_free_bytes,
            "computeCapability": (
                f"{self.compute_capability[0]}.{self.compute_capability[1]}"
                if self.compute_capability
                else None
            ),
            "bf16": self.bf16,
            "fp16": self.fp16,
            "detail": self.detail,
        }


def cpu_accelerator(detail: str) -> Accelerator:
    """The CPU, stated as a device. ``fp32`` is supported; nothing else is claimed."""
    return Accelerator(
        kind="cpu",
        name=platform.processor() or platform.machine() or "cpu",
        vendor="",
        bf16=UNSUPPORTED,
        fp16=UNSUPPORTED,
        detail=detail,
    )


@dataclass(frozen=True)
class HardwareReport:
    """Everything preflight needs to know about this machine."""

    cpu_model: str = "unknown"
    cpu_logical: int = 0
    cpu_features: tuple[str, ...] = ()
    ram_total_bytes: int | None = None
    ram_available_bytes: int | None = None
    disk_path: str = ""
    disk_free_bytes: int | None = None
    accelerator: Accelerator = field(default_factory=lambda: cpu_accelerator(""))
    observed_gpus: tuple[ObservedGpu, ...] = ()
    torch_version: str = ""
    torch_cuda_version: str = ""
    platform_name: str = ""
    python_version: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "cpu": {
                "model": self.cpu_model,
                "logicalCpus": self.cpu_logical,
                "features": list(self.cpu_features),
            },
            "memory": {
                "totalBytes": self.ram_total_bytes,
                "availableBytes": self.ram_available_bytes,
            },
            "disk": {"path": self.disk_path, "freeBytes": self.disk_free_bytes},
            "accelerator": self.accelerator.to_json(),
            "observedGpus": [item.to_json() for item in self.observed_gpus],
            "torch": {"version": self.torch_version, "cudaVersion": self.torch_cuda_version},
            "platform": self.platform_name,
            "pythonVersion": self.python_version,
        }


# --------------------------------------------------------------------------- #
# CPU, memory, disk
# --------------------------------------------------------------------------- #


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cpu() -> tuple[str, int, tuple[str, ...]]:
    model = platform.processor() or "unknown"
    flags: set[str] = set()
    content = _read(Path("/proc/cpuinfo"))
    for line in content.splitlines():
        lowered = line.lower()
        if lowered.startswith(("flags", "features")) and ":" in line:
            flags.update(line.split(":", 1)[1].split())
        elif lowered.startswith("model name") and ":" in line:
            model = line.split(":", 1)[1].strip()
    # The subset that changes a training decision: wide vector units and the
    # bfloat16 CPU instructions, which are what a future CPU bf16 path would
    # need. Reported, never acted on by the current precision rule.
    relevant = sorted(
        flags.intersection(
            {"avx", "avx2", "avx512f", "avx512_bf16", "amx_bf16", "sse4_2", "fma", "neon", "asimd"}
        )
    )
    return model, os.cpu_count() or 0, tuple(relevant)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory() -> tuple[int | None, int | None]:
    """Total and available RAM, or ``None`` where the platform will not say.

    Three sources, in order of directness: ``/proc/meminfo`` on Linux, the Win32
    memory status on Windows, and ``sysconf`` for the Unixes that have it.
    ``None`` rather than a guess is the point; a plan that cannot see RAM is a
    plan that refuses, and that is better than one sized against an invention.
    """
    content = _read(Path("/proc/meminfo"))
    if content:
        values: dict[str, int] = {}
        for line in content.splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            number = raw.strip().split()[0] if raw.strip() else ""
            if number.isdigit():
                values[key] = int(number) * 1024
        return values.get("MemTotal"), values.get("MemAvailable")

    if sys.platform == "win32":  # pragma: no cover - platform-specific
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except (AttributeError, OSError):
            return None, None
        return None, None

    try:  # pragma: no cover - platform-specific
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return int(pages) * int(size), None
    except (AttributeError, ValueError, OSError):
        return None, None


def _disk(path: Path) -> tuple[str, int | None]:
    """Free bytes where the output will be written, not where the code lives.

    Walks up to the nearest directory that exists: an output path is usually
    named before it is created, and ``disk_usage`` on a path that does not exist
    raises rather than answering about the filesystem that will hold it.
    """
    candidate = path.resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        return str(candidate), shutil.disk_usage(candidate).free
    except OSError:
        return str(candidate), None


# --------------------------------------------------------------------------- #
# GPUs, with and without torch
# --------------------------------------------------------------------------- #


#: Where ``nvidia-smi`` lives when it is not on ``PATH``. WSL puts the driver
#: shim here and adds the directory to an interactive login's ``PATH`` — but a
#: systemd service gets ``/usr/local/bin:/usr/bin`` and nothing else, so a run
#: started by ``systemd-run`` fell back to sysfs and reported "unknown display
#: controller" for a card the same probe names correctly from a shell. The
#: point of this function is to say "this machine has an RTX 4050 that the
#: installed torch cannot use", and it could not say it where it mattered.
_NVIDIA_SMI_FALLBACKS = ("/usr/lib/wsl/lib/nvidia-smi", "/usr/bin/nvidia-smi")


def _nvidia_smi() -> tuple[ObservedGpu, ...]:
    program = shutil.which("nvidia-smi")
    if not program:
        program = next((path for path in _NVIDIA_SMI_FALLBACKS if Path(path).is_file()), "")
    if not program:
        return ()
    try:
        completed = subprocess.run(
            [program, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment
        return ()
    if completed.returncode != 0:
        return ()
    found: list[ObservedGpu] = []
    for line in completed.stdout.splitlines():
        if "," not in line:
            continue
        name, _, memory = line.partition(",")
        megabytes = memory.strip()
        found.append(
            ObservedGpu(
                name=name.strip(),
                vendor="nvidia",
                vram_bytes=int(megabytes) * 1024 * 1024 if megabytes.isdigit() else None,
                source="nvidia-smi",
            )
        )
    return tuple(found)


def _sysfs_gpus() -> tuple[ObservedGpu, ...]:
    """Display-class PCI devices, for a machine with no vendor tool installed.

    Reports the vendor and nothing else: sysfs will not tell us the marketing
    name or the VRAM without a driver-specific interface, so those stay
    ``UNKNOWN`` rather than being filled with the device id.
    """
    root = Path("/sys/bus/pci/devices")
    if not root.is_dir():
        return ()
    found: list[ObservedGpu] = []
    for entry in sorted(root.iterdir()):
        klass = _read(entry / "class").strip()
        if not klass.startswith("0x03"):  # display controller
            continue
        vendor = _PCI_VENDORS.get(_read(entry / "vendor").strip(), "unknown")
        found.append(
            ObservedGpu(name=f"{vendor} display controller {entry.name}", vendor=vendor, source="sysfs")
        )
    return tuple(found)


def _capability_bf16(module: Any, index: int, capability: tuple[int, int] | None) -> str:
    """Ask torch first; fall back to the architecture only if it will not answer.

    ``torch.cuda.is_bf16_supported()`` is the right question because it accounts
    for the driver and the torch build as well as the silicon. It is also newer
    than some torch versions in the wild, hence the fallback — and the fallback
    is a *lower bound* on capability, never an upper one.
    """
    try:
        supported = module.cuda.is_bf16_supported()
    except (AttributeError, RuntimeError, TypeError):
        if capability is None:
            return UNKNOWN
        return SUPPORTED if capability >= _BF16_MINIMUM_CAPABILITY else UNSUPPORTED
    return SUPPORTED if bool(supported) else UNSUPPORTED


def _accelerator_from_torch(module: Any) -> Accelerator:
    """The device torch would train on, asked of torch itself."""
    try:
        cuda_available = bool(module.cuda.is_available())
    except (AttributeError, RuntimeError):
        cuda_available = False

    if cuda_available:
        try:
            index = int(module.cuda.current_device())
            name = str(module.cuda.get_device_name(index))
            properties = module.cuda.get_device_properties(index)
            total = int(getattr(properties, "total_memory", 0)) or None
            capability = (
                int(getattr(properties, "major", 0)),
                int(getattr(properties, "minor", 0)),
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return Accelerator(
                kind="cuda",
                name="cuda device",
                vendor="nvidia",
                detail="CUDA reports available but the device could not be queried",
            )
        free: int | None = None
        try:
            free = int(module.cuda.mem_get_info(index)[0])
        except (AttributeError, RuntimeError, TypeError, IndexError):
            free = None
        return Accelerator(
            kind="cuda",
            name=name,
            vendor="nvidia",
            vram_bytes=total,
            vram_free_bytes=free,
            compute_capability=capability,
            bf16=_capability_bf16(module, index, capability),
            # Every CUDA device torch will run on does float16. Stated because
            # it was checked against the same object, not because CUDA implies it.
            fp16=SUPPORTED,
            detail=f"torch {getattr(module, '__version__', '?')} CUDA runtime "
                   f"{getattr(getattr(module, 'version', None), 'cuda', None)}",
        )

    try:
        mps_available = bool(module.backends.mps.is_available())
    except (AttributeError, RuntimeError):
        mps_available = False
    if mps_available:
        bf16 = UNKNOWN
        try:
            bf16 = SUPPORTED if module.backends.mps.is_macos_or_newer(14, 0) else UNSUPPORTED
        except (AttributeError, RuntimeError, TypeError):
            bf16 = UNKNOWN
        return Accelerator(
            kind="mps",
            name="Apple Metal",
            vendor="apple",
            # Unified memory: there is no separate VRAM figure to report, and
            # reporting system RAM here would let a plan size against memory the
            # model does not exclusively have.
            vram_bytes=None,
            bf16=bf16,
            fp16=SUPPORTED,
            detail="Metal Performance Shaders backend",
        )

    cuda_build = getattr(getattr(module, "version", None), "cuda", None)
    detail = (
        "torch is a CPU build; no CUDA runtime"
        if not cuda_build
        else f"torch was built against CUDA {cuda_build} but no device is available"
    )
    return cpu_accelerator(detail)


def probe_hardware(
    *,
    disk_path: Path | str | None = None,
    torch_module: Any = _UNSET,
) -> HardwareReport:
    """Measure this machine.

    ``torch_module`` is injected by the regression tests, which have to be able
    to describe an Ampere card, a Turing card and a machine with no CUDA runtime
    on a host that has none of them. Nothing else passes it; production calls
    import torch here, and get a CPU report if it is absent.

    Not-passed and ``None`` are different, and the sentinel is why: omitting the
    argument means "find torch yourself", and passing ``None`` means "there is
    no torch". Without the distinction the test for a machine with no torch
    would quietly use the real one and pass for the wrong reason on any host
    that has it.
    """
    model, logical, features = _cpu()
    total, available = _memory()
    path, free = _disk(Path(disk_path) if disk_path else Path.cwd())

    module = torch_module
    if module is _UNSET:
        try:
            import torch as module  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 - a broken torch install must not stop a probe
            module = None

    if module is None:
        accelerator = cpu_accelerator("torch is not installed; no accelerator could be queried")
        torch_version = ""
        torch_cuda = ""
    else:
        accelerator = _accelerator_from_torch(module)
        torch_version = str(getattr(module, "__version__", ""))
        torch_cuda = str(getattr(getattr(module, "version", None), "cuda", "") or "")

    observed = _nvidia_smi() or _sysfs_gpus()

    return HardwareReport(
        cpu_model=model,
        cpu_logical=logical,
        cpu_features=features,
        ram_total_bytes=total,
        ram_available_bytes=available,
        disk_path=path,
        disk_free_bytes=free,
        accelerator=accelerator,
        observed_gpus=observed,
        torch_version=torch_version,
        torch_cuda_version=torch_cuda,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
    )
