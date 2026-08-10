# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether this machine should be listening at all, and how capably.

§10 says to use the existing capability runtime, and this module reads it
rather than measuring anything — the same position
:mod:`companion.voice.policy` takes and for the same reason: Bunny OS has one
capability service, and a second classifier living inside speech input would
eventually disagree with the first. The signals come from
:func:`companion.capability_bridge.capability_signals`, plus the facts only
this subsystem can supply: whether a capture device is reachable, whether a
recogniser is installed, and how much memory its model claims to need.

**The outcomes are §10's four and no others.**

``local-streaming-recognition``
    The full path: frames fed to a local recogniser as they arrive, partial
    transcripts on the way.
``local-batch-recognition``
    Capture first, recognise after. Cheaper while the microphone is open —
    the machine under pressure spends nothing on recognition until the user
    stops talking — at the price of no partials.
``capture-disabled-transcript-manual``
    The microphone may not open, and the surface offers the transcript box
    for typing instead. The distinction from the next outcome is *why*: here
    the machine or its policy refuses capture while text entry is untouched.
``typed-input-only``
    Speech input is off — the user's own setting, or no capture device, or no
    recogniser. Typing is the whole of input, as it always safely can be.

**Local incapability never authorises remote recognition.** There is no remote
recogniser in this build; the descent below runs *down* to typing and has no
rung that leaves the machine. §10 states it, the request schema refuses the
locality, the recogniser contract refuses the declaration — and this module is
where somebody adding one would have to argue with all three.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import threading
from typing import Any, Mapping

from capability.apply.identity import digest

__all__ = [
    "SPEECH_INPUT_OUTCOMES",
    "SpeechInputDecision",
    "SpeechInputPolicy",
    "SpeechInputPreferences",
    "SpeechInputSignals",
    "evaluate",
    "signals_from_capability",
]

#: §10's four outcomes, most capable first. Compared by index, never by string.
SPEECH_INPUT_OUTCOMES = (
    "local-streaming-recognition",
    "local-batch-recognition",
    "capture-disabled-transcript-manual",
    "typed-input-only",
)

_OUTCOME_RANK = {name: index for index, name in enumerate(SPEECH_INPUT_OUTCOMES)}

_MIB = 1024 * 1024


@dataclass(frozen=True)
class SpeechInputPreferences:
    """What the user asked for. May only ever make capture *less* likely.

    The asymmetry every companion preference type carries: a setting that
    could raise capture above what the machine supports would make the system
    unstable, and one that could raise it above what policy permits would be a
    consent bypass with a checkbox. ``allow_immediate_submission`` is §13's
    guarded exception and is the only field here that widens anything — it
    widens what a *confirmed explicit request* may do, never what the
    microphone may do.
    """

    enabled: bool = True
    input_device: str = ""
    language: str = "en"
    locale: str = "en-GB"
    provider_preference: str = ""
    model_id: str = ""
    partial_transcripts: bool = True
    #: §13: off by default, and turning it on is an explicit user act the
    #: surface must accompany with a clear warning. Even on, every capture
    #: still carries its own ``confirmation_required`` and both must agree.
    allow_immediate_submission: bool = False
    #: ``interactive`` prefers streaming recognition; ``relaxed`` accepts the
    #: batch path. §10's user latency preference.
    latency_preference: str = "interactive"
    #: Whether raw audio may be retained past recognition. There is no ``True``
    #: path in this build: §8's default is the only policy, and the field
    #: exists so the indicator can honestly display where the answer comes
    #: from.
    retain_audio: bool = False

    def __post_init__(self) -> None:
        if self.latency_preference not in ("interactive", "relaxed"):
            raise ValueError(
                f"unknown latency preference: {self.latency_preference!r}"
            )
        if self.retain_audio:
            raise ValueError(
                "audio retention beyond active recognition is not available in this "
                "build; recordings are deleted when recognition ends"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "inputDevice": self.input_device,
            "language": self.language,
            "locale": self.locale,
            "providerPreference": self.provider_preference,
            "modelId": self.model_id,
            "partialTranscripts": self.partial_transcripts,
            "allowImmediateSubmission": self.allow_immediate_submission,
            "latencyPreference": self.latency_preference,
            "retainAudio": self.retain_audio,
        }


