# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Continuous capability scoring across independent dimensions.

There is deliberately no overall score, no rank and no label. A machine is not
"high" or "low"; it is a vector of thirteen numbers, each of which answers one
question and none of which is allowed to compensate for another. The
requirement this implements is explicit in both the brief and
``docs/phase-1/BUNNY_OS_PHASE_1.md`` C11: *a profile keyed on a product tier
fails review*, and a single collapsed "power level" is a product tier wearing a
number.

The concrete failure a single score produces: a workstation with two RTX 6000s
and 4 GB of usable RAM inside a restrictive cgroup would score "very high" on
any weighted average, and the policy engine would start a service that is then
OOM-killed. Here that machine scores ~97 on ``gpu_compute`` and ~55 on
``memory_available``, and the memory dimension is the one that gates the
service. A powerful GPU cannot hide a severe memory shortage because no
arithmetic path exists by which it could.

**Score contract.** Every dimension is:

* bounded to ``0.0..100.0`` inclusive, or ``None`` when nothing relevant was
  measured;
* a pure, deterministic function of the inventory — same inventory, same
  numbers, on any host, in any order;
* accompanied by the raw measurements it used, so a number can always be
  re-derived by hand;
* accompanied by a confidence, which is *not* a score: ``measured`` means every
  input was measured, ``partial`` means some were, ``unknown`` means none were
  and the score is ``None``.

``None`` is the important case. A dimension with no evidence must not be scored
zero, because zero means "measured, and there is none" and would let a policy
decision proceed on a fact nobody established.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence

from .model import Inventory, Observation

__all__ = [
    "CONFIDENCES",
    "DIMENSIONS",
    "Score",
    "ScoreSet",
    "compute_scores",
]

MEASURED, PARTIAL, UNKNOWN = "measured", "partial", "unknown"
CONFIDENCES = (MEASURED, PARTIAL, UNKNOWN)

#: The dimensions, with the question each one answers. The list is the public
#: contract: adding one is a schema change, and collapsing two is a design
#: change that has to be argued rather than done.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("cpu_compute", "How much CPU work can this machine do, given its schedulable cores?"),
    ("memory_available", "How much memory may Bunny OS actually use, after every imposed ceiling?"),
    ("gpu_compute", "Is there a GPU that work can genuinely be submitted to?"),
    ("gpu_memory", "How much dedicated video memory is there?"),
    ("storage_capacity", "How much free storage is there?"),
    ("storage_performance", "How fast is that storage, and is it currently congested?"),
    ("network_quality", "Is there usable connectivity, and what does it cost to use?"),
    ("local_ai", "Can model inference run on this machine at all?"),
    ("graphics", "Can accelerated rendering happen locally?"),
    ("audio", "Are there audio endpoints for speech in and out?"),
    ("interactive_desktop", "Can a person sit at this machine and use it?"),
    ("background_capacity", "How much headroom is left for work nobody is waiting on?"),
    ("energy_thermal_headroom", "How much may be spent without hurting battery life or heat?"),
)

_MIB = 1024 ** 2
_GIB = 1024 ** 3


# --------------------------------------------------------------------------- #
# Curve helpers
# --------------------------------------------------------------------------- #


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _log_scale(value: float, floor: float, ceiling: float) -> float:
    """Position of ``value`` between ``floor`` and ``ceiling`` on a log2 curve.

    Log rather than linear because every resource this module scores is
    perceived logarithmically. The step from 512 MB to 1 GB changes what Bunny
    OS can run; the step from 64 GB to 64.5 GB changes nothing. A linear scale
    would put every constrained device — the exact devices this subsystem
    exists to serve — into an indistinguishable smear near zero.
    """
    if value <= floor:
        return 0.0
    if value >= ceiling:
        return 100.0
    return 100.0 * math.log2(value / floor) / math.log2(ceiling / floor)


def _confidence(*observations: Observation) -> str:
    known = [item for item in observations if item.is_known]
    if not known:
        return UNKNOWN
    return MEASURED if len(known) == len(observations) else PARTIAL


