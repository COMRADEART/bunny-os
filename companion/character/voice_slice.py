# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The voice-to-renderer path, end to end, on an installed system.

The compositor probe (``scripts/gtk_voice_viseme_probe.py``) proves the pixels.
It needs a display, so it cannot run on a headless installed system, in CI, or
inside the stress harness — which is exactly where a regression would first be
noticed and exactly where nothing was watching.

This is the same chain with the last link replaced by a recorder:

    canonical projection
        -> CompanionService (the installed service, with its real voice runtime)
        -> a local synthesiser, or the caption alone where there is none
        -> the worker's own viseme timeline
        -> companion.character.speech_link.VisemeLink
        -> companion.character.lipsync.LipSyncController
        -> the mouth shapes a renderer would have been handed

Everything above the widget is the shipped code, imported from wherever this
module was installed from. What the widget would have drawn is recorded instead
of drawn, and the report says plainly which of the two it is: the steps that
need a compositor are ``NOT_RUN`` here with the probe named, never quietly
omitted and never marked passed.

Run as ``bunny-os companion run-voice-renderer-slice``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any

from ..presentation import PresentationState
from ..service import CompanionService, ServiceOptions
from ..voice.policy import VoicePreferences
from .defaults import default_character_path
from .lipsync import MouthShape
from .speech_link import VisemeLink
from .surface import CharacterPresenter

__all__ = ["VoiceRendererSliceReport", "run_voice_renderer_slice"]

#: What the slice says, once, as one utterance. A canonical caption, not a
#: sentence written to make an envelope look good.
CAPTION = "Bunny counted the words in your document and is showing you the result."

#: How long to wait for one utterance to settle. Generous: a synthesiser on a
#: loaded machine is slow, and a slice that timed out under load would report a
#: failure that was not one.
SETTLE_TIMEOUT = 40.0


