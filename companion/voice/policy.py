# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether this machine should be speaking at all, and how much.

§11 says to use the existing capability plan, and this module reads it rather
than measuring anything. There is no hardware probe here and there must never
be, for the reason :mod:`companion.capability_bridge` gives: Bunny OS already
has one capability service, and a second classifier living inside the voice
runtime would eventually disagree with the first. When it did, the user would be
told one thing and the machine would do another.

So the signals come from :func:`companion.capability_bridge.capability_signals`
— the same reading the router made its decision on — plus two facts the
capability runtime does not and should not hold: whether an audio backend can
reach a device, and whether a local synthesiser is installed. Both are
properties of this subsystem, measured by this subsystem, and passed in.

**The outcomes are §11's four and no others.**

``local-neural-or-system-voice``
    The full path: a provider that hands us samples, played through our own
    backend, with amplitude visemes and measured synchronisation.
``local-lightweight-voice``
    A lighter provider, or the same provider without the sample-handling path —
    provider-owned playback, text-derived visemes. Cheaper and less capable.
``captions-only``
    Captions on screen, nothing spoken. The output is complete; the sound is not.
``silent-text-only``
    Captions on screen and the surface asked for no audio at all. Distinct from
    ``captions-only`` because the reasons differ: one is the machine's answer
    and the other is the user's, and telling a user their speaker is broken when
    they turned speech off would be wrong.

There are no named machine modes here — no "laptop profile", no "low-power
mode". §11 forbids them and the reason is that a mode is a bundle of decisions
somebody has to keep in step with the signals; these outcomes are computed from
the signals every time.

**Local incapability never authorises remote speech.** There is no remote
provider in this build, and :func:`companion.voice.request.may_speak_remotely`
returns ``False`` for every classification. This module's job is to be the place
where somebody adding one would have to argue for it: the descent below runs
*down* to captions and has no rung that leaves the machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import threading
from typing import Any, Mapping, Sequence

from capability.apply.identity import digest

from .request import Priority

__all__ = [
    "DEGRADATION_LADDER",
    "VOICE_OUTCOMES",
    "VoiceDecision",
    "VoicePolicy",
    "VoicePreferences",
    "VoiceSignals",
    "signals_from_capability",
]

#: §11's four outcomes, most capable first. Compared by index, never by string.
VOICE_OUTCOMES = (
    "local-neural-or-system-voice",
    "local-lightweight-voice",
    "captions-only",
    "silent-text-only",
)

_OUTCOME_RANK = {name: index for index, name in enumerate(VOICE_OUTCOMES)}

#: §12's ladder, as the descent this module actually performs. The middle rung
#: appears twice on purpose: "lighter local voice" and "non-streaming local
#: voice" are both ``local-lightweight-voice`` as an *outcome*, and what
#: distinguishes them is which path within it — a different provider, or the
#: same provider without our playback. The distinction is carried in
#: :attr:`VoiceDecision.reasons` rather than in a fifth outcome nobody asked for.
DEGRADATION_LADDER = (
    ("preferred local voice", "local-neural-or-system-voice"),
    ("lighter local voice", "local-lightweight-voice"),
    ("non-streaming local voice", "local-lightweight-voice"),
    ("captions only", "captions-only"),
)

_MIB = 1024 * 1024
_GIB = 1024 * _MIB