@dataclass(frozen=True)
class Score:
    """One dimension, its value, its confidence and the evidence behind it."""

    name: str
    value: float | None
    confidence: str
    question: str = ""
    inputs: Mapping[str, Any] = field(default_factory=dict)
    notes: Sequence[str] = ()

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"unknown confidence: {self.confidence!r}")
        if self.value is None:
            if self.confidence != UNKNOWN:
                raise ValueError("a scoreless dimension must have unknown confidence")
        elif not 0.0 <= self.value <= 100.0:
            raise ValueError(f"{self.name} score {self.value} is outside 0..100")

    def at_least(self, threshold: float, *, when_unknown: bool) -> bool:
        """Whether this dimension clears ``threshold``.

        ``when_unknown`` is mandatory and has no default, because "we did not
        measure this" is the case every caller gets wrong by accident. A
        requirement check passes ``False`` (unmeasured capability is not
        assumed present); a safety check that must not fire on missing data
        passes ``True``. Making it explicit means the choice appears in the
        call site and in review.
        """
        if self.value is None:
            return when_unknown
        return self.value >= threshold

    def to_json(self) -> dict[str, Any]:
        return {
            "dimension": self.name,
            "score": None if self.value is None else round(self.value, 1),
            "confidence": self.confidence,
            "question": self.question,
            "inputs": dict(self.inputs),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ScoreSet:
    scores: Mapping[str, Score]

    def __getitem__(self, name: str) -> Score:
        return self.scores[name]

    def get(self, name: str) -> Score:
        return self.scores.get(name, Score(name, None, UNKNOWN, "unrecognised dimension"))

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "range": {"minimum": 0.0, "maximum": 100.0, "unmeasured": None},
            "note": (
                "There is no overall score. Dimensions are independent by design: a high "
                "score in one may not be used to satisfy a requirement in another."
            ),
            "dimensions": [self.scores[name].to_json() for name, _ in DIMENSIONS if name in self.scores],
        }


# --------------------------------------------------------------------------- #
# The dimensions
# --------------------------------------------------------------------------- #


def _cpu_compute(inventory: Inventory) -> Score:
    """Schedulable cores on a log curve from 1 to 64, with an instruction-set bonus.

    ``effective_cores``, not the physical count: a container holding 0.5 CPU on
    a 96-thread host scores as half a core, because that is what it can use.
    """
    cpu = inventory.cpu
    cores = cpu.effective_cores(0.0)
    isa = cpu.instruction_sets.get([])
    confidence = _confidence(cpu.logical_threads, cpu.instruction_sets)
    if cores <= 0:
        return Score("cpu_compute", None, UNKNOWN, DIMENSIONS[0][1],
                     {"effectiveCores": None},
                     ["No schedulable core count was measured; capability is not assumed."])

    base = _log_scale(cores * 2, 2.0, 128.0)
    wide = {"avx2", "avx512f", "sve", "sve2", "asimd", "amx_int8"}
    bonus = 8.0 if isinstance(isa, list) and wide.intersection(isa) else 0.0
    notes = []
    if bonus:
        notes.append("Wide-vector instructions present; +8 for throughput-bound work.")
    if cpu.quota_cores.is_measured:
        notes.append(f"A cgroup quota of {cpu.quota_cores.value:g} cores is the binding limit, not the physical core count.")
    return Score("cpu_compute", _clamp(base + bonus), confidence, DIMENSIONS[0][1],
                 {
                     "effectiveCores": cores,
                     "logicalThreads": cpu.logical_threads.get(None),
                     "quotaCores": cpu.quota_cores.get(None),
                     "instructionSets": isa if isinstance(isa, list) else [],
                 }, notes)


def _memory_available(inventory: Inventory) -> Score:
    """Usable memory on a log curve from 64 MiB to 128 GiB.

    The floor is 64 MiB because that is the explicit architectural constraint in
    §5 of the brief: the smallest board Bunny OS must boot on scores 0 here, and
    0 is a real, correct score for it rather than an error.
    """
    memory = inventory.memory
    usable = memory.usable_bytes(None)
    available = memory.usable_available_bytes(None)
    confidence = _confidence(memory.physical_bytes, memory.available_bytes)
    if usable is None:
        return Score("memory_available", None, UNKNOWN, DIMENSIONS[1][1],
                     {"usableBytes": None},
                     ["Neither physical memory nor a cgroup ceiling was measured."])

    score = _log_scale(float(usable), 64.0 * _MIB, 128.0 * _GIB)
    notes: list[str] = []
    if memory.cgroup_limit_bytes.is_measured:
        notes.append(
            f"A cgroup ceiling of {memory.cgroup_limit_bytes.value / _MIB:.0f} MiB is in force; "
            "the host's physical memory is not the operative number."
        )
    pressure = memory.pressure_some_avg10.get(None)
    if isinstance(pressure, (int, float)) and pressure > 10.0:
        notes.append(f"Memory pressure (PSI some avg10) is {pressure:.1f}%; the machine is stalling on reclaim.")
    return Score("memory_available", _clamp(score), confidence, DIMENSIONS[1][1],
                 {
                     "usableBytes": usable,
                     "currentlyAvailableBytes": available,
                     "physicalBytes": memory.physical_bytes.get(None),
                     "cgroupLimitBytes": memory.cgroup_limit_bytes.get(None),
                     "pressureSomeAvg10": pressure,
                 }, notes)


