# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The offline voice story: Vosk → action → TTS, with honest NOT_RUN.

A person speaks; Bunny recognises locally; a bounded intent becomes a
planned action; a local voice reads the caption. None of those steps is
faked into a PASS when the runtime is missing.

This module never vendors model weights. A missing ``libvosk.so``, a
missing recognition model, a missing microphone, or a missing TTS binary
is recorded as ``NOT_RUN`` with the reason. The *text* half of the story
(intent → plan) still runs, because it needs no microphone.

The planned action is a declared desktop tool. There is no shell command
path from the utterance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any

from companion.executor import TaskContext
from companion.intents import recognise
from companion.local_intent import LocalIntentExecutor
from companion.speech.vosk_runtime import VoskRuntimeUnavailable, probe as probe_vosk
from companion.voice.system import local_voice_available

__all__ = [
    "VOICE_STORY_UTTERANCE",
    "VoiceStoryReport",
    "run_voice_story",
]

#: What the fixture path "heard". A recognised local intent so the action
#: half of the story is deterministic without a microphone.
VOICE_STORY_UTTERANCE = "how much memory am i using"


@dataclass
class VoiceStoryReport:
    steps: list[dict[str, Any]] = field(default_factory=list)
    transcript: str = ""
    intent_kind: str = ""
    planned_tool: str = ""
    requires_approval: bool = False
    caption: str = ""

    def record(
        self, number: int, name: str, *, passed: bool | None, detail: str = "", **extra: Any
    ) -> None:
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
            "story": "vosk-action-tts",
            "passed": self.passed,
            "steps": list(self.steps),
            "notRun": list(self.not_run),
            "transcript": self.transcript,
            "intentKind": self.intent_kind,
            "plannedTool": self.planned_tool,
            "requiresApproval": self.requires_approval,
            "caption": self.caption,
            "physicalMicrophoneValidated": False,
            "modelBytesVendored": False,
            "unrestrictedShell": False,
        }


def _vosk_status() -> tuple[bool | None, str]:
    try:
        origin = probe_vosk()
    except VoskRuntimeUnavailable as exc:
        return None, str(exc)
    except OSError as exc:
        return None, str(exc)
    return True, f"packaged Vosk C runtime at {origin}"


def _model_status() -> tuple[bool | None, str]:
    candidates = (
        Path("/usr/share/vosk/model"),
        Path("/usr/share/vosk/vosk-model-small-en-us"),
        Path("/usr/share/vosk-models/small-en-us"),
    )
    for path in candidates:
        if path.is_dir():
            return True, str(path)
    return None, "no packaged Vosk model directory; this repo does not vendor model bytes"


def _microphone_status() -> tuple[bool | None, str]:
    pulse = shutil.which("parec") or shutil.which("pw-record")
    if Path("/dev/snd").is_dir() and pulse:
        return True, f"capture helper {pulse}"
    if Path("/dev/snd").is_dir():
        return None, "sound devices present; no parec/pw-record capture helper"
    return None, "no microphone capture path on this host"


def run_voice_story(*, utterance: str = VOICE_STORY_UTTERANCE) -> VoiceStoryReport:
    """Run the story as far as this host allows. Never invents a PASS."""
    report = VoiceStoryReport()

    vosk_ok, vosk_detail = _vosk_status()
    report.record(1, "probe packaged Vosk runtime", passed=vosk_ok, detail=vosk_detail)

    model_ok, model_detail = _model_status()
    report.record(2, "locate a local recognition model", passed=model_ok, detail=model_detail)

    mic_ok, mic_detail = _microphone_status()
    report.record(3, "probe microphone capture", passed=mic_ok, detail=mic_detail)

    if vosk_ok and model_ok and mic_ok:
        report.record(
            4, "speech-to-text",
            passed=None,
            detail="runtime present; physical microphone journey is NOT_RUN in this host demo",
        )
    else:
        report.record(
            4, "speech-to-text",
            passed=None,
            detail="STT not live; using a labelled fixture transcript, not a recorded microphone",
            fixture=True,
        )
    report.transcript = utterance

    intent = recognise(utterance)
    report.record(
        5, "recognise a bounded local intent",
        passed=intent is not None,
        detail="" if intent is None else intent.kind,
    )
    if intent is None:
        report.record(6, "plan a local action", passed=False, detail="no intent recognised")
        report.record(7, "local TTS caption", passed=None, detail="skipped; no plan")
        return report
    report.intent_kind = intent.kind

    executor = LocalIntentExecutor()
    context = TaskContext(
        task={"taskId": "voice-story", "originalRequest": utterance},
        classification="internal",
        plan_revision=1,
    )
    plan = executor.plan(context)
    operation = plan.operations[0] if plan.operations else None
    if operation is None:
        report.record(6, "plan a local action", passed=False, detail=plan.summary)
        report.record(7, "local TTS caption", passed=None, detail="skipped; no operation")
        return report
    report.planned_tool = operation.tool
    report.requires_approval = bool(operation.requires_approval)
    local = operation.destination == "local"
    report.record(
        6, "plan a local action",
        passed=local,
        detail=operation.tool if local else "voice story planned a non-local destination",
        requiresApproval=operation.requires_approval,
        destination=operation.destination,
    )

    caption = intent.description
    report.caption = caption
    tts = local_voice_available()
    if tts:
        report.record(
            7, "local TTS",
            passed=True,
            detail="a local system voice is installed; this demo does not play it unattended",
        )
    else:
        report.record(
            7, "local TTS",
            passed=None,
            detail="no local system voice (espeak-ng / speech-dispatcher) on this host",
        )
    return report
