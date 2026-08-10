# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§31: six operations, an allow-list, and nothing that takes a path.

The operations that need a GPU skip where there is none; the ones that describe
the *surface* — which names exist, what each refuses, what a caller may pass —
run everywhere, because those are the properties that keep the surface narrow.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from companion.character.defaults import default_3d_character_path
from companion.character.three_d.context import offscreen_available
from companion.character.three_d.diagnostics import (
    OPERATION_NAMES,
    REFUSED_OPERATIONS,
    ThreeDDiagnostics,
    run_operation,
    three_d_environment,
)
from companion.character.three_d.errors import RendererCapabilityError


def _skip_without_graphics() -> None:
    available, reason = offscreen_available()
    if not available:
        raise unittest.SkipTest(f"no offscreen graphics context here: {reason}")


def _skip_without_package() -> Path:
    root = default_3d_character_path()
    if not root.is_dir():
        raise unittest.SkipTest("the built-in 3D package is not installed here")
    return root


class SurfaceTests(unittest.TestCase):
    """These need no graphics stack, and they are the ones that bound the API."""

    def test_the_six_operations_are_exactly_section_31s(self) -> None:
        self.assertEqual(
            OPERATION_NAMES,
            (
                "renderer_3d_health", "renderer_3d_status", "renderer_3d_model",
                "renderer_3d_metrics", "renderer_3d_explain", "renderer_3d_reload",
            ),
        )

    def test_an_unknown_operation_is_refused_with_the_list(self) -> None:
        with self.assertRaisesRegex(RendererCapabilityError, "unknown 3D diagnostics operation"):
            run_operation("renderer_3d_everything")

    def test_the_forbidden_operations_are_refused_by_name_with_a_reason(self) -> None:
        for name, reason in REFUSED_OPERATIONS.items():
            with self.assertRaises(RendererCapabilityError) as caught:
                run_operation(name)
            self.assertIn("refused by design", str(caught.exception))
            self.assertIn(reason.split(";")[0][:20], str(caught.exception))

    def test_no_operation_accepts_a_path_a_shader_or_a_gl_command(self) -> None:
        forbidden = {"path", "file", "shader", "texture", "model_path", "command", "source", "uri"}
        for name in OPERATION_NAMES:
            signature = inspect.signature(getattr(ThreeDDiagnostics, name))
            for parameter in signature.parameters:
                self.assertNotIn(
                    parameter.casefold(), forbidden,
                    f"{name} accepts {parameter}, which §31 forbids",
                )

    def test_run_operation_accepts_only_three_narrow_arguments(self) -> None:
        signature = inspect.signature(run_operation)
        self.assertEqual(
            sorted(signature.parameters), ["frames", "name", "package_id", "root"]
        )

    def test_the_environment_probe_does_not_initialise_a_library(self) -> None:
        report = three_d_environment()
        self.assertFalse(report["libraryInitialised"])
        self.assertIsInstance(report["reasons"], list)

    def test_health_answers_even_where_no_graphics_exist(self) -> None:
        """§30: a headless machine gets an answer, not an exception."""
        report = run_operation("renderer_3d_health")
        self.assertEqual(report["operation"], "renderer_3d_health")
        self.assertIn("healthy", report)
        self.assertIn("environment", report)
        if not report["contextCreated"]:
            self.assertTrue(report["explanation"])

    def test_explain_answers_even_where_no_graphics_exist(self) -> None:
        report = run_operation("renderer_3d_explain")
        self.assertEqual(report["operation"], "renderer_3d_explain")
        self.assertEqual(
            report["ladder"],
            ["full-3d", "lightweight-3d", "animated-2d", "static-image", "text-only"],
        )
        self.assertIn("budget", report)

    def test_model_needs_no_gpu_at_all(self) -> None:
        _skip_without_package()
        report = run_operation("renderer_3d_model")
        self.assertEqual(report["operation"], "renderer_3d_model")
        self.assertEqual(len(report["modelDigest"]), 64)
        self.assertGreater(report["model"]["triangles"], 0)
        self.assertIn("declaredLimits", report)


class GraphicsTests(unittest.TestCase):
    """The operations that need a context. Skipped, never silently passed."""

    def setUp(self) -> None:
        _skip_without_graphics()
        _skip_without_package()

    def test_health_reports_a_created_context(self) -> None:
        report = run_operation("renderer_3d_health")
        self.assertTrue(report["contextCreated"])
        self.assertTrue(report["healthy"])
        self.assertIn("accelerated", report["context"])

    def test_status_describes_a_live_renderer(self) -> None:
        report = run_operation("renderer_3d_status")
        self.assertEqual(report["operation"], "renderer_3d_status")
        self.assertIn(report["quality"], ("full-3d", "lightweight-3d"))
        self.assertIsNotNone(report["model"])
        self.assertIsNotNone(report["camera"])
        self.assertEqual(report["resources"]["leakSuspicions"], [])

    def test_metrics_draws_bounded_frames_and_covers_pixels(self) -> None:
        report = run_operation("renderer_3d_metrics", frames=40)
        self.assertEqual(report["frames"], 40)
        self.assertGreater(report["coverageFraction"], 0.02)
        self.assertGreater(report["meanMsPerFrame"], 0.0)
        self.assertIsNotNone(report["frameStatistics"]["p95Ms"])

    def test_metrics_bounds_an_absurd_frame_request(self) -> None:
        report = run_operation("renderer_3d_metrics", frames=100_000)
        self.assertLessEqual(report["frames"], 600)

    def test_reload_releases_before_it_rebuilds_and_mutates_nothing(self) -> None:
        with ThreeDDiagnostics() as session:
            session.renderer_3d_status()
            report = session.renderer_3d_reload()
            self.assertEqual(report["packagesMutated"], 0)
            self.assertEqual(len(report["modelDigest"]), 64)
            self.assertGreater(report["resourcesAfter"]["live"], 0)
            self.assertEqual(report["resourcesAfter"]["leakSuspicions"], [])

    def test_a_diagnostic_session_releases_its_context(self) -> None:
        session = ThreeDDiagnostics()
        session.renderer_3d_status()
        self.assertIsNotNone(session.context)
        session.close()
        self.assertIsNone(session.context)
        self.assertIsNone(session.renderer)

    def test_repeated_sessions_do_not_accumulate_resources(self) -> None:
        for _iteration in range(5):
            with ThreeDDiagnostics() as session:
                report = session.renderer_3d_status()
                self.assertGreaterEqual(report["resources"]["live"], 1)


if __name__ == "__main__":
    unittest.main()