@dataclass(frozen=True)
class SpeechInputSignals:
    """The machine facts a speech-input decision is made from. None measured here."""

    capture_device_available: bool = False
    recognizer_available: bool = False
    #: A recogniser that can stream exists. When false while the one above is
    #: true, the machine can recognise but only in batch — the middle rung.
    streaming_recognizer_available: bool = False
    #: The selected recogniser's declared model memory requirement.
    model_memory_bytes: int = 0
    available_memory_bytes: int | None = None
    cpu_score: float | None = None
    on_battery: bool = False
    battery_percent: float | None = None
    thermal_throttled: bool = False
    foreground_workload: int = 0
    plan_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "captureDeviceAvailable": self.capture_device_available,
            "recognizerAvailable": self.recognizer_available,
            "streamingRecognizerAvailable": self.streaming_recognizer_available,
            "modelMemoryBytes": self.model_memory_bytes,
            "availableMemoryBytes": self.available_memory_bytes,
            "cpuScore": self.cpu_score,
            "onBattery": self.on_battery,
            "batteryPercent": self.battery_percent,
            "thermalThrottled": self.thermal_throttled,
            "foregroundWorkload": self.foreground_workload,
            "planId": self.plan_id,
        }


def signals_from_capability(
    signals: Mapping[str, Any],
    *,
    capture_device_available: bool,
    recognizer_available: bool,
    streaming_recognizer_available: bool,
    model_memory_bytes: int = 0,
    foreground_workload: int = 0,
    plan_id: str = "",
) -> SpeechInputSignals:
    """Read the §10 signals the capability runtime already produced.

    Read, never re-measured: a decision explained by a different measurement
    from the one it was made on is an explanation that will eventually be
    wrong in a way nobody can reproduce.
    """
    memory = signals.get("availableMemoryBytes")
    battery = signals.get("batteryPercent")
    cpu = signals.get("cpuScore")
    return SpeechInputSignals(
        capture_device_available=capture_device_available,
        recognizer_available=recognizer_available,
        streaming_recognizer_available=streaming_recognizer_available,
        model_memory_bytes=max(0, int(model_memory_bytes)),
        available_memory_bytes=(
            int(memory) if isinstance(memory, int) and not isinstance(memory, bool) else None
        ),
        cpu_score=(
            float(cpu) if isinstance(cpu, (int, float)) and not isinstance(cpu, bool) else None
        ),
        on_battery=bool(signals.get("onBattery", False)),
        battery_percent=(
            float(battery)
            if isinstance(battery, (int, float)) and not isinstance(battery, bool) else None
        ),
        thermal_throttled=bool(signals.get("thermalThrottled", False)),
        foreground_workload=max(0, int(foreground_workload)),
        plan_id=plan_id,
    )


@dataclass(frozen=True)
class SpeechInputDecision:
    """What this machine will do about speech input, and every reason."""

    outcome: str = "typed-input-only"
    eligible: str = "typed-input-only"
    limited_by_implementation: bool = False
    #: Whether partial transcripts survive the current pressure. §12 permits
    #: suppressing them without invalidating final recognition, and this is
    #: the field that says so before a capture starts.
    partial_transcripts_permitted: bool = True
    reasons: tuple[str, ...] = ()
    plan_id: str = ""
    plan_fingerprint: str = ""

    @property
    def may_capture(self) -> bool:
        return self.outcome in (
            "local-streaming-recognition", "local-batch-recognition",
        )

    @property
    def streaming(self) -> bool:
        return self.outcome == "local-streaming-recognition"

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "eligible": self.eligible,
            "limitedByImplementation": self.limited_by_implementation,
            "mayCapture": self.may_capture,
            "streaming": self.streaming,
            "partialTranscriptsPermitted": self.partial_transcripts_permitted,
            "remotePermitted": False,
            "reasons": list(self.reasons),
            "planId": self.plan_id,
            "planFingerprint": self.plan_fingerprint,
        }


def _degrade(current: str, floor: str) -> str:
    """The more restricted of two outcomes. Never moves back up the ladder."""
    return SPEECH_INPUT_OUTCOMES[max(_OUTCOME_RANK[current], _OUTCOME_RANK[floor])]


