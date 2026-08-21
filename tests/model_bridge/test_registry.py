# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Discovery, enablement, fallback and rollback — Phases 4, 6 and 14.

The theme is that every failure has the same destination. A checksum mismatch, a
missing backend, an artifact that vanished, a backend that accepts a request and
does nothing: all of them end with no adapter in effect, a code, and a sentence.
None of them ends with a crash, and none of them ends with a partially validated
adapter in use.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.models import MANIFEST_FILE_NAME
from companion.models.errors import UnknownModel
from companion.models.inference import NullAdapterBackend
from companion.models.registry import ModelRegistry
from companion.models.validation import FAIL, PASS, RuntimeExpectations, UNKNOWN
from tests.model_bridge.support import BASE_REFERENCE, BASE_REVISION, FakeBackend, write_artifact


class RegistryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.root = self.base / "agent-models"
        self.root.mkdir(parents=True)
        self.state = self.base / "state"
        self.backend = FakeBackend()

    def registry(self, **overrides) -> ModelRegistry:
        expectations = RuntimeExpectations(
            base_model_reference=overrides.pop("base_reference", BASE_REFERENCE),
            base_model_revision=overrides.pop("base_revision", BASE_REVISION),
            base_model_present=overrides.pop("base_present", True),
            trusted_roots=(self.root,),
            check_modes=False,
        )
        return ModelRegistry(
            roots=[self.root], state_root=self.state,
            backend=overrides.pop("backend", self.backend),
            expectations=expectations, **overrides,
        )


class Discovery(RegistryCase):
    def test_an_empty_machine_is_not_an_error(self) -> None:
        self.assertEqual(self.registry().discover(), ())

    def test_a_missing_root_is_not_an_error(self) -> None:
        registry = ModelRegistry(roots=[self.base / "nowhere"], state_root=self.state)
        self.assertEqual(registry.discover(), ())

    def test_it_finds_and_validates_each_artifact(self) -> None:
        write_artifact(self.root, "alpha")
        write_artifact(self.root, "beta")
        models = self.registry().discover()
        self.assertEqual([model.model_id for model in models], ["alpha", "beta"])
        self.assertTrue(all(model.valid for model in models))

    def test_a_directory_without_a_manifest_is_not_a_model(self) -> None:
        (self.root / "just-some-folder").mkdir()
        self.assertEqual(self.registry().discover(), ())

    def test_one_bad_artifact_does_not_hide_the_good_ones(self) -> None:
        """The deliberate difference from the curated catalogue."""
        write_artifact(self.root, "good")
        write_artifact(self.root, "bad", corrupt_digest=True)
        models = {model.model_id: model for model in self.registry().discover()}
        self.assertEqual(sorted(models), ["bad", "good"])
        self.assertTrue(models["good"].valid)
        self.assertEqual(models["bad"].status, FAIL)

    def test_get_refuses_a_model_it_never_saw(self) -> None:
        with self.assertRaises(UnknownModel):
            self.registry().get("never-installed")


class Enabling(RegistryCase):
    def test_a_valid_model_becomes_active(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        decision = registry.enable("demo")
        self.assertTrue(decision.using_adapter)
        self.assertEqual(decision.model_id, "demo")
        self.assertEqual(self.backend.applied, ["demo"])

    def test_enablement_survives_a_new_registry(self) -> None:
        write_artifact(self.root, "demo")
        first = self.registry()
        first.discover()
        first.enable("demo")

        second = self.registry()
        models = {model.model_id: model for model in second.discover()}
        self.assertTrue(models["demo"].enabled, "an intent must survive a restart")
        self.assertEqual(second.enabled_model_id(), "demo")

    def test_an_invalid_model_is_not_activated(self) -> None:
        write_artifact(self.root, "demo", corrupt_digest=True)
        registry = self.registry()
        registry.discover()
        decision = registry.enable("demo")
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "ADAPTER_CHECKSUM_MISMATCH")
        self.assertEqual(self.backend.applied, [], "a failing artifact must not reach the backend")

    def test_an_unknown_status_is_not_activated_either(self) -> None:
        write_artifact(self.root, "demo", base_revision="main")
        registry = self.registry()
        registry.discover()
        decision = registry.enable("demo")
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "BASE_REVISION_UNVERIFIED")
        self.assertEqual(self.backend.applied, [])

    def test_enabling_revalidates_rather_than_trusting_the_listing(self) -> None:
        """A model is not enabled on the strength of a list drawn a minute ago."""
        directory = write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        original = (directory / "adapter.gguf").read_bytes()
        (directory / "adapter.gguf").write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        decision = registry.enable("demo")
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "ADAPTER_CHECKSUM_MISMATCH")

    def test_a_backend_that_accepts_and_does_nothing_is_not_success(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry(backend=FakeBackend(lies_about_state=True))
        registry.discover()
        decision = registry.enable("demo")
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "VERIFY_FAILED")

    def test_a_backend_that_never_saw_the_adapter(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry(backend=FakeBackend(knows_adapter=False))
        registry.discover()
        decision = registry.enable("demo")
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "ADAPTER_NOT_PRELOADED")


