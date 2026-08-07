# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renderer orchestration that preserves task-independent presentation state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .adaptation import (
    AdaptiveRendererSelector,
    CapabilityPresentationPlan,
    Presentation,
    RendererDecision,
    RendererSignals,
)
from .animated_renderer import Animated2DRenderer
from .bubble import BubbleLayout, BubbleState
from .lipsync import LipSyncController, LipSyncEvent, LipSyncStatus
from .mapper import MappedCharacterState
from .package import ValidatedPackage
from .positioning import PositionDecision
from .renderer import CharacterRenderer, RenderedFrame, RendererFailureEvent
from .static_renderer import StaticImageRenderer


@dataclass(frozen=True)
class CharacterRendererSnapshot:
    presentation: RendererDecision
    mapped_state: MappedCharacterState | None
    frame: RenderedFrame | None
    renderer_status: dict[str, Any] | None
    position: dict[str, Any] | None
    bubble: dict[str, Any] | None
    lip_sync: dict[str, Any] | None
    events: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "presentation": self.presentation.to_json(),
            "mappedState": self.mapped_state.to_json() if self.mapped_state else None,
            "frame": self.frame.to_json() if self.frame else None,
            "rendererStatus": self.renderer_status,
            "position": self.position,
            "bubble": self.bubble,
            "lipSync": self.lip_sync,
            "events": list(self.events),
        }