def _gpu_compute(inventory: Inventory) -> Score:
    """Whether work can actually be submitted to a GPU, not whether one exists.

    A device with no bound driver scores 0 with ``measured`` confidence: we
    looked, and there is nothing usable. That is a different statement from a
    machine where DRM could not be read at all, which scores ``None``.
    """
    devices = list(inventory.gpu)
    if not devices:
        # No DRM cards enumerated at all. On Linux this is a real observation
        # (headless server, container without /dev/dri); elsewhere it means the
        # probe could not run. The probe outcomes distinguish them.
        drm_probed = any(item.name == "gpu" and item.state == "ok" for item in inventory.probes)
        if drm_probed:
            return Score("gpu_compute", 0.0, MEASURED, DIMENSIONS[2][1],
                         {"devices": 0}, ["No GPU devices are present."])
        return Score("gpu_compute", None, UNKNOWN, DIMENSIONS[2][1],
                     {"devices": None}, ["The GPU probe did not complete."])

    best = 0.0
    inputs: list[dict[str, Any]] = []
    notes: list[str] = []
    for device in devices:
        kind = device.kind.get("unknown")
        compute = device.runtime_ready("cuda") or device.runtime_ready("rocm")
        graphics = device.runtime_ready("vulkan")
        if not device.driver_ready:
            value = 0.0
            notes.append(
                f"GPU {device.index} ({device.description.get('unknown')}) is present but unusable: "
                f"{'no driver is bound' if not device.driver.get('') else 'no render node was created'}."
            )
        elif kind == "discrete" and compute:
            value = 95.0
        elif kind == "discrete" and graphics:
            value = 70.0
        elif kind == "discrete":
            value = 45.0
            notes.append(f"GPU {device.index} has a driver but no compute or graphics runtime was verified.")
        elif kind == "integrated":
            value = 40.0 if graphics else 25.0
        elif kind == "virtual":
            value = 10.0
            notes.append(f"GPU {device.index} is a virtual adapter; it is not a compute device.")
        else:
            value = 20.0
        best = max(best, value)
        inputs.append({
            "index": device.index,
            "kind": kind,
            "driverReady": device.driver_ready,
            "driver": device.driver.get(None),
            "cuda": device.runtime_ready("cuda"),
            "rocm": device.runtime_ready("rocm"),
            "vulkan": device.runtime_ready("vulkan"),
        })

    # More than one usable accelerator raises throughput but not the ceiling of
    # what a single job can do, so the bonus is small and capped.
    usable = len(inventory.usable_gpus)
    if usable > 1:
        best = min(100.0, best + min(5.0, usable - 1))
        notes.append(f"{usable} usable GPUs; scheduling is a throughput gain, not a larger single device.")
    return Score("gpu_compute", _clamp(best), MEASURED, DIMENSIONS[2][1],
                 {"devices": inputs, "usableDevices": usable}, notes)