class Fallback(RegistryCase):
    def test_no_model_enabled_is_the_ordinary_state(self) -> None:
        decision = self.registry().active()
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "NO_MODEL_ENABLED")

    def test_a_vanished_artifact_falls_back_with_a_reason(self) -> None:
        directory = write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")

        for item in directory.iterdir():
            item.unlink()
        directory.rmdir()
        after = self.registry()
        decision = after.active()
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "MODEL_NOT_FOUND")
        self.assertEqual(decision.requested_model_id, "demo")

    def test_a_tampered_artifact_falls_back_rather_than_being_used(self) -> None:
        directory = write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")

        original = (directory / "adapter.gguf").read_bytes()
        (directory / "adapter.gguf").write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        decision = self.registry().active()
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "ADAPTER_CHECKSUM_MISMATCH")

    def test_a_backend_that_went_away_falls_back(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")
        gone = self.registry(backend=FakeBackend(available=False))
        decision = gone.active()
        self.assertFalse(decision.using_adapter)
        # The backend reporting no formats is caught by validation before the
        # apply is attempted, which is the earlier and more informative refusal.
        self.assertIn(decision.code, {"BACKEND_UNAVAILABLE", "NO_BACKEND_FOR_FORMAT"})

    def test_no_backend_at_all_lists_but_activates_nothing(self) -> None:
        """A Bunny image as it ships: artifacts are listed, none can be used."""
        write_artifact(self.root, "demo")
        registry = self.registry(backend=NullAdapterBackend())
        models = registry.discover()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].status, UNKNOWN,
                         "a machine that cannot apply the format has not found a bad "
                         "artifact; it has found one it cannot use")
        self.assertEqual(models[0].report.code, "NO_BACKEND_FOR_FORMAT")
        self.assertFalse(registry.enable("demo").using_adapter)


class DisableAndRollback(RegistryCase):
    def test_disable_falls_back_and_keeps_the_artifact(self) -> None:
        directory = write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")

        decision = registry.disable("demo")
        self.assertFalse(decision.using_adapter)
        self.assertEqual(decision.code, "DISABLED")
        self.assertTrue((directory / "adapter.gguf").is_file(), "disable must not delete")
        self.assertTrue((directory / MANIFEST_FILE_NAME).is_file())
        self.assertEqual(self.backend.released, ["demo"])

    def test_disable_is_remembered(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")
        registry.disable("demo")
        self.assertEqual(self.registry().active().code, "NO_MODEL_ENABLED")

    def test_the_previous_model_is_remembered_for_rollback(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")
        registry.disable("demo")
        self.assertEqual(registry.previous_model_id(), "demo")

    def test_re_enabling_after_a_disable_works(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        registry.enable("demo")
        registry.disable("demo")
        again = self.registry()
        again.discover()
        self.assertTrue(again.enable("demo").using_adapter)


class Provenance(RegistryCase):
    def test_it_exposes_what_phase_12_asks_for(self) -> None:
        write_artifact(self.root, "demo")
        registry = self.registry()
        registry.discover()
        record = registry.provenance("demo")
        for key in ("modelId", "baseModel", "baseRevision", "adapterSha256",
                    "trainingSource", "bunnyCommit", "artifactVersion", "validationStatus"):
            self.assertIn(key, record)
        self.assertEqual(record["baseModel"], BASE_REFERENCE)
        self.assertEqual(record["validationStatus"], PASS)
        self.assertEqual(record["trainingSource"], "bunny-model-studio")

    def test_provenance_is_available_even_for_a_broken_artifact(self) -> None:
        directory = write_artifact(self.root, "demo")
        (directory / MANIFEST_FILE_NAME).write_text("{", encoding="utf-8")
        registry = self.registry()
        registry.discover()
        record = registry.provenance("demo")
        self.assertFalse(record["available"])
        self.assertEqual(record["validationStatus"], FAIL)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
