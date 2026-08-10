# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeping the companion's own voice out of the companion's own microphone.

§19's problem is physical: this build has no echo cancellation, so a speaker
playing narration into a room with an open microphone is the runtime dictating
to itself. The answer is scheduling rather than signal processing — output
speech is stopped or paused *before* the microphone opens, and what was done
is recorded so the capture's record says whether output audio was active when
listening began.

The policy is priority-shaped, read from the voice runtime's own ladder:

* **noncritical speech is cancelled.** A progress line or a decorative remark
  whose moment has passed is not worth replaying; cancelling it is what the
  voice queue's dispositions were built for.
* **essential speech is paused** where the playback path supports pausing, and
  cancelled where it does not — a paused approval prompt resumes as the same
  utterance; a cancelled one stays in the captions, which §8 makes the
  authoritative copy anyway.

**Nothing resumes automatically after task submission** (§19's last sentence).
:meth:`VoiceOutputCoordinator.release` resumes a *paused* utterance only when
the caller passes ``resume_paused=True``, and the one caller that does is the
cancellation path — capture that never produced a task. The confirmation path
never passes it: a user who just dictated a task is listening for its result,
not for the tail of a sentence from before they pressed the button.

The coordinator holds the :class:`companion.voice.worker.VoiceWorker` and
nothing else of voice's — no policy, no ledger, no registry — and the speech
worker holds the coordinator rather than the voice worker, so the one place
speech input can touch speech output is this file.
"""

from __future__ import annotations

import threading
from typing import Any

__all__ = ["CoordinationRecord", "VoiceOutputCoordinator"]


class CoordinationRecord:
    """What was done to output speech for one capture, for the record."""

    def __init__(
        self,
        *,
        output_was_active: bool,
        action: str,
        request_id: str = "",
        detail: str = "",
    ) -> None:
        self.output_was_active = output_was_active
        self.action = action
        self.request_id = request_id
        self.detail = detail
        self.resumed = False

    def to_json(self) -> dict[str, Any]:
        return {
            "outputAudioWasActive": self.output_was_active,
            "action": self.action,
            "voiceRequestId": self.request_id,
            "detail": self.detail,
            "resumed": self.resumed,
            "automaticReplayAfterSubmission": False,
        }


class VoiceOutputCoordinator:
    """The one door between speech input and speech output.

    Constructed with the voice worker or with nothing: a service running
    without a voice runtime coordinates against silence, which is a
    no-op with a truthful record rather than a special case in the worker.
    """

    def __init__(self, voice_worker: Any = None) -> None:
        self._worker = voice_worker
        self._guard = threading.Lock()
        self._held: CoordinationRecord | None = None

    def quiesce(self, *, capture_request_id: str) -> CoordinationRecord:
        """Make output audio stop before the microphone opens.

        Called by the capture worker after validation and before the
        indicator. Never raises: a voice fault must not stop a capture the
        user explicitly asked for, so every failure collapses to "nothing was
        playing" with the failure in the detail.
        """
        worker = self._worker
        if worker is None:
            record = CoordinationRecord(
                output_was_active=False, action="none",
                detail="no voice runtime is attached; nothing could be playing",
            )
            with self._guard:
                self._held = record
            return record
        try:
            status = worker.status()
            current = status.get("current") or {}
            active = bool(current)
            if not active:
                record = CoordinationRecord(output_was_active=False, action="none")
            else:
                voice_request_id = str(current.get("requestId", ""))
                priority = str(current.get("priority", ""))
                essential = priority in (
                    "critical_warning", "approval_required", "task_error",
                    "direct_user_response", "task_result",
                )
                if essential and worker.pause():
                    record = CoordinationRecord(
                        output_was_active=True, action="paused",
                        request_id=voice_request_id,
                        detail=f"essential speech ({priority}) paused for capture "
                               f"{capture_request_id}",
                    )
                else:
                    worker.cancel(voice_request_id)
                    record = CoordinationRecord(
                        output_was_active=True, action="cancelled",
                        request_id=voice_request_id,
                        detail=(
                            f"{priority or 'unclassified'} speech cancelled for capture "
                            f"{capture_request_id}; the caption remains the record"
                        ),
                    )
        except Exception as exc:  # noqa: BLE001 - a voice fault must not stop capture
            record = CoordinationRecord(
                output_was_active=False, action="none",
                detail=f"the voice runtime could not be consulted: {type(exc).__name__}",
            )
        with self._guard:
            self._held = record
        return record

    def release(self, *, resume_paused: bool = False) -> CoordinationRecord | None:
        """Capture is over; decide what happens to what was interrupted.

        ``resume_paused=False`` — the default, and what the confirmation path
        uses — resumes nothing: §19 forbids automatically replaying
        interrupted narration after task submission. ``True`` is passed only
        by the cancellation path, where resuming a *paused* utterance is
        explicitly safe: no task was created, the microphone is closed, and
        the user's last act was "never mind".
        """
        with self._guard:
            record, self._held = self._held, None
        if record is None:
            return None
        if resume_paused and record.action == "paused" and self._worker is not None:
            try:
                record.resumed = bool(self._worker.resume())
            except Exception:  # noqa: BLE001 - resuming is best-effort by design
                record.resumed = False
        return record

    def describe(self) -> dict[str, Any]:
        with self._guard:
            held = self._held
        return {
            "voiceRuntimeAttached": self._worker is not None,
            "held": held.to_json() if held else None,
            "echoCancellationAvailable": False,
            "outputQuiescedBeforeCapture": True,
            "automaticReplayAfterSubmission": False,
        }
