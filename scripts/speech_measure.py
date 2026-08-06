#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§25's measurements: what speech input actually costs on this machine.

Every number is measured on this host and labelled with how: RSS and PSS from
``/proc/self`` (``NOT_RUN`` where there is no ``/proc``), latencies from the
capture worker's own :class:`companion.speech.worker.CaptureMeasurement` —
monotonic stamps taken where the events happen — and CPU from
``/proc/self/stat`` deltas across the interval. The audio path is the loopback
the installed slice uses: the voice runtime speaks a known sentence into the
sink and capture reads the sink's monitor, so the capture chain, the energy
gate and the recogniser are all real while no physical microphone is claimed.

What is deliberately NOT here: any claim about full Bunny OS memory use (§25's
last sentence), any phoneme or accuracy figure, and any number for a machine
this did not run on.

Output: one JSON document, with min/median/p95/max/count per series.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

SPOKEN = "count the words in this note please"


def _memory() -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    result["rssBytes"] = int(line.split()[1]) * 1024
    except OSError:
        return {"result": "NOT_RUN", "reason": "no /proc/self/status"}
    try:
        with open("/proc/self/smaps_rollup", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    result["pssBytes"] = int(line.split()[1]) * 1024
    except OSError:
        result["pssBytes"] = None
    return result


def _cpu_seconds() -> float | None:
    try:
        with open("/proc/self/stat", encoding="ascii") as handle:
            fields = handle.read().split()
        ticks = int(fields[13]) + int(fields[14])
        return ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, AttributeError):
        return None


