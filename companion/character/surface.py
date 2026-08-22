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
from .diagnostics import registry_for, selected_package, signals_from_assessment, three_d_signals
from .errors import CharacterError
from .first_run import FirstRunGreeting
from .integration import bubble_request_for, mapper_input_for
from .lipsync import LipSyncEvent, LipSyncStatus
from .mapper import AccessibilityPreferences, map_character_state
from .package import ValidatedPackage
from .positioning import (
    Display,
    PixelRect,
    Placement,
    PositionDecision,
    PositionStore,
    place_character,
    saved_from_decision,
)

__all__ = [
    "CharacterPresenter",
    "CharacterUpdate",
    "DEFAULT_CHARACTER_PIXELS",
]

#: The character's nominal size before the user's scale is applied.
DEFAULT_CHARACTER_PIXELS = 288

#: How much room each chrome level gives the figure, as a fraction of
#: :data:`DEFAULT_CHARACTER_PIXELS`. The ratios are the design tokens'
#: companion sizes (lib/design/tokens.js ``COMPANION_SIZE``: full 220,
#: compact 128, minimal 48) — the tokens are the shell's absolute pixels
#: and these are the same proportions applied to the presenter's base size.
#: The user's ``scale`` multiplies on top: compact at scale 1.4 is a large
#: compact companion, not a silent return to full.
COMPANION_MODE_FACTORS = {
    "full": 1.0,
    "compact": 128 / 220,
    "minimal": 48 / 220,
}

