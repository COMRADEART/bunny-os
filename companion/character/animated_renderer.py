# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded frame-sequence animated 2D renderer."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import RendererError
from .mapper import CharacterState, MappedCharacterState
from .renderer import CharacterRenderer, RenderedFrame
from .schema import AnimationSpec

SAFETY_STATES = {
    CharacterState.ERROR.value,
    CharacterState.WARNING.value,
    CharacterState.WAITING_FOR_APPROVAL.value,
    CharacterState.CANCELLED.value,
    CharacterState.LISTENING.value,
}


@dataclass
class _Playback:
    animation: AnimationSpec
    started_ms: int
    paused_at_ms: int | None = None
    paused_total_ms: int = 0
    last_frame_index: int = 0
    last_frame_number: int = 0
    last_rendered_at_ms: int = 0


class Animated2DRenderer(CharacterRenderer):
    renderer_name = "animated-2d"

    def __init__(self, *, display_available: bool = True) -> None:
        super().__init__(display_available=display_available)
        self.playback: _Playback | None = None
        self.queued_animation: str | None = None
        self.playback_speed = 1.0

    def unload_package(self) -> None:
        self.playback = None
        self.queued_animation = None
        super().unload_package()

    def _animation(self, name: str) -> AnimationSpec:
        package = self._require_package()
        if name == "__static_fallback__":
            from .schema import FrameSpec
            return AnimationSpec(
                name, "static", (FrameSpec(package.manifest.fallback_asset, 1000),),
                False, "immediate", 1.0,
            )
        return package.manifest.animation(name)

    def _can_interrupt(self, incoming_state: str, incoming: AnimationSpec) -> bool:
        if incoming_state in SAFETY_STATES:
            return True
        if self.playback is None:
            return True
        current = self.playback.animation
        if current.transition == "non-interruptible":
            return False
        if current.transition in {"complete-current", "queue-next"}:
            return False
        return incoming.transition != "queue-next"

    def display_state(self, state: MappedCharacterState, *, now_ms: int = 0) -> RenderedFrame | None:
        self._require_package()
        self.mapped_state = state
        self.expression = state.expression
        animation = self._animation(state.animation)
        if self.reduced_motion or state.playback_policy in {"static-first-frame", "hold-first-frame"}:
            animation = AnimationSpec(
                animation.name, "static", (animation.frames[0],), False, "immediate", 1.0
            )
        if not self._can_interrupt(state.character_state.value, animation):
            self.queued_animation = animation.name  # exactly one bounded slot
            return self.frame
        return self._start(animation, now_ms=now_ms)

    def play_animation(self, name: str, *, now_ms: int = 0) -> RenderedFrame | None:
        return self._start(self._animation(name), now_ms=now_ms)

    def _start(self, animation: AnimationSpec, *, now_ms: int) -> RenderedFrame | None:
        self.playback = _Playback(animation, now_ms, last_rendered_at_ms=now_ms)
        self.queued_animation = None
        self.paused = False
        self.running = True
        if not self.display_available:
            self.frame = None
            return None
        return self._render_index(0, elapsed_ms=0)

    def stop_animation(self, *, now_ms: int = 0) -> RenderedFrame | None:
        package = self._require_package()
        idle = package.manifest.state_map.get("idle", "__static_fallback__")
        return self.play_animation(idle, now_ms=now_ms)

    def pause(self, *, now_ms: int = 0) -> None:
        if self.playback is not None and self.playback.paused_at_ms is None:
            self.playback.paused_at_ms = now_ms
        super().pause(now_ms=now_ms)

    def resume(self, *, now_ms: int = 0) -> None:
        if self.playback is not None and self.playback.paused_at_ms is not None:
            self.playback.paused_total_ms += max(0, now_ms - self.playback.paused_at_ms)
            self.playback.paused_at_ms = None
        super().resume(now_ms=now_ms)

    def set_playback_speed(self, speed: float) -> None:
        if not 0.25 <= speed <= 4.0:
            raise ValueError("animation playback speed must be between 0.25 and 4")
        self.playback_speed = float(speed)

    def _render_index(self, index: int, *, elapsed_ms: int) -> RenderedFrame:
        if self.playback is None:
            raise RendererError("animated renderer has no active playback")
        animation = self.playback.animation
        frame_spec = animation.frames[index]
        state = self.mapped_state.character_state.value if self.mapped_state else "idle"
        self.frame = self._frame_for_asset(
            frame_spec.asset_id, animation=animation.name, frame_index=index, state=state
        )
        self.last_frame_ms = float(elapsed_ms)
        self.playback.last_frame_index = index
        return self.frame

    def tick(self, *, now_ms: int) -> RenderedFrame | None:
        if self.playback is None or self.paused or not self.running:
            return self.frame
        playback = self.playback
        effective_now = playback.paused_at_ms if playback.paused_at_ms is not None else now_ms
        elapsed = max(0, effective_now - playback.started_ms - playback.paused_total_ms)
        speed = self.playback_speed * playback.animation.playback_speed
        scaled = int(elapsed * speed)
        durations = [frame.duration_ms for frame in playback.animation.frames]
        total = sum(durations)
        completed = scaled >= total
        cycles = 0
        if playback.animation.loop and total:
            cycles, position = divmod(scaled, total)
        else:
            position = min(scaled, max(0, total - 1))
        accumulated = 0
        index = len(durations) - 1
        for candidate, duration in enumerate(durations):
            accumulated += duration
            if position < accumulated:
                index = candidate
                break
        absolute_frame = cycles * len(durations) + index if playback.animation.loop else index
        advance = absolute_frame - playback.last_frame_number
        if advance > 1:
            self.dropped_frames += advance - 1
        playback.last_frame_number = absolute_frame
        frame = self.frame
        minimum_interval = 1000 / self.frame_rate_cap
        if (
            self.display_available
            and (
                now_ms - playback.last_rendered_at_ms >= minimum_interval
                or (completed and not playback.animation.loop)
            )
        ):
            frame = self._render_index(index, elapsed_ms=elapsed)
            playback.last_rendered_at_ms = now_ms
        if completed and not playback.animation.loop:
            queued = self.queued_animation
            if queued is not None:
                return self.play_animation(queued, now_ms=now_ms)
            if playback.animation.transition == "return-to-idle":
                return self.stop_animation(now_ms=now_ms)
            self.running = False
        return frame

    def set_mouth_shape(self, shape: str) -> None:
        super().set_mouth_shape(shape)
        package = self.package
        if (
            package is None
            or not self.display_available
            or self.mapped_state is None
            or self.mapped_state.character_state not in {
                CharacterState.SPEAKING, CharacterState.PRESENTING_RESULT
            }
        ):
            return
        animation_name = package.manifest.mouth_shape_map.get(shape)
        if animation_name is None:
            return
        animation = self._animation(animation_name)
        self.frame = self._frame_for_asset(
            animation.frames[0].asset_id,
            animation=animation_name,
            frame_index=0,
            state=self.mapped_state.character_state.value,
        )