def evaluate(
    signals: SpeechInputSignals,
    preferences: SpeechInputPreferences | None = None,
) -> SpeechInputDecision:
    """Decide the outcome from the signals and the user's settings.

    A single pass down the ladder, collecting every reason that bites —
    deliberately not short-circuited, because a user asking "why can I not
    talk to it" deserves the whole answer.
    """
    preferences = preferences or SpeechInputPreferences()
    reasons: list[str] = []
    partials = preferences.partial_transcripts

    if not preferences.enabled:
        return SpeechInputDecision(
            outcome="typed-input-only",
            eligible="typed-input-only",
            partial_transcripts_permitted=False,
            reasons=("speech input is turned off; typing is the whole of input",),
            plan_id=signals.plan_id,
            plan_fingerprint=_fingerprint(signals, preferences),
        )

    eligible = "local-streaming-recognition"

    if not signals.capture_device_available:
        eligible = _degrade(eligible, "typed-input-only")
        reasons.append("no capture device is reachable; typing remains available")
    if not signals.recognizer_available:
        eligible = _degrade(eligible, "typed-input-only")
        reasons.append(
            "no local speech recogniser is installed; capture without recognition "
            "would be a recording nobody asked for, so input stays typed"
        )
    elif not signals.streaming_recognizer_available:
        eligible = _degrade(eligible, "local-batch-recognition")
        partials = False
        reasons.append(
            "the installed recogniser cannot stream; recognition runs after capture "
            "ends and there are no partial transcripts"
        )

    memory = signals.available_memory_bytes
    if memory is not None and signals.recognizer_available:
        needed = signals.model_memory_bytes or 128 * _MIB
        if memory < needed + 64 * _MIB:
            eligible = _degrade(eligible, "capture-disabled-transcript-manual")
            reasons.append(
                f"the recognition model claims {needed // _MIB} MiB and the machine has "
                f"{memory // _MIB} MiB free; capture is disabled rather than the model "
                "loaded into memory that is not there"
            )
        elif memory < needed * 2:
            eligible = _degrade(eligible, "local-batch-recognition")
            partials = False
            reasons.append(
                "memory is close to the model's requirement; recognition runs after "
                "capture rather than beside it, and partials are suppressed"
            )

    if signals.cpu_score is not None and signals.cpu_score < 1.0:
        if _OUTCOME_RANK[eligible] <= _OUTCOME_RANK["local-streaming-recognition"]:
            eligible = _degrade(eligible, "local-batch-recognition")
            partials = False
            reasons.append(
                "the capability runtime scores this processor below the threshold for "
                "streaming recognition; recognition runs after capture instead"
            )
    if signals.thermal_throttled:
        partials = False
        reasons.append("the machine is thermally throttled; partial transcripts are off")
    if signals.foreground_workload >= 2:
        partials = False
        reasons.append(
            f"{signals.foreground_workload} tasks are running; partial transcripts "
            "give way to the work"
        )
    if signals.on_battery and signals.battery_percent is not None and signals.battery_percent < 10:
        eligible = _degrade(eligible, "capture-disabled-transcript-manual")
        reasons.append("the battery is critically low; the microphone is not opened")

    if preferences.latency_preference == "relaxed" and eligible == "local-streaming-recognition":
        # A preference may narrow, so this is permitted: the user asked for
        # the cheaper path and gets it, partials included — batch has none.
        eligible = "local-batch-recognition"
        partials = False
        reasons.append("the user prefers the relaxed path; recognition runs after capture")

    outcome = eligible
    limited = False
    while outcome not in _IMPLEMENTED_OUTCOMES:  # pragma: no cover - all implemented
        limited = True
        outcome = SPEECH_INPUT_OUTCOMES[_OUTCOME_RANK[outcome] + 1]

    return SpeechInputDecision(
        outcome=outcome,
        eligible=eligible,
        limited_by_implementation=limited,
        partial_transcripts_permitted=partials and outcome == "local-streaming-recognition",
        reasons=tuple(reasons),
        plan_id=signals.plan_id,
        plan_fingerprint=_fingerprint(signals, preferences),
    )