#: Where a dragged position is remembered, beside the character registry.
#:
#: Its own file rather than a field in ``settings.json`` because the two answer
#: different questions and change at different rates: settings hold *what the
#: user chose* — a named corner, a mode, a scale — and this holds *where the
#: window ended up on this display*, which is a pixel fraction tied to a display
#: id. Putting a display-specific fraction in the settings document would make
#: every settings read a reader of this machine's monitor layout.
POSITION_FILE_NAME = "character-position.json"

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
        three_d_context: Any = None,
        three_d_seed: int | None = None,
        mode: Any = None,
        performance: str = "automatic",
        idle_animation: bool = True,
        animation_intensity: float = 1.0,
        contextual_reactions: bool = True,
        scale: float = 1.0,
        companion_mode: str = "full",
        first_run_greeting: bool = False,
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
        self.base_signals = replace(
            signals_from_assessment(assessment),
            **three_d_signals(
                package, context_provider_configured=three_d_context is not None
            ),
        )
        #: A callable returning a graphics context, or ``None``.
        #:
        #: ``None`` is not "3D is broken" — it is "nobody offered this presenter
        #: a way to draw in 3D", which is the correct state for a headless
        #: client, a text-only client, and every caller written before this
        #: phase. The 3D rungs are then unreachable and no graphics library is
        #: opened, which is §30.
        self.three_d_context = three_d_context
        #: The renderer mode, or ``None`` for "no mode ceiling".
        #:
        #: ``None`` by default so that every caller written before modes — the
        #: 3D slice, the diagnostics, the demo — keeps drawing what its
        #: capability plan permits. The launcher passes the user's setting, and
        #: that is where the product's pre-rendered default takes effect.
        self.controller = CharacterRendererController(
            three_d_context=three_d_context,
            three_d_seed=three_d_seed,
            mode=mode,
            performance=performance,
            idle_animation=idle_animation,
            animation_intensity=animation_intensity,
            contextual_reactions=contextual_reactions,
        )
        self.controller.load_package(package)
        #: Sustained-slowness tracking, so §22's frame-time trigger fires on a
        #: trend rather than on one frame.
        from .three_d.budget import DEFAULT_BUDGET, FrameHealth

        self.three_d_budget = DEFAULT_BUDGET
        self.frame_health = FrameHealth(DEFAULT_BUDGET)
        self.controller.selector.budget = DEFAULT_BUDGET
        if fallback_event is not None:
            self.controller.events.append(fallback_event)
        self.bubbles = SpeechBubbleController()
        self.placement = placement
        #: Where the user dragged the companion, if they ever did.
        #:
        #: ``PositionStore`` and ``saved_from_decision`` were written with the
        #: placement engine and then never called by anything: ``place_character``
        #: was invoked with a ``placement`` and no ``saved``, so a dragged
        #: position lasted until the window closed and the companion returned to
        #: its default corner on every login. §7 asks for a position that
        #: survives a restart, and this is the wiring that was missing rather
        #: than a new mechanism.
        self.position_store = PositionStore(self.root / POSITION_FILE_NAME)
        #: §5's one-shot first-run greeting, or ``None`` when nobody asked for
        #: one. Its marker lives beside the character registry, so resetting
        #: settings does not re-trigger it.
        #:
        #: **Off by default**, and that default is load-bearing. Greeting is a
        #: product behaviour belonging to the thing that opens a session; the
        #: presenter is the mechanism underneath it. Constructing it
        #: unconditionally meant every fresh root looked like a first boot — so
        #: the vertical slice, which builds a presenter over a temporary
        #: directory, opened on ``greeting`` and failed its step 4 asserting a
        #: static idle state. That is the same mistake the renderer *mode*
        #: default made a phase earlier: a mechanism that quietly asserts a
        #: product policy breaks every caller that only wanted the mechanism.
        self.greeting = FirstRunGreeting(self.root) if first_run_greeting else None
        self.saved_position = self.position_store.load()
        self.display = display or Display("headless", PixelRect(0, 0, 1024, 768), primary=True)
        #: The user's companion size. Taken as a constructor argument so a
        #: presenter opens at the size the person chose rather than at 1.0 and
        #: then jumping once something calls ``set_scale``.
        self.scale = max(0.5, min(3.0, float(scale)))
        #: The chrome-density level (``full``/``compact``/``minimal``) from
        #: ``character.companionMode``. An unknown value means full, for the
        #: same reason an unknown dock name means the default corner: this is
        #: on the path that opens the companion.
        self.companion_mode = (
            companion_mode if companion_mode in COMPANION_MODE_FACTORS else "full"
        )
        self._healthy = True
        self._unhealthy_since: float | None = None
        self._restarts = _RestartGuard()
        self._reported = 0

    def character_pixels(self) -> int:
        """The rendered square's side: base size × chrome level × user scale.

        One computation, used by every placement call, so the figure cannot
        be placed at one size and drawn at another.
        """
        return round(
            DEFAULT_CHARACTER_PIXELS
            * COMPANION_MODE_FACTORS[self.companion_mode]
            * self.scale
        )

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

    def reposition(self, origin: tuple[int, int], *, persist: bool = True) -> PositionDecision:
        """Move the companion to a dragged pixel origin and remember it.

        Persisted as a *fraction* of the display work area rather than as
        coordinates, so a resolution change moves the companion proportionally
        instead of leaving it off-screen — §6 asks for exactly that and
        :func:`saved_from_decision` already computed it. What was missing was
        anyone calling it.

        Snapping happens inside :func:`place_character`, so what is saved is the
        snapped position and not the raw pointer. A companion that was dragged
        almost-but-not-quite to the corner should come back in the corner it
        appeared to land in.
        """
        decision = place_character(
            [self.display],
            size=(self.character_pixels(),) * 2,
            placement=Placement.USER_DRAGGED,
            dragged_origin=origin,
        )
        self.placement = Placement.USER_DRAGGED
        self.saved_position = saved_from_decision(decision, self.display)
        if persist:
            try:
                self.position_store.save(self.saved_position)
            except OSError as error:
                # A position that could not be written is not worth refusing the
                # move over. The companion goes where it was dragged and simply
                # does not remember next time, which is the failure the user can
                # see and work around.
                self.controller.events.append({
                    "eventType": "character.position-not-saved",
                    "explanation": f"the companion position could not be written: {error}",
                    "taskContinues": True,
                })
        self.controller.set_position(decision)
        return decision

    def forget_position(self) -> None:
        """Drop a saved drag and return to the named placement from settings."""
        self.saved_position = None
        try:
            self.position_store.path.unlink()
        except OSError:
            pass

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
        # §5's greeting. Started on the first update this machine ever performs
        # and timed out by the clock the caller is already passing, so it needs
        # no timer of its own and nothing waits for it. The mapper ranks
        # ``greeting`` below everything that needs an answer, so a first boot
        # that opens on a permission request shows the request.
        greeting = False
        if self.greeting is not None:
            self.greeting.begin(now=now)
            greeting = self.greeting.active(now=now)
        mapper_input = mapper_input_for(
            state,
            accessibility=accessibility,
            listening=listening,
            speaking=speaking,
            transcribing=transcribing,
            repositioning=repositioning,
            renderer_healthy=self._healthy,
            greeting=greeting,
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
        derived.update(self._three_d_health())
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
            size=(self.character_pixels(),) * 2,
            placement=self.placement,
            saved=self.saved_position,
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

    def _three_d_health(self) -> dict[str, Any]:
        """The 3D signals that change per frame: context loss and frame timing.

        Read from the renderer that is actually running rather than measured
        here. A presenter that timed its own frames would be a second clock
        disagreeing with the renderer's, and the renderer is the one that knows
        when a draw began.
        """
        renderer = self.controller.renderer
        if renderer is None or renderer.renderer_name not in {"full-3d", "lightweight-3d"}:
            self.frame_health.reset()
            return {}
        statistics = renderer.frame_statistics()
        p95 = statistics.get("p95Ms")
        # Frames are only meaningful once there are enough of them to have a
        # 95th percentile that is not just the shader-compile frame.
        sample = p95 if statistics.get("frames", 0) >= 20 else None
        sustained = self.frame_health.observe(sample, renderer.quality)
        frames = max(1, int(statistics.get("frames", 0)))
        dropped = int(statistics.get("droppedFrames", 0))
        context = getattr(renderer, "context", None)
        return {
            "frame_p95_ms": sample,
            "sustained_slow_frames": sustained,
            "dropped_frame_ratio": min(1.0, dropped / (frames + dropped)) if dropped else 0.0,
            "gpu_context_lost": bool(context is not None and context.lost),
            "three_d_healthy": self._healthy and not (context is not None and context.lost),
        }

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
            size=(self.character_pixels(),) * 2,
            placement=self.placement,
            saved=self.saved_position,
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
                Presentation.FULL_3D.value,
                Presentation.LIGHTWEIGHT_3D.value,
                Presentation.ANIMATED_2D.value,
                Presentation.STATIC_IMAGE.value,
                Presentation.TEXT_ONLY.value,
            ],
            "threeDimensionalRenderer": self._describe_three_d(),
        }

    def _describe_three_d(self) -> dict[str, Any] | None:
        """What the 3D subsystem is doing, or why it is not doing anything.

        Never ``None`` for "not implemented" any more — that is what this field
        said for two phases and it was true then. It is ``None`` now only when
        this presenter was given no context provider at all, which is a
        statement about the caller rather than about the build.
        """
        renderer = self.controller.renderer
        if renderer is not None and renderer.renderer_name in {"full-3d", "lightweight-3d"}:
            return renderer.describe()
        return {
            "renderer": None,
            "contextProviderConfigured": self.three_d_context is not None,
            "packageSupports3d": self.package.model is not None,
            "available": self.base_signals.three_d_available,
            "frameHealth": self.frame_health.to_json(),
            "budget": self.three_d_budget.to_json(),
        }
