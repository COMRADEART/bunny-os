# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Watching for the changes that should make the engine think again.

A monitor is where an adaptive system usually goes wrong. Sample too often and
it costs more than it saves, on precisely the machines that can least afford it.
React to every sample and services flap. React to none and the adaptation never
happens. This module is built around the four mechanisms that make the
difference, and it is worth being precise about what each one does, because they
are routinely confused:

**Hysteresis** — two thresholds, not one. Pressure is *entered* at one level and
*left* at a lower one, so a signal sitting on a boundary does not toggle. This
is about the value.

**Debounce** — a threshold crossing must persist for a minimum time before it
counts as an event. This is about how long the value has held.

**Cooldown** — after an event fires, the same event cannot fire again for a
period, whatever the signal does. This is about how often we are willing to act.

**Coalescing** — several events raised in the same sample become one
reevaluation, because the engine is going to look at everything anyway and
running it four times produces four identical plans.

Together they mean that a laptop whose free memory oscillates around a threshold
produces one event, not forty; and that the service which was suspended under
pressure is not restarted the instant memory blips upward, but only once the
recovery has actually held.

**Sampling is not free and is not assumed.** Every signal is optional and
individually switchable, because §18 requires this to be usable on a node where
reading ten sysfs files every thirty seconds is a measurable fraction of the
machine. A node can enable memory and nothing else.

**The monitor decides nothing.** It emits typed reasons. What to do about
``memory_pressure_entered`` is the engine's question, and the monitor has no
opinion — it cannot start, stop or reprioritise anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

__all__ = [
    "DEFAULT_SIGNALS",
    "EVENTS",
    "MonitorEvent",
    "MonitorSettings",
    "RuntimeMonitor",
    "Sample",
    "SignalConfig",
]

#: Every reevaluation reason the monitor can raise. A strict subset of
#: :data:`capability.apply.identity.REEVALUATION_REASONS`, which is what lets an
#: event be handed to the engine as a plan's stated cause without translation.
EVENTS = (
    "memory_pressure_entered",
    "memory_pressure_recovered",
    "thermal_limit_entered",
    "thermal_limit_recovered",
    "battery_critical",
    "battery_recovered",
    "network_lost",
    "network_restored",
    "display_attached",
    "display_removed",
    "audio_device_changed",
    "cpu_saturation_entered",
    "cpu_saturation_recovered",
    "gpu_memory_pressure_entered",
    "gpu_memory_pressure_recovered",
    "service_failed",
    "remote_provider_unavailable",
    "user_policy_changed",
    "manifest_registry_changed",
)

#: Events that mean the machine is in trouble now. These bypass the cooldown:
#: a cooldown that suppressed "memory is critically short" would be a stability
#: mechanism that let the machine run out of memory quietly.
EMERGENCY_EVENTS = frozenset({"memory_pressure_entered", "thermal_limit_entered", "battery_critical"})


@dataclass(frozen=True)
class SignalConfig:
    """One watched signal, and the arithmetic that turns it into an event.

    ``enter`` and ``leave`` are the two halves of the hysteresis band and they
    are not interchangeable: for a signal where *higher is worse* (memory
    pressure, temperature) ``enter`` is above ``leave``; for one where *lower is
    worse* (free memory, battery percent) it is below. ``higher_is_worse`` says
    which, so a misconfigured band is a value error rather than a monitor that
    silently never fires.
    """

    name: str
    enter_threshold: float
    leave_threshold: float
    entered_event: str
    recovered_event: str
    higher_is_worse: bool = True
    enabled: bool = True
    #: Seconds the condition must hold before the event is raised.
    debounce_seconds: float = 10.0
    #: Seconds before the same event may be raised again.
    cooldown_seconds: float = 60.0

    def __post_init__(self) -> None:
        for event in (self.entered_event, self.recovered_event):
            if event not in EVENTS:
                raise ValueError(f"unknown monitor event: {event!r}")
        if self.higher_is_worse and self.enter_threshold <= self.leave_threshold:
            raise ValueError(
                f"{self.name}: with higher_is_worse the enter threshold must be above the leave "
                "threshold, or there is no hysteresis band"
            )
        if not self.higher_is_worse and self.enter_threshold >= self.leave_threshold:
            raise ValueError(
                f"{self.name}: with lower_is_worse the enter threshold must be below the leave "
                "threshold, or there is no hysteresis band"
            )

    def breached(self, value: float) -> bool:
        return value >= self.enter_threshold if self.higher_is_worse else value <= self.enter_threshold

    def recovered(self, value: float) -> bool:
        return value < self.leave_threshold if self.higher_is_worse else value > self.leave_threshold

    def to_json(self) -> dict[str, Any]:
        return {
            "signal": self.name,
            "enabled": self.enabled,
            "enterThreshold": self.enter_threshold,
            "leaveThreshold": self.leave_threshold,
            "higherIsWorse": self.higher_is_worse,
            "debounceSeconds": self.debounce_seconds,
            "cooldownSeconds": self.cooldown_seconds,
            "enteredEvent": self.entered_event,
            "recoveredEvent": self.recovered_event,
        }


