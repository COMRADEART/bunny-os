# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The normalized capability inventory: typed models and their JSON form.

Every measurable fact is an :class:`Observation`, which carries a value *and*
the reason it has that value. Three states are distinguished, and the
distinction is the whole point of this module:

``measured``
    The probe ran and returned this value.
``absent``
    The probe ran and the thing is not there. A machine with no battery has an
    ``absent`` battery, which is knowledge.
``unknown``
    The probe could not run, timed out, was refused, or returned something
    unparseable. Nothing is known.

``docs/phase-1/BUNNY_OS_PHASE_1.md`` §A.9 requires exactly this: *"A failed
probe yields absent, which is a distinct value from unknown and from a
plausible-looking default."* The reason is not tidiness. If a GPU probe fails
and the field defaults to ``0 VRAM``, the router makes a confident wrong
decision; if it defaults to ``unknown``, the router is conservative and says
why. A silently wrong capability field produces a silently wrong routing
decision, which is worse than a missing one.

Consumers must therefore never write ``inventory.memory.physical_bytes.value``
without checking the state, and are steered away from it: the accessor is
:meth:`Observation.get`, which requires a default the caller has thought about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from . import INVENTORY_SCHEMA_VERSION

__all__ = [
    "ABSENT",
    "AudioFacts",
    "CpuFacts",
    "DisplayFacts",
    "GpuFacts",
    "Inventory",
    "MEASURED",
    "MemoryFacts",
    "NetworkFacts",
    "Observation",
    "PowerFacts",
    "ProbeOutcome",
    "STATES",
    "StorageFacts",
    "SystemFacts",
    "ThermalFacts",
    "UNKNOWN",
    "absent",
    "inventory_from_json",
    "measured",
    "unknown",
]

MEASURED = "measured"
ABSENT = "absent"
UNKNOWN = "unknown"

#: The three availability states, in decreasing order of knowledge.
STATES = (MEASURED, ABSENT, UNKNOWN)


@dataclass(frozen=True)
class Observation:
    """One fact, with the provenance and confidence attached to it."""

    value: Any = None
    state: str = UNKNOWN
    source: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown observation state: {self.state!r}")
        if self.state != MEASURED and self.value is not None:
            raise ValueError("only a measured observation may carry a value")

    @property
    def is_measured(self) -> bool:
        return self.state == MEASURED

    @property
    def is_known(self) -> bool:
        """True when the probe ran, whether or not the hardware was there."""
        return self.state in (MEASURED, ABSENT)

    def get(self, default: Any) -> Any:
        """The value, or ``default`` when nothing was measured.

        The default is mandatory so that every call site records what it
        decided to assume. There is deliberately no zero-argument form: a
        caller that has not chosen a fallback has not thought about the
        unmeasured case, and this is the module whose entire purpose is that
        the unmeasured case be thought about.
        """
        return self.value if self.state == MEASURED else default

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {"state": self.state}
        if self.state == MEASURED:
            value["value"] = self.value
        if self.source:
            value["source"] = self.source
        if self.detail:
            value["detail"] = self.detail
        return value

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Observation":
        state = str(value.get("state", UNKNOWN))
        return cls(
            value=value.get("value") if state == MEASURED else None,
            state=state if state in STATES else UNKNOWN,
            source=str(value.get("source", "")),
            detail=str(value.get("detail", "")),
        )


def measured(value: Any, source: str, detail: str = "") -> Observation:
    return Observation(value=value, state=MEASURED, source=source, detail=detail)


def absent(source: str, detail: str = "") -> Observation:
    return Observation(state=ABSENT, source=source, detail=detail)


def unknown(source: str, detail: str = "") -> Observation:
    return Observation(state=UNKNOWN, source=source, detail=detail)


def _observations(**values: Observation) -> dict[str, Any]:
    return {name: item.to_json() for name, item in values.items()}


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SystemFacts:
    architecture: Observation = field(default_factory=lambda: unknown(""))
    kernel_release: Observation = field(default_factory=lambda: unknown(""))
    virtualized: Observation = field(default_factory=lambda: unknown(""))
    containerized: Observation = field(default_factory=lambda: unknown(""))
    container_runtime: Observation = field(default_factory=lambda: unknown(""))
    boot_id_present: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            architecture=self.architecture,
            kernelRelease=self.kernel_release,
            virtualized=self.virtualized,
            containerized=self.containerized,
            containerRuntime=self.container_runtime,
            bootIdPresent=self.boot_id_present,
        )


