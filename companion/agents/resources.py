# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine resources for local model selection: measured, not tiered.

The brief asks for "intelligent model selection" and is explicit about what
that is *not*: no invented product tiers like Low / Medium / Ultra. The
vocabulary is hardware-capability facts — available RAM, the memory-pressure
band, measured VRAM when a trustworthy source exists, GPU runtime readiness,
honest NPU-unknown, and *measured* throughput when a script has actually
run — and the rule falls out of those the way §9's selection falls out of
configuration order: a derivation, not a ranking.

* a **small machine** has a small usable-memory budget, so the largest
  discovered model whose footprint still fits is a smaller model;
* a **powerful machine** has a large budget, so the same rule binds the
  largest discovered model that fits, preferring GPU-offload when the
  runtime is actually usable;
* **memory pressure** shrinks the RAM budget; **unknown VRAM** does not
  invent a pool and does not refuse on a number nobody measured;
* **NPU presence** is recorded; NPU *usability* is never claimed from
  sysfs alone, so nothing is scheduled on it.

The estimate is honest about being an estimate. ``model_runtime_footprint``
is a conservative upper bound for a CPU ``llama-cli`` process — the weight
file plus a KV/context-cache allowance — labelled as such so the §25
measurements can replace it.

The guard is opt-in by measurement, not by flag. When the host cannot be
measured — no ``/proc/meminfo`` (a non-Linux build host, or a test that
injects nothing) — ``available_ram_bytes`` is zero and
:func:`model_memory_budget` returns zero, which the registry reads as "no
constraint is known" and does not refuse on. The same discipline applies to
VRAM and throughput: unknown disables that axis. A zero is *not* a
fabricated empty GPU.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

__all__ = [
    "ACCELERATOR_GPU_RUNTIMES",
    "CONTEXT_BYTES_PER_TOKEN",
    "GPU_OFFLOAD_ALL_LAYERS",
    "MachineResources",
    "NPU_STATES",
    "PRESSURE_LEVELS",
    "VRAM_STATES",
    "default_machine_resources",
    "llama_cli_gpu_layers",
    "machine_resources_from_inventory",
    "model_memory_budget",
    "model_runtime_footprint",
    "probe_host_accelerators",
    "selection_memory_budget",
    "tier_product",
]

#: Conservative KV/context-cache allowance per resident token, in bytes, for a
#: small CPU model running through llama-cli. The weight file dominates for a
#: 1-3B model; this term covers the context window's resident cache and a
#: margin for runtime overhead. It is an estimate, labelled as one, and §25
#: measurements replace it.
CONTEXT_BYTES_PER_TOKEN = 512

#: llama.cpp convention: request every layer on the GPU when the runtime is
#: *known usable*. This is not a measured layer count and is not derived from
#: VRAM size. The engine accepts or refuses; this package retries CPU on
#: failure rather than inventing a layer split.
GPU_OFFLOAD_ALL_LAYERS = 99

#: The pressure bands, in order of severity. ``"unknown"`` is the off-Linux /
#: unreadable case and disables the guard rather than refusing.
PRESSURE_LEVELS = ("nominal", "elevated", "critical", "unknown")

VRAM_STATES = ("unknown", "measured", "absent")
NPU_STATES = ("unknown", "absent", "present-unusable")
ACCELERATOR_GPU_RUNTIMES = ("", "cuda", "rocm", "vulkan")

#: The share of available RAM a *new* model may occupy at each pressure band.
#: Critical pressure leaves the machine room for everything that is not the
#: model, so the budget is smallest; nominal gives the model half of what the
#: OS reports spare. ``unknown`` is never reached (the caller checks
#: :attr:`MachineResources.known` first) but the table is total.
_SHARE = {
    "nominal": 0.50,
    "elevated": 0.30,
    "critical": 0.15,
    "unknown": 0.0,
}

#: Drivers whose devices share system memory rather than owning a VRAM pool.
_SHARED_MEMORY_DRIVERS = frozenset({
    "i915", "xe", "v3d", "vc4", "panfrost", "lima", "msm", "etnaviv",
})