#: The signals a full node watches. Every one is off by default on a constrained
#: node except ``memory_pressure``, which is the one that decides whether the
#: machine survives.
DEFAULT_SIGNALS: tuple[SignalConfig, ...] = (
    SignalConfig(
        "memory_pressure", 60.0, 20.0,
        "memory_pressure_entered", "memory_pressure_recovered",
        higher_is_worse=True, debounce_seconds=10.0, cooldown_seconds=60.0,
    ),
    SignalConfig(
        "memory_available_fraction", 0.10, 0.25,
        "memory_pressure_entered", "memory_pressure_recovered",
        higher_is_worse=False, debounce_seconds=10.0, cooldown_seconds=60.0,
    ),
    SignalConfig(
        "cpu_saturation", 0.90, 0.60,
        "cpu_saturation_entered", "cpu_saturation_recovered",
        higher_is_worse=True, debounce_seconds=30.0, cooldown_seconds=120.0,
    ),
    SignalConfig(
        "thermal_celsius", 85.0, 70.0,
        "thermal_limit_entered", "thermal_limit_recovered",
        higher_is_worse=True, debounce_seconds=15.0, cooldown_seconds=120.0,
    ),
    SignalConfig(
        "battery_percent", 10.0, 25.0,
        "battery_critical", "battery_recovered",
        higher_is_worse=False, debounce_seconds=30.0, cooldown_seconds=300.0,
    ),
    SignalConfig(
        "gpu_memory_used_fraction", 0.92, 0.75,
        "gpu_memory_pressure_entered", "gpu_memory_pressure_recovered",
        higher_is_worse=True, debounce_seconds=15.0, cooldown_seconds=120.0,
    ),
)

#: Signals a constrained node watches. Memory only, sampled rarely.
CONSTRAINED_SIGNALS: tuple[SignalConfig, ...] = (
    replace(DEFAULT_SIGNALS[0], debounce_seconds=30.0, cooldown_seconds=300.0),
)


@dataclass(frozen=True)
class Sample:
    """One reading of everything the monitor is watching.

    Every field is optional, and ``None`` means *not measured*, never zero. A
    monitor that read an unmeasured battery as 0% would raise
    ``battery_critical`` on every desktop computer.
    """

    at_monotonic: float
    numeric: Mapping[str, float] = field(default_factory=dict)
    #: Boolean conditions: network up, display present, audio present.
    boolean: Mapping[str, bool] = field(default_factory=dict)
    #: Services observed to have failed since the last sample.
    failed_services: tuple[str, ...] = ()
    #: Remote providers that did not answer their bounded probe.
    unreachable_providers: tuple[str, ...] = ()
    #: Fingerprints, so a policy or manifest change is detected rather than polled.
    policy_fingerprint: str | None = None
    registry_fingerprint: str | None = None

    def value(self, name: str) -> float | None:
        found = self.numeric.get(name)
        return None if found is None else float(found)

    def to_json(self) -> dict[str, Any]:
        return {
            "atMonotonic": self.at_monotonic,
            "numeric": {key: self.numeric[key] for key in sorted(self.numeric)},
            "boolean": {key: self.boolean[key] for key in sorted(self.boolean)},
            "failedServices": list(self.failed_services),
            "unreachableProviders": list(self.unreachable_providers),
        }