@dataclass(frozen=True)
class CpuFacts:
    vendor: Observation = field(default_factory=lambda: unknown(""))
    model: Observation = field(default_factory=lambda: unknown(""))
    physical_cores: Observation = field(default_factory=lambda: unknown(""))
    logical_threads: Observation = field(default_factory=lambda: unknown(""))
    instruction_sets: Observation = field(default_factory=lambda: unknown(""))
    max_frequency_hz: Observation = field(default_factory=lambda: unknown(""))
    virtualization_supported: Observation = field(default_factory=lambda: unknown(""))
    quota_cores: Observation = field(default_factory=lambda: unknown(""))
    load_average_1m: Observation = field(default_factory=lambda: unknown(""))
    frequency_throttled: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            vendor=self.vendor,
            model=self.model,
            physicalCores=self.physical_cores,
            logicalThreads=self.logical_threads,
            instructionSets=self.instruction_sets,
            maxFrequencyHz=self.max_frequency_hz,
            virtualizationSupported=self.virtualization_supported,
            quotaCores=self.quota_cores,
            loadAverage1m=self.load_average_1m,
            frequencyThrottled=self.frequency_throttled,
        )

    def effective_cores(self, default: float) -> float:
        """Schedulable cores: the cgroup quota when one is imposed.

        A 64-core host that has given this container 0.5 CPU has 0.5 cores. The
        physical count is the wrong number to budget against and is exactly the
        mistake this method exists to prevent.
        """
        quota = self.quota_cores.get(None)
        threads = self.logical_threads.get(None)
        candidates = [value for value in (quota, threads) if isinstance(value, (int, float)) and value > 0]
        return float(min(candidates)) if candidates else default


@dataclass(frozen=True)
class MemoryFacts:
    physical_bytes: Observation = field(default_factory=lambda: unknown(""))
    available_bytes: Observation = field(default_factory=lambda: unknown(""))
    cgroup_limit_bytes: Observation = field(default_factory=lambda: unknown(""))
    cgroup_usage_bytes: Observation = field(default_factory=lambda: unknown(""))
    swap_total_bytes: Observation = field(default_factory=lambda: unknown(""))
    swap_free_bytes: Observation = field(default_factory=lambda: unknown(""))
    pressure_some_avg10: Observation = field(default_factory=lambda: unknown(""))
    reserved_bytes: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            physicalBytes=self.physical_bytes,
            availableBytes=self.available_bytes,
            cgroupLimitBytes=self.cgroup_limit_bytes,
            cgroupUsageBytes=self.cgroup_usage_bytes,
            swapTotalBytes=self.swap_total_bytes,
            swapFreeBytes=self.swap_free_bytes,
            pressureSomeAvg10=self.pressure_some_avg10,
            reservedBytes=self.reserved_bytes,
        )

    def usable_bytes(self, default: int | None = None) -> int | None:
        """The smaller of physical memory and any imposed cgroup limit.

        This is the number the budget engine must use. Trusting
        ``physicalBytes`` inside a memory-limited container is how a service
        sized for a 256 GB host gets OOM-killed in a 512 MB cgroup.
        """
        physical = self.physical_bytes.get(None)
        limit = self.cgroup_limit_bytes.get(None)
        candidates = [value for value in (physical, limit) if isinstance(value, int) and value > 0]
        if not candidates:
            return default
        return min(candidates)

    def usable_available_bytes(self, default: int | None = None) -> int | None:
        """Free memory, never reported as more than the usable ceiling."""
        available = self.available_bytes.get(None)
        ceiling = self.usable_bytes(None)
        if not isinstance(available, int):
            return default
        if isinstance(ceiling, int):
            return min(available, ceiling)
        return available