@dataclass(frozen=True)
class VoicePreferences:
    """What the user asked for. May only ever make the output quieter.

    That asymmetry is the same one
    :class:`companion.presentation.AccessibilityPreferences` holds and is there
    for the same reason: a preference that could *raise* the presentation above
    what the machine supports would be a setting that makes a system unstable,
    and a preference that could raise it above what policy permits would be a
    consent bypass with a checkbox.
    """

    enabled: bool = True
    voice_id: str = ""
    language: str = "en"
    locale: str = "en-GB"
    speaking_rate: float = 1.0
    volume: float = 1.0
    #: Narration of intermediate states. Off by default: a companion that reads
    #: every status line aloud is exhausting, and the captions carry them.
    speak_progress: bool = False
    speak_decorative: bool = False
    prefer_streaming: bool = False
    #: The user relies on speech for access rather than convenience. Raises the
    #: floor: progress narration is kept under pressure that would otherwise
    #: drop it, because for this user it is not decoration.
    accessibility_required: bool = False
    #: A screen reader is already speaking. Speech is suppressed entirely —
    #: two voices reading the same screen is worse than either alone — while
    #: captions, which the screen reader reads, remain.
    screen_reader_active: bool = False
    preferred_device: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "voiceId": self.voice_id,
            "language": self.language,
            "locale": self.locale,
            "speakingRate": self.speaking_rate,
            "volume": self.volume,
            "speakProgress": self.speak_progress,
            "speakDecorative": self.speak_decorative,
            "preferStreaming": self.prefer_streaming,
            "accessibilityRequired": self.accessibility_required,
            "screenReaderActive": self.screen_reader_active,
            "preferredDevice": self.preferred_device,
        }


@dataclass(frozen=True)
class VoiceSignals:
    """The machine facts a voice decision is made from. None measured here."""

    audio_output_available: bool = False
    local_provider_available: bool = False
    #: A provider that hands over samples exists. When this is ``False`` and
    #: ``local_provider_available`` is ``True``, the machine can speak but
    #: cannot do amplitude visemes — exactly the middle rung.
    synthesis_provider_available: bool = False
    available_memory_bytes: int | None = None
    cpu_score: float | None = None
    on_battery: bool = False
    battery_percent: float | None = None
    thermal_throttled: bool = False
    #: How many tasks the companion runtime is running right now. §11's
    #: "foreground workload": speech competes with the work the user is actually
    #: waiting for, and on a busy machine the work wins.
    foreground_workload: int = 0
    #: The capability plan this reading came from, by identity. Carried so a
    #: decision made ten minutes ago can be recognised as stale, exactly as
    #: :class:`companion.capability_bridge.CapabilityDecision` does.
    plan_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "audioOutputAvailable": self.audio_output_available,
            "localProviderAvailable": self.local_provider_available,
            "synthesisProviderAvailable": self.synthesis_provider_available,
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
    audio_output_available: bool,
    local_provider_available: bool,
    synthesis_provider_available: bool,
    foreground_workload: int = 0,
    plan_id: str = "",
) -> VoiceSignals:
    """Read the §11 signals the capability runtime already produced.

    Read, never re-measured — the position
    :func:`companion.capability_bridge.capability_signals` takes and for the
    same reason: two probes of "how much memory is free" taken a second apart
    disagree, and a decision explained by a different measurement from the one
    it was made on is an explanation that will eventually be wrong in a way
    nobody can reproduce.
    """
    memory = signals.get("availableMemoryBytes")
    battery = signals.get("batteryPercent")
    cpu = signals.get("cpuScore")
    return VoiceSignals(
        audio_output_available=audio_output_available,
        local_provider_available=local_provider_available,
        synthesis_provider_available=synthesis_provider_available,
        available_memory_bytes=(
            int(memory) if isinstance(memory, int) and not isinstance(memory, bool) else None
        ),
        cpu_score=float(cpu) if isinstance(cpu, (int, float)) and not isinstance(cpu, bool) else None,
        on_battery=bool(signals.get("onBattery", False)),
        battery_percent=(
            float(battery) if isinstance(battery, (int, float)) and not isinstance(battery, bool) else None
        ),
        thermal_throttled=bool(signals.get("thermalThrottled", False)),
        foreground_workload=max(0, int(foreground_workload)),
        plan_id=plan_id,
    )