@dataclass
class VoiceRendererSliceReport:
    """What the slice did, step by step, with nothing inferred."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)
    shapes_drawn: list[str] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    link_report: dict[str, Any] = field(default_factory=dict)
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
    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.steps if item["status"] == "FAIL"]

    @property
    def passed(self) -> bool:
        return not self.failed

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "slice": "voice-to-renderer",
            "steps": self.steps,
            "stepCount": len(self.steps),
            "passedCount": sum(1 for item in self.steps if item["status"] == "PASS"),
            "notRunCount": sum(1 for item in self.steps if item["status"] == "NOT_RUN"),
            "failedCount": len(self.failed),
            "passed": self.passed,
            "requestIds": self.request_ids,
            "shapesDrawn": self.shapes_drawn,
            "measurements": self.measurements,
            "link": self.link_report,
            "notes": self.notes,
            "captionsAuthoritative": True,
            "compositorValidated": False,
        }


def _state(text: str, *, phase: str = "presenting_result") -> PresentationState:
    return PresentationState(
        session_id="voice-renderer-slice", task_id="voice-renderer-task", phase=phase,
        status_text=text, result_summary=text,
    )


def _settled(events, request_id: str) -> bool:
    return any(
        item.request_id == request_id and item.kind in (
            "speech_finished", "speech_cancelled", "speech_interrupted",
            "speech_failed", "speech_degraded",
        )
        for item in events
    )


def run_voice_renderer_slice(root: Path) -> VoiceRendererSliceReport:
    """The whole path against a real service, with the widget recorded."""
    report = VoiceRendererSliceReport()
    drawn: list[Any] = []
    events: list[Any] = []
    service = CompanionService(ServiceOptions(
        root=Path(root),
        machine="laptop",
        audio_output_available=True,
        display_available=True,
        voice_preferences=VoicePreferences(speak_progress=True),
    ))
    try:
        service.start()
        report.record(
            1, "start the installed companion service with its voice runtime",
            passed=service.ready and service.voice is not None,
            detail=f"store at {service.root}",
            startupSteps=list(service.completed_steps),
        )
        voice = service.voice
        if voice is None:
            report.record(
                2, "build a character presenter", passed=None,
                detail="there is no voice runtime on this machine, so there is nothing to draw",
            )
            return report

        presenter = CharacterPresenter(default_character_path().parent)
        report.record(
            2, "build a character presenter from the installed package",
            passed=presenter.package is not None,
            detail=f"package {presenter.package.manifest.package_id}",
            mouthShapes=sorted(presenter.package.manifest.mouth_shape_map),
        )

        link = VisemeLink(presenter=presenter, draw=drawn.append)
        voice.worker.subscribe(link.on_voice_event)
        voice.worker.subscribe(events.append)
        link.publish(1)
        report.record(
            3, "join the voice worker to the renderer",
            passed=True, detail="companion.character.speech_link.VisemeLink",
        )

        # 4 -- one canonical caption, spoken -------------------------------
        health = voice.voice_health()
        can_speak = (
            any(item["ready"] and item["supportsSynthesis"] for item in health["providers"])
            and any(item["ready"] for item in health["audio"]["backends"])
        )
        state = _state(CAPTION)
        presenter.update(state)
        request, reason = voice.announce(state)
        if request is None and not can_speak:
            # NOT_RUN, not FAIL. A machine with no synthesiser or no output is
            # a machine where §8's answer is the caption alone, and reporting
            # that as a failure would make the slice a test of what is
            # installed rather than of what the code does.
            report.record(
                4, "speak a canonical caption", passed=None,
                detail=(
                    f"this machine cannot speak ({reason}); the caption stands and there "
                    "is no viseme stream to draw"
                ),
                providers=[item["providerId"] for item in health["providers"] if item["ready"]],
                backends=[item["backendId"] for item in health["audio"]["backends"] if item["ready"]],
            )
            report.record(
                5, "the utterance settles", passed=None, detail="nothing was spoken",
            )
            report.notes.append(
                "The voice-to-renderer path was NOT exercised on this machine: no local "
                "synthesiser and audio backend pair was ready. This is the honest outcome "
                "on a development host; the reference target runs it in full."
            )
            report.link_report = link.describe()
            return report
        report.record(
            4, "speak a canonical caption",
            passed=request is not None,
            detail=reason or "accepted", requestId=request.request_id if request else "",
        )
        if request is None:
            return report
        report.request_ids.append(request.request_id)

        deadline = time.monotonic() + SETTLE_TIMEOUT
        while time.monotonic() < deadline and not _settled(events, request.request_id):
            time.sleep(0.01)
        settled = _settled(events, request.request_id)
        report.record(
            5, "the utterance settles", passed=settled,
            detail="settled" if settled else "the utterance did not settle in time",
        )

        timeline_frames = [item for item in drawn if item.origin == "timeline"]
        report.shapes_drawn = [item.shape for item in drawn]
        non_neutral = sorted({
            item.shape for item in timeline_frames if item.shape != MouthShape.NEUTRAL.value
        })

        # 6 -- the properties §5 asks for, each on its own ------------------
        report.record(
            6, "the timeline came from the voice runtime, not a fixture",
            passed=any(item.kind == "viseme_timeline" for item in events),
            detail="companion.voice.visemes, carried by the viseme_timeline event",
            source=next(
                (item.payload.get("sourceMethod", "") for item in events
                 if item.kind == "viseme_timeline"), "",
            ),
        )
        report.record(
            7, "at least two distinct non-neutral mouth shapes",
            passed=len(non_neutral) >= 2, detail=", ".join(non_neutral) or "none",
            shapes=non_neutral,
        )
        sequences = [item.sequence for item in timeline_frames]
        report.record(
            8, "mouth frames are ordered", passed=sequences == sorted(sequences),
            detail=f"{len(sequences)} frame(s)",
        )
        report.record(
            9, "every mouth frame carries the audio's request id",
            passed=all(item.request_id == request.request_id for item in timeline_frames),
            detail=request.request_id,
        )
        report.record(
            10, "every mouth frame carries the current presentation revision",
            passed=all(item.revision == 1 for item in timeline_frames),
            detail="revision 1 throughout",
        )
        report.record(
            11, "completion returned the mouth to neutral",
            passed=bool(drawn) and drawn[-1].shape == MouthShape.NEUTRAL.value,
            detail=drawn[-1].origin if drawn else "nothing was drawn",
        )
        report.record(
            12, "the caption is unchanged by anything the mouth did",
            passed=voice.ledger.get(request.caption_reference) is not None,
            detail=CAPTION,
        )

        # 13 -- cancellation ------------------------------------------------
        cancel_state = _state(
            "Bunny is reading a longer sentence so that there is something to interrupt "
            "part of the way through it.",
        )
        presenter.update(cancel_state)
        second, _ = voice.announce(cancel_state)
        if second is not None:
            report.request_ids.append(second.request_id)
            moving_deadline = time.monotonic() + SETTLE_TIMEOUT
            while time.monotonic() < moving_deadline and not any(
                item.origin == "timeline" and item.request_id == second.request_id
                for item in drawn
            ):
                time.sleep(0.005)
            before = len(drawn)
            cancelled_at = time.monotonic()
            voice.voice_cancel(requestId=second.request_id)
            deadline = time.monotonic() + SETTLE_TIMEOUT
            while time.monotonic() < deadline and not _settled(events, second.request_id):
                time.sleep(0.005)
            after = drawn[before:]
            neutral = next(
                (item for item in after if item.shape == MouthShape.NEUTRAL.value), None,
            )
            moved_after = [
                item for item in after
                if neutral is not None and item.at_monotonic > neutral.at_monotonic
                and item.shape != MouthShape.NEUTRAL.value
            ]
            report.record(
                13, "cancellation returns the mouth to neutral and stops it",
                passed=neutral is not None and not moved_after,
                detail=f"{len(moved_after)} mouth change(s) after neutral",
            )
            if neutral is not None:
                report.measurements["cancellationToNeutralMs"] = round(
                    (neutral.at_monotonic - cancelled_at) * 1000, 3,
                )
        else:
            report.record(13, "cancellation returns the mouth to neutral", passed=None,
                          detail="the second utterance was not accepted")

        # 14 -- a voice-worker restart --------------------------------------
        voice.restart_worker()
        voice.worker.subscribe(link.on_voice_event)
        voice.worker.subscribe(events.append)
        report.record(
            14, "a voice-worker restart leaves the mouth neutral",
            passed=bool(drawn) and drawn[-1].shape == MouthShape.NEUTRAL.value,
            detail=drawn[-1].origin if drawn else "nothing was drawn",
        )

        # 15 -- a renderer restart ------------------------------------------
        decision = link.restart_renderer(CharacterPresenter(default_character_path().parent))
        report.record(
            15, "a renderer restart resumes safely or degrades explicitly",
            passed="degraded-to-neutral" in decision, detail=decision,
        )

        # 16 -- teardown -----------------------------------------------------
        link.close()
        report.record(
            16, "closing the link leaves the mouth neutral and no callback behind",
            passed=bool(drawn) and drawn[-1].shape == MouthShape.NEUTRAL.value,
            detail=drawn[-1].origin if drawn else "nothing was drawn",
        )

        # The two things this cannot do, said rather than skipped.
        report.record(
            17, "the mouth frames reach a compositor", passed=None,
            detail=(
                "this slice records what the widget would have been handed; the pixels "
                "are proved by scripts/gtk_voice_viseme_probe.py, which needs a display"
            ),
        )
        report.record(
            18, "the audio reaches a physical speaker", passed=None,
            detail="no physical speaker has been validated anywhere in this build",
        )

        report.link_report = link.describe()
        report.measurements["mouthChanges"] = len(timeline_frames)
        report.measurements["distinctNonNeutralShapes"] = non_neutral
        report.notes.append(
            "Timing method is measured amplitude over the synthesiser's own samples. "
            "No phoneme boundary was measured, and no phoneme-accurate lip sync is claimed."
        )
        return report
    finally:
        service.close()
