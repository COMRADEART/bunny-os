# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-honest inventory of the spoken pipeline. Every voice stage is NOT_RUN.

Platform confirmed there is no Fedora 44 builder/image on the horizon.
Package lists may name ``llama-cpp``, ``espeak-ng``, and ``vosk-api-devel``;
that is not evidence they land in an image. Finding a binary on this host
is not spoken e2e and is not IMAGE/BOOT.

A labelled fixture transcript is never live speech. Spoken e2e is NOT_RUN.
Do not wait for image evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any

from companion.gtk_shell import CompanionViewModel
from companion.intents import recognise
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
    "NOT_RUN",
    "VOICE_STAGES",
    "VoicePipelineReport",
    "run_voice_pipeline_inventory",
]

CODE = "CODE"
NOT_RUN = "NOT_RUN"

#: Every spoken-pipeline stage. Host label is always NOT_RUN.
VOICE_STAGES: tuple[str, ...] = (
    "push-to-talk",
    "microphone",
    "STT (Vosk)",
    "intent / model",
    "tool / task",
    "response",
    "TTS (Pocket/Kitten/eSpeak)",
    "spoken e2e",
)

_CAPTURE_HELPERS = ("pw-record", "parec", "arecord")
_LLAMA_CANDIDATES = ("/usr/bin/llama-cli", "/bin/llama-cli")
_GGUF_DIRECTORIES = (
    "/usr/share/bunny-os/agent-models",
    "~/.local/share/bunny-os/agent-models",
)
_POCKET_ROOT = Path("/usr/share/bunny-os/voice/pocket/english")
_KITTEN_ROOT = Path("/usr/share/bunny-os/voice/kitten/nano-int8")
_NO_IMAGE = (
    "Platform: no Fedora 44 builder/image on the horizon. "
    "A package-list name is not image evidence. Host label is NOT_RUN."
)


def _not_image(detail: str) -> str:
    return detail.rstrip(".") + ". " + _NO_IMAGE