@dataclass(frozen=True)
class MachineResources:
    """What this machine can spare for a local model right now.

    ``available_ram_bytes`` is the OS-reported available memory (Linux
    ``MemAvailable``). ``memory_pressure_level`` is the PSI memory-pressure
    band, or ``"unknown"`` where PSI is not readable. ``active_model_bytes``
    is memory already committed to a loaded model the caller is accounting
    for, so a second model's budget is what remains after the first.

    Accelerator fields follow the same unknown-is-not-absence rule. VRAM of
    ``0`` with ``vram_state="unknown"`` is *not* "this GPU has no memory".
    Throughput of ``None`` is *not* "zero tokens per second".
    """

    available_ram_bytes: int = 0
    memory_pressure_level: str = "unknown"
    active_model_bytes: int = 0
    vram_available_bytes: int = 0
    vram_total_bytes: int = 0
    vram_state: str = "unknown"
    gpu_runtime: str = ""
    gpu_kind: str = "unknown"
    gpu_usable: bool = False
    npu_state: str = "unknown"
    throughput_tokens_per_second: float | None = None
    throughput_by_model: tuple[tuple[str, float], ...] = ()
    accelerator_evidence: str = "unknown"

    def __post_init__(self) -> None:
        if self.available_ram_bytes < 0 or self.active_model_bytes < 0:
            raise ValueError("resource bytes must be non-negative")
        if self.vram_available_bytes < 0 or self.vram_total_bytes < 0:
            raise ValueError("VRAM bytes must be non-negative")
        if self.memory_pressure_level not in PRESSURE_LEVELS:
            raise ValueError(
                f"memory pressure level {self.memory_pressure_level!r} "
                f"is not one of {PRESSURE_LEVELS}"
            )
        if self.vram_state not in VRAM_STATES:
            raise ValueError(f"vram_state {self.vram_state!r} is not one of {VRAM_STATES}")
        if self.npu_state not in NPU_STATES:
            raise ValueError(f"npu_state {self.npu_state!r} is not one of {NPU_STATES}")
        if self.gpu_runtime not in ACCELERATOR_GPU_RUNTIMES:
            raise ValueError(
                f"gpu_runtime {self.gpu_runtime!r} is not one of {ACCELERATOR_GPU_RUNTIMES}"
            )
        if self.throughput_tokens_per_second is not None and self.throughput_tokens_per_second < 0:
            raise ValueError("throughput must be non-negative when known")
        for model_id, rate in self.throughput_by_model:
            if rate < 0:
                raise ValueError(f"throughput for {model_id!r} must be non-negative")

    @property
    def known(self) -> bool:
        """Whether the RAM budget is a constraint at all. Unknown → no refusal."""
        return self.available_ram_bytes > 0

    @property
    def vram_known(self) -> bool:
        return self.vram_state == "measured"

    @property
    def throughput_known(self) -> bool:
        return self.throughput_tokens_per_second is not None

    def throughput_for(self, model_id: str) -> float | None:
        """Per-model measured tok/s, or the machine-level figure, or unknown."""
        for name, rate in self.throughput_by_model:
            if name == model_id:
                return rate
        return self.throughput_tokens_per_second


def model_memory_budget(resources: MachineResources) -> int:
    """The most bytes a *new* model may consume from RAM on this machine right now.

    Zero means "no constraint is known" — the caller must NOT refuse a model
    on a zero budget. A non-zero budget that a model exceeds is a real
    refusal: under critical pressure the budget shrinks to 15% of available
    minus what an active model already holds, so the largest model that
    still fits is what selection keeps and the rest become ineligible.
    """
    if not resources.known:
        return 0
    share = _SHARE.get(resources.memory_pressure_level, _SHARE["nominal"])
    budget = int(resources.available_ram_bytes * share) - resources.active_model_bytes
    return max(0, budget)


def selection_memory_budget(resources: MachineResources) -> tuple[int, str]:
    """The budget axis selection should weigh, and its name.

    GPU-usable + measured VRAM → VRAM bytes (weights should fit the card).
    Otherwise RAM, with the same unknown-disables-the-guard rule as today.
    Integrated GPUs with ``vram_state="absent"`` use RAM: there is no
    dedicated pool to budget against, and none is invented.
    """
    if resources.gpu_usable and resources.vram_known:
        return max(0, resources.vram_available_bytes - resources.active_model_bytes), "vram"
    return model_memory_budget(resources), "ram"


def tier_product(resources: MachineResources) -> int | None:
    """Usable memory × measured throughput, or ``None`` when either is unknown.

    ADR 0012 tiers *machines* this way. The product is never synthesised from
    TOPS, marketing VRAM, or a guessed tok/s.
    """
    budget, _axis = selection_memory_budget(resources)
    if budget <= 0 or not resources.throughput_known:
        return None
    return int(budget * resources.throughput_tokens_per_second)


