# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral character renderer interface and common safe state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .bubble import BubbleLayout, BubbleState
from .errors import RendererError
from .mapper import MappedCharacterState
from .package import ValidatedPackage
from .positioning import PositionDecision


@dataclass(frozen=True)
class RenderedFrame:
    asset_id: str
    asset_path: Path
    width: int
    height: int
    state: str
    animation: str
    frame_index: int
    opacity: float
    scale: float
    mouth_shape: str
    accessibility_description: str

    def to_json(self) -> dict[str, Any]:
        return {
            "assetId": self.asset_id,
            "assetPath": str(self.asset_path),
            "width": self.width,
            "height": self.height,
            "state": self.state,
            "animation": self.animation,
            "frameIndex": self.frame_index,
            "opacity": self.opacity,
            "scale": self.scale,
            "mouthShape": self.mouth_shape,
            "accessibilityDescription": self.accessibility_description,
        }


@dataclass(frozen=True)
class RendererFailureEvent:
    event_type: str
    renderer: str
    code: str
    explanation: str
    recoverable: bool
    task_continues: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "eventType": self.event_type,
            "renderer": self.renderer,
            "code": self.code,
            "explanation": self.explanation,
            "recoverable": self.recoverable,
            "taskContinues": self.task_continues,
        }


@dataclass(frozen=True)
class RendererStatus:
    renderer: str
    loaded_package_id: str | None
    loaded_package_digest: str | None
    running: bool
    paused: bool
    visible: bool
    reduced_motion: bool
    frame_rate_cap: int
    last_frame_ms: float
    dropped_frames: int
    observed_memory_bytes: int
    failure: RendererFailureEvent | None

    def to_json(self) -> dict[str, Any]:
        return {
            "renderer": self.renderer,
            "loadedPackageId": self.loaded_package_id,
            "loadedPackageDigest": self.loaded_package_digest,
            "running": self.running,
            "paused": self.paused,
            "visible": self.visible,
            "reducedMotion": self.reduced_motion,
            "frameRateCap": self.frame_rate_cap,
            "lastFrameMs": self.last_frame_ms,
            "droppedFrames": self.dropped_frames,
            "observedMemoryBytes": self.observed_memory_bytes,
            "failure": self.failure.to_json() if self.failure else None,
        }