def _gpu_memory(inventory: Inventory) -> Score:
    """Dedicated VRAM on a log curve from 512 MiB to 96 GiB.

    Shared-memory devices score 0 with ``measured`` confidence and a note. They
    are not scored against system RAM, because doing so would let an integrated
    GPU borrow the memory dimension's score and defeat the separation this
    module exists to enforce.
    """
    usable = inventory.usable_gpus
    if not usable:
        if inventory.gpu:
            return Score("gpu_memory", 0.0, MEASURED, DIMENSIONS[3][1],
                         {"vramTotalBytes": 0}, ["No usable GPU, so no usable video memory."])
        return Score("gpu_memory", None, UNKNOWN, DIMENSIONS[3][1], {}, ["No GPU devices were enumerated."])

    totals = [device.vram_total_bytes for device in usable]
    measured_totals = [item.value for item in totals if item.is_measured]
    if measured_totals:
        largest = max(measured_totals)
        confidence = MEASURED if len(measured_totals) == len(totals) else PARTIAL
        return Score("gpu_memory", _clamp(_log_scale(float(largest), 512.0 * _MIB, 96.0 * _GIB)), confidence,
                     DIMENSIONS[3][1],
                     {
                         "largestVramBytes": largest,
                         "totalVramBytes": sum(measured_totals),
                         "devicesWithMeasuredVram": len(measured_totals),
                     },
                     ["Scored on the largest single device: a model must fit in one of them, not in their sum."])

    if all(item.state == "absent" for item in totals):
        return Score("gpu_memory", 0.0, MEASURED, DIMENSIONS[3][1],
                     {"largestVramBytes": 0},
                     ["Every usable GPU shares system memory; there is no dedicated pool. See the memory dimension."])
    return Score("gpu_memory", None, UNKNOWN, DIMENSIONS[3][1], {},
                 ["VRAM has no trustworthy source on this machine; a generic adapter-memory field is not read."])


def _storage_capacity(inventory: Inventory) -> Score:
    storage = inventory.storage
    available = storage.root_available_bytes.get(None)
    if not isinstance(available, int):
        return Score("storage_capacity", None, UNKNOWN, DIMENSIONS[4][1], {},
                     ["Free space on / was not measured."])
    notes = []
    if storage.read_only.get(False) is True:
        notes.append("The root filesystem is mounted read-only; capacity is not writable capacity.")
    return Score("storage_capacity", _clamp(_log_scale(float(available), 1.0 * _GIB, 2048.0 * _GIB)),
                 _confidence(storage.root_available_bytes, storage.root_total_bytes), DIMENSIONS[4][1],
                 {
                     "availableBytes": available,
                     "totalBytes": storage.root_total_bytes.get(None),
                     "filesystem": storage.filesystem.get(None),
                     "readOnly": storage.read_only.get(None),
                 }, notes)


def _storage_performance(inventory: Inventory) -> Score:
    storage = inventory.storage
    kind = storage.storage_class.get(None)
    pressure = storage.io_pressure_some_avg10.get(None)
    if kind is None:
        return Score("storage_performance", None, UNKNOWN, DIMENSIONS[5][1],
                     {"ioPressureSomeAvg10": pressure},
                     ["The backing device class could not be determined; speed is not guessed."])
    base = {"solid-state": 85.0, "rotational": 30.0}.get(kind, 50.0)
    notes = [f"Device class {kind}."]
    if isinstance(pressure, (int, float)) and pressure > 0:
        # PSI is a stall percentage; subtracting it directly means a filesystem
        # stalling half the time loses half its score.
        base = base * max(0.0, 1.0 - pressure / 100.0)
        notes.append(f"I/O pressure (PSI some avg10) is {pressure:.1f}%, applied as a proportional reduction.")
    return Score("storage_performance", _clamp(base),
                 _confidence(storage.storage_class, storage.io_pressure_some_avg10), DIMENSIONS[5][1],
                 {"storageClass": kind, "ioPressureSomeAvg10": pressure}, notes)


def _network_quality(inventory: Inventory) -> Score:
    network = inventory.network
    if not network.default_route.is_known:
        return Score("network_quality", None, UNKNOWN, DIMENSIONS[6][1], {},
                     ["The routing table could not be read; connectivity is neither claimed nor denied."])
    if not network.online:
        return Score("network_quality", 0.0, MEASURED, DIMENSIONS[6][1],
                     {"defaultRoute": False},
                     ["No default route. Anything requiring the network is ineligible, not merely slow."])

    kind = network.connection_type.get(None)
    base = {"wired": 85.0, "wireless": 60.0}.get(kind, 50.0)
    notes: list[str] = [f"Connection type {kind or 'unclassified'}."]
    metered = network.metered.get(None)
    if metered is True:
        base -= 25.0
        notes.append("The connection is metered; bulk transfer is a cost the user pays.")
    elif metered is None:
        notes.append("Metering is unknown, which policy treats as possibly metered.")
    latency = network.latency_ms.get(None)
    if isinstance(latency, (int, float)):
        notes.append(f"A configured endpoint answered in {latency:.0f} ms.")
    elif network.endpoint_reachable.get(None) is False:
        base -= 20.0
        notes.append("A route exists but no configured endpoint answered; this can be a captive portal.")
    return Score("network_quality", _clamp(base),
                 _confidence(network.default_route, network.connection_type), DIMENSIONS[6][1],
                 {
                     "defaultRoute": True,
                     "connectionType": kind,
                     "metered": metered,
                     "latencyMs": latency,
                     "endpointReachable": network.endpoint_reachable.get(None),
                 }, notes)


