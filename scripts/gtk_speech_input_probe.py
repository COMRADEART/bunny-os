#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech input driving a real GTK surface, on a real compositor.

The deterministic suite proves the ordering — indicator before open, cleared
after close, postures walked and reset — against recording sinks. What it
cannot prove is that a real widget toolkit, on a real compositor, displays the
§5 indicator and draws the §18 listening posture without a GLib critical, a
leaked idle source or a stale frame. This probe is that join, executed:

    explicit protocol activation
        -> companion.speech.service.SpeechInputService (real parec, real server)
        -> the §5 indicator, as a Gtk.Label fed through GLib.idle_add
        -> companion.character.listening_link.ListeningLink
        -> companion.character.surface.CharacterPresenter (listening posture)
        -> Gtk.Picture.set_filename, on a compositor
    while companion.voice speaks a known sentence into the sink whose monitor
    is being captured — real audio through a real capture chain.

What it will not do: run without a display; select a monitor source silently
(the monitor is named explicitly and the report says so); claim a physical
microphone was validated; or claim recognition accuracy — the recogniser's
transcript is recorded verbatim as what a real model heard over a loopback.

Exit status: 0 every check held, 2 something did not.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import Any

for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

SPOKEN = "count the words in this note please"


def display_environment() -> dict[str, Any]:
    wayland = os.environ.get("WAYLAND_DISPLAY")
    x11 = os.environ.get("DISPLAY")
    wslg = Path("/mnt/wslg").exists()
    if wayland and wslg:
        kind = "wayland-wslg-remoted"
        note = (
            "A real Wayland compositor supplied by the WSLg system distribution. "
            "NOT a GNOME session, NOT physical hardware; no physical microphone "
            "was validated — capture is the sink monitor carrying synthesised speech."
        )
    elif wayland:
        kind, note = "wayland-unclassified", "A Wayland compositor that was not identified."
    elif x11:
        kind, note = "x11-unclassified", "An X server that was not identified."
    else:
        kind, note = "none", "No display. The widgets cannot be driven."
    return {
        "kind": kind, "note": note,
        "waylandDisplay": wayland, "display": x11,
        "isGnomeSession": False, "isPhysicalHardware": False,
        "physicalMicrophoneValidated": False,
        "available": kind != "none",
    }


class LogCapture:
    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def install(self, GLib: Any) -> None:
        def writer(level: Any, fields: Any, _user_data: Any = None) -> Any:
            entry: dict[str, str] = {"level": str(level)}
            try:
                for key in ("GLIB_DOMAIN", "MESSAGE"):
                    value = fields.get(key) if hasattr(fields, "get") else None
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "replace")
                    if value:
                        entry[key] = str(value)
            except Exception:  # noqa: BLE001
                pass
            self.records.append(entry)
            return GLib.LogWriterOutput.HANDLED

        try:
            GLib.log_set_writer_func(writer, None)
        except Exception:  # noqa: BLE001
            pass

    @property
    def serious(self) -> list[dict[str, str]]:
        return [
            record for record in self.records
            if "CRITICAL" in record.get("level", "").upper()
            or "ERROR" in record.get("level", "").upper()
        ]