@dataclass(frozen=True)
class MonitorEvent:
    """One typed reason to think again."""

    event: str
    at_monotonic: float
    signal: str = ""
    value: float | None = None
    threshold: float | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.event not in EVENTS:
            raise ValueError(f"unknown monitor event: {self.event!r}")

    @property
    def emergency(self) -> bool:
        return self.event in EMERGENCY_EVENTS

    def to_json(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "atMonotonic": self.at_monotonic,
            "signal": self.signal,
            "value": self.value,
            "threshold": self.threshold,
            "emergency": self.emergency,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MonitorSettings:
    """How often to look, and how hard to try not to react."""

    interval_seconds: float = 30.0
    signals: tuple[SignalConfig, ...] = DEFAULT_SIGNALS
    #: Coalesce every event from one sample into a single reevaluation.
    coalesce: bool = True
    #: Watch for services entering a failed state.
    watch_service_failures: bool = True
    #: Watch policy and manifest fingerprints.
    watch_configuration: bool = True

    def enabled_signals(self) -> tuple[SignalConfig, ...]:
        return tuple(item for item in self.signals if item.enabled)

    def to_json(self) -> dict[str, Any]:
        return {
            "intervalSeconds": self.interval_seconds,
            "coalesce": self.coalesce,
            "watchServiceFailures": self.watch_service_failures,
            "watchConfiguration": self.watch_configuration,
            "signals": [item.to_json() for item in self.signals],
        }


@dataclass
class _SignalState:
    """Where one signal is in its hysteresis and debounce cycle."""

    breached: bool = False
    #: When the current candidate condition first held. ``None`` when the signal
    #: is settled in its current state.
    pending_since: float | None = None
    pending_direction: str = ""       # "enter" | "leave"
    last_event_at: float | None = None
    last_value: float | None = None


@dataclass
class RuntimeMonitor:
    """Turns samples into reevaluation reasons, sparingly.

    Stateful by necessity — hysteresis, debounce and cooldown are all memory of
    what happened before — but with no clock of its own: every method takes the
    time from the sample. That is what makes the whole thing deterministic under
    test, and it is why there is no thread here. Something else decides when to
    call :meth:`observe`; this decides what it means.
    """

    settings: MonitorSettings = field(default_factory=MonitorSettings)
    states: dict[str, _SignalState] = field(default_factory=dict)
    last_sample_at: float | None = None
    last_policy_fingerprint: str | None = None
    last_registry_fingerprint: str | None = None
    known_failed: set[str] = field(default_factory=set)
    #: Events raised, most recent last. Bounded so a long-running monitor on a
    #: constrained node cannot grow without limit.
    history: list[MonitorEvent] = field(default_factory=list)
    history_limit: int = 256
    #: Booleans whose transitions are events in themselves.
    _booleans: dict[str, bool] = field(default_factory=dict)

    def due(self, now: float) -> bool:
        """Whether enough time has passed to be worth sampling.

        The monitor does not recalculate continuously; a caller polling this in
        a tight loop still samples at the configured interval.
        """
        if self.last_sample_at is None:
            return True
        return (now - self.last_sample_at) >= self.settings.interval_seconds

    def observe(self, sample: Sample) -> tuple[MonitorEvent, ...]:
        """Take one sample and return the events it justifies. Usually none."""
        now = sample.at_monotonic
        self.last_sample_at = now
        events: list[MonitorEvent] = []

        for config in self.settings.enabled_signals():
            value = sample.value(config.name)
            if value is None:
                # Unmeasured is not zero and not recovered. A signal that stops
                # being readable holds its state rather than resolving itself.
                continue
            events.extend(self._evaluate_signal(config, value, now))

        events.extend(self._evaluate_booleans(sample, now))

        if self.settings.watch_service_failures:
            for service_id in sorted(set(sample.failed_services) - self.known_failed):
                events.append(MonitorEvent(
                    "service_failed", now, signal="service",
                    detail=f"{service_id} entered a failed state",
                ))
            self.known_failed = set(sample.failed_services)

        for provider in sorted(sample.unreachable_providers):
            events.append(MonitorEvent(
                "remote_provider_unavailable", now, signal="provider",
                detail=f"{provider} did not answer its bounded reachability probe",
            ))

        if self.settings.watch_configuration:
            events.extend(self._evaluate_configuration(sample, now))

        self.history.extend(events)
        if len(self.history) > self.history_limit:
            del self.history[: len(self.history) - self.history_limit]
        return tuple(events)

    # ------------------------------------------------------------------ #

    def _evaluate_signal(self, config: SignalConfig, value: float, now: float) -> list[MonitorEvent]:
        state = self.states.setdefault(config.name, _SignalState())
        state.last_value = value

        if not state.breached and config.breached(value):
            direction = "enter"
        elif state.breached and config.recovered(value):
            direction = "leave"
        else:
            # Inside the band, or already where the value says it should be.
            # Any candidate change is abandoned: this is the debounce doing its
            # job, and it is why a signal that crosses the line for one sample
            # produces nothing at all.
            state.pending_since = None
            state.pending_direction = ""
            return []

        if state.pending_direction != direction:
            state.pending_since = now
            state.pending_direction = direction
            return []

        held = now - (state.pending_since if state.pending_since is not None else now)
        if held < config.debounce_seconds:
            return []

        event_name = config.entered_event if direction == "enter" else config.recovered_event
        emergency = event_name in EMERGENCY_EVENTS
        if not emergency and state.last_event_at is not None:
            if (now - state.last_event_at) < config.cooldown_seconds:
                # Held by the cooldown — *delayed*, not discarded.
                #
                # An earlier version flipped ``breached`` here and cleared the
                # pending direction, on the reasoning that the machine's view of
                # itself should stay accurate. Measured against a real kernel,
                # that silently destroyed the event: a recovery arriving inside
                # the cooldown window was suppressed, the state flipped so the
                # condition was no longer a transition, and the recovery could
                # never be raised again. The service stayed on the degraded plan
                # indefinitely, because nothing ever told the engine to look.
                #
                # A cooldown exists to bound how *often* we act, not to decide
                # that something did not happen. So the candidate is left
                # pending and fires on the first sample past the window.
                return []

        state.breached = direction == "enter"
        state.pending_since = None
        state.pending_direction = ""
        state.last_event_at = now
        return [MonitorEvent(
            event_name, now,
            signal=config.name,
            value=value,
            threshold=config.enter_threshold if direction == "enter" else config.leave_threshold,
            detail=(
                f"{config.name} was {value:g} against a {config.enter_threshold:g} entry threshold, "
                f"held for {held:.0f}s"
                if direction == "enter" else
                f"{config.name} returned to {value:g}, past the {config.leave_threshold:g} "
                f"recovery threshold, and held there for {held:.0f}s"
            ),
        )]

    def _evaluate_booleans(self, sample: Sample, now: float) -> list[MonitorEvent]:
        """Presence signals, where the transition is the event.

        No hysteresis: a display is plugged in or it is not, and there is no
        intermediate value to oscillate across. Debounce would only delay a
        response to something a person just did with their hands.
        """
        mapping = (
            ("network_online", "network_restored", "network_lost"),
            ("display_present", "display_attached", "display_removed"),
        )
        events: list[MonitorEvent] = []
        for name, on_event, off_event in mapping:
            value = sample.boolean.get(name)
            if value is None:
                continue
            previous = self._booleans.get(name)
            self._booleans[name] = value
            if previous is None or previous == value:
                continue
            events.append(MonitorEvent(
                on_event if value else off_event, now, signal=name,
                detail=f"{name} changed from {previous} to {value}",
            ))

        audio = sample.boolean.get("audio_present")
        if audio is not None:
            previous = self._booleans.get("audio_present")
            self._booleans["audio_present"] = audio
            if previous is not None and previous != audio:
                events.append(MonitorEvent(
                    "audio_device_changed", now, signal="audio_present",
                    detail=f"audio availability changed from {previous} to {audio}",
                ))
        return events

    def _evaluate_configuration(self, sample: Sample, now: float) -> list[MonitorEvent]:
        events: list[MonitorEvent] = []
        if sample.policy_fingerprint is not None:
            if self.last_policy_fingerprint is not None and sample.policy_fingerprint != self.last_policy_fingerprint:
                events.append(MonitorEvent(
                    "user_policy_changed", now, signal="policy",
                    detail="the effective capability policy changed",
                ))
            self.last_policy_fingerprint = sample.policy_fingerprint
        if sample.registry_fingerprint is not None:
            if self.last_registry_fingerprint is not None and sample.registry_fingerprint != self.last_registry_fingerprint:
                events.append(MonitorEvent(
                    "manifest_registry_changed", now, signal="registry",
                    detail="a service capability manifest changed",
                ))
            self.last_registry_fingerprint = sample.registry_fingerprint
        return events

    # ------------------------------------------------------------------ #

    def reevaluation_reason(self, events: Sequence[MonitorEvent]) -> str | None:
        """The single reason to hand the engine for a batch of events.

        Coalescing is not "pick the first". An emergency outranks everything,
        because a plan generated in response to a display being attached is not
        the plan a machine short of memory needs. Otherwise the events are
        ordered by the fixed :data:`EVENTS` vocabulary so that the same batch
        always produces the same reason.
        """
        if not events:
            return None
        if not self.settings.coalesce:
            return events[0].event
        emergencies = [item for item in events if item.emergency]
        pool = emergencies or list(events)
        return min(pool, key=lambda item: (EVENTS.index(item.event), item.signal)).event

    def status(self) -> dict[str, Any]:
        return {
            "lastSampleAtMonotonic": self.last_sample_at,
            "settings": self.settings.to_json(),
            "signals": [
                {
                    "signal": name,
                    "breached": state.breached,
                    "lastValue": state.last_value,
                    "pendingSince": state.pending_since,
                    "pendingDirection": state.pending_direction,
                    "lastEventAt": state.last_event_at,
                }
                for name, state in sorted(self.states.items())
            ],
            "knownFailedServices": sorted(self.known_failed),
            "recentEvents": [item.to_json() for item in self.history[-16:]],
        }


def sample_from_inventory(
    inventory: Any,
    *,
    at_monotonic: float,
    policy_fingerprint: str | None = None,
    registry_fingerprint: str | None = None,
    failed_services: Sequence[str] = (),
    unreachable_providers: Sequence[str] = (),
) -> Sample:
    """Build a sample from a freshly discovered inventory.

    Every value is taken from a measurement or omitted. There is no default and
    no estimate: an unmeasured signal must not be able to raise an event, and
    the only way to guarantee that is to leave it out of the sample entirely.
    """
    numeric: dict[str, float] = {}
    boolean: dict[str, bool] = {}

    pressure = inventory.memory.pressure_some_avg10.get(None)
    if isinstance(pressure, (int, float)) and not isinstance(pressure, bool):
        numeric["memory_pressure"] = float(pressure)

    usable = inventory.memory.usable_bytes(None)
    available = inventory.memory.usable_available_bytes(None)
    if isinstance(usable, int) and usable > 0 and isinstance(available, int):
        numeric["memory_available_fraction"] = available / usable

    load = inventory.cpu.load_average_1m.get(None)
    cores = inventory.cpu.effective_cores(0.0)
    if isinstance(load, (int, float)) and not isinstance(load, bool) and cores > 0:
        numeric["cpu_saturation"] = float(load) / cores

    temperature = inventory.thermal.max_celsius.get(None)
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        numeric["thermal_celsius"] = float(temperature)

    battery = inventory.power.battery_percent.get(None)
    if isinstance(battery, (int, float)) and not isinstance(battery, bool):
        numeric["battery_percent"] = float(battery)

    vram_used: list[float] = []
    for device in inventory.usable_gpus:
        total = device.vram_total_bytes.get(None)
        free = device.vram_available_bytes.get(None)
        if isinstance(total, int) and total > 0 and isinstance(free, int):
            vram_used.append((total - free) / total)
    if vram_used:
        numeric["gpu_memory_used_fraction"] = max(vram_used)

    if inventory.network.default_route.is_known:
        boolean["network_online"] = inventory.network.online
    if inventory.display.connected_outputs.is_known:
        boolean["display_present"] = inventory.display.has_display
    if inventory.audio.output_present.is_known:
        boolean["audio_present"] = inventory.audio.output_present.get(False) is True

    return Sample(
        at_monotonic=at_monotonic,
        numeric=numeric,
        boolean=boolean,
        failed_services=tuple(failed_services),
        unreachable_providers=tuple(unreachable_providers),
        policy_fingerprint=policy_fingerprint,
        registry_fingerprint=registry_fingerprint,
    )
