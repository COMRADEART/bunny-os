# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline by default, and no upload path at all."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from model_studio.errors import NetworkRefused
from model_studio.models import resolve_base_model
from model_studio.network import OFFLINE, NetworkPolicy, applied, refuse_upload
from tests.model_studio.support import write_model_config


class Defaults(unittest.TestCase):
    def test_the_default_policy_downloads_nothing(self) -> None:
        self.assertFalse(OFFLINE.allow_model_download)
        with self.assertRaises(NetworkRefused):
            OFFLINE.require_download("a base model")

    def test_the_offline_environment_is_set(self) -> None:
        environment = OFFLINE.environment()
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "1")

    def test_telemetry_is_off_even_when_a_download_is_approved(self) -> None:
        approved = NetworkPolicy(allow_model_download=True, reason="a test")
        environment = approved.environment()
        self.assertNotIn("HF_HUB_OFFLINE", environment)
        for key in ("HF_HUB_DISABLE_TELEMETRY", "DISABLE_TELEMETRY", "DO_NOT_TRACK"):
            self.assertEqual(environment[key], "1", f"{key} must never be lifted")

    def test_the_policy_reports_that_upload_is_impossible(self) -> None:
        self.assertIs(NetworkPolicy(allow_model_download=True).to_json()["allowUpload"], False)


class Applied(unittest.TestCase):
    def test_it_sets_and_restores(self) -> None:
        environment = {"HF_HUB_OFFLINE": "0", "UNRELATED": "keep"}
        with applied(OFFLINE, environment):
            self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
            self.assertEqual(environment["DO_NOT_TRACK"], "1")
        self.assertEqual(environment["HF_HUB_OFFLINE"], "0")
        self.assertNotIn("DO_NOT_TRACK", environment, "a variable it added must be removed")
        self.assertEqual(environment["UNRELATED"], "keep")

    def test_it_restores_after_an_exception(self) -> None:
        environment: dict[str, str] = {}
        with self.assertRaises(ValueError):
            with applied(OFFLINE, environment):
                raise ValueError("boom")
        self.assertEqual(environment, {})

    def test_the_real_process_environment_is_left_as_found(self) -> None:
        before = dict(os.environ)
        with applied(OFFLINE):
            pass
        self.assertEqual(dict(os.environ), before)


class Uploads(unittest.TestCase):
    def test_there_is_no_upload(self) -> None:
        with self.assertRaises(NetworkRefused) as caught:
            refuse_upload("huggingface.co/someone/model")
        self.assertIn("does not publish adapters", str(caught.exception))


class Resolution(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def test_a_local_directory_is_used_directly(self) -> None:
        write_model_config(self.root / "model")
        resolved = resolve_base_model(str(self.root / "model"))
        self.assertEqual(resolved.state, "local")
        self.assertTrue(resolved.present)
        self.assertIsNotNone(resolved.architecture)

    def test_an_absent_model_is_reported_not_fetched(self) -> None:
        os.environ["HF_HUB_CACHE"] = str(self.root / "empty-cache")
        self.addCleanup(os.environ.pop, "HF_HUB_CACHE", None)
        resolved = resolve_base_model("HuggingFaceTB/SmolLM2-135M-Instruct")
        self.assertEqual(resolved.state, "absent")
        self.assertFalse(resolved.present)
        self.assertIn("not in the local hub cache", resolved.detail)

    def test_a_download_without_approval_raises(self) -> None:
        os.environ["HF_HUB_CACHE"] = str(self.root / "empty-cache")
        self.addCleanup(os.environ.pop, "HF_HUB_CACHE", None)
        with self.assertRaises(NetworkRefused):
            resolve_base_model(
                "HuggingFaceTB/SmolLM2-135M-Instruct", policy=OFFLINE, download=True
            )

    def test_a_cached_snapshot_is_found_through_its_ref(self) -> None:
        cache = self.root / "cache"
        folder = cache / "models--org--name"
        (folder / "refs").mkdir(parents=True)
        (folder / "refs" / "main").write_text("a" * 40, encoding="utf-8")
        write_model_config(folder / "snapshots" / ("a" * 40))
        os.environ["HF_HUB_CACHE"] = str(cache)
        self.addCleanup(os.environ.pop, "HF_HUB_CACHE", None)

        resolved = resolve_base_model("org/name", revision="main")
        self.assertEqual(resolved.state, "cached")
        self.assertEqual(resolved.resolved_revision, "a" * 40,
                         "provenance needs the commit 'main' meant, not the word 'main'")

    def test_a_nonsense_reference_is_refused_before_any_lookup(self) -> None:
        resolved = resolve_base_model("not a model")
        self.assertEqual(resolved.state, "absent")
        self.assertIn("repository identifier", resolved.detail)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