def _series(values: list[float]) -> dict[str, Any]:
    cleaned = sorted(value for value in values if value is not None)
    if not cleaned:
        return {"count": 0, "result": "NOT_RUN", "reason": "no samples were produced"}
    def _at(fraction: float) -> float:
        index = min(len(cleaned) - 1, max(0, round(fraction * (len(cleaned) - 1))))
        return cleaned[index]
    return {
        "count": len(cleaned),
        "min": round(cleaned[0], 6),
        "median": round(_at(0.5), 6),
        "p95": round(_at(0.95), 6),
        "max": round(cleaned[-1], 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=int, default=12)
    parser.add_argument("--cancellations", type=int, default=6)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-directory", type=Path, default=Path("/tmp/bunny-speech-measure"))
    arguments = parser.parse_args()
    arguments.runtime_directory.mkdir(parents=True, exist_ok=True)

    from companion.presentation import PresentationState
    from companion.speech.service import SpeechInputService, SpeechInputServiceOptions
    from companion.voice.service import VoiceService, VoiceServiceOptions

    report: dict[str, Any] = {
        "schema": "bunny-os/speech-input-measurements/1",
        "spokenSentence": SPOKEN,
        "path": (
            "voice runtime -> sink -> sink monitor -> parec -> energy gate -> "
            "local recogniser; no physical microphone validated"
        ),
        "fullSystemMemoryClaimed": False,
        "memory": {},
        "latency": {},
        "cpu": {},
        "storage": {},
        "notes": [],
    }

    gc.collect()
    report["memory"]["processBaseline"] = _memory()

    from companion.speech.vertical_slice import _LoopbackSink
    from companion.voice.policy import VoicePreferences

    loop_sink = _LoopbackSink().create()
    report["loopbackSink"] = loop_sink.sink or "host monitor fallback"
    voice = VoiceService(VoiceServiceOptions(
        runtime_directory=arguments.runtime_directory / "voice",
        preferences=VoicePreferences(preferred_device=loop_sink.sink),
    ))
    gc.collect()
    report["memory"]["withVoiceRuntime"] = _memory()

    speech = SpeechInputService(SpeechInputServiceOptions(
        runtime_directory=arguments.runtime_directory / "speech",
        voice_worker=voice.worker,
    ))
    speech.refresh()
    gc.collect()
    # §25: "capture worker idle" — the whole subsystem constructed, no capture
    # running, no model loaded. The recogniser's own cost is measured below by
    # the first capture, which is what loads it.
    report["memory"]["speechInputIdle"] = _memory()

    class _Sink:
        def show(self, state: Any) -> bool:
            return True

        def clear(self, state: Any) -> bool:
            return True

    speech.attach_indicator_sink(_Sink())

    device = loop_sink.monitor
    if not device:
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
    if not device or not recognizer_ready or not speech.policy.decision.may_capture:
        report["result"] = "NOT_RUN"
        report["reason"] = (
            f"monitor={device or 'none'}, recognizerReady={recognizer_ready}, "
            f"decision={speech.policy.decision.outcome}"
        )
        _write(report, arguments)
        speech.close()
        voice.close()
        loop_sink.destroy()
        return 2

    def _wait_idle(timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not speech.worker.active:
                return True
            time.sleep(0.01)
        return not speech.worker.active

    def _speak() -> None:
        state = PresentationState(
            session_id="measure-session", task_id="measure-injection",
            phase="presenting_result", base_phase="presenting_result",
            result_summary=SPOKEN, revision=1,
        )
        voice.refresh()
        voice.announce(state)

    open_latency: list[float] = []
    first_frame: list[float] = []
    indicator_latency: list[float] = []
    speech_detect: list[float] = []
    first_partial: list[float] = []
    final_latency: list[float] = []
    close_latency: list[float] = []
    buffer_peaks: list[float] = []
    capture_cpu: list[float] = []
    recognition_cpu: list[float] = []
    orderings_held = 0
    transcripts: list[str] = []
    storage_peaks: list[float] = []

    for index in range(arguments.captures):
        cpu_before = _cpu_seconds()
        outcome = speech.speech_input_start(
            sessionId="measure-session",
            activationSource="explicit-protocol-request",
            deviceId=device,
            maxCaptureMs=25_000,
            initialSilenceMs=12_000,
            endpointSilenceMs=1_500,
        )
        if not outcome.get("accepted"):
            report["notes"].append(f"capture {index} refused: {outcome.get('detail')}")
            continue
        request_id = outcome["requestId"]
        # Inject only once frames are actually flowing: the monitor stream's
        # first bytes arrive a couple of seconds after the recorder spawns,
        # and a sentence played before them is a sentence the capture never
        # met — measured as eleven of twelve captures hearing nothing.
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            current = speech.worker.status().get("current") or {}
            if int(current.get("bytesCaptured") or 0) > 0:
                break
            time.sleep(0.02)
        _speak()
        _wait_idle()
        cpu_after = _cpu_seconds()
        measurement = speech.worker.measurement(request_id)
        if measurement is None:
            continue
        document = measurement.to_json()
        if document["indicatorBeforeOpen"] and document["indicatorClearedAfterClose"]:
            orderings_held += 1
        indicator_latency.append(document["indicatorLatencySeconds"])
        open_latency.append(document["microphoneOpenLatencySeconds"])
        first_frame.append(document["firstFrameLatencySeconds"])
        speech_detect.append(document["speechDetectLatencySeconds"])
        first_partial.append(document["firstPartialLatencySeconds"])
        final_latency.append(document["finalTranscriptLatencySeconds"])
        close_latency.append(document["deviceCloseLatencySeconds"])
        buffer_peaks.append(document["peakBufferedBytes"])
        if cpu_before is not None and cpu_after is not None:
            capture_cpu.append(cpu_after - cpu_before)
        entry = speech.ledger.get(request_id)
        if entry is not None:
            transcripts.append(entry.transcript.text)
            speech.ledger.reject(request_id, reason="measurement complete")
        if index == 0:
            gc.collect()
            report["memory"]["afterFirstRecognition"] = _memory()

    # Cancellation latency: start, wait for capture, cancel, time the settle.
    cancel_latency: list[float] = []
    for _index in range(arguments.cancellations):
        outcome = speech.speech_input_start(
            sessionId="measure-session",
            activationSource="explicit-protocol-request",
            deviceId=device,
            maxCaptureMs=20_000,
            initialSilenceMs=15_000,
        )
        if not outcome.get("accepted"):
            continue
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            current = speech.worker.status().get("current") or {}
            if current.get("phase") == "capturing":
                break
            time.sleep(0.02)
        started = time.monotonic()
        speech.speech_input_cancel(
            requestId=outcome["requestId"],
            cancellationToken=outcome.get("cancellationToken", ""),
        )
        _wait_idle(timeout=20.0)
        cancel_latency.append(time.monotonic() - started)

    # Device-loss shutdown: start a capture, kill the recorder, time the settle.
    loss_latency: list[float] = []
    outcome = speech.speech_input_start(
        sessionId="measure-session",
        activationSource="explicit-protocol-request",
        deviceId=device,
        maxCaptureMs=20_000,
        initialSilenceMs=15_000,
    )
    if outcome.get("accepted"):
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            current = speech.worker.status().get("current") or {}
            if current.get("phase") == "capturing":
                break
            time.sleep(0.02)
        killed = _kill_recorders()
        if killed:
            started = time.monotonic()
            _wait_idle(timeout=20.0)
            loss_latency.append(time.monotonic() - started)
            report["notes"].append(
                f"device loss produced by terminating {killed} recorder process(es); "
                "everything downstream — detection, closure, indicator — is real"
            )
        else:
            speech.worker.cancel(outcome["requestId"], token=outcome.get("cancellationToken", ""))
            _wait_idle()
            report["notes"].append("no recorder process was found to kill; loss latency NOT_RUN")

    # Restart time.
    restart: list[float] = []
    for _index in range(5):
        started = time.monotonic()
        speech.restart_worker(timeout=15.0)
        restart.append(time.monotonic() - started)

    workspaces = list(Path("/tmp").glob("bunny-speech-*"))
    storage_peaks.append(sum(
        item.stat().st_size for workspace in workspaces
        for item in workspace.rglob("*") if item.is_file()
    ) if workspaces else 0)

    gc.collect()
    report["memory"]["combinedEnd"] = _memory()
    report["memory"]["note"] = (
        "processBaseline is this interpreter; withVoiceRuntime adds the voice "
        "service; speechInputIdle adds the constructed speech subsystem with no "
        "model loaded; afterFirstRecognition includes the loaded recognition "
        "model. Differences between stages attribute cost; none of these is a "
        "full-system figure."
    )
    report["latency"] = {
        "indicatorRaiseSeconds": _series(indicator_latency),
        "microphoneOpenSeconds": _series(open_latency),
        "firstFrameSeconds": _series(first_frame),
        "speechDetectSeconds": _series(speech_detect),
        "firstPartialSeconds": _series(first_partial),
        "finalTranscriptSeconds": _series(final_latency),
        "cancellationSeconds": _series(cancel_latency),
        "deviceLossShutdownSeconds": _series(loss_latency),
        "deviceCloseSeconds": _series(close_latency),
        "serviceRestartSeconds": _series(restart),
        "indicatorOrderingHeld": orderings_held,
        "capturesMeasured": len(open_latency),
    }
    report["cpu"] = {
        "captureAndRecognitionCpuSeconds": _series(capture_cpu),
        "note": (
            "process CPU (utime+stime) across each whole capture including "
            "recognition; the recogniser runs in-process so the two are not "
            "separable without a second process, and no separate number is invented"
        ),
    }
    report["storage"] = {
        "peakBufferedBytes": _series(buffer_peaks),
        "temporaryStorageBytes": _series(storage_peaks),
    }
    report["transcripts"] = transcripts[:4]

    speech.close()
    voice.close()
    loop_sink.destroy()
    _write(report, arguments)
    return 0


def _kill_recorders() -> int:
    import signal

    killed = 0
    proc = Path("/proc")
    if not proc.is_dir():
        return 0
    own = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = ""
        parent = 0
        for line in status.splitlines():
            if line.startswith("Name:"):
                name = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
            elif line.startswith("PPid:"):
                parent = int(line.split()[1])
            if name and parent:
                break
        if parent == own and name in ("parec", "pw-record", "arecord"):
            try:
                os.kill(int(entry.name), signal.SIGKILL)
                killed += 1
            except OSError:
                continue
    return killed


def _write(report: dict[str, Any], arguments: argparse.Namespace) -> None:
    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
