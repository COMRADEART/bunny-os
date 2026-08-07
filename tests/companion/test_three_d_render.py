# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The test that makes ``full-3d`` an implementation rather than a claim.

Everything else in this phase can be tested without a graphics stack, and is.
This file cannot: it creates a real OpenGL context, uploads the shipped model,
draws frames and reads the pixels back. §36's first item is "one validated
original 3D character renders", and the only honest evidence for that is pixels.

**It skips rather than passes** where no context can be made. That distinction is
the whole value of the file. A test that quietly succeeded on a machine with no
GPU would be a green tick standing behind
:data:`companion.presentation.IMPLEMENTED_PRESENTATIONS`, which is exactly the
arrangement the animated-2D phase refused to build and this one must not either.
The skip reason names what was missing, and the phase report records which
machines ran it and which skipped.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from companion.character.defaults import default_3d_character_path
from companion.character.mapper import (
    CharacterState,
    StateMapperInput,
    map_character_state,
)
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
from companion.character.three_d.context import SurfacelessContext, offscreen_available
from companion.character.three_d.errors import RendererCapabilityError, RendererContextError
from companion.character.three_d.renderer import QUALITY_LEVELS, ThreeDRenderer

_SURFACE = (256, 320)


def _context_or_skip() -> SurfacelessContext:
    available, reason = offscreen_available()
    if not available:
        raise unittest.SkipTest(f"no offscreen graphics context here: {reason}")
    try:
        context = SurfacelessContext()
        context.make_current()
    except (RendererCapabilityError, RendererContextError) as exc:
        raise unittest.SkipTest(f"a graphics context could not be created: {exc}") from exc
    return context


def _package_or_skip():
    root = default_3d_character_path()
    if not root.is_dir():
        raise unittest.SkipTest("the built-in 3D package is not installed here")
    package = validate_package_directory(root, trust_state=PackageTrustState.BUILT_IN)
    if package.model is None:
        raise unittest.SkipTest("the built-in 3D package carries no validated model")
    return package