def llama_cli_gpu_layers(resources: MachineResources | None) -> int | None:
    """Layers to request via ``--n-gpu-layers``, or ``None`` to pass no flag.

    ``None`` is the unknown/absent path: do not claim GPU offload. A positive
    number is "ask the engine to offload"; it is not a VRAM-derived split.
    """
    if resources is None or not resources.gpu_usable:
        return None
    return GPU_OFFLOAD_ALL_LAYERS


def model_runtime_footprint(*, model_size_bytes: int, context_limit_tokens: int) -> int:
    """A conservative estimate of the bytes a model needs resident to run.

    Weights plus a context-cache allowance. Both inputs are non-negative;
    either being zero yields the other term alone, so a discovered model
    whose size the probe could not stat is estimated from context only, and
    a model with no declared context window is estimated from weights only.
    """
    if model_size_bytes < 0 or context_limit_tokens < 0:
        raise ValueError("footprint inputs must be non-negative")
    return model_size_bytes + context_limit_tokens * CONTEXT_BYTES_PER_TOKEN


_MEMINFO_AVAILABLE = re.compile(r"^MemAvailable:\s+(\d+)\s+kB", re.MULTILINE)
_PRESSURE_AVG = re.compile(r"^(full|some)\s+avg10=(\d+\.\d+)", re.MULTILINE)


def _read_pressure_level(proc_root: Path) -> str:
    """Map /proc/pressure/memory to a band, or ``"unknown"`` where unreadable.

    The "full" line's avg10 is the share of time *all* tasks were stalled on
    memory; where only "some" is reported, that line is used instead. The
    thresholds are conservative: 30% sustained stall is elevated, 60% is
    critical. Below 30% the machine is nominal for a model that fits.
    """
    try:
        text = (proc_root / "pressure" / "memory").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    full: float | None = None
    some: float | None = None
    for kind, value in _PRESSURE_AVG.findall(text):
        if kind == "full" and full is None:
            full = float(value)
        elif kind == "some" and some is None:
            some = float(value)
    avg = full if full is not None else some
    if avg is None:
        return "unknown"
    if avg >= 60.0:
        return "critical"
    if avg >= 30.0:
        return "elevated"
    return "nominal"