#: System memory below which no inference runtime can be hosted at all, GPU or
#: not. A CUDA or ROCm context, the loader, and the process itself all live in
#: system memory; the accelerator only changes where the *weights* live. Set at
#: 1 GiB, which is already optimistic for a CUDA context plus a host process.
HOST_RUNTIME_FLOOR_BYTES = 1 * _GIB


def _local_ai(inventory: Inventory, memory: Score, cpu: Score, gpu_compute: Score, gpu_memory: Score) -> Score:
    """Whether model inference can run here at all, and how capably.

    Two independent paths, and the larger wins: weights in VRAM bounded by VRAM
    and GPU compute, or weights in RAM bounded by system memory and cores. They
    are a maximum rather than a sum because a model runs on one of them.

    Underneath both is a **hard feasibility floor on system memory**. This is
    the correction that makes the dimension honest: a machine with eight 80 GB
    accelerators and a 512 MiB cgroup cannot run inference, because the runtime
    that would drive those accelerators does not fit. Bounding only the CPU path
    by memory — which an earlier version of this function did — let the GPU path
    score 96 on exactly that machine, which is the "powerful GPU hides a severe
    memory shortage" failure this module exists to prevent, reproduced inside
    the function meant to prevent it.
    """
    if memory.value is None:
        return Score("local_ai", None, UNKNOWN, DIMENSIONS[7][1], {},
                     ["Usable memory is unknown, so local inference feasibility is unknown."])

    usable = inventory.memory.usable_bytes(0) or 0
    confidence = PARTIAL if UNKNOWN in {memory.confidence, cpu.confidence} else memory.confidence

    if usable < HOST_RUNTIME_FLOOR_BYTES:
        # Scaled rather than flat zero so that 900 MiB and 64 MiB remain
        # distinguishable, and capped low enough that no requirement gated on
        # this dimension can be satisfied here.
        value = 10.0 * (usable / HOST_RUNTIME_FLOOR_BYTES)
        return Score("local_ai", _clamp(value), confidence, DIMENSIONS[7][1],
                     {
                         "usableBytes": usable,
                         "hostRuntimeFloorBytes": HOST_RUNTIME_FLOOR_BYTES,
                         "memoryScore": memory.value,
                         "gpuComputeScore": gpu_compute.value,
                         "gpuMemoryScore": gpu_memory.value,
                     },
                     [
                         f"Usable memory is below the {HOST_RUNTIME_FLOOR_BYTES // _MIB} MiB floor at which any "
                         "inference runtime can be hosted. An accelerator does not change this: the runtime "
                         "driving it lives in system memory.",
                     ])

    notes: list[str] = []
    if (gpu_compute.value or 0.0) >= 60.0 and (gpu_memory.value or 0.0) > 0.0:
        accelerated = min(gpu_compute.value or 0.0, gpu_memory.value or 0.0)
        notes.append("Weights can live in dedicated VRAM; bounded by the smaller of GPU compute and VRAM.")
    else:
        accelerated = 0.0
        if (gpu_compute.value or 0.0) >= 60.0:
            notes.append("A capable GPU is present but has no measured dedicated memory, so it does not raise this score.")

    cpu_path = min(memory.value, (cpu.value or 0.0) + 20.0)
    notes.append("The CPU path is bounded by usable memory; memory is a gate, never an average term.")
    return Score("local_ai", _clamp(max(accelerated, cpu_path)), confidence, DIMENSIONS[7][1],
                 {
                     "usableBytes": usable,
                     "hostRuntimeFloorBytes": HOST_RUNTIME_FLOOR_BYTES,
                     "memoryScore": memory.value,
                     "cpuScore": cpu.value,
                     "gpuComputeScore": gpu_compute.value,
                     "gpuMemoryScore": gpu_memory.value,
                     "acceleratedPath": accelerated,
                     "cpuPath": cpu_path,
                 }, notes)