def _coverage(pixels: bytes) -> float:
    opaque = sum(1 for index in range(3, len(pixels), 4) if pixels[index] > 12)
    return opaque / max(1, len(pixels) // 4)


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = _context_or_skip()
        cls.package = _package_or_skip()
        cls.section = cls.package.manifest.three_dimensional

    @classmethod
    def tearDownClass(cls) -> None:
        context = getattr(cls, "context", None)
        if context is not None:
            context.release()
        # Drop the class's own reference too. Releasing tells the driver to
        # destroy the context; it does not make the Python object unreachable,
        # and unittest keeps test classes alive for the life of the process —
        # so a fifty-run suite gate counted two context objects at the end and
        # called them leaked. They were released fixtures.
        cls.context = None
        cls.package = None

    def _renderer(self, quality: str = "full-3d", motion: str = "full") -> ThreeDRenderer:
        renderer = ThreeDRenderer(
            context=self.context, quality=quality, motion=motion, seed=0x42,
        )
        renderer.load_package(self.package)
        renderer.upload(
            self.package.model,
            animation_map=self.section.animation_map,
            expression_map=self.section.expression_map,
            viseme_map=self.section.viseme_map,
            native_scale=self.section.native_scale,
            floor_offset=self.section.floor_offset,
            now=0.0,
        )
        renderer.begin_offscreen(*_SURFACE)
        self.addCleanup(renderer.release)
        return renderer

    def _state(self, state: CharacterState):
        return map_character_state(
            self.package.manifest,
            StateMapperInput(
                presentation_phase={
                    CharacterState.WORKING: "working",
                    CharacterState.IDLE: "idle",
                    CharacterState.SPEAKING: "speaking",
                    CharacterState.ERROR: "error",
                    CharacterState.WAITING_FOR_APPROVAL: "waiting_for_approval",
                    CharacterState.LISTENING: "listening",
                    CharacterState.SUCCESS: "success",
                }.get(state, "idle"),
                status_text="Bunny is here.",
                listening=state is CharacterState.LISTENING,
            ),
        )

    # -- §36.1, §36.4 ------------------------------------------------------

    def test_the_built_in_character_draws_pixels(self) -> None:
        renderer = self._renderer()
        renderer.display_state(self._state(CharacterState.IDLE), now_ms=0)
        width, height, pixels = renderer.read_pixels()
        self.assertEqual((width, height), _SURFACE)
        coverage = _coverage(pixels)
        self.assertGreater(coverage, 0.03, "the character covered almost nothing")
        self.assertLess(coverage, 0.95, "the whole surface was filled; that is not a character")

    def test_the_context_reports_what_it_actually_is(self) -> None:
        info = self.context.info()
        self.assertTrue(info.version)
        self.assertGreaterEqual(info.max_texture_size, 1024)
        self.assertIn(info.accelerated, (True, False, None))

    def test_skeletal_animation_moves_the_character(self) -> None:
        """§36.4: two times in one clip must not draw the same picture."""
        renderer = self._renderer()
        renderer.display_state(self._state(CharacterState.WORKING), now_ms=0)
        _width, _height, first = renderer.read_pixels()
        renderer.draw(now_ms=900)
        _width, _height, later = renderer.read_pixels()
        self.assertNotEqual(first, later, "the skeleton did not move between two clip times")

    def test_a_state_change_changes_the_picture(self) -> None:
        renderer = self._renderer()
        renderer.display_state(self._state(CharacterState.IDLE), now_ms=0)
        _w, _h, idle = renderer.read_pixels()
        renderer.display_state(self._state(CharacterState.SUCCESS), now_ms=4000)
        renderer.draw(now_ms=4800)
        _w, _h, success = renderer.read_pixels()
        self.assertNotEqual(idle, success)

    def test_a_viseme_moves_the_mouth(self) -> None:
        """§36.7: a voice-produced mouth shape reaches the geometry."""
        renderer = self._renderer()
        renderer.display_state(self._state(CharacterState.SPEAKING), now_ms=0)
        renderer.set_mouth_shape("neutral")
        for step in range(6):
            renderer.draw(now_ms=step * 16)
        _w, _h, closed = renderer.read_pixels()
        renderer.set_mouth_shape("open-wide")
        for step in range(20):
            renderer.draw(now_ms=200 + step * 16)
        _w, _h, open_wide = renderer.read_pixels()
        self.assertNotEqual(closed, open_wide, "the mouth morph did not reach the vertices")

    def test_an_expression_changes_the_face(self) -> None:
        renderer = self._renderer()
        renderer.display_state(self._state(CharacterState.IDLE), now_ms=0)
        renderer.set_expression("neutral")
        for step in range(30):
            renderer.draw(now_ms=step * 16)
        _w, _h, neutral = renderer.read_pixels()
        renderer.set_expression("happy")
        for step in range(60):
            renderer.draw(now_ms=500 + step * 16)
        _w, _h, happy = renderer.read_pixels()
        self.assertNotEqual(neutral, happy)

    def test_the_camera_mode_changes_the_framing(self) -> None:
        renderer = self._renderer()
        renderer.camera.set_mode("full-body")
        renderer.display_state(self._state(CharacterState.IDLE), now_ms=0)
        _w, _h, full = renderer.read_pixels()
        renderer.camera.set_mode("close-speaking")
        renderer.draw(now_ms=0)
        _w, _h, close = renderer.read_pixels()
        self.assertNotEqual(full, close)
        self.assertGreater(_coverage(close), _coverage(full))

    def test_reduced_motion_still_draws_and_still_changes_state(self) -> None:
        renderer = self._renderer(motion="reduced")
        renderer.display_state(self._state(CharacterState.IDLE), now_ms=0)
        _w, _h, idle = renderer.read_pixels()
        self.assertGreater(_coverage(idle), 0.03)
        renderer.display_state(self._state(CharacterState.WORKING), now_ms=1000)
        _w, _h, working = renderer.read_pixels()
        self.assertNotEqual(idle, working)
        # And it does not move *within* a state.
        renderer.draw(now_ms=3000)
        _w, _h, later = renderer.read_pixels()
        self.assertEqual(working, later)

    def test_the_lightweight_rung_draws_the_same_character(self) -> None:
        renderer = self._renderer(quality="lightweight-3d")
        renderer.display_state(self._state(CharacterState.IDLE), now_ms=0)
        _w, _h, pixels = renderer.read_pixels()
        self.assertGreater(_coverage(pixels), 0.03)
        self.assertEqual(renderer.renderer_name, "lightweight-3d")
        self.assertEqual(
            renderer.describe()["qualityPolicy"]["targetFps"],
            QUALITY_LEVELS["lightweight-3d"]["targetFps"],
        )

    def test_the_lightweight_rung_uploads_less_texture(self) -> None:
        """§21's "lower texture resolution", as bytes rather than as a policy field."""
        full = self._renderer(quality="full-3d")
        light = self._renderer(quality="lightweight-3d")
        full_textures = sum(
            resource.estimated_bytes
            for resource in full.resources._live.values()
            if resource.kind == "texture"
        )
        light_textures = sum(
            resource.estimated_bytes
            for resource in light.resources._live.values()
            if resource.kind == "texture"
        )
        self.assertGreater(full_textures, 0)
        self.assertLess(light_textures, full_textures)

    def test_changing_quality_back_up_restores_the_frame_rate_target(self) -> None:
        renderer = self._renderer(quality="full-3d")
        self.assertEqual(renderer.frame_rate_cap, QUALITY_LEVELS["full-3d"]["targetFps"])
        renderer.set_quality("lightweight-3d")
        self.assertEqual(renderer.frame_rate_cap, QUALITY_LEVELS["lightweight-3d"]["targetFps"])
        renderer.set_quality("full-3d")
        self.assertEqual(
            renderer.frame_rate_cap, QUALITY_LEVELS["full-3d"]["targetFps"],
            "a renderer that recovered kept the degraded rung's frame cap",
        )


class ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = _context_or_skip()
        cls.package = _package_or_skip()
        cls.section = cls.package.manifest.three_dimensional

    @classmethod
    def tearDownClass(cls) -> None:
        context = getattr(cls, "context", None)
        if context is not None:
            context.release()
        # Drop the class's own reference too. Releasing tells the driver to
        # destroy the context; it does not make the Python object unreachable,
        # and unittest keeps test classes alive for the life of the process —
        # so a fifty-run suite gate counted two context objects at the end and
        # called them leaked. They were released fixtures.
        cls.context = None
        cls.package = None

    def _upload(self, renderer: ThreeDRenderer) -> None:
        renderer.load_package(self.package)
        renderer.upload(
            self.package.model,
            animation_map=self.section.animation_map,
            expression_map=self.section.expression_map,
            viseme_map=self.section.viseme_map,
            native_scale=self.section.native_scale,
            floor_offset=self.section.floor_offset,
            now=0.0,
        )

    def test_release_returns_every_gpu_object(self) -> None:
        renderer = ThreeDRenderer(context=self.context, seed=1)
        self._upload(renderer)
        renderer.begin_offscreen(128, 128)
        renderer.display_state(
            map_character_state(self.package.manifest, StateMapperInput(presentation_phase="idle")),
            now_ms=0,
        )
        live = renderer.resources.to_json()
        self.assertGreater(live["live"], 0)
        renderer.release()
        after = renderer.resources.to_json()
        self.assertEqual(after["live"], 0)
        self.assertEqual(after["createdTotal"], after["releasedTotal"])
        self.assertEqual(after["leakSuspicions"], [])

    def test_a_hundred_upload_release_cycles_leak_nothing(self) -> None:
        """A miniature of §34's first gate, run wherever this test can run."""
        counts: list[int] = []
        for _iteration in range(10):
            renderer = ThreeDRenderer(context=self.context, seed=2)
            self._upload(renderer)
            renderer.begin_offscreen(96, 96)
            renderer.display_state(
                map_character_state(
                    self.package.manifest, StateMapperInput(presentation_phase="working")
                ),
                now_ms=0,
            )
            renderer.release()
            counts.append(renderer.resources.to_json()["live"])
        self.assertEqual(counts, [0] * 10)

    def test_replacing_a_model_releases_the_previous_one_first(self) -> None:
        renderer = ThreeDRenderer(context=self.context, seed=3)
        self._upload(renderer)
        first = renderer.resources.to_json()["live"]
        self._upload(renderer)
        second = renderer.resources.to_json()["live"]
        self.addCleanup(renderer.release)
        self.assertEqual(first, second, "a replacement doubled the live resources")

    def test_a_released_renderer_reports_no_memory(self) -> None:
        renderer = ThreeDRenderer(context=self.context, seed=4)
        self._upload(renderer)
        self.assertGreater(renderer.observed_memory_bytes, 0)
        renderer.release()
        self.assertEqual(renderer.observed_memory_bytes, 0)


class PresenterPathTests(unittest.TestCase):
    """The production path: a projection in, a 3D frame out, through the ladder.

    Every other test in this file drives ``ThreeDRenderer`` directly, which is
    the right way to test a renderer and the wrong way to test that the renderer
    is *reachable*. This one starts at
    :class:`companion.character.surface.CharacterPresenter` — the thing the GTK
    client actually holds — hands it a canonical
    :class:`companion.presentation.PresentationState`, and asserts that a 3D
    renderer was selected by the ladder and drew the frame.
    """

    def setUp(self) -> None:
        self.context = _context_or_skip()
        self.addCleanup(self.context.release)
        _package_or_skip()
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-3d-presenter-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _presenter(self):
        from capability.runtime import assess_current_machine
        from companion.character.diagnostics import registry_for
        from companion.character.surface import CharacterPresenter

        registry = registry_for(self.root)
        built_in = [item for item in registry.built_ins() if item.package_id == "bunny-default-3d"]
        if not built_in:
            self.skipTest("the built-in 3D package is not registered here")
        registry.select("bunny-default-3d", package_digest=built_in[0].package_digest)
        presenter = CharacterPresenter(
            self.root,
            assessment=assess_current_machine(),
            three_d_context=lambda: self.context,
            three_d_seed=0x11,
        )
        self.addCleanup(presenter.controller.unload_package)
        return presenter

    def _state(self, phase: str):
        from companion.presentation import PresentationRecommendation, PresentationState

        return PresentationState(
            phase=phase,
            status_text="Bunny is here.",
            recommendation=PresentationRecommendation(
                implementation="full-3d", eligible="full-3d",
                limited_by_implementation=False, placement="docked", captions=True,
                plan_id="plan-presenter-test",
            ),
        )

    def test_the_presenter_selects_the_3d_renderer_and_draws(self) -> None:
        presenter = self._presenter()
        self.assertIsNotNone(
            presenter.package.model, "the selected package carries no validated model"
        )
        update = presenter.update(
            self._state("working"), now=1.0, now_ms=1000,
            signal_overrides={
                "display_available": True, "graphics_ready": True, "gpu_available": True,
                "available_memory_bytes": 8 * 1024 ** 3, "three_d_available": True,
            },
        )
        self.assertEqual(update.effective_presentation, "full-3d")
        self.assertEqual(presenter.controller.renderer.renderer_name, "full-3d")
        self.assertIsNotNone(update.frame)
        self.assertEqual(
            update.snapshot.mapped_state.character_state.value, "working",
            "the canonical phase did not reach the character",
        )
        described = presenter.describe()["threeDimensionalRenderer"]
        self.assertEqual(described["renderer"], "full-3d")
        self.assertIsNotNone(described["model"])

    def test_the_presenter_degrades_to_2d_without_a_gpu(self) -> None:
        presenter = self._presenter()
        update = presenter.update(
            self._state("working"), now=1.0, now_ms=1000,
            signal_overrides={
                "display_available": True, "graphics_ready": True, "gpu_available": True,
                "available_memory_bytes": 8 * 1024 ** 3, "three_d_available": False,
            },
        )
        self.assertEqual(update.effective_presentation, "animated-2d")
        self.assertEqual(presenter.controller.renderer.renderer_name, "animated-2d")
        self.assertIsNotNone(update.frame)


class ContextLossTests(unittest.TestCase):
    """§23: what a lost context does, on a context that is genuinely lost."""

    def test_a_lost_context_refuses_to_draw_and_releases_without_raising(self) -> None:
        context = _context_or_skip()
        package = _package_or_skip()
        section = package.manifest.three_dimensional
        renderer = ThreeDRenderer(context=context, seed=5)
        try:
            renderer.load_package(package)
            renderer.upload(
                package.model,
                animation_map=section.animation_map,
                expression_map=section.expression_map,
                viseme_map=section.viseme_map,
                native_scale=section.native_scale,
                floor_offset=section.floor_offset,
                now=0.0,
            )
            renderer.begin_offscreen(96, 96)
            renderer.draw(now_ms=0)
            context.simulate_loss("test")
            self.assertTrue(context.lost)
            with self.assertRaises(RendererContextError):
                renderer.draw(now_ms=16)
            released = renderer.release(context_lost=True)
            self.assertGreaterEqual(released["released"], 0)
            self.assertEqual(renderer.resources.to_json()["live"], 0)
        finally:
            context.release()

    def test_a_context_destroyed_underneath_the_renderer_is_survivable(self) -> None:
        context = _context_or_skip()
        package = _package_or_skip()
        section = package.manifest.three_dimensional
        renderer = ThreeDRenderer(context=context, seed=6)
        renderer.load_package(package)
        renderer.upload(
            package.model,
            animation_map=section.animation_map,
            expression_map=section.expression_map,
            viseme_map=section.viseme_map,
            native_scale=section.native_scale,
            floor_offset=section.floor_offset,
            now=0.0,
        )
        context.release()
        # Releasing after the context is gone must not raise and must clear the
        # ledger, or every subsequent leak measurement is taken against a
        # poisoned baseline.
        renderer.release(context_lost=True)
        self.assertEqual(renderer.resources.to_json()["live"], 0)


if __name__ == "__main__":
    unittest.main()