def _first_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def _read_int_file(path: Path) -> int | None:
    text = _first_line(path)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def probe_host_accelerators(
    *,
    sys_root: Path | None = None,
    dev_root: Path | None = None,
    usr_bin: Path | None = None,
) -> dict[str, object]:
    """Read GPU/NPU *presence and readiness* without inventing VRAM or TOPS.

    This probe does not spawn ``nvidia-smi`` or ``vulkaninfo`` (the agents
    package may not import ``subprocess`` outside llamacli). NVIDIA VRAM
    therefore stays ``unknown`` unless a caller injects an inventory that
    already measured it. AMD VRAM is read from amdgpu sysfs when present.
    CUDA usability is ``/dev/nvidiactl`` plus the vendor tool existing on
    disk — the same pair capability discovery uses, minus running the tool.
    """
    sysfs = sys_root if sys_root is not None else Path("/sys")
    dev = dev_root if dev_root is not None else Path("/dev")
    bin_dir = usr_bin if usr_bin is not None else Path("/usr/bin")

    evidence: list[str] = []
    gpu_runtime = ""
    gpu_kind = "unknown"
    gpu_usable = False
    vram_state = "unknown"
    vram_available = 0
    vram_total = 0

    nvidiactl = (dev / "nvidiactl").exists()
    nvidia_smi = (bin_dir / "nvidia-smi").is_file()
    kfd = (dev / "kfd").exists()

    if nvidiactl and nvidia_smi:
        gpu_runtime = "cuda"
        gpu_usable = True
        gpu_kind = "discrete"
        evidence.append("/dev/nvidiactl and /usr/bin/nvidia-smi present; VRAM not read here")
    elif nvidiactl or nvidia_smi:
        gpu_kind = "discrete"
        evidence.append(
            "NVIDIA pieces are incomplete "
            f"(nvidiactl={nvidiactl}, nvidia-smi={nvidia_smi}); CUDA is not claimed"
        )
    if kfd:
        if not gpu_usable:
            gpu_runtime = "rocm"
            gpu_usable = True
            gpu_kind = "discrete"
        evidence.append("/dev/kfd present; ROCm compute node exists")

    drm = sysfs / "class" / "drm"
    amd_vram_found = False
    shared_memory_gpu = False
    if drm.is_dir():
        try:
            cards = sorted(p for p in drm.iterdir() if p.name.startswith("card") and p.name[4:].isdigit())
        except OSError:
            cards = []
        for card in cards:
            device = card / "device"
            driver = ""
            try:
                driver = (device / "driver").resolve(strict=True).name
            except OSError:
                pass
            if driver in _SHARED_MEMORY_DRIVERS:
                shared_memory_gpu = True
                if gpu_kind == "unknown":
                    gpu_kind = "integrated"
                evidence.append(f"{driver} shares system memory; dedicated VRAM is absent")
            if driver == "amdgpu":
                total = _read_int_file(device / "mem_info_vram_total")
                used = _read_int_file(device / "mem_info_vram_used")
                if total is not None and total > 0:
                    amd_vram_found = True
                    vram_state = "measured"
                    vram_total = total
                    vram_available = max(0, total - used) if used is not None and used >= 0 else total
                    if gpu_kind == "unknown":
                        gpu_kind = "discrete"
                    evidence.append("amdgpu mem_info_vram_total")
                    if not gpu_usable and kfd:
                        gpu_runtime = "rocm"
                        gpu_usable = True
    if shared_memory_gpu and vram_state == "unknown":
        vram_state = "absent"

    npu_state = "unknown"
    accel = sysfs / "class" / "accel"
    if accel.is_dir():
        try:
            entries = [p for p in accel.iterdir() if p.name != "."]
        except OSError:
            entries = []
        if entries:
            npu_state = "present-unusable"
            evidence.append(
                "/sys/class/accel has devices; no userspace runtime was probed; "
                "NPU offload is not claimed"
            )
        else:
            npu_state = "absent"
            evidence.append("/sys/class/accel is empty")
    elif sysfs.joinpath("class").is_dir():
        npu_state = "absent"
        evidence.append("/sys/class/accel is not present")

    if not nvidiactl and not nvidia_smi and not kfd and not amd_vram_found and not shared_memory_gpu:
        evidence.append("no CUDA/ROCm device nodes; GPU offload is not claimed")

    return {
        "gpu_runtime": gpu_runtime,
        "gpu_kind": gpu_kind,
        "gpu_usable": gpu_usable,
        "vram_state": vram_state,
        "vram_available_bytes": vram_available,
        "vram_total_bytes": vram_total,
        "npu_state": npu_state,
        "accelerator_evidence": "; ".join(evidence)[:512],
        "amd_vram_found": amd_vram_found,
    }


def default_machine_resources(
    proc_root: Path | None = None,
    *,
    sys_root: Path | None = None,
    dev_root: Path | None = None,
    usr_bin: Path | None = None,
) -> MachineResources:
    """Read the live machine, or report unknown where it cannot be read.

    On Linux this reads ``/proc/meminfo`` for ``MemAvailable`` and
    ``/proc/pressure/memory`` for the pressure band, then a subprocess-free
    accelerator probe. Off Linux (the build host, or a unit test) both RAM
    reads miss and the result is unknown — which disables the resource guard
    rather than refusing every model. Accelerator axes independently stay
    unknown when their sources are missing.
    """
    proc = proc_root if proc_root is not None else Path("/proc")
    accel = probe_host_accelerators(sys_root=sys_root, dev_root=dev_root, usr_bin=usr_bin)
    try:
        meminfo = (proc / "meminfo").read_text(encoding="utf-8")
    except OSError:
        return MachineResources(
            available_ram_bytes=0,
            memory_pressure_level="unknown",
            vram_available_bytes=int(accel["vram_available_bytes"]),
            vram_total_bytes=int(accel["vram_total_bytes"]),
            vram_state=str(accel["vram_state"]),
            gpu_runtime=str(accel["gpu_runtime"]),
            gpu_kind=str(accel["gpu_kind"]),
            gpu_usable=bool(accel["gpu_usable"]),
            npu_state=str(accel["npu_state"]),
            accelerator_evidence=str(accel["accelerator_evidence"]),
        )
    match = _MEMINFO_AVAILABLE.search(meminfo)
    available = int(match.group(1)) * 1024 if match is not None else 0  # kB → bytes
    level = _read_pressure_level(proc)
    if available == 0:
        level = "unknown"
    return MachineResources(
        available_ram_bytes=available,
        memory_pressure_level=level,
        vram_available_bytes=int(accel["vram_available_bytes"]),
        vram_total_bytes=int(accel["vram_total_bytes"]),
        vram_state=str(accel["vram_state"]),
        gpu_runtime=str(accel["gpu_runtime"]),
        gpu_kind=str(accel["gpu_kind"]),
        gpu_usable=bool(accel["gpu_usable"]),
        npu_state=str(accel["npu_state"]),
        accelerator_evidence=str(accel["accelerator_evidence"]),
    )