class Probe:
    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        self.report: dict[str, Any] = {
            "schema": "bunny-os/gtk-speech-input-probe/1",
            "display": display_environment(),
            "checks": {},
            "measurements": {},
            "limitations": [],
        }
        self.failures: list[str] = []
        self.started = time.monotonic()
        self.idle_sources: set[int] = set()
        self.retired: set[int] = set()
        self.indicator_shown: list[dict[str, Any]] = []
        self.indicator_cleared: list[dict[str, Any]] = []
        self.postures: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def now_ms(self) -> float:
        return round((time.monotonic() - self.started) * 1000, 3)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    # -- GTK plumbing ------------------------------------------------------

    def dispatch(self, action) -> None:
        box: dict[str, int] = {}

        def once() -> bool:
            try:
                action()
            finally:
                self.retired.add(box.get("id", -1))
            return self.GLib.SOURCE_REMOVE

        identifier = self.GLib.idle_add(once)
        box["id"] = identifier
        self.idle_sources.add(identifier)

    def pump(self, *, seconds: float, until=None) -> None:
        deadline = time.monotonic() + seconds
        context = self.GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if until is not None and until():
                while context.pending():
                    context.iteration(False)
                return
            time.sleep(0.005)
        while context.pending():
            context.iteration(False)

    # -- the sinks the runtime drives --------------------------------------

    def show_indicator(self, state: Any) -> bool:
        """The §5 sink: marshal to the main loop, set a real label, show it."""
        document = state.to_json(monotonic_now=time.monotonic())
        document["atMs"] = self.now_ms()
        self.indicator_shown.append(document)

        def paint() -> None:
            self.indicator_label.set_text(
                f"Listening — {document['deviceId'] or 'default'} · "
                f"{document['locality']} · {document['providerId']}"
            )
            self.indicator_label.set_visible(True)

        self.dispatch(paint)
        return True

    def clear_indicator(self, state: Any) -> bool:
        document = state.to_json(monotonic_now=time.monotonic())
        document["atMs"] = self.now_ms()
        self.indicator_cleared.append(document)

        def paint() -> None:
            self.indicator_label.set_text("")
            self.indicator_label.set_visible(False)

        self.dispatch(paint)
        return True

    def draw_posture(self, posture: Any) -> None:
        """The §18 draw: the presenter's own mapping, a real file into GTK."""
        update = self.presenter.update(
            self.idle_state,
            listening=posture.listening,
            transcribing=posture.transcribing,
        )
        frame = update.frame
        record = {
            "atMs": self.now_ms(),
            "posture": posture.posture,
            "characterState": update.snapshot.mapped.character_state.value
            if hasattr(update.snapshot, "mapped") else "",
            "asset": str(frame.asset_path) if frame is not None else "",
        }
        if frame is not None:
            self.picture.set_filename(str(frame.asset_path))
        self.postures.append(record)

    def observe(self, event: Any) -> None:
        record = {
            "kind": event.kind,
            "requestId": event.request_id,
            "sequence": event.sequence,
            "atMs": self.now_ms(),
        }
        if event.kind in ("microphone_opened", "capture_stopped", "device_lost",
                          "speech_input_degraded"):
            record["payload"] = dict(event.payload)
        self.events.append(record)

    def _routing_snapshot(self, label: str) -> None:
        """The pulse server's own routing table, taken while the fault is live.

        ``sink-inputs`` names which sink each playback stream feeds;
        ``source-outputs`` names which source each record stream reads. The
        one question this answers is the one no runtime record can: were the
        two ends of the loopback attached to the same device.
        """
        import subprocess

        snapshot: dict[str, str] = {"label": label}
        for name, argv in (
            ("sinks", ["pactl", "list", "short", "sinks"]),
            ("sources", ["pactl", "list", "short", "sources"]),
            ("sinkInputs", ["pactl", "list", "short", "sink-inputs"]),
            ("sourceOutputs", ["pactl", "list", "short", "source-outputs"]),
            ("defaultSink", ["pactl", "get-default-sink"]),
        ):
            try:
                completed = subprocess.run(
                    argv, capture_output=True, text=True, timeout=10,
                )
                snapshot[name] = completed.stdout.strip()[:2000]
            except Exception as exc:  # noqa: BLE001
                snapshot[name] = f"error: {type(exc).__name__}"
        self.report.setdefault("routing", []).append(snapshot)

    def raw_loopback_control(self) -> dict[str, Any]:
        """A control experiment inside this exact process and environment.

        Run only when the runtime heard nothing: raw ``parec`` records the
        monitor while raw ``paplay`` plays an espeak WAV, no runtime involved.
        Real audio here means the server was delivering and the runtime path
        lost it; zeros here mean the server itself was serving silence to this
        process, which is a fact about the host and not about this phase.
        """
        import subprocess
        import struct
        import tempfile as _tempfile

        result: dict[str, Any] = {}
        try:
            wav = Path(_tempfile.mkdtemp(prefix="probe-control-")) / "control.wav"
            subprocess.run(
                ["espeak-ng", "-w", str(wav), SPOKEN],
                check=True, capture_output=True, timeout=30,
            )
            recorder = subprocess.Popen(
                ["parec", "--device=RDPSink.monitor", "--format=s16le",
                 "--rate=16000", "--channels=1", "--latency-msec=60",
                 "--client-name=probe-control", "--raw"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            play = subprocess.run(
                ["paplay", "--client-name=probe-control-play", "--", str(wav)],
                capture_output=True, timeout=30,
            )
            time.sleep(0.5)
            recorder.terminate()
            data, _ = recorder.communicate(timeout=10)
            count = len(data) // 2
            total = 0
            peak = 0
            for index in range(0, count * 2, 2):
                sample = struct.unpack_from("<h", data, index)[0]
                total += sample * sample
                peak = max(peak, abs(sample))
            result = {
                "paplayExit": play.returncode,
                "bytes": len(data),
                "rms": round((total / count) ** 0.5, 1) if count else 0.0,
                "peak": peak,
            }
        except Exception as exc:  # noqa: BLE001 - the control reports, never raises
            result = {"error": f"{type(exc).__name__}: {exc}"}
        self.report["rawLoopbackControl"] = result
        return result

    # -- the run -----------------------------------------------------------

    def run(self) -> int:
        if not self.report["display"]["available"]:
            self.report["gate"] = {
                "passed": False, "failures": ["no display; refusing to pretend"],
            }
            print(json.dumps(self.report, indent=2, sort_keys=True))
            return 2

        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        from companion.character.defaults import default_character_path
        from companion.character.listening_link import ListeningLink
        from companion.character.package import validate_package_directory
        from companion.character.surface import CharacterPresenter
        from companion.presentation import PresentationState
        from companion.speech.service import SpeechInputService, SpeechInputServiceOptions
        from companion.voice.service import VoiceService, VoiceServiceOptions

        self.GLib, self.Gtk = GLib, Gtk
        self.report["gtkVersion"] = (
            f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        )
        capture = LogCapture()
        capture.install(GLib)
        self.capture = capture

        package = validate_package_directory(
            Path(self.arguments.package_root) / self.arguments.package
            if self.arguments.package_root else default_character_path()
        )
        window = Gtk.Window(title="Bunny speech input probe")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.indicator_label = Gtk.Label(label="")
        self.indicator_label.set_visible(False)
        self.picture = Gtk.Picture()
        box.append(self.indicator_label)
        box.append(self.picture)
        window.set_child(box)
        window.set_default_size(320, 360)
        window.present()
        self.pump(seconds=1.5)

        self.presenter = CharacterPresenter(package.root.parent)
        self.idle_state = PresentationState(
            session_id="probe-session", task_id="probe-task",
            phase="idle", base_phase="idle", status_text="",
        )

        voice = VoiceService(VoiceServiceOptions(
            runtime_directory=Path(self.arguments.runtime_directory) / "voice",
        ))
        self.voice = voice
        #: Everything the voice worker says about each injection: which
        #: backend, which device, whether playback was provider-owned, and the
        #: full playback outcome on settle. The first three probe failures
        #: recorded only "played", which is a disposition, not a path.
        self.voice_events: list[dict[str, Any]] = []

        def _observe_voice(event: Any) -> None:
            if event.kind in ("audio_started", "speech_finished", "speech_failed",
                              "speech_degraded", "speech_started"):
                self.voice_events.append({
                    "kind": event.kind,
                    "requestId": event.request_id,
                    "atMs": self.now_ms(),
                    "payload": dict(event.payload),
                })

        voice.worker.subscribe(_observe_voice)
        speech = SpeechInputService(SpeechInputServiceOptions(
            runtime_directory=Path(self.arguments.runtime_directory) / "speech",
            voice_worker=voice.worker,
        ))
        self.speech = speech
        speech.indicator.attach(self)  # show/clear are this probe's methods
        link = ListeningLink(draw=self.draw_posture, dispatch=self.dispatch)
        self.link = link
        speech.worker.subscribe(link.on_speech_event)
        speech.worker.subscribe(self.observe)
        speech.refresh()

        device = ""
        for backend in speech.router.backends:
            try:
                if not backend.health(monotonic=time.monotonic()).ready:
                    continue
                for item in backend.discover():
                    if item.monitor:
                        device = item.device_id
                        break
            except Exception:  # noqa: BLE001
                continue
            if device:
                break
        recognizer_ready = any(item.ready for item in speech.registry.health())
        self.report["environment"] = {
            "monitorSource": device,
            "recognizerReady": recognizer_ready,
            "decision": speech.policy.decision.to_json(),
        }
        if not device:
            self.fail("no monitor source is reachable; there is no loopback to capture")
        if not recognizer_ready:
            self.fail("no local recogniser is ready; there is nothing to transcribe with")
        if not speech.policy.decision.may_capture:
            self.fail(f"policy refuses capture: {speech.policy.decision.outcome}")

        try:
            if not self.failures:
                self.check_full_capture(device)
                self.check_cancellation(device)
                self.check_renderer_restart(device)
        finally:
            self.teardown()

        self.report["glib"] = {
            "records": len(capture.records),
            "criticals": len(capture.serious),
            "examples": capture.serious[:4],
        }
        if capture.serious:
            self.fail(f"{len(capture.serious)} GLib critical or error record(s)")
        self.report["gate"] = {"passed": not self.failures, "failures": self.failures}
        print(json.dumps(self.report, indent=2, sort_keys=True))
        if self.arguments.output:
            self.arguments.output.parent.mkdir(parents=True, exist_ok=True)
            self.arguments.output.write_text(
                json.dumps(self.report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8", newline="\n",
            )
        return 0 if not self.failures else 2

    # -- the checks --------------------------------------------------------

    def _event_ms(self, kind: str, request_id: str) -> float | None:
        for item in self.events:
            if item["kind"] == kind and item["requestId"] == request_id:
                return item["atMs"]
        return None

    def _speak_into_loopback(self, *, attempt: int = 1) -> dict[str, Any]:
        """Play the known sentence into the sink, and record what became of it.

        Recorded rather than assumed, because the first observed failures of
        this probe were exactly here and carried no evidence: the capture ran
        its silence timeout and nothing said whether the injection had played,
        degraded or never been announced.
        """
        from companion.presentation import PresentationState

        state = PresentationState(
            session_id="probe-session", task_id=f"probe-injection-{attempt}",
            phase="presenting_result", base_phase="presenting_result",
            result_summary=SPOKEN, revision=attempt,
        )
        self.voice.refresh()
        request, reason = self.voice.announce(state)
        record: dict[str, Any] = {
            "attempt": attempt,
            "announced": request is not None,
            "reason": reason,
            "disposition": "",
            "detail": "",
        }
        if request is not None:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                entry = next(
                    (item for item in self.voice.queue.ledger
                     if item.get("requestId") == request.request_id), None,
                )
                if entry is not None:
                    record["disposition"] = str(entry.get("disposition", ""))
                    record["detail"] = str(entry.get("detail", ""))[:200]
                    break
                # Keep the main loop turning while the utterance plays: the
                # voice worker does not need it, but the capture-side events
                # this probe watches arrive through it.
                self.pump(seconds=0.1)
            record["voiceEvents"] = [
                item for item in self.voice_events
                if item["requestId"] == request.request_id
            ]
        self.report.setdefault("injections", []).append(record)
        return record

    def check_full_capture(self, device: str) -> None:
        outcome = self.speech.speech_input_start(
            sessionId="probe-session",
            activationSource="explicit-protocol-request",
            deviceId=device,
            maxCaptureMs=25_000,
            initialSilenceMs=12_000,
            endpointSilenceMs=1_500,
        )
        if not outcome.get("accepted"):
            self.fail(f"the capture was refused: {outcome.get('detail')}")
            return
        request_id = outcome["requestId"]
        self.pump(seconds=10.0, until=lambda: self._event_ms("capture_started", request_id) is not None)
        self._speak_into_loopback(attempt=1)
        # One retry, and only of the *stimulus*: the injection is harness, not
        # runtime — a person would simply speak again — and the WSLg sink's
        # cold-resume has been observed to swallow a first utterance whole.
        self.pump(seconds=8.0, until=lambda: self._event_ms("speech_detected", request_id) is not None)
        if (self._event_ms("speech_detected", request_id) is None
                and self.speech.worker.active):
            self._routing_snapshot("before-retry")
            self._speak_into_loopback(attempt=2)
            self.pump(seconds=1.0)
            self._routing_snapshot("during-retry")
        self.pump(seconds=45.0, until=lambda: not self.speech.worker.active)
        self.pump(seconds=1.0)

        if self._event_ms("speech_detected", request_id) is None:
            self.raw_loopback_control()

        opened = self._event_ms("microphone_opened", request_id)
        raised = self._event_ms("microphone_indicator_raised", request_id)
        closed = self._event_ms("microphone_closed", request_id)
        cleared = self._event_ms("indicator_cleared", request_id)
        final = self._event_ms("final_transcript", request_id)
        entry = self.speech.ledger.get(request_id)
        transcript = entry.transcript.text if entry is not None else ""
        postures = [item["posture"] for item in self.postures]

        self.report["checks"]["fullCapture"] = {
            "requestId": request_id,
            "indicatorShownOnWidget": bool(self.indicator_shown),
            "indicatorBeforeOpen": bool(raised is not None and opened is not None and raised <= opened),
            "clearedAfterClose": bool(closed is not None and cleared is not None and cleared >= closed),
            "finalTranscript": transcript,
            "posturesWalked": postures,
            "posturesDrawnOnWidget": len(self.postures),
            "listeningDrawn": "listening" in postures,
            "lipSyncDriven": False,
        }
        self.report["measurements"]["fullCapture"] = {
            "indicatorRaisedAtMs": raised,
            "microphoneOpenedAtMs": opened,
            "microphoneClosedAtMs": closed,
            "indicatorClearedAtMs": cleared,
            "finalTranscriptAtMs": final,
            "raisedToOpenMs": round(opened - raised, 3) if raised is not None and opened is not None else None,
            "closedToClearedMs": round(cleared - closed, 3) if closed is not None and cleared is not None else None,
        }
        if not self.indicator_shown:
            self.fail("the indicator never reached the widget")
        if not self.report["checks"]["fullCapture"]["indicatorBeforeOpen"]:
            self.fail("the microphone opened before the indicator was raised")
        if not self.report["checks"]["fullCapture"]["clearedAfterClose"]:
            self.fail("the indicator cleared before the microphone closed")
        if "listening" not in postures:
            self.fail("the character never took the listening posture")
        if not transcript:
            self.fail("no final transcript was produced from the loopback audio")
        if entry is not None:
            self.speech.ledger.reject(request_id, reason="probe complete")

    def check_cancellation(self, device: str) -> None:
        before = len(self.postures)
        outcome = self.speech.speech_input_start(
            sessionId="probe-session",
            activationSource="explicit-protocol-request",
            deviceId=device,
            maxCaptureMs=20_000,
            initialSilenceMs=15_000,
        )
        if not outcome.get("accepted"):
            self.fail(f"the second capture was refused: {outcome.get('detail')}")
            return
        request_id = outcome["requestId"]
        self.pump(seconds=10.0, until=lambda: self._event_ms("capture_started", request_id) is not None)
        cancelled_at = self.now_ms()
        self.speech.speech_input_cancel(
            requestId=request_id,
            cancellationToken=outcome.get("cancellationToken", ""),
        )
        self.pump(seconds=15.0, until=lambda: not self.speech.worker.active)
        self.pump(seconds=1.0)
        closed = self._event_ms("microphone_closed", request_id)
        cleared = self._event_ms("indicator_cleared", request_id)
        frames = self.postures[before:]
        self.report["checks"]["cancellation"] = {
            "requestId": request_id,
            "clearedAfterClose": bool(closed is not None and cleared is not None and cleared >= closed),
            "endedNeutral": bool(frames) and frames[-1]["posture"] == "neutral",
            "transcriptHeld": self.speech.ledger.get(request_id) is not None,
        }
        self.report["measurements"]["cancellation"] = {
            "cancelRequestedAtMs": cancelled_at,
            "indicatorClearedAtMs": cleared,
            "cancelToClearedMs": round(cleared - cancelled_at, 3) if cleared is not None else None,
        }
        if not self.report["checks"]["cancellation"]["clearedAfterClose"]:
            self.fail("cancellation cleared the indicator before the device closed")
        if not self.report["checks"]["cancellation"]["endedNeutral"]:
            self.fail("cancellation left the character out of neutral")
        if self.report["checks"]["cancellation"]["transcriptHeld"]:
            self.fail("a cancelled capture left a transcript waiting")

    def check_renderer_restart(self, device: str) -> None:
        from companion.character.surface import CharacterPresenter

        outcome = self.speech.speech_input_start(
            sessionId="probe-session",
            activationSource="explicit-protocol-request",
            deviceId=device,
            maxCaptureMs=15_000,
            initialSilenceMs=3_000,
        )
        if not outcome.get("accepted"):
            self.fail(f"the third capture was refused: {outcome.get('detail')}")
            return
        request_id = outcome["requestId"]
        self.pump(seconds=10.0, until=lambda: self._event_ms("capture_started", request_id) is not None)
        self.presenter = CharacterPresenter(self.presenter.root)
        answer = self.link.restart_renderer(self.draw_posture)
        self.pump(seconds=20.0, until=lambda: not self.speech.worker.active)
        settled = [
            item["kind"] for item in self.events if item["requestId"] == request_id
        ]
        self.report["checks"]["rendererRestart"] = {
            "decision": answer,
            "captureSurvived": "capture_stopped" in settled,
            "lastPosture": self.postures[-1]["posture"] if self.postures else "",
        }
        if "capture_stopped" not in settled:
            self.fail("a renderer restart stopped the capture")

    # -- teardown ----------------------------------------------------------

    def teardown(self) -> None:
        self.link.close()
        self.speech.close()
        self.voice.close()
        self.pump(seconds=1.0)
        survivors = sorted(self.idle_sources - self.retired)
        speech_threads = sum(
            1 for item in threading.enumerate()
            if item.name.startswith("companion-speech") or item.name.startswith("speech-capture")
        )
        self.report["checks"]["teardown"] = {
            "idleSourcesCreated": len(self.idle_sources),
            "idleSourcesSurviving": len(survivors),
            "speechThreadsRemaining": speech_threads,
            "indicatorVisible": bool(self.speech.indicator.listening),
        }
        if survivors:
            self.fail(f"{len(survivors)} GLib idle source(s) survived teardown")
        if speech_threads:
            self.fail("a capture thread survived teardown")
        if self.speech.indicator.listening:
            self.fail("the indicator stayed lit through teardown")
        self.report["link"] = self.link.describe()

    # The indicator-sink protocol, satisfied by this probe object itself.
    def show(self, state: Any) -> bool:
        return self.show_indicator(state)

    def clear(self, state: Any) -> bool:
        return self.clear_indicator(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", default="")
    parser.add_argument("--package", default="default-bunny")
    parser.add_argument(
        "--runtime-directory", default="/tmp/bunny-speech-input-probe",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    Path(arguments.runtime_directory).mkdir(parents=True, exist_ok=True)

    probe = Probe(arguments)
    try:
        return probe.run()
    except Exception:  # noqa: BLE001 - the probe reports its own failure
        probe.report["gate"] = {
            "passed": False,
            "failures": ["the probe raised", traceback.format_exc().splitlines()[-1]],
        }
        probe.report["traceback"] = traceback.format_exc()
        print(json.dumps(probe.report, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
