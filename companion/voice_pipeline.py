# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-honest inventory of the spoken pipeline. Never a spoken e2e PASS.

The product path is:

    push-to-talk → STT (Vosk) → intent/model → tool/task → response → TTS
    (Pocket / Kitten / eSpeak)

This module *probes* that path on the development host. A missing
``libvosk.so``, Vosk model directory, microphone, ``llama-cli``/GGUF, or TTS
binary is ``NOT_RUN``. A labelled fixture transcript is never live speech.
Spoken end-to-end on a Fedora image is ``IMAGE_BOOT`` and stays ``NOT_RUN``
until Platform produces that evidence.

``passed`` is true when nothing failed. ``NOT_RUN`` is not ``FAIL``, and it is
not spoken ``PASS`` either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any

from companion.executor import TaskContext
from companion.gtk_shell import CompanionViewModel
from companion.intents import recognise
from companion.local_intent import LocalIntentExecutor
from companion.model import CompanionPhase
from companion.speech.recognizers import MODEL_DIRECTORIES
from companion.speech.vosk_runtime import (
    LIBRARY_CANDIDATES,
    VoskRuntimeUnavailable,
    probe as probe_vosk,
)
from companion.visual_keys import VISUAL_KEYS
from companion.voice.system import VOICE_CANDIDATES, local_voice_available
from companion.voice_story import VOICE_STORY_UTTERANCE

__all__ = [
    "CODE",
    "IMAGE_BOOT",
    "NOT_RUN",
    "VoicePipelineReport",
    "run_voice_pipeline_inventory",
]

CODE = "CODE"
NOT_RUN = "NOT_RUN"
IMAGE_BOOT = "IMAGE_BOOT"

_CAPTURE_HELPERS = ("pw-record", "parec", "arecord")
_LLAMA_CANDIDATES = ("/usr/bin/llama-cli", "/bin/llama-cli")
_GGUF_DIRECTORIES = (
    "/usr/share/bunny-os/agent-models",
    "~/.local/share/bunny-os/agent-models",
)
_POCKET_ROOT = Path("/usr/share/bunny-os/voice/pocket/english")
_KITTEN_ROOT = Path("/usr/share/bunny-os/voice/kitten/nano-int8")


@dataclass
class VoicePipelineReport:
    stages: list[dict[str, Any]] = field(default_factory=list)
    transcript: str = ""
    transcript_source: str = "labelled-fixture"
    intent_kind: str = ""
    planned_tool: str = ""
    spoken_e2e: str = NOT_RUN
    ai_status: str = "PARTIAL"

    def record(
        self,
        number: int,
        name: str,
        *,
        evidence: str,
        status: str,
        detail: str = "",
        **extra: Any,
    ) -> None:
        if status == "PASS" and evidence in {IMAGE_BOOT, NOT_RUN}:
            raise ValueError(
                f"{name}: {evidence} evidence cannot be recorded as PASS "
                "(host harness must not mint spoken or image success)"
            )
        if name == "spoken e2e" and status == "PASS":
            raise ValueError("spoken e2e must never be PASS from this host harness")
        self.stages.append({
            "step": number,
            "name": name,
            "evidence": evidence,
            "status": status,
            "detail": detail,
            **extra,
        })

    @property
    def passed(self) -> bool:
        return all(item["status"] != "FAIL" for item in self.stages)

    @property
    def not_run(self) -> tuple[str, ...]:
        return tuple(
            f"{item['step']}. {item['name']}: {item['detail']}"
            for item in self.stages if item["status"] == NOT_RUN
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "story": "voice-pipeline-inventory",
            "aiStatus": self.ai_status,
            "passed": self.passed,
            "spokenE2e": self.spoken_e2e,
            "physicalMicrophoneValidated": False,
            "modelBytesVendored": False,
            "gpuClaimed": False,
            "npuClaimed": False,
            "transcript": self.transcript,
            "transcriptSource": self.transcript_source,
            "intentKind": self.intent_kind,
            "plannedTool": self.planned_tool,
            "typedInputPreserved": True,
            "stages": list(self.stages),
            "notRun": list(self.not_run),
        }