def machine_resources_from_inventory(
    inventory: object,
    *,
    ram: MachineResources | None = None,
    throughput_tokens_per_second: float | None = None,
    throughput_by_model: Mapping[str, float] | None = None,
) -> MachineResources:
    """Copy measured GPU/NPU facts from a capability inventory.

    Unknown inventory fields stay unknown. No VRAM number is taken from a
    generic adapter-memory field — only ``vram_available_bytes`` /
    ``vram_total_bytes`` observations that the inventory already classified
    as measured or absent. Throughput is accepted only as an explicit
    argument from a measurement script, never guessed from TOPS.
    """
    base = ram if ram is not None else MachineResources()
    gpus = tuple(getattr(inventory, "gpu", ()) or ())
    accelerators = tuple(getattr(inventory, "accelerators", ()) or ())

    gpu_runtime = base.gpu_runtime
    gpu_kind = base.gpu_kind
    gpu_usable = base.gpu_usable
    vram_state = base.vram_state
    vram_available = base.vram_available_bytes
    vram_total = base.vram_total_bytes
    evidence = [base.accelerator_evidence] if base.accelerator_evidence != "unknown" else []

    for device in gpus:
        kind = getattr(device, "kind", None)
        kind_value = kind.get("unknown") if kind is not None else "unknown"
        if isinstance(kind_value, str) and kind_value and gpu_kind == "unknown":
            gpu_kind = kind_value
        ready = False
        runtime_ready = getattr(device, "runtime_ready", None)
        if callable(runtime_ready):
            ready = bool(runtime_ready("cuda") or runtime_ready("rocm"))
            if runtime_ready("cuda"):
                gpu_runtime = "cuda"
            elif runtime_ready("rocm") and not gpu_runtime:
                gpu_runtime = "rocm"
        driver_ready = bool(getattr(device, "driver_ready", False))
        if ready and driver_ready:
            gpu_usable = True
        vram_avail_obs = getattr(device, "vram_available_bytes", None)
        vram_total_obs = getattr(device, "vram_total_bytes", None)
        if vram_avail_obs is not None and getattr(vram_avail_obs, "is_measured", False):
            value = vram_avail_obs.get(None)
            if isinstance(value, int) and value >= 0:
                vram_state = "measured"
                vram_available = max(vram_available, value)
                source = getattr(vram_avail_obs, "source", "") or "inventory"
                evidence.append(f"VRAM available from {source}")
        elif vram_avail_obs is not None and getattr(vram_avail_obs, "state", "") == "absent":
            if vram_state == "unknown":
                vram_state = "absent"
                evidence.append("inventory reports dedicated VRAM absent")
        if vram_total_obs is not None and getattr(vram_total_obs, "is_measured", False):
            value = vram_total_obs.get(None)
            if isinstance(value, int) and value >= 0:
                vram_total = max(vram_total, value)

    npu_state = base.npu_state
    for item in accelerators:
        kind = str(getattr(item, "kind", "") or "")
        if kind in ("npu", "accel"):
            npu_state = "present-unusable"
            evidence.append(
                f"inventory lists {kind}; driver_ready was not treated as a scheduleable runtime"
            )

    by_model = tuple(
        (str(name), float(rate))
        for name, rate in (throughput_by_model or {}).items()
        if rate >= 0
    )
    return MachineResources(
        available_ram_bytes=base.available_ram_bytes,
        memory_pressure_level=base.memory_pressure_level,
        active_model_bytes=base.active_model_bytes,
        vram_available_bytes=vram_available,
        vram_total_bytes=vram_total,
        vram_state=vram_state,
        gpu_runtime=gpu_runtime,
        gpu_kind=gpu_kind,
        gpu_usable=gpu_usable,
        npu_state=npu_state,
        throughput_tokens_per_second=throughput_tokens_per_second,
        throughput_by_model=by_model,
        accelerator_evidence="; ".join(evidence)[:512] or "inventory",
    )