class CharacterRenderer(ABC):
    """Presentation-only contract implemented by static and animated renderers."""

    renderer_name = "abstract"

    def __init__(self, *, display_available: bool = True) -> None:
        self.package: ValidatedPackage | None = None
        self.mapped_state: MappedCharacterState | None = None
        self.frame: RenderedFrame | None = None
        self.position: PositionDecision | None = None
        self.bubble_state: BubbleState | None = None
        self.bubble_layout: BubbleLayout | None = None
        self.running = False
        self.paused = False
        self.visible = True
        self.reduced_motion = False
        self.display_available = display_available
        self.scale = 1.0
        self.opacity = 1.0
        self.frame_rate_cap = 60
        self.last_frame_ms = 0.0
        self.dropped_frames = 0
        self.observed_memory_bytes = 0
        self.failure: RendererFailureEvent | None = None
        self.expression = "neutral"
        self.mouth_shape = "neutral"

    def load_package(self, package: ValidatedPackage) -> None:
        if not isinstance(package, ValidatedPackage):
            raise TypeError("renderer accepts only a fully validated package")
        self.package = package
        self.running = True
        self.paused = False
        self.failure = None
        self.observed_memory_bytes = sum(info.decoded_bytes for info in package.image_info.values())

    def unload_package(self) -> None:
        self.package = None
        self.mapped_state = None
        self.frame = None
        self.running = False
        self.paused = False
        self.observed_memory_bytes = 0
        self.mouth_shape = "neutral"

    @abstractmethod
    def display_state(self, state: MappedCharacterState, *, now_ms: int = 0) -> RenderedFrame | None:
        """Display a mapped state or return ``None`` for headless text-only output."""

    @abstractmethod
    def play_animation(self, name: str, *, now_ms: int = 0) -> RenderedFrame | None:
        """Start a package animation by validated manifest name."""

    @abstractmethod
    def stop_animation(self, *, now_ms: int = 0) -> RenderedFrame | None:
        """Stop animation and return to a safe static/idle frame."""

    def pause(self, *, now_ms: int = 0) -> None:
        del now_ms
        self.paused = True

    def resume(self, *, now_ms: int = 0) -> None:
        del now_ms
        self.paused = False

    def set_expression(self, expression: str) -> None:
        self.expression = str(expression)

    def set_mouth_shape(self, shape: str) -> None:
        self.mouth_shape = str(shape)
        if self.frame is not None:
            self.frame = replace(self.frame, mouth_shape=self.mouth_shape)

    def set_position(self, position: PositionDecision) -> None:
        if position.accepts_keyboard_focus:
            raise RendererError("character repositioning cannot take keyboard focus")
        self.position = position

    def set_scale(self, scale: float) -> None:
        if not 0.5 <= scale <= 3.0:
            raise ValueError("character scale must be between 0.5 and 3")
        self.scale = float(scale)

    def set_opacity(self, opacity: float) -> None:
        if not 0 <= opacity <= 1:
            raise ValueError("renderer opacity must be normalized")
        self.opacity = float(opacity)

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion = bool(enabled)

    def set_visibility(self, visible: bool) -> None:
        self.visible = bool(visible)

    def set_frame_rate_cap(self, value: int) -> None:
        if not 1 <= value <= 60:
            raise ValueError("renderer frame-rate cap must be between 1 and 60")
        self.frame_rate_cap = value

    def attach_speech_bubble(self, state: BubbleState, layout: BubbleLayout) -> None:
        self.bubble_state = state
        self.bubble_layout = layout

    def detach_speech_bubble(self) -> None:
        self.bubble_state = None
        self.bubble_layout = None

    def report_frame_timing(self) -> dict[str, float | int]:
        return {"lastFrameMs": self.last_frame_ms, "droppedFrames": self.dropped_frames}

    def report_memory_use(self) -> int:
        return self.observed_memory_bytes

    def report_failure(self, code: str, explanation: str, *, recoverable: bool = True) -> RendererFailureEvent:
        self.failure = RendererFailureEvent(
            "renderer.failed", self.renderer_name, code, explanation, recoverable, True
        )
        self.running = False
        return self.failure

    def accessibility_description(self) -> str:
        if self.mapped_state is None:
            return "Bunny character is not loaded."
        return self.mapped_state.accessibility_description

    def capture_diagnostic_frame(self, *, development_mode: bool = False) -> dict[str, Any]:
        if not development_mode:
            raise RendererError("diagnostic frame capture is available only in development mode")
        return {
            "frame": self.frame.to_json() if self.frame else None,
            "position": self.position.to_json() if self.position else None,
            "bubble": self.bubble_state.to_json() if self.bubble_state else None,
            "bubbleLayout": self.bubble_layout.to_json() if self.bubble_layout else None,
            "status": self.status().to_json(),
        }

    def status(self) -> RendererStatus:
        return RendererStatus(
            self.renderer_name,
            self.package.manifest.package_id if self.package else None,
            self.package.package_digest if self.package else None,
            self.running,
            self.paused,
            self.visible,
            self.reduced_motion,
            self.frame_rate_cap,
            self.last_frame_ms,
            self.dropped_frames,
            self.observed_memory_bytes,
            self.failure,
        )

    def _require_package(self) -> ValidatedPackage:
        if self.package is None:
            raise RendererError("renderer has no validated character package loaded")
        return self.package

    def _frame_for_asset(
        self,
        asset_id: str,
        *,
        animation: str,
        frame_index: int,
        state: str,
    ) -> RenderedFrame:
        package = self._require_package()
        asset = package.manifest.asset(asset_id)
        if not asset.media_type.startswith("image/"):
            raise RendererError("renderer frame does not reference a validated raster asset")
        description = self.accessibility_description()
        return RenderedFrame(
            asset_id, package.asset_path(asset_id), asset.width, asset.height,
            state, animation, frame_index, self.opacity, self.scale,
            self.mouth_shape, description,
        )