_IMPLEMENTED_OUTCOMES = frozenset(SPEECH_INPUT_OUTCOMES)


def _fingerprint(signals: SpeechInputSignals, preferences: SpeechInputPreferences) -> str:
    return digest({"signals": signals.to_json(), "preferences": preferences.to_json()})


class SpeechInputPolicy:
    """Holds the current decision and moves it deterministically, with hysteresis.

    Degradation is immediate — a machine that just ran out of memory should
    stop offering capture now — and improvement requires
    :attr:`RESTORE_OBSERVATIONS` consecutive readings at the better level,
    because symmetric thresholds oscillate and a push-to-talk button that
    appears and disappears every few seconds is worse than one that stays
    conservative. A *user setting* changes take effect at once in both
    directions, exactly as :meth:`companion.voice.policy.VoicePolicy.set_preferences`
    argues.
    """

    RESTORE_OBSERVATIONS = 3

    def __init__(
        self,
        preferences: SpeechInputPreferences | None = None,
        *,
        restore_observations: int = RESTORE_OBSERVATIONS,
    ) -> None:
        self.preferences = preferences or SpeechInputPreferences()
        self.restore_observations = max(1, restore_observations)
        self._decision = SpeechInputDecision()
        self._observed = False
        self._pending: SpeechInputDecision | None = None
        self._streak = 0
        self._transitions: list[dict[str, Any]] = []
        self._guard = threading.RLock()

    @property
    def decision(self) -> SpeechInputDecision:
        with self._guard:
            return self._decision

    @property
    def transitions(self) -> tuple[dict[str, Any], ...]:
        with self._guard:
            return tuple(self._transitions)

    def set_preferences(self, preferences: SpeechInputPreferences) -> None:
        with self._guard:
            self.preferences = preferences
            self._pending = None
            self._streak = 0
            self._observed = False

    def observe(self, signals: SpeechInputSignals, *, monotonic: float = 0.0) -> SpeechInputDecision:
        candidate = evaluate(signals, self.preferences)
        with self._guard:
            current = self._decision
            current_rank = _OUTCOME_RANK[current.outcome]
            candidate_rank = _OUTCOME_RANK[candidate.outcome]

            if not self._observed:
                self._observed = True
                if candidate.outcome != current.outcome:
                    self._record(current, candidate, "initial", monotonic)
                self._decision = candidate
                self._pending = None
                self._streak = 0
                return candidate

            if candidate_rank > current_rank:
                self._record(current, candidate, "degraded", monotonic)
                self._decision = candidate
                self._pending = None
                self._streak = 0
                return candidate

            if candidate_rank < current_rank:
                if self._pending is not None and self._pending.outcome == candidate.outcome:
                    self._streak += 1
                else:
                    self._pending = candidate
                    self._streak = 1
                if self._streak >= self.restore_observations:
                    self._record(current, candidate, "restored", monotonic)
                    self._decision = candidate
                    self._pending = None
                    self._streak = 0
                    return candidate
                held = replace(
                    current,
                    reasons=current.reasons + (
                        f"the machine now supports {candidate.outcome}; restoring after "
                        f"{self.restore_observations - self._streak} more consistent readings",
                    ),
                )
                self._decision = held
                return held

            self._decision = candidate
            self._pending = None
            self._streak = 0
            return candidate

    def _record(
        self,
        before: SpeechInputDecision,
        after: SpeechInputDecision,
        kind: str,
        monotonic: float,
    ) -> None:
        self._transitions.append({
            "kind": kind,
            "from": before.outcome,
            "to": after.outcome,
            "atMonotonic": monotonic,
            "reasons": list(after.reasons),
        })
        if len(self._transitions) > 64:
            del self._transitions[:-64]

    def describe(self) -> dict[str, Any]:
        with self._guard:
            return {
                "decision": self._decision.to_json(),
                "preferences": self.preferences.to_json(),
                "restoreObservations": self.restore_observations,
                "pending": self._pending.outcome if self._pending else "",
                "streak": self._streak,
                "outcomes": list(SPEECH_INPUT_OUTCOMES),
                "transitions": list(self._transitions[-16:]),
            }