@dataclass(frozen=True)
class GpuFacts:
    """One graphics or compute device.

    ``usable`` is deliberately not a probe result. A PCI device existing says
    nothing about whether anything can be run on it, and the brief and the
    Phase 1 specification agree on this point: driver and runtime readiness are
    evaluated separately from presence.
    """

    index: int = 0
    vendor: Observation = field(default_factory=lambda: unknown(""))
    device_id: Observation = field(default_factory=lambda: unknown(""))
    description: Observation = field(default_factory=lambda: unknown(""))
    kind: Observation = field(default_factory=lambda: unknown(""))
    driver: Observation = field(default_factory=lambda: unknown(""))
    render_node: Observation = field(default_factory=lambda: unknown(""))
    vram_total_bytes: Observation = field(default_factory=lambda: unknown(""))
    vram_available_bytes: Observation = field(default_factory=lambda: unknown(""))
    runtimes: Mapping[str, Observation] = field(default_factory=dict)

    @property
    def driver_ready(self) -> bool:
        """A bound kernel driver and a render node the user could open."""
        return bool(self.driver.get("")) and bool(self.render_node.get(""))

    def runtime_ready(self, name: str) -> bool:
        observation = self.runtimes.get(name)
        return bool(observation is not None and observation.get(False) is True)

    def to_json(self) -> dict[str, Any]:
        value = _observations(
            vendor=self.vendor,
            deviceId=self.device_id,
            description=self.description,
            kind=self.kind,
            driver=self.driver,
            renderNode=self.render_node,
            vramTotalBytes=self.vram_total_bytes,
            vramAvailableBytes=self.vram_available_bytes,
        )
        value["index"] = self.index
        value["driverReady"] = self.driver_ready
        value["runtimes"] = {name: item.to_json() for name, item in sorted(self.runtimes.items())}
        return value


@dataclass(frozen=True)
class AcceleratorFacts:
    kind: str = "unknown"
    description: Observation = field(default_factory=lambda: unknown(""))
    driver_ready: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        value = _observations(description=self.description, driverReady=self.driver_ready)
        value["kind"] = self.kind
        return value


@dataclass(frozen=True)
class StorageFacts:
    root_total_bytes: Observation = field(default_factory=lambda: unknown(""))
    root_available_bytes: Observation = field(default_factory=lambda: unknown(""))
    filesystem: Observation = field(default_factory=lambda: unknown(""))
    read_only: Observation = field(default_factory=lambda: unknown(""))
    storage_class: Observation = field(default_factory=lambda: unknown(""))
    io_pressure_some_avg10: Observation = field(default_factory=lambda: unknown(""))
    temporary_available_bytes: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            rootTotalBytes=self.root_total_bytes,
            rootAvailableBytes=self.root_available_bytes,
            filesystem=self.filesystem,
            readOnly=self.read_only,
            storageClass=self.storage_class,
            ioPressureSomeAvg10=self.io_pressure_some_avg10,
            temporaryAvailableBytes=self.temporary_available_bytes,
        )


@dataclass(frozen=True)
class NetworkFacts:
    interfaces_present: Observation = field(default_factory=lambda: unknown(""))
    carrier_up: Observation = field(default_factory=lambda: unknown(""))
    default_route: Observation = field(default_factory=lambda: unknown(""))
    connection_type: Observation = field(default_factory=lambda: unknown(""))
    metered: Observation = field(default_factory=lambda: unknown(""))
    endpoint_reachable: Observation = field(default_factory=lambda: unknown(""))
    latency_ms: Observation = field(default_factory=lambda: unknown(""))
    bandwidth_bits_per_second: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            interfacesPresent=self.interfaces_present,
            carrierUp=self.carrier_up,
            defaultRoute=self.default_route,
            connectionType=self.connection_type,
            metered=self.metered,
            endpointReachable=self.endpoint_reachable,
            latencyMs=self.latency_ms,
            bandwidthBitsPerSecond=self.bandwidth_bits_per_second,
        )

    @property
    def offline(self) -> bool:
        """True only when the machine is *known* to have no route.

        Unknown is not offline. Treating an unrun probe as "no network" would
        disable remote execution on a healthy machine whose probe was merely
        slow, and treating it as "network present" would send a task into a
        void. The callers therefore ask this question and the inverse
        (:attr:`online`) separately, and neither is the negation of the other.
        """
        return self.default_route.is_known and self.default_route.get(False) is not True

    @property
    def online(self) -> bool:
        return self.default_route.get(False) is True