def _status(present: bool, *, missing: str, present_detail: str) -> tuple[str, str]:
    if present:
        return "PASS", present_detail
    return NOT_RUN, missing


def _vosk_runtime() -> tuple[str, str]:
    try:
        origin = probe_vosk()
    except (VoskRuntimeUnavailable, OSError) as exc:
        return NOT_RUN, str(exc)
    return "PASS", f"packaged Vosk C runtime at {origin}"


def _vosk_model() -> tuple[str, str]:
    searched: list[str] = []
    for raw in MODEL_DIRECTORIES:
        root = Path(raw).expanduser()
        searched.append(str(root))
        if not root.is_dir():
            continue
        try:
            matches = sorted(
                path for path in root.iterdir()
                if path.is_dir() and path.name.startswith("vosk-model")
            )
        except OSError as exc:
            return NOT_RUN, f"{root} could not be listed: {exc}"
        if matches:
            return "PASS", str(matches[0])
    return NOT_RUN, (
        "no vosk-model-* directory under "
        + ", ".join(searched)
        + "; this repo does not vendor model bytes"
    )


def _capture_helpers() -> tuple[tuple[str, ...], bool]:
    found = tuple(name for name in _CAPTURE_HELPERS if shutil.which(name))
    return found, Path("/dev/snd").is_dir()


def _llama_cli() -> tuple[str, str]:
    for path in _LLAMA_CANDIDATES:
        if Path(path).is_file():
            return "PASS", path
    return NOT_RUN, "llama-cli is not at /usr/bin or /bin; this host does not search PATH"


def _gguf() -> tuple[str, str]:
    searched: list[str] = []
    for raw in _GGUF_DIRECTORIES:
        root = Path(raw).expanduser()
        searched.append(str(root))
        if not root.is_dir():
            continue
        matches = sorted(root.glob("*.gguf"))
        if matches:
            return "PASS", str(matches[0])
    return NOT_RUN, "no GGUF under " + ", ".join(searched)


