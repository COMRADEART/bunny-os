# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§24's installed slice: a real service, a real recorder, a real recogniser.

Twenty-eight steps against an actual :class:`companion.service.CompanionService`
over its socket, with the speech-input runtime the service builds for itself.
No fake backend and no fake recogniser: if this host has a PulseAudio-compatible
server and a Vosk model, this slice captures real audio through ``parec`` and
transcribes it with a real model; where it has neither, every step that needs
one records ``NOT_RUN`` with the reason, and the steps that do not still run.

**How known speech reaches the microphone without a person.** An automated gate
cannot speak into a laptop. So the slice names the sink's **monitor source** as
its capture device — the one place a monitor may be selected, explicitly and by
its own name — and then has the companion's *voice runtime* speak a sentence.
The audio path is entirely real: a synthesiser produces a WAV, a real player
plays it into the real sink, the real server carries it to the monitor source,
``parec`` captures it, the energy gate detects it and Vosk transcribes it. What
is simulated is only the room, and the report labels it: **no physical
microphone was validated by this slice.**

That arrangement also makes step 8 an honest test of §19's machinery rather
than a bypass of it: the capture's own start quiesced companion speech, and the
slice submits the spoken sentence *afterwards*, deliberately, as the injected
signal.

**Exactly one task, checked by counting.** Steps 16 and 22 count tasks in the
session before and after — a confirmation creates exactly one; a cancelled
capture creates exactly none. Counting is the only shape of this check that
catches a double submission, which is the §1 failure this flow exists to
prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping

from ..protocol import CompanionClient
from ..service import CompanionService, ServiceOptions
from ..voice.policy import VoicePreferences
from .policy import SpeechInputPreferences

__all__ = ["SPEECH_SLICE_SENTENCE", "SpeechSliceReport", "run_speech_slice"]

#: What the voice runtime speaks into the loopback, and therefore what the
#: recogniser hears. Chosen to be short, common-vocabulary and unambiguous —
#: this is a plumbing test, not a benchmark.
SPEECH_SLICE_SENTENCE = "count the words in this note please"

#: What the user "corrects" the transcript to at step 14 — one word changed,
#: whatever the recogniser produced, so the edited flag and the edited text are
#: both exercised deterministically.
SPEECH_SLICE_CONFIRMED = "count the words in this short note please"

_WAIT = 90.0
_POLL = 0.05