@dataclass(frozen=True)
class PowerFacts:
    supply: Observation = field(default_factory=lambda: unknown(""))
    battery_present: Observation = field(default_factory=lambda: unknown(""))
    battery_percent: Observation = field(default_factory=lambda: unknown(""))
    power_saving: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            supply=self.supply,
            batteryPresent=self.battery_present,
            batteryPercent=self.battery_percent,
            powerSaving=self.power_saving,
        )

    @property
    def on_battery(self) -> bool:
        return self.supply.get("") == "battery"


@dataclass(frozen=True)
class ThermalFacts:
    max_celsius: Observation = field(default_factory=lambda: unknown(""))
    throttled: Observation = field(default_factory=lambda: unknown(""))
    cooling_state: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            maxCelsius=self.max_celsius,
            throttled=self.throttled,
            coolingState=self.cooling_state,
        )


@dataclass(frozen=True)
class DisplayFacts:
    headless: Observation = field(default_factory=lambda: unknown(""))
    connected_outputs: Observation = field(default_factory=lambda: unknown(""))
    max_resolution: Observation = field(default_factory=lambda: unknown(""))
    touch: Observation = field(default_factory=lambda: unknown(""))
    keyboard: Observation = field(default_factory=lambda: unknown(""))
    pointer: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            headless=self.headless,
            connectedOutputs=self.connected_outputs,
            maxResolution=self.max_resolution,
            touch=self.touch,
            keyboard=self.keyboard,
            pointer=self.pointer,
        )

    @property
    def has_display(self) -> bool:
        """A display is present only when something actually reported one."""
        outputs = self.connected_outputs.get(0)
        return isinstance(outputs, int) and outputs > 0


@dataclass(frozen=True)
class AudioFacts:
    output_present: Observation = field(default_factory=lambda: unknown(""))
    input_present: Observation = field(default_factory=lambda: unknown(""))
    camera_present: Observation = field(default_factory=lambda: unknown(""))

    def to_json(self) -> dict[str, Any]:
        return _observations(
            outputPresent=self.output_present,
            inputPresent=self.input_present,
            cameraPresent=self.camera_present,
        )


@dataclass(frozen=True)
class ProbeOutcome:
    """What one discovery probe did, and how long it was allowed to take."""

    name: str
    state: str = "ok"
    duration_ms: int = 0
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {"name": self.name, "state": self.state, "durationMs": self.duration_ms}
        if self.detail:
            value["detail"] = self.detail
        return value


@dataclass(frozen=True)
class Inventory:
    """The normalized, versioned capability inventory.

    Nothing here identifies the machine. There is no serial number, no MAC
    address, no hostname and no UUID: §14 of the brief and the repository's own
    ``docs/PRIVACY_MODEL.md`` both require that a capability document be safe to
    show a user and safe to attach to a diagnostic, and the cheapest way to
    guarantee that is never to collect the identifiers in the first place.
    """

    detected_at: str = ""
    system: SystemFacts = field(default_factory=SystemFacts)
    cpu: CpuFacts = field(default_factory=CpuFacts)
    memory: MemoryFacts = field(default_factory=MemoryFacts)
    gpu: Sequence[GpuFacts] = ()
    accelerators: Sequence[AcceleratorFacts] = ()
    storage: StorageFacts = field(default_factory=StorageFacts)
    network: NetworkFacts = field(default_factory=NetworkFacts)
    power: PowerFacts = field(default_factory=PowerFacts)
    thermal: ThermalFacts = field(default_factory=ThermalFacts)
    display: DisplayFacts = field(default_factory=DisplayFacts)
    audio: AudioFacts = field(default_factory=AudioFacts)
    probes: Sequence[ProbeOutcome] = ()
    detection_budget_ms: int = 0
    detection_duration_ms: int = 0

    @property
    def usable_gpus(self) -> list[GpuFacts]:
        """Devices with a bound driver *and* an openable render node.

        Presence is not usability. This property is the only sanctioned way to
        ask "can we put work on a GPU", and it is why a detected NVIDIA card
        with no driver loaded produces a CPU-only plan rather than a plan that
        fails at start-up.
        """
        return [item for item in self.gpu if item.driver_ready]

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": INVENTORY_SCHEMA_VERSION,
            "detectedAt": self.detected_at,
            "detection": {
                "budgetMs": self.detection_budget_ms,
                "durationMs": self.detection_duration_ms,
                "probes": [item.to_json() for item in self.probes],
            },
            "system": self.system.to_json(),
            "cpu": self.cpu.to_json(),
            "memory": self.memory.to_json(),
            "gpu": [item.to_json() for item in self.gpu],
            "accelerators": [item.to_json() for item in self.accelerators],
            "storage": self.storage.to_json(),
            "network": self.network.to_json(),
            "power": self.power.to_json(),
            "thermal": self.thermal.to_json(),
            "display": self.display.to_json(),
            "audio": self.audio.to_json(),
            "constraints": self.constraints_json(),
            "privacy": {
                "identifiersCollected": False,
                "transmitted": False,
                "note": "The inventory is local. Nothing in this document is uploaded by default.",
            },
        }

    def constraints_json(self) -> dict[str, Any]:
        """The restrictions that make this machine smaller than its hardware."""
        return {
            "memoryLimited": self.memory.cgroup_limit_bytes.is_measured,
            "cpuQuotaLimited": self.cpu.quota_cores.is_measured,
            "containerized": self.system.containerized.get(False) is True,
            "virtualized": self.system.virtualized.get(False) is True,
            "readOnlyRoot": self.storage.read_only.get(False) is True,
            "headless": not self.display.has_display,
            "offline": self.network.offline,
            "onBattery": self.power.on_battery,
            "thermallyThrottled": self.thermal.throttled.get(False) is True,
            "meteredNetwork": self.network.metered.get(False) is True,
        }