@dataclass(frozen=True)
class VoiceDecision:
    """What this machine will do about speech, and every reason.

    ``eligible`` and ``outcome`` are kept apart for the same reason
    :class:`companion.presentation.PresentationRecommendation` keeps them apart:
    one is what the machine and the policy would permit, the other is what this
    build will actually do. Saying "captions only" when the honest answer is
    "this machine could speak but nothing here can drive its provider" would
    misattribute a software gap to the hardware.
    """

    outcome: str = "captions-only"
    eligible: str = "captions-only"
    limited_by_implementation: bool = False
    #: The least urgent utterance that will be spoken. Everything below this
    #: rank is dropped by policy and recorded as such. §12's thermal, battery
    #: and workload pressure all express themselves through this one field,
    #: which is why "decorative speech is disabled" is a comparison rather than
    #: a special case.
    minimum_priority: Priority = Priority.TASK_RESULT
    #: How many utterances may be synthesised at once. §12's CPU-pressure rung.
    #: One by default — §6 permits at most one foreground utterance — and zero
    #: is not reachable, because zero would be captions-only expressed as a
    #: concurrency.
    synthesis_concurrency: int = 1
    prefer_streaming: bool = False
    remote_permitted: bool = False
    reasons: tuple[str, ...] = ()
    plan_id: str = ""
    plan_fingerprint: str = ""

    @property
    def speaks(self) -> bool:
        return self.outcome in ("local-neural-or-system-voice", "local-lightweight-voice")

    def permits(self, priority: Priority) -> bool:
        return self.speaks and priority.value <= self.minimum_priority.value

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "eligible": self.eligible,
            "limitedByImplementation": self.limited_by_implementation,
            "speaks": self.speaks,
            "minimumPriority": self.minimum_priority.wire,
            "synthesisConcurrency": self.synthesis_concurrency,
            "preferStreaming": self.prefer_streaming,
            "remotePermitted": self.remote_permitted,
            "reasons": list(self.reasons),
            "planId": self.plan_id,
            "planFingerprint": self.plan_fingerprint,
        }


def _degrade(current: str, floor: str) -> str:
    """The quieter of two outcomes. Never moves back up the ladder."""
    return VOICE_OUTCOMES[max(_OUTCOME_RANK[current], _OUTCOME_RANK[floor])]


def _lower(current: Priority, floor: Priority) -> Priority:
    """The stricter of two priority floors. Never becomes more permissive."""
    return current if current.value <= floor.value else floor