class CharacterRendererController:
    """Own renderer health only.  The companion task remains in runtime-core."""

    def __init__(
        self,
        *,
        selector: AdaptiveRendererSelector | None = None,
        three_d_context: Any = None,
        three_d_seed: int | None = None,
    ) -> None:
        self.selector = selector or AdaptiveRendererSelector()
        #: A zero-argument callable returning a
        #: :class:`companion.character.three_d.context.GraphicsContext`, or
        #: ``None``. Injected rather than constructed here so this module — which
        #: every 2D client imports — never reaches a graphics library. With
        #: ``None`` the 3D rungs are simply unreachable, which is what a
        #: headless or text-only client should get and §30 requires.
        self.three_d_context = three_d_context
        self.three_d_seed = three_d_seed
        self.package: ValidatedPackage | None = None
        self.renderer: CharacterRenderer | None = None
        self.mapped_state: MappedCharacterState | None = None
        self.decision: RendererDecision | None = None
        self.position: PositionDecision | None = None
        self.bubble_state: BubbleState | None = None
        self.bubble_layout: BubbleLayout | None = None
        self.lip_sync: LipSyncController | None = None
        self.lip_status: LipSyncStatus | None = None
        self.events: list[dict[str, Any]] = []
        self._selector_event_count = 0

    def load_package(self, package: ValidatedPackage) -> None:
        previous = self.package
        if (
            self.renderer is not None
            and previous is not None
            and previous.package_digest != package.package_digest
        ):
            self.renderer.unload_package()
            self.renderer = None
            self.mapped_state = None
            self.events.append({
                "eventType": "renderer.package-changed",
                "previousPackageDigest": previous.package_digest,
                "packageDigest": package.package_digest,
                "taskContinues": True,
            })
        self.package = package
        self.lip_sync = LipSyncController(package.manifest.mouth_shape_map)
        self.lip_status = None

    def unload_package(self) -> None:
        if self.renderer is not None:
            self.renderer.unload_package()
        self.renderer = None
        self.package = None
        self.mapped_state = None
        self.lip_sync = None
        self.lip_status = None

    def _renderer_for(self, presentation: Presentation, signals: RendererSignals) -> CharacterRenderer | None:
        if presentation is Presentation.TEXT_ONLY:
            return None
        expected = presentation.value
        if self.renderer is not None and self.renderer.renderer_name == expected:
            self.renderer.display_available = signals.display_available
            return self.renderer
        package = self.package
        if package is None:
            raise RuntimeError("renderer controller has no validated package")
        previous = self.renderer
        if presentation in (Presentation.FULL_3D, Presentation.LIGHTWEIGHT_3D):
            renderer = self._three_d_renderer(presentation, signals, package)
        elif presentation is Presentation.ANIMATED_2D:
            renderer = Animated2DRenderer(display_available=signals.display_available)
            renderer.load_package(package)
        else:
            renderer = StaticImageRenderer(display_available=signals.display_available)
            renderer.load_package(package)
        if previous is not None:
            renderer.set_scale(previous.scale)
            renderer.set_opacity(previous.opacity)
            renderer.set_visibility(previous.visible)
            # A 3D renderer being replaced must give its GPU objects back before
            # the replacement draws. ``unload_package`` releases them; calling
            # it here rather than leaving it to garbage collection is what makes
            # §34's GL-object delta zero across a hundred rung changes.
            previous.unload_package()
        if self.position is not None:
            renderer.set_position(self.position)
        if self.bubble_state is not None and self.bubble_layout is not None:
            renderer.attach_speech_bubble(self.bubble_state, self.bubble_layout)
        self.renderer = renderer
        return renderer

    def _three_d_renderer(
        self, presentation: Presentation, signals: RendererSignals, package: ValidatedPackage
    ) -> CharacterRenderer:
        """Build and populate a 3D renderer, or refuse in a way the ladder reads.

        Every failure below raises, and every caller of ``_renderer_for`` is
        inside the presenter's ``try``: a refusal here becomes a typed
        degradation and the next evaluation lands on animated-2D. That is why
        this method does not itself fall back — one fallback path, in the place
        that already had one.
        """
        from .three_d.renderer import ThreeDRenderer

        if self.three_d_context is None:
            raise RuntimeError("no graphics context provider is configured for 3D presentation")
        model = package.model
        section = package.manifest.three_dimensional
        if model is None or section is None:
            raise RuntimeError("the selected package carries no validated 3D model")
        context = self.three_d_context() if callable(self.three_d_context) else self.three_d_context
        renderer = ThreeDRenderer(
            context=context,
            display_available=signals.display_available,
            quality=presentation.value,
            motion="reduced" if (signals.reduced_motion or signals.no_animation) else "full",
            seed=self.three_d_seed,
        )
        renderer.load_package(package)
        renderer.model_path = package.asset_path(
            next(asset.asset_id for asset in package.manifest.assets if asset.purpose == "model")
        )
        renderer.upload(
            model,
            animation_map=section.animation_map,
            expression_map=section.expression_map,
            viseme_map=section.viseme_map,
            native_scale=section.native_scale,
            floor_offset=section.floor_offset,
        )
        return renderer

    def apply(
        self,
        mapped: MappedCharacterState,
        plan: CapabilityPresentationPlan,
        signals: RendererSignals,
        *,
        now: float,
        now_ms: int,
    ) -> CharacterRendererSnapshot:
        package = self.package
        if package is None:
            raise RuntimeError("renderer controller has no validated package")
        decision = self.selector.evaluate(plan, package, signals, now=now)
        if mapped.frame_rate_cap < decision.frame_rate_cap:
            decision = replace(
                decision,
                frame_rate_cap=mapped.frame_rate_cap,
                reasons=decision.reasons + (
                    f"the accessibility frame-rate preference capped animation at {mapped.frame_rate_cap} fps",
                ),
            )
        self.decision = decision
        self.mapped_state = mapped
        renderer = self._renderer_for(decision.effective, signals)
        frame = None
        if renderer is not None:
            renderer.set_reduced_motion(signals.reduced_motion or signals.no_animation)
            renderer.set_frame_rate_cap(decision.frame_rate_cap)
            frame = renderer.display_state(mapped, now_ms=now_ms)
            if self.lip_status is not None and self.lip_status.active:
                renderer.set_mouth_shape(self.lip_status.shape.value)
                frame = renderer.frame
        for event in self.selector.events[self._selector_event_count:]:
            self.events.append(event.to_json())
        self._selector_event_count = len(self.selector.events)
        return self.snapshot(frame=frame)

    def set_position(self, position: PositionDecision) -> None:
        self.position = position
        if self.renderer is not None:
            self.renderer.set_position(position)

    def attach_bubble(self, state: BubbleState, layout: BubbleLayout) -> None:
        self.bubble_state, self.bubble_layout = state, layout
        if self.renderer is not None:
            self.renderer.attach_speech_bubble(state, layout)

    def detach_bubble(self) -> None:
        self.bubble_state = self.bubble_layout = None
        if self.renderer is not None:
            self.renderer.detach_speech_bubble()

    def start_lip_sync(self, events: list[LipSyncEvent], *, reduced_motion: bool = False) -> LipSyncStatus:
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.start(events, reduced_motion=reduced_motion)
        return self.lip_status

    def advance_lip_sync(self, playback_ms: int, *, audio_clock_ms: int | None = None) -> LipSyncStatus:
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.advance(playback_ms, audio_clock_ms=audio_clock_ms)
        if self.renderer is not None:
            self.renderer.set_mouth_shape(self.lip_status.shape.value)
        return self.lip_status

    def cancel_lip_sync(self, reason: str = "audio interrupted") -> LipSyncStatus:
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.cancel(reason)
        if self.renderer is not None:
            self.renderer.set_mouth_shape("neutral")
        return self.lip_status

    def finish_lip_sync(self) -> LipSyncStatus:
        """The utterance ended of its own accord; the mouth returns to neutral.

        Distinct from :meth:`cancel_lip_sync` in the record and identical on the
        screen, which is correct: a completed utterance and an interrupted one
        both leave a closed mouth, and only one of them is a cancellation.

        Not expressible as ``advance_lip_sync`` past the end of the timeline. An
        *inactive* controller's ``advance`` returns its current status — whose
        shape is the last shape it held — and the renderer would then be told to
        draw the mouth mid-syllable again.
        """
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.finish()
        if self.renderer is not None:
            self.renderer.set_mouth_shape("neutral")
        return self.lip_status

    def report_renderer_failure(self, code: str, explanation: str) -> RendererFailureEvent:
        if self.renderer is None:
            event = RendererFailureEvent("renderer.failed", "text-only", code, explanation, False, True)
        else:
            event = self.renderer.report_failure(code, explanation)
        self.events.append(event.to_json())
        return event

    def restart_renderer(self, *, now_ms: int = 0) -> CharacterRendererSnapshot:
        """Recreate only the renderer and restore package, placement and state."""
        old = self.renderer
        if old is None:
            return self.snapshot()
        try:
            presentation = Presentation(old.renderer_name)
        except ValueError:
            presentation = Presentation.STATIC_IMAGE
        package = self.package
        if package is None:
            raise RuntimeError("renderer restart has no package")
        display_available = old.display_available
        scale = old.scale
        opacity = old.opacity
        visible = old.visible
        reduced_motion = old.reduced_motion
        frame_rate_cap = old.frame_rate_cap
        mouth_shape = old.mouth_shape
        was_paused = old.paused
        old.unload_package()
        self.renderer = None
        renderer = self._renderer_for(
            presentation, RendererSignals(display_available=display_available)
        )
        frame = None
        if renderer is not None:
            renderer.set_scale(scale)
            renderer.set_opacity(opacity)
            renderer.set_visibility(visible)
            renderer.set_reduced_motion(reduced_motion)
            renderer.set_frame_rate_cap(frame_rate_cap)
            if self.mapped_state is not None:
                frame = renderer.display_state(self.mapped_state, now_ms=now_ms)
            renderer.set_mouth_shape(mouth_shape)
            frame = renderer.frame
            if was_paused:
                renderer.pause(now_ms=now_ms)
        self.events.append({
            "eventType": "renderer.restarted",
            "renderer": renderer.renderer_name if renderer else "text-only",
            "restoredPackage": package.manifest.package_id,
            "restoredState": self.mapped_state.character_state.value if self.mapped_state else None,
            "taskContinues": True,
        })
        return self.snapshot(frame=frame)

    def tick(self, *, now_ms: int) -> RenderedFrame | None:
        renderer = self.renderer
        if isinstance(renderer, Animated2DRenderer):
            return renderer.tick(now_ms=now_ms)
        if renderer is not None and renderer.renderer_name in {"full-3d", "lightweight-3d"}:
            # A skeletal renderer has no frame list to advance through: every
            # tick is a new pose sampled at a new time, so a tick *is* a draw.
            # ``draw`` is bounded by the frame-rate cap the selector set.
            return renderer.draw(now_ms=now_ms)
        return renderer.frame if renderer else None

    def snapshot(self, *, frame: RenderedFrame | None = None) -> CharacterRendererSnapshot:
        if self.decision is None:
            self.decision = RendererDecision(
                Presentation.TEXT_ONLY, Presentation.TEXT_ONLY, 1,
                ("renderer has not received a capability plan",), False, "plan-unset",
            )
        effective_frame = frame if frame is not None else (self.renderer.frame if self.renderer else None)
        return CharacterRendererSnapshot(
            self.decision,
            self.mapped_state,
            effective_frame,
            self.renderer.status().to_json() if self.renderer else None,
            self.position.to_json() if self.position else None,
            self.bubble_state.to_json() if self.bubble_state else None,
            self.lip_status.to_json() if self.lip_status else None,
            tuple(self.events),
        )
