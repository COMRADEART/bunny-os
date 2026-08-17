# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window. Disposable, and deliberately not very clever.

Everything the surface knows arrives as a :class:`companion.presentation.
PresentationState` from the runtime, and everything it can do is one of the
operations in :mod:`companion.protocol`. It holds no store, no executor, no
broker, no approval file and no task state that matters. Closing it stops
nothing; opening it again asks the runtime what has happened and draws that.

The module is in two halves and the split is load-bearing.

:class:`CompanionViewModel` is the whole of the behaviour and imports no GTK. It
reconnects, replays, folds, decides what every panel says, and produces the
strings. It is a plain object with a client, so the tests exercise the real
presentation logic on a machine with no display — which is the only way that
logic gets tested at all, since a GTK test needs a compositor and a compositor
is not available in a build gate.

:class:`BunnyCompanionApplication` is the widgets. It imports GTK inside a
function so that importing this module on a headless machine works, calls
straight into the view model, and contains no decision of its own beyond which
widget to put a string in.

Two behaviours are worth naming because they are easy to get wrong.

**A refresh never touches focus.** The poll updates labels and rebuilds the
dynamic panels; it does not call ``present``, does not raise the window and does
not grab. The single exception is an approval arriving, and that is decided by
:func:`companion.presentation.window_directive` from the phase — so "the window
came forward" always corresponds to "there is a question", and never to "an
event arrived".

**The caption is the output; the voice is a decoration.** The caption label is
set from the state before :func:`companion.voice.speak_caption` is called, and
the result of speaking is never consulted for anything except the speaking
indicator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .characters import CharacterError, describe_phase, load_static_character
from .presentation import (
    AccessibilityPreferences,
    DesktopContext,
    MonitorGeometry,
    PresentationProjector,
    PresentationState,
    WindowPreferences,
    escape_markup,
    window_directive,
)
from .protocol import CompanionClient, CompanionClientError
from .voice import SystemVoice, speak_caption

__all__ = [
    "CompanionViewModel",
    "BunnyCompanionApplication",
    "run",
]


def _character_preferences(preferences: AccessibilityPreferences):
    """Translate the client's accessibility settings for the character.

    Two dataclasses with overlapping fields, deliberately not merged: the
    client's set is about the *window* and the character's is about a renderer
    that may not exist. Translating explicitly is what stops a preference added
    to one silently changing the other.
    """
    from .character.mapper import AccessibilityPreferences as CharacterPreferences

    return CharacterPreferences(
        reduced_motion=preferences.reduced_motion,
        no_animation=preferences.no_animation,
        high_contrast=preferences.high_contrast,
        # The client scales text; the character scales itself and its bubble.
        bubble_scale=max(0.75, min(3.0, preferences.text_scale)),
    )


def _presentation_mode(root: Path | None) -> str:
    """The resolved five-way companion mode, defaulting to ``full``.

    One call to the settings document's own resolver
    (:meth:`companion.settings.Settings.presentation_mode`), so the window
    never invents its own resolution order. Unreadable settings mean the
    full companion, for the same reason `_companion_settings_arguments`
    returns defaults: a damaged file costs preferences, not the companion.
    """
    if root is None:
        return "full"
    try:
        from .settings import load_settings

        return load_settings(root).presentation_mode()
    except Exception:
        return "full"


def _character_presenter(root: Path | None):
    """Build a character presenter, or ``None`` if there is no usable package.

    Absence is not an error. Text-only is a supported presentation and a client
    that refused to open because it could not find a picture would be a client
    that fails for the least important reason it has.
    """
    if root is None:
        return None
    try:
        from .character.surface import CharacterPresenter

        return CharacterPresenter(root, **_companion_settings_arguments(root))
    except Exception:
        # Every character failure is a presentation failure. The window opens,
        # the task runs, and the surface is text.
        return None


def _companion_settings_arguments(root: Path) -> dict:
    """The user's companion settings, as presenter keyword arguments.

    Named at length to keep it distinct from :func:`_character_preferences`
    above, which translates *accessibility* preferences and is a different
    thing entirely. The first version of this was called
    ``_character_preferences`` too and shadowed it — and because both are
    called for their return value and this one catches every exception, the
    accessibility translation would have silently become an empty dict and
    taken reduced motion and high contrast with it.

    This is where §7's "single authoritative settings source" actually takes
    effect. Before it, the window constructed the presenter with no arguments at
    all: the renderer mode, the scale, the placement, the animation intensity
    and the idle-animation preference were all persisted, all validated, and all
    ignored — the companion drew its defaults on every login however the
    settings file read.

    Unreadable settings produce defaults rather than an exception. A person
    whose settings file is damaged should lose their preferences, not their
    companion.
    """
    try:
        from .settings import load_settings

        character = load_settings(root).character
        return {
            "mode": character.mode(),
            "scale": character.scale,
            "placement": character.placement(),
            "performance": character.performance,
            "idle_animation": character.idle_animation,
            "animation_intensity": character.animation_intensity,
            "contextual_reactions": character.contextual_reactions,
            # The chrome-density axis (full/compact/minimal). The presenter
            # only needs the size consequence; off and text-only never reach
            # it — visible and the accessibility preference decide those
            # before a presenter exists.
            "companion_mode": character.companion_mode,
            # §5. Enabled *here* rather than in the presenter: this function
            # runs when a person opens a session, which is the only context in
            # which "first run" means anything. A slice, a demo or a diagnostic
            # building a presenter over a temporary directory is not a first
            # boot and must not be greeted.
            "first_run_greeting": True,
        }
    except Exception:
        return {}