def run_voice_pipeline_inventory(
    *, utterance: str = VOICE_STORY_UTTERANCE,
) -> VoicePipelineReport:
    """Probe each spoken-pipeline stage. Never invents a spoken PASS."""
    report = VoicePipelineReport()
    report.transcript = utterance
    report.transcript_source = "labelled-fixture"

    report.record(
        1, "push-to-talk activation",
        evidence=CODE,
        status="PASS",
        detail=(
            "SpeechInputRequest activationSource is a closed set; "
            "wake-word enable() raises; protocol op speech_input_start"
        ),
        paths=["companion/speech/request.py", "companion/speech/wakeword.py"],
    )

    helpers, snd = _capture_helpers()
    report.record(
        2, "microphone capture helper",
        evidence=CODE,
        status="PASS" if helpers else NOT_RUN,
        detail=(
            "capture helper " + ",".join(helpers)
            if helpers else
            "no pw-record/parec/arecord on PATH"
        ),
        soundDeviceNode=snd,
        liveMicrophone=NOT_RUN,
    )
    report.record(
        3, "live microphone journey",
        evidence=IMAGE_BOOT,
        status=NOT_RUN,
        detail=(
            "guest microphone on a Fedora image is required; "
            f"/dev/snd {'present' if snd else 'absent'} on this host is not that journey"
        ),
    )

    vosk_status, vosk_detail = _vosk_runtime()
    report.record(
        4, "STT runtime (libvosk)",
        evidence=CODE,
        status=vosk_status,
        detail=vosk_detail,
        candidates=list(LIBRARY_CANDIDATES),
    )
    model_status, model_detail = _vosk_model()
    report.record(
        5, "STT Vosk model directory",
        evidence=CODE,
        status=model_status,
        detail=model_detail,
        directories=list(MODEL_DIRECTORIES),
    )
    report.record(
        6, "STT live recognition",
        evidence=IMAGE_BOOT,
        status=NOT_RUN,
        detail=(
            "STT not live; using a labelled fixture transcript, not a recorded microphone. "
            "Do not treat fixture text as spoken e2e."
        ),
        fixture=True,
        transcript=utterance,
    )

    report.record(
        7, "silence / no-speech isolation",
        evidence=CODE,
        status="PASS",
        detail="CaptureWorker settles pure silence as no-speech with no transcript",
        tests=["tests.companion.test_speech_worker.Endings.test_pure_silence_settles_as_no_speech_with_no_transcript"],
    )
    report.record(
        8, "malformed transcript isolation",
        evidence=CODE,
        status="PASS",
        detail="control characters and oversize text are refused; partials cannot become tasks",
        tests=[
            "tests.companion.test_speech_security.OversizedAndMalformedInput.test_a_malformed_frame_cannot_crash_the_detector",
            "companion/speech/transcript.py bounded_transcript_text",
        ],
    )

    intent = recognise(utterance)
    report.record(
        9, "intent (fixture transcript)",
        evidence=CODE,
        status="PASS" if intent is not None else "FAIL",
        detail="" if intent is None else intent.kind,
        fixture=True,
    )
    if intent is None:
        report.intent_kind = ""
        report.record(10, "tool/task plan (fixture transcript)", evidence=CODE, status="FAIL",
                      detail="no intent recognised")
    else:
        report.intent_kind = intent.kind
        executor = LocalIntentExecutor()
        context = TaskContext(
            task={"taskId": "voice-pipeline", "originalRequest": utterance},
            classification="internal",
            plan_revision=1,
        )
        plan = executor.plan(context)
        operation = plan.operations[0] if plan.operations else None
        local = operation is not None and operation.destination == "local"
        report.planned_tool = operation.tool if operation is not None else ""
        report.record(
            10, "tool/task plan (fixture transcript)",
            evidence=CODE,
            status="PASS" if local else "FAIL",
            detail=report.planned_tool if local else "no local operation",
            fixture=True,
            requiresApproval=bool(operation.requires_approval) if operation else False,
        )

    llama_status, llama_detail = _llama_cli()
    gguf_status, gguf_detail = _gguf()
    report.record(
        11, "local model (llama-cli)",
        evidence=CODE,
        status=llama_status,
        detail=llama_detail,
    )
    report.record(
        12, "local model (GGUF weights)",
        evidence=CODE,
        status=gguf_status,
        detail=gguf_detail,
    )
    report.record(
        13, "model timeout / crash isolation",
        evidence=CODE,
        status="PASS",
        detail=(
            "llamacli watchdog uses GenerationRequest.deadline_seconds "
            "(agent bridge 120s); adapter returns GenerationOutcome(ok=False) "
            "rather than raising into the companion process"
        ),
        liveGeneration=NOT_RUN,
        tests=["companion/agents/adapters/llamacli.py"],
    )
    report.record(
        14, "tool failure isolation",
        evidence=CODE,
        status="PASS",
        detail="ToolBroker.invoke catches Exception and records a failed outcome; the companion stays up",
        tests=["companion/tools.py"],
    )

    pocket = _POCKET_ROOT.is_dir()
    kitten = _KITTEN_ROOT.is_dir()
    espeak = local_voice_available()
    report.record(
        15, "TTS binary / weights probe",
        evidence=CODE,
        status="PASS" if (pocket or kitten or espeak) else NOT_RUN,
        detail=(
            f"pocket weights {'present' if pocket else 'absent'}; "
            f"kitten weights {'present' if kitten else 'absent'}; "
            f"espeak/spd-say {'present' if espeak else 'absent'}"
        ),
        candidates=[item[0] for item in VOICE_CANDIDATES],
        livePlayback=NOT_RUN,
    )
    report.record(
        16, "TTS live playback",
        evidence=IMAGE_BOOT,
        status=NOT_RUN,
        detail="unattended host must not play speech; Fedora image + speakers are required",
    )

    report.record(
        17, "text / keyboard fallback",
        evidence=CODE,
        status="PASS",
        detail=(
            "CompanionViewModel.submit() is the typed path; speech_input_* "
            "unavailable answers set typedInputPreserved=true and taskAffected=false"
        ),
        paths=["companion/gtk_shell.py", "companion/service.py"],
    )
    missing_client_ops = [
        name for name in ("submit", "press_to_talk", "confirm_speech")
        if not hasattr(CompanionViewModel, name)
    ]
    report.record(
        18, "keyboard path remains callable",
        evidence=CODE,
        status="PASS" if not missing_client_ops else "FAIL",
        detail="CompanionViewModel still exposes submit/press_to_talk/confirm_speech"
        if not missing_client_ops else f"missing {missing_client_ops}",
    )

    required_phases = {
        "listening": CompanionPhase.LISTENING.value,
        "understanding": CompanionPhase.UNDERSTANDING.value,
        "executing": CompanionPhase.WORKING.value,
        "failed": CompanionPhase.ERROR.value,
    }
    report.record(
        19, "companion AI states (real pipeline)",
        evidence=CODE,
        status="PASS",
        detail=(
            "listening/transcribing/understanding/working/error are real "
            "CompanionPhase values. Visual Key 'thinking' is a projection of "
            "understanding/planning/starting/recovering, not chain-of-thought "
            "and not a fake spinner over missing STT."
        ),
        phases=required_phases,
        visualKeys=list(VISUAL_KEYS),
        thinkingIsNotChainOfThought=True,
    )

    report.spoken_e2e = NOT_RUN
    report.ai_status = "PARTIAL"
    report.record(
        20, "spoken e2e",
        evidence=IMAGE_BOOT,
        status=NOT_RUN,
        detail=(
            "BLOCKED on Fedora image evidence: libvosk, vosk-model dir, guest mic, "
            "llama-cli/GGUF, TTS weights or espeak-ng, speakers. Host unit tests are not that."
        ),
    )
    return report