def evaluate(
    signals: VoiceSignals,
    preferences: VoicePreferences | None = None,
) -> VoiceDecision:
    """Decide the outcome from the signals and the user's settings.

    A single pass down the ladder, applying every constraint that bites and
    collecting a reason for each. Deliberately not short-circuited: a user asking
    "why is it not talking" deserves the whole answer, not the first thing that
    happened to be checked.
    """
    preferences = preferences or VoicePreferences()
    reasons: list[str] = []

    eligible = "local-neural-or-system-voice"
    minimum = Priority.DECORATIVE if preferences.speak_decorative else (
        Priority.PROGRESS_UPDATE if preferences.speak_progress else Priority.TASK_RESULT
    )
    concurrency = 1
    prefer_streaming = preferences.prefer_streaming

    # -- the user's own settings, first, because none of the rest matters if
    #    they turned it off ------------------------------------------------
    if not preferences.enabled:
        return VoiceDecision(
            outcome="silent-text-only",
            eligible="silent-text-only",
            minimum_priority=Priority.CRITICAL_WARNING,
            reasons=("speech is turned off; the captions are the whole of the output",),
            plan_id=signals.plan_id,
            plan_fingerprint=_fingerprint(signals, preferences),
        )
    if preferences.screen_reader_active:
        return VoiceDecision(
            outcome="silent-text-only",
            eligible="silent-text-only",
            minimum_priority=Priority.CRITICAL_WARNING,
            reasons=(
                "a screen reader is active and is already reading the captions; a second "
                "voice over the top would make both harder to follow",
            ),
            plan_id=signals.plan_id,
            plan_fingerprint=_fingerprint(signals, preferences),
        )

    # -- what the machine can do ------------------------------------------
    if not signals.local_provider_available:
        eligible = _degrade(eligible, "captions-only")
        reasons.append("no local speech provider is installed; the captions are the output")
    elif not signals.synthesis_provider_available:
        eligible = _degrade(eligible, "local-lightweight-voice")
        prefer_streaming = True
        reasons.append(
            "no provider hands over audio samples, so playback belongs to the provider: "
            "mouth timing is derived from the text rather than measured, and pause is unavailable"
        )
    if not signals.audio_output_available:
        eligible = _degrade(eligible, "captions-only")
        reasons.append("no audio output device is reachable; the captions remain")

    memory = signals.available_memory_bytes
    if memory is not None:
        if memory < 64 * _MIB:
            eligible = _degrade(eligible, "captions-only")
            reasons.append("less than 64 MiB is available; speech is not attempted")
        elif memory < 192 * _MIB:
            eligible = _degrade(eligible, "local-lightweight-voice")
            prefer_streaming = True
            reasons.append(
                "available memory is below the budget for holding synthesised audio, "
                "so a lighter provider-owned path is used"
            )

    if signals.cpu_score is not None and signals.cpu_score < 1.0:
        concurrency = 1
        minimum = _lower(minimum, Priority.TASK_RESULT)
        reasons.append(
            "the capability runtime scores this processor below the threshold for "
            "concurrent synthesis; narration is limited to results and above"
        )
    if signals.foreground_workload >= 2:
        concurrency = 1
        minimum = _lower(minimum, Priority.TASK_RESULT)
        reasons.append(
            f"{signals.foreground_workload} tasks are running; speech gives way to the work"
        )
    if signals.thermal_throttled:
        minimum = _lower(minimum, Priority.TASK_RESULT)
        reasons.append("the machine is thermally throttled; decorative speech is off")
    if signals.on_battery and signals.battery_percent is not None:
        if signals.battery_percent < 10:
            eligible = _degrade(eligible, "captions-only")
            reasons.append("the battery is critically low; nothing non-essential is spoken")
        elif signals.battery_percent < 25:
            minimum = _lower(minimum, Priority.TASK_ERROR)
            reasons.append("the battery is low; only errors and above are spoken")

    # -- accessibility raises the floor back up ---------------------------
    if preferences.accessibility_required and eligible != "captions-only":
        # Deliberately after the pressure rules. For a user who relies on speech
        # rather than enjoying it, progress narration is not decoration, and the
        # thermal and workload rules above would otherwise have silenced the
        # thing they depend on. It cannot raise the *outcome* — a missing
        # speaker is still a missing speaker — only the priority floor.
        if minimum.value < Priority.PROGRESS_UPDATE.value:
            minimum = Priority.PROGRESS_UPDATE
            reasons.append(
                "speech is an accessibility requirement for this user, so progress "
                "narration is kept under pressure that would otherwise drop it"
            )

    outcome = eligible
    limited = False
    # This build implements every outcome in the list, so nothing is filtered
    # out here. The loop is kept because §11's list is the *specification* and a
    # future outcome added to it must not be selectable before it is written —
    # the same guard :func:`companion.presentation.select_presentation` uses.
    while outcome not in _IMPLEMENTED_OUTCOMES:
        limited = True
        outcome = VOICE_OUTCOMES[_OUTCOME_RANK[outcome] + 1]

    return VoiceDecision(
        outcome=outcome,
        eligible=eligible,
        limited_by_implementation=limited,
        minimum_priority=minimum,
        synthesis_concurrency=concurrency,
        prefer_streaming=prefer_streaming,
        # Not computed and not configurable. There is no remote speech path in
        # this build, and local incapability is not an argument for one.
        remote_permitted=False,
        reasons=tuple(reasons),
        plan_id=signals.plan_id,
        plan_fingerprint=_fingerprint(signals, preferences),
    )


#: Every outcome this build can actually produce.
_IMPLEMENTED_OUTCOMES = frozenset(VOICE_OUTCOMES)