@dataclass
class CompanionViewModel:
    """Everything the window knows, and how it comes to know it.

    The caches here are all disposable by construction: ``state`` is replaced
    wholesale on every refresh, ``projector`` can be discarded and rebuilt from
    the runtime's events, and nothing is ever written to disk. §7 requires the
    client not to become a second persistence layer, and the way to guarantee
    that is to have nowhere to persist to.
    """

    client: CompanionClient
    preferences: AccessibilityPreferences = field(default_factory=AccessibilityPreferences)
    voice: SystemVoice | None = None
    speech_enabled: bool = True
    task_id: str = ""
    session_id: str = ""
    state: PresentationState = field(default_factory=PresentationState)
    projector: PresentationProjector = field(default_factory=PresentationProjector)
    revision: int = 0
    connection_error: str = ""
    last_error: str = ""
    speaking: bool = False
    spoken_result: str = ""
    health: Mapping[str, Any] = field(default_factory=dict)
    #: The character, when one could be loaded. Presentation only: it is fed the
    #: same :class:`companion.presentation.PresentationState` this model already
    #: holds and can reach nothing else.
    character: Any = None
    character_update: Any = None
    #: Speech input, entirely through the protocol. The window holds a request
    #: id and a token — never a device, never audio — and everything it shows
    #: is read back from ``speech_input_status``. ``speech_phase`` is the
    #: window's own idea of where the flow is: ``idle``, ``listening``,
    #: ``transcribing`` or ``confirming``.
    speech_request_id: str = ""
    speech_token: str = ""
    speech_phase: str = "idle"
    speech_partial: str = ""
    speech_final: Mapping[str, Any] | None = None
    speech_error: str = ""
    speech_indicator: Mapping[str, Any] = field(default_factory=dict)
    #: Agent providers, entirely through the protocol. The window holds two
    #: read-back documents — the subsystem overview and the current task's
    #: provider status — and everything it shows is built from them. Nothing
    #: here can name an endpoint or carry a credential, because the protocol
    #: responses cannot.
    providers_overview: Mapping[str, Any] = field(default_factory=dict)
    provider_status: Mapping[str, Any] = field(default_factory=dict)

    # -- connection --------------------------------------------------------

    def connect(self) -> bool:
        """Attach to whatever the runtime is already doing.

        Picks up the most recent unfinished task, or the most recent task of
        any kind. A window that opened onto nothing while a task was running
        would be a window that had failed at its one job.
        """
        try:
            self.health = dict(self.client.health())
            sessions = self.client.list_sessions().get("sessions", [])
            if isinstance(sessions, list) and sessions:
                latest = sessions[-1]
                if isinstance(latest, Mapping):
                    self.session_id = str(latest.get("sessionId", ""))
            tasks = self.client.list_tasks().get("tasks", [])
            if not self.task_id and isinstance(tasks, list) and tasks:
                unfinished = [
                    item for item in tasks
                    if isinstance(item, Mapping)
                    and item.get("state") not in ("completed", "failed", "cancelled")
                ]
                chosen = (unfinished or [item for item in tasks if isinstance(item, Mapping)])[-1]
                self.task_id = str(chosen.get("taskId", ""))
                self.session_id = str(chosen.get("sessionId", "")) or self.session_id
            self.connection_error = ""
        except (CompanionClientError, OSError) as exc:
            self.connection_error = str(exc)
            return False
        self.refresh(full=True)
        return not self.connection_error

    def refresh(self, *, full: bool = False) -> PresentationState:
        """Ask for what has happened since, and fold it in.

        ``full=True`` throws away the local fold and starts again from
        sequence zero — what a freshly opened window does. Otherwise the
        runtime is told the revision already held and supplies only the events
        after it, which is §7's reconnect in one call.
        """
        if full:
            self.projector = PresentationProjector()
            self.revision = 0
        try:
            answer = self.client.get_presentation_state(
                self.task_id or None,
                session_id=self.session_id or None,
                after_sequence=self.revision,
            )
        except (CompanionClientError, OSError) as exc:
            self.connection_error = str(exc)
            return self.state
        self.connection_error = ""
        events = answer.get("events")
        if isinstance(events, list):
            # Replayed locally as well as trusted from the runtime. Both paths
            # exist on purpose: the runtime's state is what is drawn, and the
            # local fold is what proves the client *could* have drawn it from
            # the events alone. A test compares the two and fails if they part.
            for document in events:
                if isinstance(document, Mapping):
                    self.projector.apply_document(document)
        served = answer.get("state")
        if isinstance(served, Mapping):
            self.state = _state_from_json(served)
        self.revision = max(self.revision, int(self.state.revision or 0))
        self.session_id = str(answer.get("sessionId", "")) or self.session_id
        self.task_id = str(answer.get("taskId", "")) or self.task_id
        self._update_character()
        return self.state

    def _update_character(self) -> None:
        """Feed the character the projection this model already holds.

        Wrapped, because the character is decoration over a surface that is
        already complete: a renderer fault must reach the picture and stop
        there, never the caption, the approval or the task.
        """
        if self.character is None:
            return
        try:
            self.character_update = self.character.update(
                self.state,
                accessibility=_character_preferences(self.preferences),
                speaking=self.speaking,
                # §18: the microphone drives posture, never the mouth. The
                # mapper already models listening and transcribing as
                # first-class character states with their own fallback chains;
                # these flags are the whole of what speech input contributes,
                # and no lip-sync method is reachable from here.
                listening=self.speech_phase == "listening",
                transcribing=self.speech_phase == "transcribing",
            )
        except Exception as exc:  # pragma: no cover - the renderer's own guard runs first
            self.character_update = None
            self.last_error = f"the character surface degraded safely: {exc}"

    @property
    def replayed_phase(self) -> str:
        """The phase the client reached by folding the events it was given."""
        return self.projector.state.phase

    # -- actions -----------------------------------------------------------

    def submit(self, request: str) -> bool:
        """Ask for something. The runtime decides everything about it."""
        body = request.strip()
        if not body:
            return False
        try:
            if not self.session_id:
                created = self.client.create_session("Bunny Companion")
                session = created.get("session")
                self.session_id = str(session.get("sessionId", "")) if isinstance(session, Mapping) else ""
            answer = self.client.submit_task(self.session_id, body)
            task = answer.get("task")
            if isinstance(task, Mapping):
                self.task_id = str(task.get("taskId", ""))
            self.last_error = ""
        except (CompanionClientError, OSError) as exc:
            self.last_error = str(exc)
            return False
        self.refresh(full=True)
        return True

    def resolve(self, approval: Mapping[str, Any], decision: str) -> bool:
        """Answer a question, repeating back exactly what was displayed.

        The binding is taken from the approval as it was received and is not
        rebuilt, edited or defaulted here. If the runtime disagrees with any
        field it refuses, and the refusal is shown rather than retried — a
        client that responded to "this is not the question that was asked" by
        asking again with different values would be doing the exact thing §9
        exists to prevent.
        """
        binding = {
            key: approval.get(key)
            for key in (
                "requestId", "sessionId", "taskId", "planId", "transitionId", "action",
                "destination", "providerId", "dataClassification", "estimatedCostUnits",
                "destinationFingerprint",
            )
        }
        try:
            self.client.resolve_approval(binding, decision)
            self.last_error = ""
        except (CompanionClientError, OSError) as exc:
            self.last_error = str(exc)
            self.refresh()
            return False
        self.refresh()
        return True

    def cancel(self) -> bool:
        if not self.task_id:
            self.last_error = "there is no task to stop"
            return False
        try:
            self.client.cancel_task(self.task_id)
            self.last_error = ""
        except (CompanionClientError, OSError) as exc:
            self.last_error = str(exc)
            return False
        self.refresh()
        return True

    # -- speech input -------------------------------------------------------
    #
    # Every method here is one protocol operation and a fold of its answer.
    # The window never sees audio, never names a device it did not enumerate,
    # and cannot start a capture except by the user's own press — these are
    # the client half of §4, and the runtime enforces all of it again.

    def speech_available(self) -> bool:
        return bool(self.health.get("speechInputAvailable", False))

    def press_to_talk(self) -> bool:
        """The explicit activation. Called from the button and nowhere else."""
        try:
            if not self.session_id:
                created = self.client.create_session("Bunny Companion")
                session = created.get("session")
                self.session_id = str(session.get("sessionId", "")) if isinstance(session, Mapping) else ""
            answer = self.client.call("speech_input_start", {
                "sessionId": self.session_id,
                "activationSource": "push-to-talk-button",
                "presentationRevision": self.revision,
            })
        except (CompanionClientError, OSError) as exc:
            self.speech_error = str(exc)
            return False
        if not answer.get("accepted"):
            self.speech_error = str(answer.get("detail", "the capture was refused"))
            return False
        self.speech_request_id = str(answer.get("requestId", ""))
        self.speech_token = str(answer.get("cancellationToken", ""))
        self.speech_phase = "listening"
        self.speech_partial = ""
        self.speech_final = None
        self.speech_error = ""
        return True

    def stop_talking(self) -> bool:
        """§15: the person's stop, overriding every automatic one."""
        if not self.speech_request_id:
            return False
        try:
            answer = self.client.call("speech_input_stop", {"requestId": self.speech_request_id})
        except (CompanionClientError, OSError) as exc:
            self.speech_error = str(exc)
            return False
        if answer.get("stopped"):
            self.speech_phase = "transcribing"
        return bool(answer.get("stopped"))

    def cancel_speech(self) -> bool:
        """Abandon the capture or the waiting transcript. No task either way."""
        if not self.speech_request_id:
            return False
        try:
            answer = self.client.call("speech_input_cancel", {
                "requestId": self.speech_request_id,
                "cancellationToken": self.speech_token,
            })
        except (CompanionClientError, OSError) as exc:
            self.speech_error = str(exc)
            return False
        self._clear_speech()
        return bool(answer.get("cancelled"))

    def poll_speech(self) -> str:
        """Fold the runtime's answer into the window's speech state.

        Reads ``speech_input_status`` and the event stream it carries; the
        transcript text shown for editing comes from the ``final_transcript``
        event, which is the recogniser's answer as the runtime recorded it.
        """
        if self.speech_phase == "idle" or not self.speech_request_id:
            return self.speech_phase
        try:
            status = self.client.call("speech_input_status")
        except (CompanionClientError, OSError) as exc:
            self.speech_error = str(exc)
            return self.speech_phase
        indicator = status.get("indicator")
        if isinstance(indicator, Mapping):
            state = indicator.get("state")
            self.speech_indicator = dict(state) if isinstance(state, Mapping) else {}
        current = status.get("current")
        mine = isinstance(current, Mapping) and \
            str(current.get("requestId", "")) == self.speech_request_id
        for document in status.get("recentEvents", ()):
            if not isinstance(document, Mapping):
                continue
            if str(document.get("requestId", "")) != self.speech_request_id:
                continue
            kind = document.get("kind")
            if kind == "final_transcript":
                self.speech_final = dict(document)
                self.speech_phase = "confirming"
            elif kind in ("speech_input_cancelled", "recognition_failed", "device_lost"):
                if self.speech_phase != "confirming":
                    self.speech_error = str(document.get("detail", "")) or str(kind)
                    self._clear_speech()
                    return self.speech_phase
        if mine and self.speech_phase == "listening" and isinstance(current, Mapping):
            partial = current.get("partialText")
            if isinstance(partial, str) and partial:
                self.speech_partial = partial
            if str(current.get("phase", "")) == "finalizing":
                self.speech_phase = "transcribing"
        elif not mine and self.speech_phase == "listening":
            # The capture ended without a final transcript reaching the ring
            # yet; the next poll settles it one way or the other.
            self.speech_phase = "transcribing"
        return self.speech_phase

    def confirm_speech(self, text: str) -> bool:
        """Submit what the user reviewed — and possibly corrected — as a task."""
        if not self.speech_request_id or self.speech_final is None:
            self.speech_error = "there is no transcript waiting for confirmation"
            return False
        original = str(self.speech_final.get("text", ""))
        edited = text.strip()
        try:
            answer = self.client.call("speech_input_confirm", {
                "requestId": self.speech_request_id,
                "sessionId": self.session_id,
                "text": edited if edited and edited != original else None,
                "reviewedDigest": str(self.speech_final.get("textDigest", "")),
                "cancellationToken": self.speech_token,
            })
        except (CompanionClientError, OSError) as exc:
            self.speech_error = str(exc)
            return False
        if not answer.get("submitted"):
            self.speech_error = str(answer.get("reason", "the confirmation was refused"))
            return False
        task = answer.get("task")
        if isinstance(task, Mapping):
            self.task_id = str(task.get("taskId", ""))
        self._clear_speech()
        self.refresh(full=True)
        return True

    def retry_speech(self) -> bool:
        """Another take. Pressing retry is itself the explicit activation."""
        if not self.speech_request_id:
            return False
        try:
            answer = self.client.call("speech_input_retry", {
                "requestId": self.speech_request_id,
                "activationSource": "push-to-talk-button",
            })
        except (CompanionClientError, OSError) as exc:
            self.speech_error = str(exc)
            return False
        if not answer.get("accepted"):
            self.speech_error = str(answer.get("detail", "the retry was refused"))
            return False
        self.speech_request_id = str(answer.get("requestId", ""))
        self.speech_token = str(answer.get("cancellationToken", ""))
        self.speech_phase = "listening"
        self.speech_partial = ""
        self.speech_final = None
        return True

    def _clear_speech(self) -> None:
        self.speech_request_id = ""
        self.speech_token = ""
        self.speech_phase = "idle"
        self.speech_partial = ""
        self.speech_final = None
        self.speech_indicator = {}

    def speech_indicator_line(self) -> str:
        """§5's facts, as one sentence the persistent indicator shows.

        Built from the indicator state the runtime reported, never invented:
        listening, device, locality, provider, elapsed time, retention.
        """
        state = self.speech_indicator
        if not state or not state.get("listening"):
            if self.speech_phase == "transcribing":
                return "Transcribing — the microphone is closed"
            if self.speech_phase == "confirming":
                return "Review the transcript — nothing is submitted until you confirm"
            return ""
        parts = [
            "Listening — the microphone is ON",
            f"device {state.get('deviceId') or 'default'}",
            str(state.get("locality", "local")),
        ]
        if state.get("providerId"):
            parts.append(f"recogniser {state.get('providerId')}")
        parts.append(f"{float(state.get('elapsedSeconds', 0.0)):.1f}s")
        parts.append(
            "audio not retained" if not state.get("audioRetained") else "audio retained"
        )
        return " · ".join(parts)

    def speech_transcript_markup(self) -> str:
        """Transcript text as Pango markup may carry it. The only path to a
        markup-capable widget, and it escapes — §22's injection test reads
        this method."""
        from .speech.transcript import pango_escaped

        if self.speech_final is not None:
            return pango_escaped(str(self.speech_final.get("text", "")))
        return pango_escaped(self.speech_partial)

    # -- agent providers ----------------------------------------------------

    @property
    def providers_available(self) -> bool:
        return bool(self.health.get("agentProvidersAvailable", False))

    def poll_providers(self) -> Mapping[str, Any]:
        """Read the subsystem overview back: remote indicator, degradation."""
        if not self.providers_available:
            self.providers_overview = {}
            return self.providers_overview
        try:
            answer = self.client.call("providers_status", {})
        except (CompanionClientError, OSError) as exc:
            self.last_error = str(exc)
            return self.providers_overview
        if isinstance(answer, Mapping) and answer.get("available"):
            self.providers_overview = dict(answer)
        return self.providers_overview

    def poll_task_provider(self) -> Mapping[str, Any]:
        """Read the current task's provider status back."""
        if not (self.providers_available and self.task_id):
            self.provider_status = {}
            return self.provider_status
        try:
            answer = self.client.call("task_provider_status", {"taskId": self.task_id})
        except (CompanionClientError, OSError) as exc:
            self.last_error = str(exc)
            return self.provider_status
        if isinstance(answer, Mapping) and answer.get("available"):
            self.provider_status = dict(answer)
        return self.provider_status

    def provider_line(self) -> str:
        """§22's facts as one sentence: who is generating, where, at what cost.

        Built from what the runtime reported, never invented. The remote
        sentence exists at two strengths, and the stronger one — data is
        leaving now — is driven by ``remoteActive``, which the service derives
        from the worker's live state, not from this window's guess. The
        approval question itself precedes both: a remote selection surfaces
        here before anything is dispatched, because dispatch cannot happen
        until the §8 approval resolves.
        """
        overview = self.providers_overview
        status = self.provider_status
        selected = str(status.get("selectedProviderId", ""))
        if overview.get("remoteActive"):
            return (
                f"REMOTE generation via {selected or 'a remote provider'} — "
                "data is leaving this machine under your approval"
            )
        if selected and not status.get("selectedLocal", True):
            return (
                f"Remote provider {selected} selected — nothing is sent before "
                "your approval"
            )
        parts: list[str] = []
        if selected:
            verb = "generating" if status.get("streaming") else "provider"
            parts.append(f"{verb} {selected} · local")
            selection = status.get("selection")
            if isinstance(selection, Mapping):
                spent = status.get("spentUnits", 0)
                if spent:
                    parts.append(f"cost {spent} units")
        degraded = self._degraded_providers()
        if degraded:
            parts.append("degraded: " + ", ".join(degraded))
        return " · ".join(parts)

    def _degraded_providers(self) -> tuple[str, ...]:
        health = self.providers_overview.get("health")
        if not isinstance(health, Mapping):
            return ()
        names: list[str] = []
        for provider_id, report in health.items():
            if not isinstance(report, Mapping):
                continue
            circuit = report.get("circuit")
            if isinstance(circuit, Mapping) and circuit.get("state") != "closed":
                names.append(str(provider_id))
        return tuple(names)

    # -- rendering ---------------------------------------------------------

    @property
    def phase(self) -> str:
        return "disconnected" if self.connection_error else self.state.phase

    def caption(self) -> str:
        """The line the user reads. Always present, in every presentation."""
        if self.connection_error:
            return (
                "This window cannot reach the companion runtime. Anything already "
                "running is unaffected and will still be there when it can."
            )
        if self.state.result_summary and self.phase in ("success", "presenting_result"):
            return self.state.result_summary
        return self.state.status_text or describe_phase(self.phase)

    def character_description(self) -> str:
        """What the picture would be saying, in words. Never omitted.

        Prefers the character package's own description when one is loaded, and
        falls back to the built-in phrasing otherwise — so the text-only surface
        says the same thing whether or not a character exists.
        """
        if self.character_update is not None and self.character_update.description:
            return self.character_update.description
        return describe_phase(self.phase)

    def character_frame(self) -> Any:
        """The frame to draw, or ``None`` for a text-only surface."""
        return self.character_update.frame if self.character_update is not None else None

    def character_presentation(self) -> str:
        """Which renderer is actually in use right now."""
        if self.character_update is None:
            return "text-only"
        return self.character_update.effective_presentation

    def indicator(self) -> str:
        labels = {
            "waiting_for_approval": "Waiting for your answer",
            "listening": "Listening — the microphone is on",
            "speaking": "Speaking",
            "working": "Working on this device",
            "reviewing": "A reviewer is looking at it",
            "blocked": "Blocked",
            "error": "Error",
            "cancelled": "Cancelled",
            "cancelling": "Stopping",
            "success": "Done",
            "paused": "Paused",
            "disconnected": "Disconnected",
        }
        return labels.get(self.phase, self.phase.replace("_", " ").capitalize())

    def privacy_line(self) -> str:
        """One sentence naming every boundary that is currently in play."""
        parts = [
            f"data {self.state.privacy_classification}",
            self.state.locality_indicator,
            "paid provider" if self.state.paid_provider else "no paid provider",
            "microphone on" if self.state.microphone_active else "microphone off",
        ]
        if self.state.content_withheld:
            parts.append("some content withheld from this view")
        return "Privacy: " + " · ".join(parts)

    def task_rows(self) -> tuple[tuple[str, str], ...]:
        """The task panel, as label/value pairs. Escaped at the source."""
        state = self.state
        return tuple(
            (name, escape_markup(value))
            for name, value in (
                ("Task", state.task_id or "none"),
                ("Phase", self.phase.replace("_", " ")),
                ("Status", state.status_text or "—"),
                ("Executor", state.active_executor or "none selected"),
                ("Reviewers", ", ".join(state.reviewers) or "none"),
                ("Current step", state.current_operation or "none"),
                ("Current tool", state.current_tool or "none"),
                ("Progress", f"{state.progress:.0%}"),
                ("Approval", state.approval_state),
                ("Result", state.result_summary or "pending"),
                ("Error", state.error_summary or "none"),
                ("Explanation", state.explanation_reference or "none"),
                ("Presentation", state.recommendation.implementation),
            )
        )

    def observation_cards(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Reviewer observations, disagreements first and never hidden."""
        ordered = sorted(
            self.state.observations,
            key=lambda item: (not item.disagreement, item.round_number),
        )
        cards = []
        for item in ordered:
            heading = (
                f"{'Disagreement' if item.disagreement else 'Observation'} · "
                f"{item.severity} · {item.category} · {item.reviewer_id}"
            )
            lines = [item.summary or "(no summary)"]
            if item.suggested_action:
                lines.append(f"Suggested: {item.suggested_action}")
            if item.evidence_event_ids:
                lines.append("Evidence: " + ", ".join(item.evidence_event_ids))
            if item.absent:
                lines.append("This reviewer produced no observation.")
            # Stated on every card. A reviewer's remark sitting next to an
            # Approve button would read as a component with authority, and the
            # one thing a reviewer has is no authority at all.
            lines.append("Reviewers observe only: no tools, no approvals, no changes.")
            cards.append((escape_markup(heading), tuple(escape_markup(line) for line in lines)))
        return tuple(cards)

    def approval_cards(self) -> tuple[tuple[Mapping[str, Any], tuple[tuple[str, str], ...]], ...]:
        """Each open question: the binding to answer with, and the rows to show.

        The two are separate values because they are two different things. The
        binding is *exactly* the fields the runtime recorded and will check —
        nothing else, so a client cannot accidentally send a rendering back as
        though it were part of the record, and the protocol's strict parameter
        check refuses anything extra. The rows are for the person, and include
        the specific destination, the alternatives and the safe default, none of
        which the runtime wants back.
        """
        cards = []
        for approval in self.state.approvals:
            document = approval.binding()
            rows = (
                ("Requested action", approval.action.replace("_", " ")),
                ("Why", approval.reason or "—"),
                ("Task", approval.task_id),
                ("Plan", approval.plan_id),
                ("Step", approval.transition_id),
                ("Destination", approval.destination),
                ("Specifically", approval.destination_detail or "this device"),
                ("Provider", approval.provider_id or "none"),
                ("Data", approval.data_classification),
                (
                    "Cost",
                    "free" if approval.estimated_cost_units in (None, 0)
                    else f"{approval.estimated_cost_units} units",
                ),
                ("Instead", "; ".join(approval.alternatives) or "—"),
                ("If you do nothing", "nothing happens"),
            )
            cards.append((document, tuple((name, escape_markup(str(value))) for name, value in rows)))
        return tuple(cards)

    def text_only_view(self) -> str:
        """The whole surface as text. What a screen reader is read, and what a
        ``text-only`` presentation shows instead of the picture."""
        lines = [
            self.character_description(),
            self.caption(),
            self.privacy_line(),
            f"Character: {self.character_presentation()}",
            "",
        ]
        lines.extend(f"{name}: {value}" for name, value in self.task_rows())
        for heading, body in self.observation_cards():
            lines.extend(["", heading, *body])
        for _binding, rows in self.approval_cards():
            lines.extend(["", "Approval Centre"])
            lines.extend(f"{name}: {value}" for name, value in rows)
        return "\n".join(lines)

    # -- voice -------------------------------------------------------------

    def speak_if_new(self) -> bool:
        """Read a completed result aloud, once, if there is a voice for it.

        Returns whether it spoke, which drives the speaking indicator and
        nothing else. Every failure path returns ``False`` and leaves the task,
        the caption and the record untouched.
        """
        if not self.speech_enabled or self.voice is None:
            return False
        if self.phase not in ("success", "presenting_result"):
            return False
        caption = self.caption()
        if not caption or caption == self.spoken_result:
            return False
        self.spoken_result = caption
        self.speaking = True
        try:
            outcome = speak_caption(self.voice, f"speech-{self.revision}", caption)
        finally:
            self.speaking = False
        return outcome.spoken

    def window(self, context: DesktopContext | None = None) -> Any:
        return window_directive(self.phase, WindowPreferences(), context or DesktopContext())


def _state_from_json(document: Mapping[str, Any]) -> PresentationState:
    """Rebuild a state value from the wire. Unknown fields are dropped.

    Not a schema check — the runtime's own output is validated against
    ``schemas/companion-presentation-state.schema.json`` in the tests. This is
    the client being conservative about a document it did not write: anything it
    does not recognise is ignored rather than carried into the widgets.
    """
    from .presentation import ApprovalPresentation, PresentationRecommendation, ReviewerPresentation

    def _string(key: str, default: str = "") -> str:
        value = document.get(key, default)
        return value if isinstance(value, str) else default

    recommendation = document.get("recommendation")
    recommendation = recommendation if isinstance(recommendation, Mapping) else {}
    observations = document.get("observations")
    approvals = document.get("approvals")
    progress = document.get("progress")
    revision = document.get("revision")
    return PresentationState(
        session_id=_string("sessionId"),
        task_id=_string("taskId"),
        phase=_string("phase", "idle"),
        base_phase=_string("basePhase", "idle"),
        status_text=_string("statusText"),
        progress=float(progress) if isinstance(progress, (int, float)) and not isinstance(progress, bool) else 0.0,
        active_executor=_string("activeExecutor"),
        reviewers=tuple(
            str(item) for item in document.get("reviewers", ()) if isinstance(item, str)
        ),
        observations=tuple(
            ReviewerPresentation(
                reviewer_id=str(item.get("reviewerId", "")),
                severity=str(item.get("severity", "info")),
                category=str(item.get("category", "correctness")),
                summary=str(item.get("summary", "")),
                suggested_action=str(item.get("suggestedAction", "")),
                evidence_event_ids=tuple(
                    str(value) for value in item.get("evidenceEventIds", ()) if isinstance(value, str)
                ),
                disagreement=bool(item.get("disagreement", False)),
                round_number=int(item.get("roundNumber", 0) or 0),
                absent=bool(item.get("absent", False)),
            )
            for item in (observations if isinstance(observations, list) else ())
            if isinstance(item, Mapping)
        ),
        current_operation=_string("currentOperation"),
        current_tool=_string("currentTool"),
        approval_state=_string("approvalState", "not_required"),
        approvals=tuple(
            ApprovalPresentation(
                request_id=str(item.get("requestId", "")),
                session_id=str(item.get("sessionId", "")),
                task_id=str(item.get("taskId", "")),
                plan_id=str(item.get("planId", "")),
                transition_id=str(item.get("transitionId", "")),
                action=str(item.get("action", "")),
                reason=str(item.get("reason", "")),
                destination=str(item.get("destination", "local")),
                destination_detail=str(item.get("destinationDetail", "")),
                provider_id=str(item.get("providerId", "")),
                data_classification=str(item.get("dataClassification", "internal")),
                estimated_cost_units=(
                    item.get("estimatedCostUnits")
                    if isinstance(item.get("estimatedCostUnits"), int)
                    and not isinstance(item.get("estimatedCostUnits"), bool)
                    else None
                ),
                destination_fingerprint=str(item.get("destinationFingerprint", "")),
                alternatives=tuple(
                    str(value) for value in item.get("alternatives", ()) if isinstance(value, str)
                ),
                safe_default=str(item.get("safeDefault", "denied")),
                decision=str(item.get("decision", "pending")),
            )
            for item in (approvals if isinstance(approvals, list) else ())
            if isinstance(item, Mapping)
        ),
        result_summary=_string("resultSummary"),
        error_summary=_string("errorSummary"),
        privacy_classification=_string("privacyClassification", "internal"),
        data_locality=_string("dataLocality", "device-only"),
        locality_indicator=_string("localityIndicator", "local"),
        paid_provider=bool(document.get("paidProvider", False)),
        listening=bool(document.get("listening", False)),
        speaking=bool(document.get("speaking", False)),
        microphone_active=bool(document.get("microphoneActive", False)),
        recommendation=PresentationRecommendation(
            implementation=str(recommendation.get("implementation", "text-only")),
            eligible=str(recommendation.get("eligible", "text-only")),
            limited_by_implementation=bool(recommendation.get("limitedByImplementation", False)),
            placement=str(recommendation.get("placement", "center")),
            captions=bool(recommendation.get("captions", True)),
            audio_available=bool(recommendation.get("audioAvailable", False)),
            plan_id=str(recommendation.get("planId", "")),
            reasons=tuple(
                str(item) for item in recommendation.get("reasons", ()) if isinstance(item, str)
            ),
        ),
        explanation_reference=_string("explanationReference"),
        revision=int(revision) if isinstance(revision, int) and not isinstance(revision, bool) else 0,
        content_withheld=bool(document.get("contentWithheld", False)),
    )


# --------------------------------------------------------------------------- #
# The widgets
# --------------------------------------------------------------------------- #


def _gtk() -> tuple[Any, Any, Any, Any]:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gio, GLib, Gtk
    except (ImportError, ValueError) as exc:  # pragma: no cover - needs a desktop
        raise RuntimeError(
            "GTK 4 and PyGObject are required for the Bunny Companion window. The runtime "
            "is unaffected and can be used from 'bunny-os companion'."
        ) from exc
    return Gdk, Gio, GLib, Gtk


#: How often the window asks the runtime what has happened. Deliberately not a
#: subscription: a poll cannot leak a partial write, cannot hold a connection
#: open across a runtime restart, and recovers from a runtime that went away by
#: doing nothing different. Three quarters of a second is below the threshold at
#: which a person notices a status line is stale.
POLL_MILLISECONDS = 750


class BunnyCompanionApplication:  # pragma: no cover - requires a display
    """The GTK 4 window. Contains no decision the view model does not make."""

    def __init__(
        self,
        endpoint: Path | None = None,
        *,
        preferences: AccessibilityPreferences | None = None,
    ) -> None:
        Gdk, Gio, GLib, Gtk = _gtk()
        self.Gdk, self.Gio, self.GLib, self.Gtk = Gdk, Gio, GLib, Gtk
        self.preferences = preferences or AccessibilityPreferences()
        voice = SystemVoice()
        from .cli import default_root

        self.model = CompanionViewModel(
            client=CompanionClient(endpoint, timeout=5.0),
            preferences=self.preferences,
            voice=voice if voice.available else None,
            character=_character_presenter(default_root()),
        )
        #: The wizard's five-way answer, resolved once at construction. The
        #: window acts on the chrome-density half (compact/minimal); off and
        #: text-only keep flowing through the visibility and accessibility
        #: paths that already carried them.
        self.presentation_mode = _presentation_mode(default_root())
        self.character = None
        try:
            self.character = load_static_character()
        except CharacterError as exc:
            # A replaced or malformed asset is refused and reported; the window
            # opens without a picture rather than rendering something that
            # failed its own checks. Text-only is a supported presentation, so
            # there is nothing to fall back *to* — this is simply that.
            self.model.last_error = str(exc)
        self.app = Gtk.Application(
            application_id="art.comrade.BunnyCompanion",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.app.connect("activate", self._activate)
        self.window: Any = None
        self.body: Any = None
        self.dynamic: Any = None
        self.status_label: Any = None
        self.indicator_label: Any = None
        self.caption_label: Any = None
        self.character_label: Any = None
        self.privacy_label: Any = None
        self.progress: Any = None
        self.entry: Any = None
        self.error_label: Any = None
        self.picture: Any = None
        self.mic_button: Any = None
        self.mic_indicator: Any = None
        self.provider_label: Any = None
        self.transcript_box: Any = None
        self.partial_label: Any = None
        self.transcript_entry: Any = None
        self._hidden = False
        self._drawn_revision = -1
        self._drawn_phase = ""

    # -- construction ------------------------------------------------------

    def _label(self, text: str, css: str = "", *, selectable: bool = True) -> Any:
        label = self.Gtk.Label(label=text, xalign=0, wrap=True, selectable=selectable)
        if css:
            label.add_css_class(css)
        return label

    def _button(self, text: str, callback: Any, css: str = "") -> Any:
        button = self.Gtk.Button(label=text)
        if css:
            button.add_css_class(css)
        # Every control carries its own accessible name. A button whose label is
        # the only thing naming it is a button a screen reader announces by
        # whatever the styling happened to leave in it.
        button.update_property([self.Gtk.AccessibleProperty.LABEL], [text])
        button.connect("clicked", callback)
        return button

    def _activate(self, app: Any) -> None:
        if self.window is not None:
            self._hidden = False
            self.window.set_visible(True)
            self.window.present()
            return
        self._install_css()
        self.window = self.Gtk.ApplicationWindow(application=app, title="Bunny Companion")
        # A compact or minimal install opens in the compact window shape —
        # "a smaller character in the corner" is a promise about the resting
        # window, not only the figure. The header-bar buttons still resize;
        # the mode decides where the window *starts*.
        if self.presentation_mode in ("compact", "minimal"):
            self.window.set_default_size(330, 320)
        else:
            self.window.set_default_size(460, 680)
        self.window.add_css_class("bunny-companion")

        header = self.Gtk.HeaderBar()
        header.set_title_widget(self._label("Bunny Companion", "title-3", selectable=False))
        header.pack_start(self._button("Compact", lambda _b: self._resize("compact")))
        header.pack_start(self._button("Docked", lambda _b: self._resize("docked")))
        header.pack_start(self._button("Centre", lambda _b: self._resize("center")))
        header.pack_end(self._button("Hide", lambda _b: self._hide()))
        header.pack_end(self._button("Minimise", lambda _b: self._minimise()))
        self.window.set_titlebar(header)

        scroller = self.Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        root = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=14)
        for setter in ("set_margin_top", "set_margin_bottom", "set_margin_start", "set_margin_end"):
            getattr(root, setter)(18)
        scroller.set_child(root)

        self.body = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=10)
        root.append(self.body)

        self.status_label = self._label("Connecting to the companion runtime…", "title-2")
        self.status_label.update_property(
            [self.Gtk.AccessibleProperty.DESCRIPTION], ["What the companion is doing now"]
        )
        self.body.append(self.status_label)

        self.indicator_label = self._label("Starting", "bunny-indicator")
        self.body.append(self.indicator_label)

        self.progress = self.Gtk.ProgressBar(show_text=True)
        self.progress.update_property([self.Gtk.AccessibleProperty.LABEL], ["Task progress"])
        self.body.append(self.progress)

        if self.character is not None and not self.preferences.prefer_text_only:
            self.picture = self.Gtk.Picture.new_for_filename(str(self.character.path))
            # The design tokens' companion sizes (lib/design/tokens.js
            # COMPANION_SIZE): full 220, compact 128, minimal 48. The static
            # picture used 200 before the mode existed; full keeps that.
            side = {"compact": 128, "minimal": 48}.get(self.presentation_mode, 200)
            self.picture.set_size_request(side, side)
            self.picture.set_can_shrink(True)
            self.picture.add_css_class("bunny-character")
            # The picture is decorative *because* the description below carries
            # the same information as text. Marking it presentational is what
            # stops a screen reader announcing a filename.
            self.picture.update_property(
                [self.Gtk.AccessibleProperty.LABEL], [self.character.alternative_text]
            )
            self.body.append(self.picture)
        self.character_label = self._label(describe_phase("starting"), "bunny-character-text")
        self.body.append(self.character_label)

        bubble = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=6)
        bubble.add_css_class("bunny-bubble")
        bubble.append(self._label("Caption", "caption-heading", selectable=False))
        self.caption_label = self._label("Bunny is ready.")
        bubble.append(self.caption_label)
        self.body.append(bubble)

        self.privacy_label = self._label("Privacy: local · microphone off", "bunny-privacy")
        self.body.append(self.privacy_label)

        entry_row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry = self.Gtk.Entry(placeholder_text="Ask Bunny to do something local")
        self.entry.set_hexpand(True)
        self.entry.update_property(
            [self.Gtk.AccessibleProperty.LABEL], ["What would you like Bunny to do"]
        )
        self.entry.connect("activate", self._submit)
        entry_row.append(self.entry)
        entry_row.append(self._button("Submit", self._submit, "suggested-action"))
        self.mic_button = self._button("🎤 Talk", self._push_to_talk)
        self.mic_button.update_property(
            [self.Gtk.AccessibleProperty.LABEL],
            ["Push to talk. The microphone opens only while a capture you started is running."],
        )
        entry_row.append(self.mic_button)
        self.body.append(entry_row)

        # §5's persistent indicator. One widget, always in the layout, visible
        # for the whole capture interval, fed only from the runtime's own
        # indicator state — the window renders listening, it never decides it.
        self.mic_indicator = self._label("", "bunny-mic-indicator")
        self.mic_indicator.set_visible(False)
        self.mic_indicator.update_property(
            [self.Gtk.AccessibleProperty.DESCRIPTION],
            ["Microphone state: shown whenever audio is being captured"],
        )
        self.body.append(self.mic_indicator)

        # §22's provider surface. One widget, fed only from the protocol's
        # provider documents — selected provider, local or remote, streaming,
        # cost, degradation. The remote sentence renders with its own CSS
        # class so a theme can make "data is leaving this machine" impossible
        # to mistake for a status line.
        self.provider_label = self._label("", "bunny-provider")
        self.provider_label.set_visible(False)
        self.provider_label.update_property(
            [self.Gtk.AccessibleProperty.DESCRIPTION],
            ["Which model provider is working, whether it is local or remote, and its cost"],
        )
        self.body.append(self.provider_label)

        # The transcript review card: partial text while listening, the final
        # text in an editable entry while confirming, and the four §14 verbs.
        # ``set_text`` throughout — a transcript never reaches ``set_markup``,
        # which is how markup in dictated words stays words.
        self.transcript_box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=6)
        self.transcript_box.add_css_class("bunny-transcript")
        self.transcript_box.set_visible(False)
        self.partial_label = self._label("", "bunny-partial")
        self.partial_label.update_property(
            [self.Gtk.AccessibleProperty.DESCRIPTION],
            ["Provisional transcript; it may still change"],
        )
        # Announced politely and only on settles: a screen reader reading
        # every partial revision aloud would talk over the person dictating.
        self.transcript_box.append(self.partial_label)
        self.transcript_entry = self.Gtk.Entry()
        self.transcript_entry.set_hexpand(True)
        self.transcript_entry.update_property(
            [self.Gtk.AccessibleProperty.LABEL],
            ["The transcript. Correct it here before confirming."],
        )
        self.transcript_entry.connect("activate", self._confirm_speech)
        self.transcript_box.append(self.transcript_entry)
        transcript_actions = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=8)
        transcript_actions.append(self._button("Confirm", self._confirm_speech, "suggested-action"))
        transcript_actions.append(self._button("Retry", self._retry_speech))
        transcript_actions.append(self._button("Cancel", self._cancel_speech, "destructive-action"))
        self.transcript_box.append(transcript_actions)
        self.body.append(self.transcript_box)

        self.error_label = self._label("", "error")
        self.body.append(self.error_label)

        self.dynamic = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=10)
        root.append(self.dynamic)

        self.window.set_child(scroller)
        self.app.set_accels_for_action("window.close", ["<Control>w"])
        self.window.present()
        self.model.connect()
        self._draw(force=True)
        self.GLib.timeout_add(POLL_MILLISECONDS, self._poll)

    def _install_css(self) -> None:
        provider = self.Gtk.CssProvider()
        # Colours are named from the system palette rather than fixed, so the
        # high-contrast and dark themes apply without this stylesheet knowing
        # about them. No transitions and no animations are declared anywhere,
        # which is how the reduced-motion preference is honoured by
        # construction rather than by a branch.
        provider.load_from_data(b"""
            .bunny-companion { background: @window_bg_color; }
            .bunny-character { margin: 6px; }
            .bunny-character-text { opacity: .85; }
            .bunny-bubble { background: alpha(@accent_bg_color, .12); border-radius: 16px; padding: 12px; }
            .bunny-privacy { background: alpha(@view_fg_color, .06); border-radius: 10px; padding: 10px; }
            .bunny-indicator { font-weight: 700; }
            .bunny-mic-indicator { font-weight: 700; background: alpha(@error_bg_color, .18); border-radius: 10px; padding: 10px; }
            .bunny-transcript { background: alpha(@accent_bg_color, .08); border-radius: 12px; padding: 10px; }
            .bunny-partial { font-style: italic; opacity: .8; }
            .caption-heading { font-size: .82em; font-weight: 700; opacity: .75; }
            .approval-card { border: 2px solid @accent_bg_color; border-radius: 14px; padding: 14px; }
            .review-card { background: alpha(@view_fg_color, .05); border-radius: 10px; padding: 10px; }
        """)
        display = self.Gdk.Display.get_default()
        if display is not None:
            self.Gtk.StyleContext.add_provider_for_display(
                display, provider, self.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    # -- interaction -------------------------------------------------------

    def _submit(self, _widget: Any) -> None:
        text = self.entry.get_text()
        if self.model.submit(text):
            self.entry.set_text("")
        self._draw(force=True)

    # -- speech input ------------------------------------------------------

    def _push_to_talk(self, _widget: Any) -> None:
        """One button, two meanings, by state: start listening, or stop."""
        if self.model.speech_phase == "listening":
            self.model.stop_talking()
        else:
            self.model.press_to_talk()
        self._draw_speech()

    def _confirm_speech(self, _widget: Any) -> None:
        if self.model.confirm_speech(self.transcript_entry.get_text()):
            self.transcript_entry.set_text("")
        self._draw(force=True)
        self._draw_speech()

    def _retry_speech(self, _widget: Any) -> None:
        self.model.retry_speech()
        self._draw_speech()

    def _cancel_speech(self, _widget: Any) -> None:
        self.model.cancel_speech()
        self._draw_speech()

    def _draw_speech(self) -> None:
        """The speech surfaces, drawn from the model's folded state."""
        phase = self.model.speech_phase
        line = self.model.speech_indicator_line()
        self.mic_indicator.set_text(line)
        self.mic_indicator.set_visible(bool(line))
        self.mic_button.set_label(
            "⏹ Stop" if phase == "listening" else "🎤 Talk"
        )
        self.mic_button.set_sensitive(phase in ("idle", "listening"))
        confirming = phase == "confirming" and self.model.speech_final is not None
        self.transcript_box.set_visible(phase in ("listening", "transcribing") or confirming)
        # set_text, never set_markup: the §22 injection test depends on the
        # transcript path having no markup-interpreting widget on it.
        self.partial_label.set_text(
            f"… {self.model.speech_partial}" if self.model.speech_partial else
            ("Transcribing…" if phase == "transcribing" else "")
        )
        self.partial_label.set_visible(phase in ("listening", "transcribing"))
        self.transcript_entry.set_visible(confirming)
        if confirming and not self.transcript_entry.get_text():
            self.transcript_entry.set_text(
                str(self.model.speech_final.get("text", ""))
            )
        if self.model.speech_error:
            self.error_label.set_text(self.model.speech_error)

    def _resolve(self, binding: Mapping[str, Any], decision: str) -> None:
        self.model.resolve(binding, decision)
        self._draw(force=True)

    def _cancel(self, _button: Any) -> None:
        self.model.cancel()
        self._draw(force=True)

    def _hide(self) -> None:
        self._hidden = True
        self.window.set_visible(False)

    def _minimise(self) -> None:
        minimise = getattr(self.window, "minimize", None)
        if callable(minimise):
            minimise()
        else:
            self._hide()

    def _resize(self, placement: str) -> None:
        sizes = {"compact": (330, 320), "docked": (460, 680), "center": (520, 720)}
        width, height = sizes.get(placement, (460, 680))
        self.window.set_default_size(width, height)

    def _poll(self) -> Any:
        self.model.refresh()
        self._draw()
        if self.model.speech_phase != "idle":
            self.model.poll_speech()
            self._draw_speech()
        self.model.poll_providers()
        self.model.poll_task_provider()
        self._draw_provider()
        self.model.speak_if_new()
        return self.GLib.SOURCE_CONTINUE

    def _draw_provider(self) -> None:
        line = self.model.provider_line()
        self.provider_label.set_text(line)
        self.provider_label.set_visible(bool(line))
        remote = bool(self.model.providers_overview.get("remoteActive")) or (
            bool(self.model.provider_status.get("selectedProviderId"))
            and not self.model.provider_status.get("selectedLocal", True)
        )
        if remote:
            self.provider_label.add_css_class("bunny-provider-remote")
        else:
            self.provider_label.remove_css_class("bunny-provider-remote")

    # -- drawing -----------------------------------------------------------

    def _clear_dynamic(self) -> None:
        child = self.dynamic.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.dynamic.remove(child)
            child = following

    def _draw(self, *, force: bool = False) -> None:
        state = self.model.state
        phase = self.model.phase
        if not force and state.revision == self._drawn_revision and phase == self._drawn_phase:
            return
        self._drawn_revision = state.revision
        self._drawn_phase = phase

        # Text first, and always. Everything below this point is decoration on
        # top of a surface that is already complete.
        self.status_label.set_text(state.status_text or self.model.caption())
        self.indicator_label.set_text(self.model.indicator())
        self.caption_label.set_text(self.model.caption())
        self.character_label.set_text(self.model.character_description())
        self.privacy_label.set_text(self.model.privacy_line())
        self.progress.set_fraction(max(0.0, min(1.0, state.progress)))
        self.progress.set_text(f"{state.progress:.0%}")
        self.error_label.set_text(self.model.connection_error or self.model.last_error or "")
        # The character frame, when a renderer produced one. Falls back to the
        # shipped static asset so a window without a character package still
        # shows something, and to nothing at all when the presentation is text.
        frame = self.model.character_frame()
        if self.picture is not None:
            if frame is not None:
                self.picture.set_filename(str(frame.asset_path))
                self.picture.update_property(
                    [self.Gtk.AccessibleProperty.LABEL], [frame.accessibility_description]
                )
                self.picture.set_visible(True)
            else:
                self.picture.set_visible(
                    self.model.character_presentation() == "static-image"
                    and self.character is not None
                )

        self._clear_dynamic()
        self._draw_task_panel()
        for heading, lines in self.model.observation_cards():
            self._draw_card(heading, lines, "review-card")
        for binding, rows in self.model.approval_cards():
            self._draw_approval(binding, rows)
        self._apply_window_policy(phase)

    def _draw_card(self, heading: str, lines: Sequence[str], css: str) -> None:
        card = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=5)
        card.add_css_class(css)
        card.append(self._label(heading, "title-4"))
        for line in lines:
            card.append(self._label(line))
        self.dynamic.append(card)

    def _draw_task_panel(self) -> None:
        panel = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=5)
        panel.add_css_class("review-card")
        panel.append(self._label("Task", "title-3"))
        for name, value in self.model.task_rows():
            panel.append(self._label(f"{name}: {value}"))
        if self.model.phase not in ("success", "cancelled", "error", "idle", "disconnected"):
            panel.append(self._button("Stop this task", self._cancel))
        self.dynamic.append(panel)

    def _draw_approval(self, binding: Mapping[str, Any], rows: Sequence[tuple[str, str]]) -> None:
        card = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=7)
        card.add_css_class("approval-card")
        card.append(self._label("Approval Centre", "title-2"))
        for name, value in rows:
            card.append(self._label(f"{name}: {value}"))
        actions = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.append(self._button(
            "Approve", lambda _b, item=binding: self._resolve(item, "granted"), "suggested-action"
        ))
        actions.append(self._button(
            "Decline", lambda _b, item=binding: self._resolve(item, "denied"), "destructive-action"
        ))
        actions.append(self._button("Stop the task", self._cancel))
        card.append(actions)
        self.dynamic.append(card)

    def _apply_window_policy(self, phase: str) -> None:
        monitors: list[MonitorGeometry] = []
        display = self.Gdk.Display.get_default()
        if display is not None:
            model = display.get_monitors()
            for index in range(model.get_n_items()):
                geometry = model.get_item(index).get_geometry()
                monitors.append(MonitorGeometry(
                    monitor_id=f"monitor-{index}",
                    x=geometry.x, y=geometry.y,
                    width=geometry.width, height=geometry.height,
                ))
        directive = self.model.window(DesktopContext(
            monitors=tuple(monitors),
            active_monitor_id="monitor-0" if monitors else "",
        ))
        if not self._hidden:
            self.window.set_visible(directive.visible)
        self._resize(directive.placement if directive.placement in ("compact", "center") else "docked")
        # The only path that brings the window forward, and it fires on the
        # phase rather than on the refresh — so a person is interrupted by a
        # question and by nothing else. GTK 4 on Wayland gives placement to the
        # compositor; `directive.absolute_placement_available` is False and no
        # code here pretends otherwise.
        if directive.accept_focus and phase == "waiting_for_approval":
            self.window.present()

    def run(self) -> int:
        return int(self.app.run(None))


def run(
    endpoint: Path | None = None,
    *,
    preferences: AccessibilityPreferences | None = None,
) -> int:  # pragma: no cover - requires a display
    """Open the window.

    ``preferences`` used to be missing here, and ``cli._shell`` built an
    :class:`AccessibilityPreferences` from ``--text-only`` and then dropped it on
    the floor — so ``bunny-os companion shell --text-only`` opened an ordinary
    window with a character in it. That flag is what the recovery surface's
    *Start text-only* action runs and what a user with a broken renderer is told
    to use, so it was the one path that had to work and the one that did not.
    """
    return BunnyCompanionApplication(endpoint, preferences=preferences).run()