@dataclass
class VoicePipelineReport:
    stages: list[dict[str, Any]] = field(default_factory=list)
    isolation: list[dict[str, Any]] = field(default_factory=list)
    transcript: str = ""
    transcript_source: str = "labelled-fixture"
    intent_kind: str = ""
    planned_tool: str = ""
    spoken_e2e: str = NOT_RUN
    ai_status: str = "PARTIAL"
    typed_fallback: dict[str, Any] = field(default_factory=dict)

    def record_voice_stage(
        self,
        number: int,
        name: str,
        *,
        detail: str,
        **extra: Any,
    ) -> None:
        if name not in VOICE_STAGES:
            raise ValueError(f"{name!r} is not a voice stage")
        if extra.get("status") == "PASS":
            raise ValueError(
                f"{name}: host harness labels every voice stage NOT_RUN"
            )
        self.stages.append({
            "step": number,
            "name": name,
            "evidence": NOT_RUN,
            "status": NOT_RUN,
            "detail": detail,
            **extra,
        })

    def record_isolation(
        self,
        failure: str,
        *,
        code: str,
        contract: str,
        detail: str,
    ) -> None:
        self.isolation.append({
            "failure": failure,
            "code": code,
            "contract": contract,
            "hostStatus": NOT_RUN,
            "detail": detail,
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
            "fedoraImageOnHorizon": False,
            "packageListIsNotImageEvidence": True,
            "physicalMicrophoneValidated": False,
            "modelBytesVendored": False,
            "gpuClaimed": False,
            "npuClaimed": False,
            "conversationSummaryWired": False,
            "cloudContextNoneTightened": False,
            "transcript": self.transcript,
            "transcriptSource": self.transcript_source,
            "intentKind": self.intent_kind,
            "plannedTool": self.planned_tool,
            "typedInputPreserved": True,
            "typedFallback": dict(self.typed_fallback),
            "stages": list(self.stages),
            "failureIsolation": list(self.isolation),
            "notRun": list(self.not_run),
        }


def _vosk_note() -> str:
    try:
        origin = probe_vosk()
    except (VoskRuntimeUnavailable, OSError) as exc:
        return _not_image(f"libvosk probe: {exc}")
    return _not_image(
        f"this host mapped {origin}; that is not Fedora image evidence and is not spoken e2e"
    )


def _model_note() -> str:
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
            return _not_image(f"{root} could not be listed: {exc}")
        if matches:
            return _not_image(
                f"this host has {matches[0]}; model bytes on a cloud host are not image evidence"
            )
    return _not_image(
        "no vosk-model-* directory under "
        + ", ".join(searched)
        + "; this repo does not vendor model bytes"
    )


def _capture_note() -> str:
    helpers = tuple(name for name in _CAPTURE_HELPERS if shutil.which(name))
    snd = Path("/dev/snd").is_dir()
    bits = []
    if helpers:
        bits.append("capture helper " + ",".join(helpers))
    if snd:
        bits.append("/dev/snd present")
    if not bits:
        bits.append("no pw-record/parec/arecord and no /dev/snd")
    return _not_image("; ".join(bits) + "; live microphone is NOT_RUN")


def _llama_note() -> str:
    for path in _LLAMA_CANDIDATES:
        if Path(path).is_file():
            return _not_image(
                f"{path} exists on this host; llama-cpp in a package list is not image evidence"
            )
    return _not_image("llama-cli is not at /usr/bin or /bin")


def _gguf_note() -> str:
    searched: list[str] = []
    for raw in _GGUF_DIRECTORIES:
        root = Path(raw).expanduser()
        searched.append(str(root))
        if not root.is_dir():
            continue
        matches = sorted(root.glob("*.gguf"))
        if matches:
            return _not_image(f"this host has {matches[0]}; GGUF on a cloud host is not image evidence")
    return _not_image("no GGUF under " + ", ".join(searched))


def _tts_note() -> str:
    pocket = _POCKET_ROOT.is_dir()
    kitten = _KITTEN_ROOT.is_dir()
    espeak = local_voice_available()
    return _not_image(
        f"pocket weights {'present' if pocket else 'absent'}; "
        f"kitten weights {'present' if kitten else 'absent'}; "
        f"espeak/spd-say {'present' if espeak else 'absent'}; "
        "espeak-ng in a package list is not image evidence"
    )


def run_voice_pipeline_inventory(
    *, utterance: str = VOICE_STORY_UTTERANCE,
) -> VoicePipelineReport:
    """Label every voice stage NOT_RUN. Never invents a spoken PASS."""
    report = VoicePipelineReport()
    report.transcript = utterance
    report.transcript_source = "labelled-fixture"
    report.spoken_e2e = NOT_RUN
    report.ai_status = "PARTIAL"

    intent = recognise(utterance)
    report.intent_kind = intent.kind if intent is not None else ""
    report.planned_tool = ""
    # Typed grammar is exercised so the keyboard path stays honest, but it is
    # not a spoken-stage PASS. Voice intent/model stays NOT_RUN.

    report.record_voice_stage(
        1, "push-to-talk",
        detail=_not_image(
            "source has closed activationSource and press_to_talk; "
            "this host did not run a live PTT capture"
        ),
        paths=["companion/speech/request.py", "companion/gtk_shell.py"],
    )
    report.record_voice_stage(
        2, "microphone",
        detail=_capture_note(),
        candidates=list(_CAPTURE_HELPERS),
    )
    report.record_voice_stage(
        3, "STT (Vosk)",
        detail=_vosk_note() + " " + _model_note(),
        candidates=list(LIBRARY_CANDIDATES),
        directories=list(MODEL_DIRECTORIES),
        fixture=True,
        transcript=utterance,
    )
    report.record_voice_stage(
        4, "intent / model",
        detail=_not_image(
            "spoken intent→model is NOT_RUN. Typed grammar on a labelled fixture "
            f"is {report.intent_kind or 'unrecognised'}; that is not live speech. "
            + _llama_note() + " " + _gguf_note()
        ),
        fixture=True,
        typedGrammar=report.intent_kind,
    )
    report.record_voice_stage(
        5, "tool / task",
        detail=_not_image(
            "spoken confirm→submit_task→tool is NOT_RUN. "
            "Typed submit_task remains the keyboard door."
        ),
    )
    report.record_voice_stage(
        6, "response",
        detail=_not_image(
            "spoken caption playback is NOT_RUN. Captions stay authoritative in source"
        ),
    )
    report.record_voice_stage(
        7, "TTS (Pocket/Kitten/eSpeak)",
        detail=_tts_note(),
        candidates=[item[0] for item in VOICE_CANDIDATES],
    )
    report.record_voice_stage(
        8, "spoken e2e",
        detail=_not_image(
            "host unit tests are not spoken e2e. Do not wait for IMAGE evidence"
        ),
    )

    report.record_isolation(
        "mic unavailable",
        code="companion/speech/service.py AUDIO_UNAVAILABLE; typedInputPreserved",
        contract="tests.companion.test_speech_service_protocol",
        detail="scripted host contract only; live mic isolation NOT_RUN",
    )
    report.record_isolation(
        "STT / libvosk missing",
        code="companion/speech/vosk_runtime.py STT_RUNTIME_MISSING; _build_speech swallows",
        contract="tests.companion.test_speech_recognizers.Availability.test_no_library_reports_unavailable_with_the_reason",
        detail="missing libvosk must not crash the companion; live STT NOT_RUN",
    )
    report.record_isolation(
        "STT failure",
        code="recognition_failed / STT_PROVIDER_FAILED; worker finally releases mic",
        contract="tests.companion.test_speech_worker.Endings.test_a_recognizer_crash_at_finalisation_offers_retry_and_typing",
        detail="scripted crash path; native libvosk crash NOT_RUN",
    )
    report.record_isolation(
        "silence",
        code="disposition no-speech; no empty transcript submitted",
        contract="tests.companion.test_speech_worker.Endings.test_pure_silence_settles_as_no_speech_with_no_transcript",
        detail="scripted PCM; room silence NOT_RUN",
    )
    report.record_isolation(
        "malformed transcript",
        code="companion/speech/transcript.py bounded_transcript_text refuses; confirm refused",
        contract="tests.companion.test_speech_security.OversizedAndMalformedInput.test_a_malformed_frame_cannot_crash_the_detector",
        detail="hostile text is refused; live malformed speech NOT_RUN",
    )
    report.record_isolation(
        "model timeout / crash",
        code="llamacli watchdog deadline_seconds=120; GenerationOutcome(ok=False)",
        contract="companion/agents/adapters/llamacli.py",
        detail="adapter path exists; live llama-cli hang NOT_RUN; llama-cpp in a package list is not image evidence",
    )
    report.record_isolation(
        "tool failure",
        code="companion/tools.py ToolBroker.invoke catches Exception",
        contract="tests.companion.test_executors_reviewers",
        detail="broker records a failed outcome; spoken-tool journey NOT_RUN",
    )
    report.record_isolation(
        "TTS unavailable",
        code="voiceFailureFailsTask false; caption remains; _build_voice swallows",
        contract="tests.companion.test_voice_worker",
        detail="unavailable provider must not crash companion; live playback NOT_RUN; espeak-ng in a package list is not image evidence",
    )

    report.typed_fallback = {
        "submit": hasattr(CompanionViewModel, "submit"),
        "pressToTalk": hasattr(CompanionViewModel, "press_to_talk"),
        "confirmSpeech": hasattr(CompanionViewModel, "confirm_speech"),
        "phases": {
            "listening": CompanionPhase.LISTENING.value,
            "understanding": CompanionPhase.UNDERSTANDING.value,
            "executing": CompanionPhase.WORKING.value,
            "failed": CompanionPhase.ERROR.value,
        },
        "thinkingIsNotChainOfThought": True,
        "visualKeys": list(VISUAL_KEYS),
    }
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
        "fedoraImageOnHorizon": False,
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
