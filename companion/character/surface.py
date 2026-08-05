# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The character, driven by the canonical projection and nothing else.

:class:`CharacterPresenter` is the whole of the character's behaviour and
imports no GTK. It takes a :class:`companion.presentation.PresentationState` —
the projection the companion runtime already computed — and produces a frame, a
bubble, a position and an accessibility description. It is therefore testable on
a build machine with no compositor, which is the only way any of this gets
tested at all.

Three things it does not do, and cannot:

* **It does not read the store.** The renderer's first implementation opened
  ``CompanionStore`` and polled it for tasks and events. That made the character
  a second reader of the record with its own idea of what a task was doing, and
  §2 forbids exactly that. The presenter is handed a projection; it has no path
  to anything else.
* **It does not decide capability.** The effective presentation arrives inside
  the projection's ``recommendation``, produced by the canonical runtime from
  the capability runtime's own signals. Nothing here probes.
* **It does not touch the task.** Every renderer failure below is caught,
  recorded as a typed presentation event, and degraded around. There is no
  exception path from this module back into the runtime, because the runtime is
  in another process and this module holds no handle to it.

**Failure is a ladder, not a crash.** §15: an exception from a renderer records
``renderer.failed``, releases the renderer, falls back to static, and falls back
again to text-only if static fails too. Recovery is held by the adaptive
selector's hysteresis and by :class:`_RestartGuard`, so a renderer that fails
repeatedly settles at the level that works rather than flapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import Any, Sequence

from companion.presentation import PresentationState

