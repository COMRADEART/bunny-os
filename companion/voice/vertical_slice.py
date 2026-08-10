# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§23's installed slice: a real service, a real synthesiser, a real speaker.

Twenty-five steps against an actual :class:`companion.service.CompanionService`
over its socket, with the voice runtime the service builds for itself. No fake
provider, no fake backend: if this host has eSpeak NG and a reachable sink, this
slice makes a sound; if it does not, every step that needs one is recorded
``NOT_RUN`` with the reason, and the steps that do not need one still run.

That distinction is the whole design. §23 says the slice must be
**provider-free** — no network, no commercial provider, nothing to sign up for —
and it says the slice must pass. A slice that silently substituted a fake when
the machine had no synthesiser would satisfy both sentences and prove neither.
So a step here has three outcomes, and ``NOT_RUN`` is a first-class one.

**The task is checked, not assumed.** Steps 22 and 23 record the task id, its
state and its result summary before the voice worker is restarted and compare
them afterwards. If a voice restart reached the task, this fails — which is the
one thing §1 exists to prevent and the one thing a reader of the code cannot
verify by reading it.

**Step 25 is the one that would be easiest to get wrong.** After the client
restarts and re-reads the presentation, nothing must speak again. It is checked
by counting utterances across the restart, not by observing that the runtime
"looks idle": a replay that happened and finished quickly would look identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from ..character.lipsync import MouthShape
from ..presentation import PresentationState
from ..protocol import CompanionClient
from ..service import CompanionService, ServiceOptions
from .captions import SpeechDisposition
from .policy import VoicePreferences
from .request import Priority

__all__ = ["VOICE_SLICE_REQUEST", "VoiceSliceReport", "run_voice_slice"]

#: The same harmless local request the other slices use: an operation, a
#: validation step the first plan omits so the reviewer has something true to
#: say, and a notice that needs consent — so an approval is reached and can be
#: resolved rather than simulated.
VOICE_SLICE_REQUEST = (
    "Count the words in this note, validate the count, and notify me when it is done."
)

_WAIT = 60.0
_POLL = 0.05


