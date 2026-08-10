# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guaranteed PNG/WebP static fallback renderer."""

from __future__ import annotations

from .errors import RendererError
from .mapper import MappedCharacterState
from .package import ValidatedPackage
from .renderer import CharacterRenderer, RenderedFrame


class StaticImageRenderer(CharacterRenderer):
    renderer_name = "static-image"

    def load_package(self, package: ValidatedPackage) -> None:
        super().load_package(package)
        # The static implementation retains one decoded canvas, not every
        # frame in an animated package. All frame canvases have already been
        # proven to use the same declared dimensions by package validation.
        self.observed_memory_bytes = package.image_info[package.manifest.fallback_asset].decoded_bytes

    def _asset_for_animation(self, name: str) -> str:
        package = self._require_package()
        if name == "__static_fallback__":
            return package.manifest.fallback_asset
        animation = package.manifest.animation(name)
        return animation.frames[0].asset_id

    def display_state(self, state: MappedCharacterState, *, now_ms: int = 0) -> RenderedFrame | None:
        del now_ms
        self._require_package()
        self.mapped_state = state
        self.expression = state.expression
        if not self.display_available:
            self.frame = None
            return None
        asset_id = self._asset_for_animation(state.animation)
        self.frame = self._frame_for_asset(
            asset_id, animation=state.animation, frame_index=0, state=state.character_state.value
        )
        self.running = True
        self.last_frame_ms = 0.0
        return self.frame

    def play_animation(self, name: str, *, now_ms: int = 0) -> RenderedFrame | None:
        del now_ms
        package = self._require_package()
        asset_id = self._asset_for_animation(name)
        if not self.display_available:
            self.frame = None
            return None
        state = self.mapped_state.character_state.value if self.mapped_state else "idle"
        self.frame = self._frame_for_asset(asset_id, animation=name, frame_index=0, state=state)
        return self.frame

    def stop_animation(self, *, now_ms: int = 0) -> RenderedFrame | None:
        del now_ms
        package = self._require_package()
        if not self.display_available:
            self.frame = None
            return None
        self.frame = self._frame_for_asset(
            package.manifest.fallback_asset,
            animation="__static_fallback__",
            frame_index=0,
            state=self.mapped_state.character_state.value if self.mapped_state else "idle",
        )
        return self.frame

    def set_mouth_shape(self, shape: str) -> None:
        super().set_mouth_shape(shape)
        package = self.package
        if package is None or not self.display_available:
            return
        animation_name = package.manifest.mouth_shape_map.get(shape)
        if animation_name is not None:
            asset_id = self._asset_for_animation(animation_name)
            state = self.mapped_state.character_state.value if self.mapped_state else "speaking"
            self.frame = self._frame_for_asset(asset_id, animation=animation_name, frame_index=0, state=state)