from .adaptation import (
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from .bubble import BubbleKind, BubbleLayout, BubbleState, SpeechBubbleController, layout_bubble
from .controller import CharacterRendererController, CharacterRendererSnapshot
from .diagnostics import registry_for, selected_package, signals_from_assessment
from .errors import CharacterError
from .integration import bubble_request_for, mapper_input_for
from .lipsync import LipSyncEvent, LipSyncStatus
from .mapper import AccessibilityPreferences, map_character_state
from .package import ValidatedPackage
from .positioning import Display, PixelRect, Placement, PositionDecision, place_character

__all__ = [
    "CharacterPresenter",
    "CharacterUpdate",
    "DEFAULT_CHARACTER_PIXELS",
]

#: The character's nominal size before the user's scale is applied.
DEFAULT_CHARACTER_PIXELS = 288

#: How many renderer restarts are permitted inside :data:`_RESTART_WINDOW_SECONDS`
#: before the presenter stops trying. §15 requires rapid restart loops to be
#: prevented; a renderer that has failed three times in a minute is not going to
#: succeed on the fourth, and each attempt costs a decode.
_RESTART_LIMIT = 3
_RESTART_WINDOW_SECONDS = 60.0

#: How long a failed renderer must behave before it is trusted again. Separate
#: from the selector's own hysteresis, which governs *capability* recovery; this
#: one governs recovery from a *fault*, and a fault deserves a longer look.
_HEALTH_RECOVERY_SECONDS = 15.0


@dataclass
class _RestartGuard:
    """Bounded restarts, so a broken renderer settles instead of thrashing."""

    attempts: list[float] = field(default_factory=list)

    def permitted(self, now: float) -> bool:
        self.attempts = [item for item in self.attempts if now - item < _RESTART_WINDOW_SECONDS]
        return len(self.attempts) < _RESTART_LIMIT

    def record(self, now: float) -> None:
        self.attempts.append(now)

    def to_json(self) -> dict[str, Any]:
        return {"recentRestarts": len(self.attempts), "limit": _RESTART_LIMIT}


@dataclass(frozen=True)
class CharacterUpdate:
    """One frame's worth of everything the window needs to draw."""

    snapshot: CharacterRendererSnapshot
    bubble: BubbleState
    layout: BubbleLayout | None
    position: PositionDecision
    description: str
    effective_presentation: str
    renderer_healthy: bool
    events: tuple[dict[str, Any], ...] = ()

    @property
    def frame(self) -> Any:
        return self.snapshot.frame

    def to_json(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "effectivePresentation": self.effective_presentation,
            "rendererHealthy": self.renderer_healthy,
            "bubble": self.bubble.to_json(),
            "layout": self.layout.to_json() if self.layout else None,
            "position": self.position.to_json(),
            "events": list(self.events),
            **self.snapshot.to_json(),
        }


class CharacterPresenter:
    """Everything the character does, with no toolkit and no task access."""

    def __init__(
        self,
        root: Path,
        *,
        assessment: Any = None,
        display: Display | None = None,
        placement: Placement = Placement.BOTTOM_RIGHT,
    ) -> None:
        self.root = Path(root)
        self.registry = registry_for(self.root)
        record, package, fallback_event = selected_package(self.registry)
        self.record = record
        self.package: ValidatedPackage = package
        if assessment is None:
            from capability.runtime import assess_current_machine

            assessment = assess_current_machine()
        self.assessment = assessment
        self.base_signals = signals_from_assessment(assessment)
        self.controller = CharacterRendererController()
        self.controller.load_package(package)
        if fallback_event is not None:
            self.controller.events.append(fallback_event)
        self.bubbles = SpeechBubbleController()
        self.placement = placement
        self.display = display or Display("headless", PixelRect(0, 0, 1024, 768), primary=True)
        self.scale = 1.0
        self._healthy = True
        self._unhealthy_since: float | None = None
        self._restarts = _RestartGuard()
        self._reported = 0

    # -- inputs ------------------------------------------------------------

    def set_display(self, display: Display) -> None:
        """Follow a display change. §13's display-removal recovery.

        A removed monitor is not a renderer fault: the character moves to
        whatever remains and the bubble is laid out again inside the new work
        area. Nothing about the task changes.
        """
        self.display = display

    def set_scale(self, scale: float) -> None:
        self.scale = float(scale)
        if self.controller.renderer is not None:
            self.controller.renderer.set_scale(scale)

    def plan_for(self, state: PresentationState) -> CapabilityPresentationPlan:
        """The allowance, taken from the projection the runtime supplied."""
        return CapabilityPresentationPlan.from_recommendation(state.recommendation)

    # -- the main path -----------------------------------------------------

    def update(
        self,
        state: PresentationState,
        *,
        accessibility: AccessibilityPreferences | None = None,
        listening: bool = False,
        speaking: bool = False,
        transcribing: bool = False,
        repositioning: bool = False,
        now: float | None = None,
        now_ms: int | None = None,
        signal_overrides: dict[str, Any] | None = None,
    ) -> CharacterUpdate:
        """Draw one canonical projection. Never raises for a renderer fault."""
        accessibility = accessibility or AccessibilityPreferences()
        now = time.monotonic() if now is None else now
        now_ms = round(now * 1000) if now_ms is None else now_ms
        self._recover_health(now)

        plan = self.plan_for(state)
        mapper_input = mapper_input_for(
            state,
            accessibility=accessibility,
            listening=listening,
            speaking=speaking,
            transcribing=transcribing,
            repositioning=repositioning,
            renderer_healthy=self._healthy,
        )
        mapped = map_character_state(self.package.manifest, mapper_input)
        # The accessibility preference and the renderer's own health are
        # derived; an explicit override wins over both, because the only caller
        # that passes one is a test or a slice deliberately putting the renderer
        # under a condition this host does not have. Merging into one dict
        # first, rather than passing both to `replace`, so an override of a
        # derived field is a *choice* rather than a TypeError.
        derived: dict[str, Any] = {
            "reduced_motion": accessibility.reduced_motion,
            "no_animation": accessibility.no_animation,
            "renderer_healthy": self._healthy,
        }
        derived.update(signal_overrides or {})
        signals = replace(self.base_signals, **derived)

        before = len(self.controller.events)
        try:
            snapshot = self.controller.apply(mapped, plan, signals, now=now, now_ms=now_ms)
        except Exception as exc:
            # §15: the renderer failed while displaying a state. Record it,
            # drop to static, and if that fails too drop to text. The task is
            # in another process and is not consulted, informed or affected.
            snapshot = self._degrade(mapped, plan, signals, exc, now=now, now_ms=now_ms)

        request = bubble_request_for(state)
        bubble = self.bubbles.update(
            request.text,
            kind=request.kind,
            final=True,
            now=now,
            # A persistent bubble has no timeout. A question that faded off the
            # screen would lapse into a denial with nobody having seen it.
            timeout_seconds=0.0 if request.persistent else 6.0,
            high_contrast=accessibility.high_contrast,
            persistent=request.persistent,
        )
        position = place_character(
            [self.display],
            size=(round(DEFAULT_CHARACTER_PIXELS * self.scale),) * 2,
            placement=self.placement,
        )
        layout: BubbleLayout | None = None
        if bubble.visible and mapped.bubble_visible:
            layout = layout_bubble(
                bubble, self.package.manifest.bubble_anchor, position.character,
                [self.display], scale=accessibility.bubble_scale,
            )
            self.controller.attach_bubble(bubble, layout)
        else:
            self.controller.detach_bubble()
        self.controller.set_position(position)

        events = tuple(self.controller.events[before:])
        return CharacterUpdate(
            snapshot=snapshot,
            bubble=bubble,
            layout=layout,
            position=position,
            description=mapped.accessibility_description,
            effective_presentation=snapshot.presentation.effective.value,
            renderer_healthy=self._healthy,
            events=events,
        )

    def tick(self, *, now_ms: int | None = None) -> Any:
        """Advance an animation. A fault here degrades and never propagates."""
        now_ms = round(time.monotonic() * 1000) if now_ms is None else now_ms
        try:
            return self.controller.tick(now_ms=now_ms)
        except Exception as exc:
            self.report_failure("animation-tick", str(exc))
            return self.controller.renderer.frame if self.controller.renderer else None

    # -- failure and recovery ---------------------------------------------

    def _degrade(
        self,
        mapped: Any,
        plan: CapabilityPresentationPlan,
        signals: RendererSignals,
        exc: Exception,
        *,
        now: float,
        now_ms: int,
    ) -> CharacterRendererSnapshot:
        self.report_failure(type(exc).__name__, str(exc), now=now)
        unhealthy = replace(signals, renderer_healthy=False)
        try:
            return self.controller.apply(mapped, plan, unhealthy, now=now, now_ms=now_ms)
        except Exception as static_exc:
            # Static failed too. §15's last rung: text-only, which needs no
            # renderer at all, so there is nothing left that can fail.
            self.report_failure("static-renderer", str(static_exc), now=now)
            text_only = replace(unhealthy, static_renderer_healthy=False)
            self.controller.unload_package()
            self.controller.load_package(self.package)
            return self.controller.apply(mapped, plan, text_only, now=now, now_ms=now_ms)

    def report_failure(self, code: str, explanation: str, *, now: float | None = None) -> None:
        """Record a typed presentation-degradation event. Never raises."""
        now = time.monotonic() if now is None else now
        self._healthy = False
        self._unhealthy_since = now
        try:
            self.controller.report_renderer_failure(code, explanation)
        except Exception:
            # Even the failure path is not permitted to throw: it is called
            # from an exception handler, and a second exception there would be
            # the one that reached the window.
            self.controller.events.append({
                "eventType": "renderer.failed",
                "code": code,
                "explanation": explanation,
                "taskContinues": True,
            })

    def _recover_health(self, now: float) -> None:
        if self._healthy or self._unhealthy_since is None:
            return
        if now - self._unhealthy_since >= _HEALTH_RECOVERY_SECONDS:
            self._healthy = True
            self._unhealthy_since = None
            self.controller.events.append({
                "eventType": "renderer.health-restored",
                "explanation": (
                    f"the renderer behaved for {_HEALTH_RECOVERY_SECONDS:g}s; "
                    "the adaptive selector still holds recovery by its own hysteresis"
                ),
                "taskContinues": True,
            })

    def restart(self, *, now: float | None = None, now_ms: int | None = None) -> CharacterUpdate | None:
        """Recreate the renderer and restore package, state and placement.

        Returns ``None`` when the restart guard refuses — which is the correct
        answer when a renderer has already failed three times in a minute, and
        is why §15 asks for restart loops to be prevented rather than merely
        bounded per attempt.
        """
        now = time.monotonic() if now is None else now
        now_ms = round(now * 1000) if now_ms is None else now_ms
        if not self._restarts.permitted(now):
            self.controller.events.append({
                "eventType": "renderer.restart-refused",
                "code": "restart-limit",
                "explanation": (
                    f"{_RESTART_LIMIT} restarts in {_RESTART_WINDOW_SECONDS:g}s; "
                    "the renderer is left at its working level rather than looping"
                ),
                "taskContinues": True,
            })
            return None
        self._restarts.record(now)
        before = len(self.controller.events)
        snapshot = self.controller.restart_renderer(now_ms=now_ms)
        self._healthy = True
        self._unhealthy_since = None
        bubble = self.bubbles.state
        position = self.controller.position or place_character(
            [self.display],
            size=(round(DEFAULT_CHARACTER_PIXELS * self.scale),) * 2,
            placement=self.placement,
        )
        return CharacterUpdate(
            snapshot=snapshot,
            bubble=bubble,
            layout=self.controller.bubble_layout,
            position=position,
            description=(
                snapshot.mapped_state.accessibility_description
                if snapshot.mapped_state else "Bunny is here."
            ),
            effective_presentation=snapshot.presentation.effective.value,
            renderer_healthy=True,
            events=tuple(self.controller.events[before:]),
        )

    # -- speech ------------------------------------------------------------

    def start_lip_sync(
        self, events: Sequence[LipSyncEvent], *, reduced_motion: bool = False
    ) -> LipSyncStatus:
        return self.controller.start_lip_sync(list(events), reduced_motion=reduced_motion)

    def advance_lip_sync(self, playback_ms: int, *, audio_clock_ms: int | None = None) -> LipSyncStatus:
        return self.controller.advance_lip_sync(playback_ms, audio_clock_ms=audio_clock_ms)

    def cancel_lip_sync(self, reason: str = "audio interrupted") -> LipSyncStatus:
        return self.controller.cancel_lip_sync(reason)

    def finish_lip_sync(self) -> LipSyncStatus:
        return self.controller.finish_lip_sync()

    # -- packages ----------------------------------------------------------

    def reload_package(self) -> bool:
        """Re-select from the registry. Returns whether the package changed.

        §15's "package removed": the previously validated package is kept and
        the selection simply fails, because a character that vanished is not a
        reason to stop drawing the one already decoded.
        """
        try:
            record, package, fallback_event = selected_package(self.registry)
        except (CharacterError, ValueError) as exc:
            self.controller.events.append({
                "eventType": "renderer.package-unavailable",
                "explanation": str(exc),
                "retainedPackageId": self.package.manifest.package_id,
                "taskContinues": True,
            })
            return False
        if package.package_digest == self.package.package_digest:
            return False
        self.record = record
        self.package = package
        self.controller.load_package(package)
        if fallback_event is not None:
            self.controller.events.append(fallback_event)
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "package": self.record.to_json(),
            "rendererHealthy": self._healthy,
            "restartGuard": self._restarts.to_json(),
            "display": {
                "displayId": self.display.display_id,
                "workArea": self.display.work_area.to_json(),
            },
            "scale": self.scale,
            "implementedPresentations": [
                Presentation.ANIMATED_2D.value,
                Presentation.STATIC_IMAGE.value,
                Presentation.TEXT_ONLY.value,
            ],
            "threeDimensionalRenderer": None,
        }