def _graphics(inventory: Inventory, gpu_compute: Score) -> Score:
    display = inventory.display
    if not display.connected_outputs.is_known:
        return Score("graphics", None, UNKNOWN, DIMENSIONS[8][1], {},
                     ["Display state is unknown; local rendering capability is not assumed."])
    if not display.has_display:
        return Score("graphics", 0.0, MEASURED, DIMENSIONS[8][1],
                     {"connectedOutputs": display.connected_outputs.get(0)},
                     ["No connected display. Local rendering has nowhere to go, whatever the GPU can do."])
    accelerated = gpu_compute.value
    if accelerated is None:
        return Score("graphics", 25.0, PARTIAL, DIMENSIONS[8][1],
                     {"connectedOutputs": display.connected_outputs.get(0), "gpuComputeScore": None},
                     ["A display is connected but GPU state is unknown; only software rendering is assumed."])
    return Score("graphics", _clamp(min(100.0, 25.0 + accelerated * 0.75)), MEASURED, DIMENSIONS[8][1],
                 {
                     "connectedOutputs": display.connected_outputs.get(0),
                     "maxResolution": display.max_resolution.get(None),
                     "gpuComputeScore": accelerated,
                 },
                 ["A connected display floors this at 25: software rendering is always possible."])


def _audio(inventory: Inventory) -> Score:
    audio = inventory.audio
    if not audio.output_present.is_known:
        return Score("audio", None, UNKNOWN, DIMENSIONS[9][1], {}, ["Audio devices were not enumerated."])
    output = audio.output_present.get(False) is True
    capture = audio.input_present.get(False) is True
    value = (65.0 if output else 0.0) + (35.0 if capture else 0.0)
    notes = []
    if not output:
        notes.append("No playback endpoint; speech synthesis has nowhere to go and text output is the fallback.")
    if not capture:
        notes.append("No capture endpoint; speech recognition cannot run locally.")
    return Score("audio", _clamp(value), _confidence(audio.output_present, audio.input_present), DIMENSIONS[9][1],
                 {"playback": output, "capture": capture, "camera": audio.camera_present.get(None)}, notes)


def _interactive_desktop(inventory: Inventory, graphics: Score, memory: Score, cpu: Score) -> Score:
    display = inventory.display
    if graphics.value is None:
        return Score("interactive_desktop", None, UNKNOWN, DIMENSIONS[10][1], {},
                     ["Display state is unknown."])
    if graphics.value == 0.0:
        return Score("interactive_desktop", 0.0, MEASURED, DIMENSIONS[10][1],
                     {"headless": True},
                     ["Headless. A desktop session is not a thing this machine can present."])
    has_input = display.keyboard.get(False) is True or display.pointer.get(False) is True or display.touch.get(False) is True
    if not has_input and display.keyboard.is_known:
        return Score("interactive_desktop", 5.0, MEASURED, DIMENSIONS[10][1],
                     {"keyboard": False, "pointer": False, "touch": False},
                     ["A display is attached but no input device was found; nobody can drive this session."])
    # A desktop session is memory-hungry and latency-sensitive: the weakest of
    # graphics, memory and CPU decides what the experience is actually like.
    value = min(graphics.value, memory.value if memory.value is not None else 100.0,
                (cpu.value if cpu.value is not None else 100.0) + 15.0)
    return Score("interactive_desktop", _clamp(value),
                 PARTIAL if UNKNOWN in {memory.confidence, cpu.confidence} else MEASURED, DIMENSIONS[10][1],
                 {
                     "graphicsScore": graphics.value,
                     "memoryScore": memory.value,
                     "cpuScore": cpu.value,
                     "keyboard": display.keyboard.get(None),
                     "pointer": display.pointer.get(None),
                     "touch": display.touch.get(None),
                 },
                 ["Bounded by the weakest of graphics, memory and CPU: a desktop is only as good as its worst input."])