def now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _section(document: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name)
    return dict(value) if isinstance(value, Mapping) else {}


def _obs(section: Mapping[str, Any], name: str) -> Observation:
    value = section.get(name)
    return Observation.from_json(value) if isinstance(value, Mapping) else unknown("")


def inventory_from_json(document: Mapping[str, Any]) -> Inventory:
    """Rebuild an inventory from its JSON form.

    Used by the simulated-hardware fixtures and by ``--inventory`` on the CLI,
    so that a plan can be reproduced from a captured inventory on a machine
    that is not the one it came from.
    """
    version = document.get("schemaVersion")
    if version != INVENTORY_SCHEMA_VERSION:
        raise ValueError(f"unsupported inventory schemaVersion: {version!r}")

    system = _section(document, "system")
    cpu = _section(document, "cpu")
    memory = _section(document, "memory")
    storage = _section(document, "storage")
    network = _section(document, "network")
    power = _section(document, "power")
    thermal = _section(document, "thermal")
    display = _section(document, "display")
    audio = _section(document, "audio")
    detection = _section(document, "detection")

    gpus: list[GpuFacts] = []
    for index, item in enumerate(document.get("gpu") or []):
        if not isinstance(item, Mapping):
            continue
        runtimes = item.get("runtimes")
        gpus.append(GpuFacts(
            index=int(item.get("index", index)),
            vendor=_obs(item, "vendor"),
            device_id=_obs(item, "deviceId"),
            description=_obs(item, "description"),
            kind=_obs(item, "kind"),
            driver=_obs(item, "driver"),
            render_node=_obs(item, "renderNode"),
            vram_total_bytes=_obs(item, "vramTotalBytes"),
            vram_available_bytes=_obs(item, "vramAvailableBytes"),
            runtimes={
                str(name): Observation.from_json(value)
                for name, value in (runtimes.items() if isinstance(runtimes, Mapping) else ())
                if isinstance(value, Mapping)
            },
        ))

    accelerators: list[AcceleratorFacts] = []
    for item in document.get("accelerators") or []:
        if isinstance(item, Mapping):
            accelerators.append(AcceleratorFacts(
                kind=str(item.get("kind", "unknown")),
                description=_obs(item, "description"),
                driver_ready=_obs(item, "driverReady"),
            ))

    probes: list[ProbeOutcome] = []
    for item in detection.get("probes") or []:
        if isinstance(item, Mapping):
            probes.append(ProbeOutcome(
                name=str(item.get("name", "")),
                state=str(item.get("state", "ok")),
                duration_ms=int(item.get("durationMs", 0)),
                detail=str(item.get("detail", "")),
            ))

    return Inventory(
        detected_at=str(document.get("detectedAt", "")),
        system=SystemFacts(
            architecture=_obs(system, "architecture"),
            kernel_release=_obs(system, "kernelRelease"),
            virtualized=_obs(system, "virtualized"),
            containerized=_obs(system, "containerized"),
            container_runtime=_obs(system, "containerRuntime"),
            boot_id_present=_obs(system, "bootIdPresent"),
        ),
        cpu=CpuFacts(
            vendor=_obs(cpu, "vendor"),
            model=_obs(cpu, "model"),
            physical_cores=_obs(cpu, "physicalCores"),
            logical_threads=_obs(cpu, "logicalThreads"),
            instruction_sets=_obs(cpu, "instructionSets"),
            max_frequency_hz=_obs(cpu, "maxFrequencyHz"),
            virtualization_supported=_obs(cpu, "virtualizationSupported"),
            quota_cores=_obs(cpu, "quotaCores"),
            load_average_1m=_obs(cpu, "loadAverage1m"),
            frequency_throttled=_obs(cpu, "frequencyThrottled"),
        ),
        memory=MemoryFacts(
            physical_bytes=_obs(memory, "physicalBytes"),
            available_bytes=_obs(memory, "availableBytes"),
            cgroup_limit_bytes=_obs(memory, "cgroupLimitBytes"),
            cgroup_usage_bytes=_obs(memory, "cgroupUsageBytes"),
            swap_total_bytes=_obs(memory, "swapTotalBytes"),
            swap_free_bytes=_obs(memory, "swapFreeBytes"),
            pressure_some_avg10=_obs(memory, "pressureSomeAvg10"),
            reserved_bytes=_obs(memory, "reservedBytes"),
        ),
        gpu=tuple(gpus),
        accelerators=tuple(accelerators),
        storage=StorageFacts(
            root_total_bytes=_obs(storage, "rootTotalBytes"),
            root_available_bytes=_obs(storage, "rootAvailableBytes"),
            filesystem=_obs(storage, "filesystem"),
            read_only=_obs(storage, "readOnly"),
            storage_class=_obs(storage, "storageClass"),
            io_pressure_some_avg10=_obs(storage, "ioPressureSomeAvg10"),
            temporary_available_bytes=_obs(storage, "temporaryAvailableBytes"),
        ),
        network=NetworkFacts(
            interfaces_present=_obs(network, "interfacesPresent"),
            carrier_up=_obs(network, "carrierUp"),
            default_route=_obs(network, "defaultRoute"),
            connection_type=_obs(network, "connectionType"),
            metered=_obs(network, "metered"),
            endpoint_reachable=_obs(network, "endpointReachable"),
            latency_ms=_obs(network, "latencyMs"),
            bandwidth_bits_per_second=_obs(network, "bandwidthBitsPerSecond"),
        ),
        power=PowerFacts(
            supply=_obs(power, "supply"),
            battery_present=_obs(power, "batteryPresent"),
            battery_percent=_obs(power, "batteryPercent"),
            power_saving=_obs(power, "powerSaving"),
        ),
        thermal=ThermalFacts(
            max_celsius=_obs(thermal, "maxCelsius"),
            throttled=_obs(thermal, "throttled"),
            cooling_state=_obs(thermal, "coolingState"),
        ),
        display=DisplayFacts(
            headless=_obs(display, "headless"),
            connected_outputs=_obs(display, "connectedOutputs"),
            max_resolution=_obs(display, "maxResolution"),
            touch=_obs(display, "touch"),
            keyboard=_obs(display, "keyboard"),
            pointer=_obs(display, "pointer"),
        ),
        audio=AudioFacts(
            output_present=_obs(audio, "outputPresent"),
            input_present=_obs(audio, "inputPresent"),
            camera_present=_obs(audio, "cameraPresent"),
        ),
        probes=tuple(probes),
        detection_budget_ms=int(detection.get("budgetMs", 0) or 0),
        detection_duration_ms=int(detection.get("durationMs", 0) or 0),
    )


def merge_observations(preferred: Observation, fallback: Observation) -> Observation:
    """The better-known of two observations of the same fact."""
    order = {MEASURED: 0, ABSENT: 1, UNKNOWN: 2}
    return preferred if order[preferred.state] <= order[fallback.state] else fallback


def known_fraction(values: Iterable[Observation]) -> float:
    """Share of observations that actually ran. Drives score confidence."""
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if item.is_known) / len(items)