def construct_speech_and_voice_safely() -> dict[str, Any]:
    """Build SpeechInputService and VoiceService. Absence must not raise."""
    import tempfile

    from companion.speech.service import SpeechInputService, SpeechInputServiceOptions
    from companion.voice.service import VoiceService, VoiceServiceOptions

    result: dict[str, Any] = {
        "speechRaised": False,
        "voiceRaised": False,
        "speechAvailable": False,
        "voiceAvailable": False,
        "typedInputPreserved": True,
        "spokenE2e": NOT_RUN,
    }
    speech_root = Path(tempfile.mkdtemp(prefix="bunny-voice-pipeline-speech-"))
    voice_root = Path(tempfile.mkdtemp(prefix="bunny-voice-pipeline-voice-"))
    try:
        speech = SpeechInputService(SpeechInputServiceOptions(runtime_directory=speech_root))
        try:
            health = speech.speech_input_health()
            result["speechAvailable"] = True
            result["speechReadiness"] = health.get("readinessState")
        finally:
            speech.close()
    except Exception as exc:  # noqa: BLE001 - the point of the probe
        result["speechRaised"] = True
        result["speechError"] = str(exc)
    try:
        voice = VoiceService(VoiceServiceOptions(
            runtime_directory=voice_root, start_worker=False,
        ))
        try:
            health = voice.voice_health()
            result["voiceAvailable"] = True
            result["voiceProviderCount"] = (
                len(health.get("providers", [])) if isinstance(health, dict) else 0
            )
        finally:
            voice.close()
    except Exception as exc:  # noqa: BLE001 - the point of the probe
        result["voiceRaised"] = True
        result["voiceError"] = str(exc)
    return result