def _background_capacity(inventory: Inventory, cpu: Score, memory: Score) -> Score:
    """Headroom for work nobody is waiting on, after current load and heat.

    This is the dimension that shrinks under pressure while ``cpu_compute``
    stays put, which is the point: capacity is a property of the hardware,
    headroom is a property of the moment.
    """
    if cpu.value is None:
        return Score("background_capacity", None, UNKNOWN, DIMENSIONS[11][1], {},
                     ["CPU capacity is unknown, so headroom cannot be derived from it."])
    cores = inventory.cpu.effective_cores(1.0)
    load = inventory.cpu.load_average_1m.get(None)
    notes: list[str] = []
    value = cpu.value
    if isinstance(load, (int, float)) and cores > 0:
        saturation = min(1.0, load / cores)
        value *= max(0.0, 1.0 - saturation)
        notes.append(f"Load average {load:.2f} over {cores:g} effective cores is {saturation * 100:.0f}% saturation.")
    else:
        notes.append("Load average was not measured; capacity is reported without a saturation reduction.")
    if inventory.thermal.throttled.get(False) is True:
        value *= 0.5
        notes.append("Active cooling is engaged; background work is halved to leave the machine room to recover.")
    if inventory.power.on_battery:
        value *= 0.5
        notes.append("Running on battery; background work is halved.")
    if memory.value is not None:
        value = min(value, memory.value)
        notes.append("Bounded by the memory dimension: background work that cannot allocate is not headroom.")
    return Score("background_capacity", _clamp(value), cpu.confidence, DIMENSIONS[11][1],
                 {
                     "cpuScore": cpu.value,
                     "loadAverage1m": load,
                     "effectiveCores": cores,
                     "throttled": inventory.thermal.throttled.get(None),
                     "onBattery": inventory.power.on_battery,
                 }, notes)


def _energy_thermal_headroom(inventory: Inventory) -> Score:
    power = inventory.power
    thermal = inventory.thermal
    if not power.supply.is_known and not thermal.throttled.is_known:
        return Score("energy_thermal_headroom", None, UNKNOWN, DIMENSIONS[12][1], {},
                     ["Neither power source nor thermal state was measured."])

    value = 100.0
    notes: list[str] = []
    supply = power.supply.get(None)
    if supply == "battery":
        percent = power.battery_percent.get(None)
        if isinstance(percent, (int, float)):
            # Below 20% the machine is minutes from the user losing work, so the
            # curve is steep rather than linear across the whole range.
            value = 30.0 + 40.0 * min(1.0, percent / 100.0) if percent >= 20 else 10.0 * (percent / 20.0)
            notes.append(f"On battery at {percent:.0f}%.")
        else:
            value = 40.0
            notes.append("On battery; charge level unknown, so a conservative allowance is used.")
    elif supply == "ac":
        notes.append("On mains power.")
    elif power.supply.state == "absent":
        notes.append("No power supplies are exposed; treated as permanently powered.")

    if power.power_saving.get(False) is True:
        value = min(value, 45.0)
        notes.append("A power-saving profile or governor is active; the platform has already chosen economy.")
    cooling = thermal.cooling_state.get(None)
    if isinstance(cooling, (int, float)) and cooling > 0:
        value *= max(0.0, 1.0 - cooling)
        notes.append(f"Cooling is engaged at {cooling * 100:.0f}% of maximum effort.")
    return Score("energy_thermal_headroom", _clamp(value),
                 _confidence(power.supply, thermal.throttled), DIMENSIONS[12][1],
                 {
                     "supply": supply,
                     "batteryPercent": power.battery_percent.get(None),
                     "powerSaving": power.power_saving.get(None),
                     "coolingState": cooling,
                     "maxCelsius": thermal.max_celsius.get(None),
                 }, notes)


def compute_scores(inventory: Inventory) -> ScoreSet:
    """Every dimension, computed from one inventory. Pure and deterministic."""
    cpu = _cpu_compute(inventory)
    memory = _memory_available(inventory)
    gpu_compute = _gpu_compute(inventory)
    gpu_memory = _gpu_memory(inventory)
    graphics = _graphics(inventory, gpu_compute)
    scores = {
        "cpu_compute": cpu,
        "memory_available": memory,
        "gpu_compute": gpu_compute,
        "gpu_memory": gpu_memory,
        "storage_capacity": _storage_capacity(inventory),
        "storage_performance": _storage_performance(inventory),
        "network_quality": _network_quality(inventory),
        "local_ai": _local_ai(inventory, memory, cpu, gpu_compute, gpu_memory),
        "graphics": graphics,
        "audio": _audio(inventory),
        "interactive_desktop": _interactive_desktop(inventory, graphics, memory, cpu),
        "background_capacity": _background_capacity(inventory, cpu, memory),
        "energy_thermal_headroom": _energy_thermal_headroom(inventory),
    }
    return ScoreSet(scores)