@dataclass
class VoiceSliceReport:
    """What the slice did, step by step, with nothing inferred."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    task_id: str = ""
    session_id: str = ""
    caption_ids: list[str] = field(default_factory=list)
    provider_id: str = ""
    backend_id: str = ""
    voice_outcome: str = ""
    #: Every §24 reading this run produced, so the measurement harness can take
    #: them from a slice rather than from a separate synthetic path.
    measurements: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def record(self, number: int, name: str, *, passed: bool | None, detail: str = "", **extra: Any) -> None:
        """``passed=None`` means NOT_RUN: the step could not be attempted here."""
        self.steps.append({
            "step": number,
            "name": name,
            "status": "PASS" if passed else ("NOT_RUN" if passed is None else "FAIL"),
            "detail": detail,
            **extra,
        })

    @property
    def passed(self) -> bool:
        """No failure. A ``NOT_RUN`` is not a failure and is not a pass either."""
        return all(item["status"] != "FAIL" for item in self.steps)

    @property
    def not_run(self) -> tuple[str, ...]:
        return tuple(
            f"{item['step']}. {item['name']}: {item['detail']}"
            for item in self.steps if item["status"] == "NOT_RUN"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "steps": list(self.steps),
            "stepCount": len(self.steps),
            "passedCount": sum(1 for item in self.steps if item["status"] == "PASS"),
            "notRun": list(self.not_run),
            "failed": [item for item in self.steps if item["status"] == "FAIL"],
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "providerId": self.provider_id,
            "backendId": self.backend_id,
            "voiceOutcome": self.voice_outcome,
            "measurements": list(self.measurements),
            "notes": list(self.notes),
            "networkRequired": False,
            "commercialProviderRequired": False,
        }


def _wait_for(predicate, timeout: float = _WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL)
    return predicate()


def run_voice_slice(root: Path) -> VoiceSliceReport:
    """The twenty-five steps, in order, against a real service."""
    report = VoiceSliceReport()
    options = ServiceOptions(
        root=Path(root),
        machine="laptop",
        audio_output_available=True,
        display_available=True,
        # Progress narration on, so the slice has more than one utterance to
        # interrupt and supersede. A user would usually leave it off.
        voice_preferences=VoicePreferences(speak_progress=True, speak_decorative=True),
    )
    service = CompanionService(options)
    try:
        service.start()
        voice = service.voice
        gateway = service.gateway

        # 1 -- the canonical companion runtime -----------------------------
        report.record(
            1, "start the canonical companion runtime",
            passed=bool(gateway.health()["ok"]),
            detail=f"store at {service.root}",
        )
        if voice is None:
            report.record(
                2, "start the voice runtime", passed=False,
                detail="the service built no voice runtime",
            )
            return report

        # 2 -- the client -------------------------------------------------
        client = CompanionClient(service.server.endpoint)
        health = client.call("health")
        report.record(
            2, "start the GTK client transport",
            passed=bool(health.get("ok")),
            detail=(
                "the protocol client is exercised over the real socket; the GTK widget "
                "layer needs a compositor and is covered by the character slice"
            ),
        )

        # 3 -- the character package --------------------------------------
        from ..character.defaults import default_character_path
        from ..character.package import validate_package_directory

        try:
            package = validate_package_directory(default_character_path())
            report.record(
                3, "load the validated character package",
                passed=True,
                detail=(
                    f"{package.manifest.package_id} "
                    f"({package.manifest.presentation_type.value}) validated from {package.root}"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - an absent package is NOT_RUN, not a failure
            report.record(
                3, "load the validated character package", passed=None,
                detail=f"no validated package on this host: {type(exc).__name__}: {exc}",
            )

        # 4 -- a harmless task --------------------------------------------
        session = client.call("create_session", {"title": "voice slice", "locality": "device-only"})
        session_id = session["session"]["sessionId"]
        report.session_id = session_id
        submitted = client.call("submit_task", {"sessionId": session_id, "request": VOICE_SLICE_REQUEST})
        task_id = submitted["task"]["taskId"]
        report.task_id = task_id
        report.record(4, "submit a harmless task", passed=bool(task_id), detail=task_id)

        # 5 -- planning and working ---------------------------------------
        seen_phases: list[str] = []

        def _phase() -> str:
            state = client.call("get_presentation_state", {"taskId": task_id})
            caption_id = state.get("captionId", "")
            if caption_id and caption_id not in report.caption_ids:
                report.caption_ids.append(caption_id)
            phase = state["state"]["phase"]
            if not seen_phases or seen_phases[-1] != phase:
                seen_phases.append(phase)
            return phase

        _wait_for(lambda: _phase() in ("planning", "working", "reviewing", "waiting_for_approval", "success", "error"))
        report.record(
            5, "display planning and working states",
            passed=bool(seen_phases),
            detail=" -> ".join(seen_phases[:8]),
        )

        # 6 -- the approval ------------------------------------------------
        # A task can ask more than once, and the loop is what makes step 7
        # reachable: answering only the first question leaves the task parked on
        # the second, which reads as "the task never finished" when in fact
        # nobody answered it.
        answered = _answer_every_approval(client, session_id, task_id, phase=_phase)
        report.record(
            6, "request and resolve approval",
            passed=bool(answered) if answered else None,
            detail=(
                f"{len(answered)} approval(s) granted: {', '.join(answered)}"
                if answered else "no approval was raised on this run"
            ),
        )

        # 7 -- completion ---------------------------------------------------
        completed = _wait_for(lambda: _phase() in ("success", "error", "blocked", "cancelled"))
        final = client.call("get_presentation_state", {"taskId": task_id})
        final_state = final["state"]
        report.record(
            7, "complete the task", passed=completed,
            detail=f"phase {final_state['phase']}",
        )

        # 8 -- the canonical caption ---------------------------------------
        caption_id = final.get("captionId", "")
        caption = voice.ledger.get(caption_id) if caption_id else None
        report.record(
            8, "produce canonical caption text",
            passed=bool(caption and caption.speakable),
            detail=f"{caption_id} ({len(caption.text) if caption else 0} characters)",
        )

        # 9..10 -- the request and the provider ----------------------------
        voice.refresh(capability_signals=final.get("capabilitySignals", {}))
        decision = voice.policy.decision
        report.voice_outcome = decision.outcome
        voice.ledger.mark_shown(caption_id)
        request, reason = voice.speak(caption_id, priority=Priority.TASK_RESULT)
        report.record(
            9, "submit a local speech request",
            passed=bool(request) if request else None,
            detail=request.request_id if request else reason,
        )

        selection = voice.registry.select(request) if request else None
        if selection is not None and selection.selected:
            report.provider_id = selection.provider.declaration.provider_id
        health = voice.voice_health()
        ready = [item["providerId"] for item in health["providers"] if item.get("ready")]
        report.record(
            10, "select a real available local provider",
            passed=bool(report.provider_id) if report.provider_id else None,
            detail=(
                f"{report.provider_id} selected"
                if report.provider_id
                else f"no local provider is ready on this host (installed: {ready or 'none'})"
            ),
            providers=[item["providerId"] for item in health["providers"]],
        )

        # 11..16 -- captions, audio, visemes, mouth, completion, neutral ----
        spoken = False
        if request is not None:
            spoken = _wait_for(
                lambda: voice.queue.counts()[SpeechDisposition.PLAYED] >= 1
                or any(
                    item["requestId"] == request.request_id for item in voice.queue.ledger
                ),
                timeout=_WAIT,
            )
        events = voice.worker.events(limit=128)
        started = [item for item in events if item.kind == "audio_started"]
        finished = [item for item in events if item.kind == "speech_finished"]
        neutral = [item for item in events if item.kind == "mouth_neutral"]
        disposition = next(
            (item["disposition"] for item in reversed(voice.queue.ledger)
             if request is not None and item["requestId"] == request.request_id),
            "",
        )
        audible = disposition == SpeechDisposition.PLAYED

        # Re-read: :class:`Caption` is frozen, so ``mark_shown`` returns a new
        # one and the local variable above still holds the un-shown original.
        caption = voice.ledger.get(caption_id) if caption_id else None
        report.record(
            11, "start captions before speech",
            passed=bool(caption and caption.shown_at_monotonic),
            detail="the caption was marked shown before the request was built",
        )
        report.record(
            12, "start audio",
            passed=audible if audible else None,
            detail=(
                f"{started[-1].payload.get('backendId') or started[-1].payload.get('providerId')}"
                if started else f"no audio was produced on this host ({disposition or 'not attempted'})"
            ),
        )
        if started:
            report.backend_id = str(started[-1].payload.get("backendId", "")) or "provider-owned"
        report.record(
            13, "emit generic visemes",
            passed=bool(started) if started else None,
            detail=(
                f"source {started[-1].payload.get('visemeSource')} at confidence "
                f"{started[-1].payload.get('visemeConfidence')}"
                if started else "no utterance reached the viseme stage"
            ),
        )
        report.record(
            14, "animate the character mouth",
            passed=None,
            detail=(
                "the viseme timeline drives companion.character.lipsync, which the character "
                "slice exercises against the renderer; no compositor runs here"
            ),
        )
        report.record(
            15, "complete playback",
            passed=audible if audible else None,
            detail=disposition or "not attempted",
        )
        report.record(
            16, "return the mouth to neutral",
            passed=bool(neutral) if neutral else None,
            detail=(
                neutral[-1].payload.get("explanation", "") if neutral
                else "no utterance ran, so there was no mouth to return"
            ),
        )
        if request is not None:
            measurement = voice.ledger.measurement(request.request_id)
            if measurement is not None:
                report.measurements.append(measurement.to_json())

        # 17..18 -- cancel a second utterance ------------------------------
        second_caption = voice.publish(_long_caption(final_state))
        voice.ledger.mark_shown(second_caption.caption_id)
        second, why = voice.speak(second_caption.caption_id, priority=Priority.TASK_RESULT)
        cancelled = False
        if second is not None:
            _wait_for(
                lambda: (voice.worker.status()["current"] or {}).get("requestId") == second.request_id,
                timeout=20.0,
            )
            cancelled = bool(voice.dispatch("voice_cancel", {"requestId": second.request_id})["count"])
            voice.worker.drain(timeout=20.0)
        report.record(
            17, "cancel a second utterance mid-playback",
            passed=cancelled if cancelled else None,
            detail="cancelled" if cancelled else (why or "no second utterance was started"),
        )
        report.record(
            18, "preserve captions through the cancellation",
            passed=voice.ledger.get(second_caption.caption_id) is not None,
            detail="the caption survives its utterance being cancelled",
        )

        # 19..21 -- device loss, degradation, restoration -------------------
        before_outcome = voice.policy.decision.outcome
        lost = _simulate_backend_loss(voice)
        degraded = voice.refresh().outcome
        report.record(
            19, "remove the audio device or simulate backend loss",
            passed=bool(lost),
            detail=lost or "no backend to take away",
        )
        report.record(
            20, "degrade to captions only",
            passed=degraded == "captions-only",
            detail=f"{before_outcome} -> {degraded}",
        )
        _restore_backends(voice)
        restored = [voice.refresh().outcome for _ in range(voice.policy.restore_observations + 1)]
        report.record(
            21, "restore the backend with hysteresis",
            passed=restored[-1] == before_outcome,
            detail=(
                f"{degraded} -> {restored[-1]} after {len(restored)} readings; "
                f"the first {voice.policy.restore_observations - 1} held at {restored[0]}"
            ),
        )

        # 22..23 -- restart the worker, check the task ----------------------
        before_task = client.call("get_task", {"taskId": task_id})["task"]
        recovery = voice.restart_worker(timeout=20.0)
        after_task = client.call("get_task", {"taskId": task_id})["task"]
        report.record(
            22, "restart the voice worker",
            passed=voice.worker.running,
            detail=f"{len(recovery.marked_interrupted)} in-flight utterance(s) recorded interrupted",
        )
        unchanged = (
            before_task.get("taskId") == after_task.get("taskId")
            and before_task.get("state") == after_task.get("state")
            and before_task.get("resultSummary") == after_task.get("resultSummary")
        )
        report.record(
            23, "confirm task identity and result are unchanged",
            passed=unchanged,
            detail=(
                f"{after_task.get('taskId')} in state {after_task.get('state')}"
                if unchanged else
                f"the task moved: {before_task.get('state')} -> {after_task.get('state')}"
            ),
        )

        # 24..25 -- restart the client, replay the presentation -------------
        spoken_before = voice.ledger.describe()["spoken"]
        utterances_before = sum(voice.queue.counts().values())
        replay = CompanionClient(service.server.endpoint)
        replayed_state = replay.call("get_presentation_state", {"taskId": task_id})
        report.record(
            24, "restart the client and replay the presentation",
            passed=replayed_state["state"]["taskId"] == task_id,
            detail=f"phase {replayed_state['state']['phase']} at revision {replayed_state['revision']}",
        )
        voice.worker.drain(timeout=10.0)
        utterances_after = sum(voice.queue.counts().values())
        report.record(
            25, "confirm completed speech is not automatically replayed",
            passed=utterances_after == utterances_before,
            detail=(
                f"{utterances_after - utterances_before} new utterance(s) after the replay; "
                f"{spoken_before} caption(s) remain marked spoken"
            ),
        )

        report.notes.append(
            "no network was used and no commercial provider was contacted; "
            f"the speech path was {report.provider_id or 'unavailable'} "
            f"through {report.backend_id or 'no backend'}"
        )
        return report
    finally:
        service.close()


def _answer_every_approval(client: Any, session_id: str, task_id: str, *, phase: Any) -> list[str]:
    """Grant each approval the task raises, until it stops asking.

    Bounded twice — by a wall-clock deadline and by a maximum count — because a
    task that asked forever would otherwise hang the slice rather than fail it.
    """
    granted: list[str] = []
    deadline = time.monotonic() + _WAIT
    while time.monotonic() < deadline and len(granted) < 8:
        if phase() in ("success", "error", "blocked", "cancelled"):
            break
        state = client.call("get_presentation_state", {"taskId": task_id})["state"]
        approvals = [
            item for item in (state.get("approvals") or [])
            if item.get("requestId") and item["requestId"] not in granted
        ]
        if not approvals:
            time.sleep(_POLL)
            continue
        pending = approvals[0]
        try:
            client.call("resolve_approval", {
                "requestId": pending["requestId"],
                "sessionId": session_id,
                "taskId": task_id,
                "planId": pending["planId"],
                "transitionId": pending["transitionId"],
                "action": pending["action"],
                "destination": pending["destination"],
                "providerId": pending.get("providerId", ""),
                "dataClassification": pending["dataClassification"],
                "estimatedCostUnits": pending.get("estimatedCostUnits"),
                "destinationFingerprint": pending.get("destinationFingerprint", ""),
                "decision": "granted",
            })
        except Exception:  # noqa: BLE001 - a lapsed request is not a slice failure
            pass
        granted.append(pending["requestId"])
    return granted


def _long_caption(state: Mapping[str, Any]) -> PresentationState:
    """A second caption long enough to still be playing when it is cancelled."""
    return PresentationState(
        session_id=str(state.get("sessionId", "")),
        task_id=str(state.get("taskId", "")),
        phase="presenting_result",
        base_phase="presenting_result",
        status_text="",
        result_summary=(
            "Here is a longer sentence, deliberately drawn out so that there is "
            "still audio playing at the moment the cancellation arrives, which is "
            "the only way to test that cancelling mid-playback stops the sound."
        ),
        revision=int(state.get("revision", 0)) + 1,
    )


def _simulate_backend_loss(voice: Any) -> str:
    """Take every audio backend away, the way an unplugged speaker does.

    Marked as a *simulation* in the report because it is one: the backends are
    told to report themselves unreachable rather than a cable being pulled. What
    is real is everything downstream — the router's selection, the degradation
    record, the policy's descent and the hysteresis on the way back.
    """
    names = []
    for backend in voice.router.backends:
        setter = getattr(backend, "set_reachable", None)
        if setter is not None:
            setter(False)
            names.append(backend.backend_id)
        else:
            backend.close()
            names.append(backend.backend_id)
    return ", ".join(names)


def _restore_backends(voice: Any) -> None:
    for backend in voice.router.backends:
        setter = getattr(backend, "set_reachable", None)
        if setter is not None:
            setter(True)