@dataclass
class SpeechSliceReport:
    """What the slice did, step by step, with nothing inferred."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    task_id: str = ""
    capture_request_id: str = ""
    provider_id: str = ""
    backend_id: str = ""
    device_id: str = ""
    transcript_text: str = ""
    measurements: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def record(
        self, number: int, name: str, *, passed: bool | None, detail: str = "", **extra: Any
    ) -> None:
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
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "captureRequestId": self.capture_request_id,
            "providerId": self.provider_id,
            "backendId": self.backend_id,
            "deviceId": self.device_id,
            "measurements": list(self.measurements),
            "notes": list(self.notes),
            "networkRequired": False,
            "commercialProviderRequired": False,
            "physicalMicrophoneValidated": False,
        }


def _wait_for(predicate, timeout: float = _WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL)
    return predicate()


class _LoopbackSink:
    """A null sink of our own, so the loopback owes nothing to the host's.

    The WSLg RDP sink's monitor was measured serving silence to some client
    constellations and sound to others — same invocations, same server,
    different processes — which makes it a fine fallback and a poor
    foundation. A ``module-null-sink`` is pure software inside the same real
    pulse server: the voice runtime genuinely plays into it, ``parec``
    genuinely records its monitor, and nothing depends on an RDP transport
    this phase makes no claims about anyway. Where ``pactl`` cannot load one,
    the slice falls back to the first monitor the host presents.
    """

    NAME = "bunny-speech-loop"

    def __init__(self) -> None:
        self.module_id = ""
        self.monitor = ""
        self.sink = ""
        self._keepalive = None

    def create(self) -> "_LoopbackSink":
        import subprocess

        try:
            loaded = subprocess.run(
                ["pactl", "load-module", "module-null-sink",
                 f"sink_name={self.NAME}", "rate=44100",
                 f"sink_properties=device.description={self.NAME}"],
                capture_output=True, text=True, timeout=15,
            )
            if loaded.returncode == 0 and loaded.stdout.strip().isdigit():
                self.module_id = loaded.stdout.strip()
                self.sink = self.NAME
                self.monitor = f"{self.NAME}.monitor"
                # A silent stream that holds the sink RUNNING for the whole
                # harness lifetime. Measured, not decoration: monitor streams
                # do not inhibit module-suspend-on-idle, and a monitor client
                # that lives through the sink's suspend→resume transition was
                # observed to receive silence for the rest of its life —
                # matrix case F against case E, same process, seconds apart.
                # Holding one sink-input open means the transition never
                # happens while capture is attached. ``pacat`` reading
                # /dev/zero is infinite silence: it costs the mix nothing and
                # the detector's calibration reads it as the quiet room it is.
                self._keepalive = subprocess.Popen(
                    ["pacat", "--playback", f"--device={self.NAME}", "--raw",
                     "--rate=8000", "--channels=1", "--format=s16le",
                     "--client-name=bunny-loop-keepalive", "/dev/zero"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except Exception:  # noqa: BLE001 - absence is a fallback, not a failure
            pass
        return self

    def destroy(self) -> None:
        import subprocess

        if self._keepalive is not None:
            try:
                self._keepalive.terminate()
                self._keepalive.wait(timeout=10)
            except Exception:  # noqa: BLE001 - teardown never raises
                pass
            self._keepalive = None
        if not self.module_id:
            return
        try:
            subprocess.run(
                ["pactl", "unload-module", self.module_id],
                capture_output=True, timeout=15,
            )
        except Exception:  # noqa: BLE001 - teardown never raises
            pass
        self.module_id = ""


class _RecordingSink:
    """An indicator sink for the slice: displays by recording that it displayed.

    The GTK widget layer needs a compositor; the *ordering* §4 and §5 assert —
    raised before open, cleared after close — is a property of the runtime and
    is what this slice measures. The compositor probe draws the real widget.
    """

    def __init__(self) -> None:
        self.shown: list[dict[str, Any]] = []
        self.cleared: list[dict[str, Any]] = []

    def show(self, state: Any) -> bool:
        self.shown.append(state.to_json())
        return True

    def clear(self, state: Any) -> bool:
        self.cleared.append(state.to_json())
        return True


def _monitor_source(speech: Any) -> tuple[str, str]:
    """The sink monitor to capture from, or the reason there is none."""
    for backend in speech.router.backends:
        try:
            if not backend.health(monotonic=time.monotonic()).ready:
                continue
            for device in backend.discover():
                if device.monitor:
                    return device.device_id, ""
        except Exception:  # noqa: BLE001 - absence is an answer
            continue
    return "", "no reachable capture backend presents a monitor source"


def _events_for(speech: Any, request_id: str) -> list[Any]:
    return [
        item for item in speech.worker.events(limit=256)
        if item.request_id == request_id
    ]


def _task_count(client: CompanionClient, session_id: str) -> int:
    return len(client.call("list_tasks", {"sessionId": session_id}).get("tasks", []))


def run_speech_slice(root: Path) -> SpeechSliceReport:
    """The twenty-eight steps, in order, against a real service."""
    report = SpeechSliceReport()
    loop_sink = _LoopbackSink().create()
    options = ServiceOptions(
        root=Path(root),
        machine="laptop",
        audio_output_available=True,
        display_available=True,
        # Into our own sink where one could be made: the injection is then a
        # deterministic software loopback rather than a hostage of the host's
        # RDP audio path. The preference only narrows — §11's rule — and the
        # report records which sink actually carried the audio.
        voice_preferences=VoicePreferences(preferred_device=loop_sink.sink),
        speech_preferences=SpeechInputPreferences(),
    )
    service = CompanionService(options)
    try:
        service.start()
        gateway = service.gateway
        speech = service.speech
        voice = service.voice

        # 1 -- the canonical companion service ------------------------------
        report.record(
            1, "start the canonical companion service",
            passed=bool(gateway.health()["ok"]),
            detail=f"store at {service.root}",
        )
        if speech is None:
            report.record(2, "start the speech-input runtime", passed=False,
                          detail="the service built no speech-input runtime")
            return report

        # 2 -- the client ---------------------------------------------------
        client = CompanionClient(service.server.endpoint)
        health = client.call("health")
        sink = _RecordingSink()
        speech.attach_indicator_sink(sink)
        report.record(
            2, "start the GTK client transport",
            passed=bool(health.get("ok")),
            detail=(
                "the protocol client is exercised over the real socket; the widget "
                "layer needs a compositor and is covered by the GTK probe"
            ),
        )

        # 3 -- the microphone is closed ------------------------------------
        report.record(
            3, "verify the microphone is closed at startup",
            passed=not health.get("microphoneActive", True)
            and not speech.worker.active,
            detail="health.microphoneActive is false and no capture session exists",
        )

        session = client.call("create_session", {"title": "speech slice", "locality": "device-only"})
        report.session_id = session["session"]["sessionId"]
        tasks_before = _task_count(client, report.session_id)

        # -- what this host can actually do --------------------------------
        speech.refresh()
        decision = speech.policy.decision
        if loop_sink.monitor:
            device_id, no_monitor = loop_sink.monitor, ""
        else:
            device_id, no_monitor = _monitor_source(speech)
        recognizer_ready = any(item.ready for item in speech.registry.health())
        capture_possible = bool(decision.may_capture and device_id and recognizer_ready)
        absence = (
            "" if capture_possible else
            "; ".join(filter(None, [
                no_monitor,
                "" if recognizer_ready else "no local recogniser is ready",
                "" if decision.may_capture else f"policy outcome is {decision.outcome}",
            ]))
        )
        report.device_id = device_id

        # 4..7 -- push-to-talk, indicator, open, capture --------------------
        answer: Mapping[str, Any] = {}
        if capture_possible:
            answer = client.call("speech_input_start", {
                "sessionId": report.session_id,
                "activationSource": "push-to-talk-button",
                "deviceId": device_id,
                "maxCaptureMs": 25_000,
                "initialSilenceMs": 12_000,
                "endpointSilenceMs": 1_500,
            })
            report.capture_request_id = str(answer.get("requestId", ""))
        report.record(
            4, "the user explicitly presses push-to-talk",
            passed=bool(answer.get("accepted")) if capture_possible else None,
            detail=(
                f"capture {report.capture_request_id} accepted from push-to-talk-button"
                if answer.get("accepted") else (absence or str(answer.get("detail", "")))
            ),
        )

        opened = capture_possible and _wait_for(
            lambda: any(
                item.kind == "microphone_opened"
                for item in _events_for(speech, report.capture_request_id)
            ),
            timeout=20.0,
        )
        events = _events_for(speech, report.capture_request_id)
        kinds = [item.kind for item in events]
        indicator_before_open = (
            "microphone_indicator_raised" in kinds
            and "microphone_opened" in kinds
            and kinds.index("microphone_indicator_raised") < kinds.index("microphone_opened")
        )
        report.record(
            5, "the listening indicator appears before the microphone opens",
            passed=(bool(sink.shown) and indicator_before_open) if capture_possible else None,
            detail=(
                f"indicator raised at event {kinds.index('microphone_indicator_raised') if 'microphone_indicator_raised' in kinds else '?'}, "
                f"microphone opened at event {kinds.index('microphone_opened') if 'microphone_opened' in kinds else '?'}"
                if capture_possible else absence
            ),
        )
        if opened:
            for item in events:
                if item.kind == "microphone_opened":
                    report.backend_id = str(dict(item.payload).get("backendId", ""))
        report.record(
            6, "the microphone opens",
            passed=opened if capture_possible else None,
            detail=(
                f"{report.backend_id} opened {device_id}" if opened else absence
            ),
        )
        report.record(
            7, "capture begins",
            passed=("capture_started" in kinds) if capture_possible else None,
            detail="capture_started was emitted" if capture_possible else absence,
        )

        # 8 -- known speech, through the loopback ---------------------------
        def _inject(attempt: int) -> dict[str, Any]:
            from ..presentation import PresentationState

            state = PresentationState(
                session_id=report.session_id,
                task_id=f"speech-slice-injection-{attempt}",
                phase="presenting_result",
                base_phase="presenting_result",
                result_summary=SPEECH_SLICE_SENTENCE,
                revision=attempt,
            )
            voice.refresh()
            request, reason = voice.announce(state)
            record = {"attempt": attempt, "announced": request is not None,
                      "reason": reason, "disposition": ""}
            if request is not None:
                _wait_for(
                    lambda: any(
                        item["requestId"] == request.request_id
                        for item in voice.queue.ledger
                    ),
                    timeout=30.0,
                )
                record["disposition"] = next(
                    (item["disposition"] for item in voice.queue.ledger
                     if item["requestId"] == request.request_id), "",
                )
            return record

        def _detected() -> bool:
            return any(
                item.kind == "speech_detected"
                for item in _events_for(speech, report.capture_request_id)
            )

        injections: list[dict[str, Any]] = []
        if opened and voice is not None:
            injections.append(_inject(1))
            _wait_for(_detected, timeout=8.0)
            if not _detected() and speech.worker.active:
                # One retry of the *stimulus* only — a person would simply
                # speak again, and the WSLg sink's cold resume has been
                # observed to swallow a first utterance whole.
                injections.append(_inject(2))
        detected = opened and _wait_for(_detected, timeout=30.0)
        injection = injections[-1] if injections else {
            "announced": False, "reason": "", "disposition": "",
        }
        report.record(
            8, "speech is detected",
            passed=detected if capture_possible else None,
            detail=(
                "the voice runtime spoke a known sentence into the sink and the "
                "monitor capture detected it"
                if detected else
                (absence or
                 f"no speech energy was detected; the injection was "
                 f"announced={injection['announced']} "
                 f"disposition={injection['disposition']!r} "
                 f"reason={injection['reason']!r}")
            ),
            injections=list(injections),
        )

        # 9 -- a partial transcript -----------------------------------------
        saw_partial = detected and _wait_for(
            lambda: (speech.worker.status().get("current") or {}).get("partialText")
            or any(
                item.kind == "final_transcript"
                for item in _events_for(speech, report.capture_request_id)
            ),
            timeout=30.0,
        )
        report.record(
            9, "a partial transcript appears",
            passed=bool(saw_partial) if capture_possible else None,
            detail=(
                "a provisional reading was available while capture ran"
                if saw_partial else (absence or "no partial was produced")
            ),
        )

        # 10..13 -- silence ends it; close; finalize; final ------------------
        finished = capture_possible and _wait_for(
            lambda: not speech.worker.active, timeout=45.0,
        )
        events = _events_for(speech, report.capture_request_id)
        kinds = [item.kind for item in events]
        report.record(
            10, "the capture ends on silence or stop",
            passed=("capture_stopped" in kinds) if capture_possible else None,
            detail=next(
                (str(dict(item.payload).get("reason", "")) for item in events
                 if item.kind == "capture_stopped"), absence,
            ),
        )
        closed_index = kinds.index("microphone_closed") if "microphone_closed" in kinds else -1
        cleared_index = kinds.index("indicator_cleared") if "indicator_cleared" in kinds else -1
        report.record(
            11, "the microphone closes, then the indicator clears",
            passed=(
                closed_index >= 0 and cleared_index > closed_index and bool(sink.cleared)
            ) if capture_possible else None,
            detail=(
                f"microphone_closed at {closed_index}, indicator_cleared at {cleared_index}"
                if capture_possible else absence
            ),
        )
        report.record(
            12, "recognition finalizes",
            passed=("recognition_finalizing" in kinds) if capture_possible else None,
            detail="recognition_finalizing was emitted" if capture_possible else absence,
        )
        final_event = next((item for item in events if item.kind == "final_transcript"), None)
        if final_event is not None:
            payload = dict(final_event.payload)
            report.transcript_text = str(payload.get("text", ""))
            report.provider_id = str(payload.get("providerId", ""))
        report.record(
            13, "a final transcript appears",
            passed=bool(report.transcript_text) if capture_possible else None,
            detail=(
                f"{report.provider_id} heard {len(report.transcript_text)} characters: "
                f"{report.transcript_text[:80]!r}"
                if report.transcript_text else
                (absence or "recognition produced no text from the loopback audio")
            ),
        )
        measurement = speech.worker.measurement(report.capture_request_id)
        if measurement is not None:
            report.measurements.append({
                "requestId": report.capture_request_id,
                **measurement.to_json(),
            })

        # 14..16 -- edit, confirm, exactly one task --------------------------
        confirmed: Mapping[str, Any] = {}
        if report.transcript_text:
            confirmed = client.call("speech_input_confirm", {
                "requestId": report.capture_request_id,
                "sessionId": report.session_id,
                "text": SPEECH_SLICE_CONFIRMED,
                "cancellationToken": str(answer.get("cancellationToken", "")),
            })
        report.record(
            14, "the user edits one word",
            passed=bool(confirmed.get("userEdited")) if report.transcript_text else None,
            detail=(
                f"the transcript was corrected to {SPEECH_SLICE_CONFIRMED!r} and "
                "marked user-edited"
                if confirmed.get("userEdited") else
                (absence or "no transcript reached confirmation")
            ),
        )
        report.record(
            15, "the user confirms",
            passed=bool(confirmed.get("submitted")) if report.transcript_text else None,
            detail=str(confirmed.get("reason", "confirmed and submitted")),
        )
        task = confirmed.get("task")
        if isinstance(task, Mapping):
            report.task_id = str(task.get("taskId", ""))
        tasks_after_confirm = _task_count(client, report.session_id)
        report.record(
            16, "the canonical runtime creates exactly one task",
            passed=(
                tasks_after_confirm == tasks_before + 1 and bool(report.task_id)
            ) if report.transcript_text else None,
            detail=(
                f"{tasks_before} task(s) before, {tasks_after_confirm} after; "
                f"task {report.task_id}"
                if report.transcript_text else absence
            ),
        )

        # 17..18 -- capability, approvals, completion ------------------------
        completed = False
        if report.task_id:
            _answer_every_approval(client, report.session_id, report.task_id)
            completed = _wait_for(
                lambda: client.call("get_task", {"taskId": report.task_id})["task"]["state"]
                in ("completed", "failed", "cancelled", "blocked"),
            )
        final_task = (
            client.call("get_task", {"taskId": report.task_id})["task"]
            if report.task_id else {}
        )
        report.record(
            17, "the task runs through capability and approval flow",
            passed=bool(report.task_id and completed) if report.task_id else None,
            detail=(
                f"state {final_task.get('state')}" if report.task_id else absence
            ),
        )
        report.record(
            18, "the task completes",
            passed=(final_task.get("state") == "completed") if report.task_id else None,
            detail=str(final_task.get("resultSummary", ""))[:120] or absence,
        )

        # 19..20 -- the voice speaks the result; the renderer ----------------
        spoke_result = False
        if report.task_id and voice is not None:
            answer_state = client.call("get_presentation_state", {"taskId": report.task_id})
            caption_id = answer_state.get("captionId", "")
            if caption_id:
                voice.ledger.mark_shown(caption_id)
                request, _reason = voice.speak(caption_id)
                if request is not None:
                    spoke_result = _wait_for(
                        lambda: any(
                            item["requestId"] == request.request_id
                            and item["disposition"] == "played"
                            for item in voice.queue.ledger
                        ),
                        timeout=45.0,
                    )
        report.record(
            19, "the voice runtime speaks the canonical result",
            passed=spoke_result if (report.task_id and voice is not None) else None,
            detail=(
                "the result caption was spoken and recorded played"
                if spoke_result else
                "no audio path completed playback on this host" if report.task_id else absence
            ),
        )
        report.record(
            20, "the renderer animates voice visemes",
            passed=None,
            detail=(
                "the viseme stream drives the GTK renderer through VisemeLink; the "
                "compositor probe (gtk_speech_input_probe) exercises it — no "
                "compositor runs inside this slice"
            ),
        )

        # 21..22 -- a second capture, cancelled, no task ---------------------
        tasks_before_cancel = _task_count(client, report.session_id)
        second: Mapping[str, Any] = {}
        cancelled = False
        if capture_possible:
            second = client.call("speech_input_start", {
                "sessionId": report.session_id,
                "activationSource": "push-to-talk-button",
                "deviceId": device_id,
                "maxCaptureMs": 20_000,
                "initialSilenceMs": 15_000,
            })
            if second.get("accepted"):
                second_id = str(second.get("requestId", ""))
                _wait_for(
                    lambda: any(
                        item.kind == "capture_started"
                        for item in _events_for(speech, second_id)
                    ),
                    timeout=20.0,
                )
                outcome = client.call("speech_input_cancel", {
                    "requestId": second_id,
                    "cancellationToken": str(second.get("cancellationToken", "")),
                })
                cancelled = bool(outcome.get("cancelled"))
                _wait_for(lambda: not speech.worker.active, timeout=20.0)
        report.record(
            21, "a second capture is cancelled mid-stream",
            passed=cancelled if capture_possible else None,
            detail=(
                "cancelled while capturing" if cancelled
                else (absence or str(second.get("detail", "")))
            ),
        )
        report.record(
            22, "no task is created from the cancelled capture",
            passed=(
                _task_count(client, report.session_id) == tasks_before_cancel
            ) if capture_possible else None,
            detail=f"{tasks_before_cancel} task(s) before and after the cancellation"
            if capture_possible else absence,
        )

        # 23..24 -- device loss, degradation to typing -----------------------
        lost = []
        for backend in speech.router.backends:
            setter = getattr(backend, "set_reachable", None)
            if setter is not None:
                setter(False)
                lost.append(backend.backend_id)
        speech.refresh()
        degraded = speech.policy.decision
        report.record(
            23, "the input device is removed or loss is simulated",
            passed=bool(lost),
            detail=f"simulated loss on {', '.join(lost)}; everything downstream is real",
        )
        report.record(
            24, "the system degrades to typed input",
            passed=not degraded.may_capture,
            detail=f"policy outcome {degraded.outcome}: {'; '.join(degraded.reasons[:2])}",
        )
        for backend in speech.router.backends:
            setter = getattr(backend, "set_reachable", None)
            if setter is not None:
                setter(True)

        # 25..28 -- restart, closed microphone, unchanged task, no resume ----
        before_task = (
            client.call("get_task", {"taskId": report.task_id})["task"]
            if report.task_id else {}
        )
        recovery = speech.restart_worker(timeout=20.0)
        replay = CompanionClient(service.server.endpoint)
        replay_health = replay.call("health")
        report.record(
            25, "the speech runtime and a new client restart",
            passed=bool(replay_health.get("ok")),
            detail=(
                f"worker restarted ({len(recovery.marked_cancelled)} capture(s) "
                "recorded cancelled-uncertain); a fresh client connected"
            ),
        )
        report.record(
            26, "the microphone remains closed after restart",
            passed=not replay_health.get("microphoneActive", True)
            and not speech.worker.active,
            detail="health.microphoneActive is false and no capture session exists",
        )
        after_task = (
            replay.call("get_task", {"taskId": report.task_id})["task"]
            if report.task_id else {}
        )
        unchanged = (
            before_task.get("taskId") == after_task.get("taskId")
            and before_task.get("state") == after_task.get("state")
            and before_task.get("resultSummary") == after_task.get("resultSummary")
        )
        report.record(
            27, "the confirmed task and result are unchanged",
            passed=unchanged if report.task_id else None,
            detail=(
                f"{after_task.get('taskId')} in state {after_task.get('state')}"
                if report.task_id else absence
            ),
        )
        report.record(
            28, "no completed or cancelled capture restarts automatically",
            passed=not speech.worker.active
            and not speech.recovery.to_json()["captureResumed"],
            detail=(
                "no capture is running and the recovery report records "
                "captureResumed=false; a new capture requires a new explicit action"
            ),
        )

        report.notes.append(
            "no network was used and no commercial provider was contacted; the "
            f"recognition path was {report.provider_id or 'unavailable'} over "
            f"{report.backend_id or 'no backend'} capturing {report.device_id or 'no device'}; "
            "the capture device was a sink monitor carrying synthesised speech — "
            "no physical microphone was validated"
            + ("; the sink was a null sink created for the slice" if loop_sink.sink else "")
        )
        return report
    finally:
        service.close()
        loop_sink.destroy()


def _answer_every_approval(client: CompanionClient, session_id: str, task_id: str) -> list[str]:
    """Grant each approval the task raises, until it stops asking. Bounded."""
    granted: list[str] = []
    deadline = time.monotonic() + _WAIT
    while time.monotonic() < deadline and len(granted) < 8:
        state = client.call("get_presentation_state", {"taskId": task_id})["state"]
        if state.get("phase") in ("success", "error", "blocked", "cancelled"):
            break
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