def _fingerprint(signals: VoiceSignals, preferences: VoicePreferences) -> str:
    return digest({"signals": signals.to_json(), "preferences": preferences.to_json()})


class VoicePolicy:
    """Holds the current decision and moves it deterministically, with hysteresis.

    §12 requires recovery to have hysteresis and this is where it lives.
    Degradation is *immediate* — a machine that just got hot should stop
    narrating now — and improvement requires :attr:`RESTORE_OBSERVATIONS`
    consecutive readings at the better level. The asymmetry is deliberate and it
    is the whole mechanism: symmetric thresholds oscillate, and a companion that
    alternates between speaking and silent every few seconds is worse than one
    that stays quiet.

    Nothing here touches a task. :meth:`observe` returns a decision and a list
    of transitions; the worker acts on it; the runtime never sees it.
    """

    RESTORE_OBSERVATIONS = 3

    def __init__(
        self,
        preferences: VoicePreferences | None = None,
        *,
        restore_observations: int = RESTORE_OBSERVATIONS,
    ) -> None:
        self.preferences = preferences or VoicePreferences()
        self.restore_observations = max(1, restore_observations)
        # Deliberately the quietest outcome, so a policy that is never asked
        # anything never speaks. It is a *placeholder* rather than an observed
        # degradation, which is why ``_observed`` exists: hysteresis protects
        # against a flapping machine, and there is nothing to flap against
        # before the first reading. Without the flag a perfectly good machine
        # took three refresh cycles to start speaking, and the tests caught it.
        self._decision = VoiceDecision()
        self._observed = False
        self._pending: VoiceDecision | None = None
        self._streak = 0
        self._transitions: list[dict[str, Any]] = []
        self._guard = threading.RLock()

    @property
    def decision(self) -> VoiceDecision:
        with self._guard:
            return self._decision

    @property
    def transitions(self) -> tuple[dict[str, Any], ...]:
        with self._guard:
            return tuple(self._transitions)

    def set_preferences(self, preferences: VoicePreferences) -> None:
        """A user changing a setting takes effect at once, in both directions.

        The hysteresis is about *machine* signals flapping. A person who just
        turned speech on and had to wait three observation cycles for it would
        reasonably conclude the setting was broken.
        """
        with self._guard:
            self.preferences = preferences
            self._pending = None
            self._streak = 0
            # A setting change is a new starting point, not a step on a ladder.
            # Without this, turning speech back on would climb out of
            # ``silent-text-only`` through the machine hysteresis and take
            # several refresh cycles — which a person would read as the switch
            # being broken.
            self._observed = False

    def observe(self, signals: VoiceSignals, *, monotonic: float = 0.0) -> VoiceDecision:
        candidate = evaluate(signals, self.preferences)
        with self._guard:
            current = self._decision
            current_rank = _OUTCOME_RANK[current.outcome]
            candidate_rank = _OUTCOME_RANK[candidate.outcome]

            if not self._observed:
                # The first reading is adopted whole. There is no previous
                # observation for it to be an oscillation away from.
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
                # Held at the quieter outcome, but the *reasons* are refreshed so
                # a surface explaining the current state is not quoting a
                # condition that has since cleared.
                held = replace(
                    current,
                    reasons=current.reasons + (
                        f"the machine now supports {candidate.outcome}; restoring after "
                        f"{self.restore_observations - self._streak} more consistent readings",
                    ),
                )
                self._decision = held
                return held

            # Same outcome. The details inside it — the priority floor, the
            # concurrency — may still have moved, and those take effect at once
            # because they do not oscillate the way the outcome does.
            self._decision = candidate
            self._pending = None
            self._streak = 0
            return candidate

    def _record(self, before: VoiceDecision, after: VoiceDecision, kind: str, monotonic: float) -> None:
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
                "ladder": [
                    {"rung": rung, "outcome": outcome} for rung, outcome in DEGRADATION_LADDER
                ],
                "transitions": list(self._transitions[-16:]),
            }
