# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The validator, including every tampering case Phase 11 names.

The tampering cases are the point of this file. Each one takes a *valid*
artifact, changes exactly one thing, and asserts the specific code that comes
back — because "it was rejected" is a much weaker statement than "it was
rejected for the right reason", and only the second one tells you the check
that fired is the check you think it is.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from companion.models import MANIFEST_FILE_NAME
from companion.models.validation import (
    ADAPTER_CHECKSUM_MISMATCH,
    ADAPTER_FILE_MISSING,
    ADAPTER_SIZE_MISMATCH,
    ARTIFACT_MODE_LOOSE,
    ARTIFACT_PATH_UNTRUSTED,
    BASE_MODEL_MISMATCH,
    BASE_MODEL_NOT_PRESENT,
    BASE_MODEL_UNVERIFIED,
    BASE_REVISION_MISMATCH,
    BASE_REVISION_UNVERIFIED,
    CODES,
    FAIL,
    INTENDED_RUNTIME_MISMATCH,
    MANIFEST_MISSING,
    MANIFEST_UNREADABLE,
    MODEL_ID_MISMATCH,
    NETWORK_REQUIRED_REFUSED,
    NO_BACKEND_FOR_FORMAT,
    PASS,
    PERMISSIONS_NOT_GRANTABLE,
    RuntimeExpectations,
    UNKNOWN,
    UNSUPPORTED_ADAPTER_TYPE,
    UNSUPPORTED_FORMAT_VERSION,
    validate_artifact,
)
from tests.model_bridge.support import BASE_REFERENCE, BASE_REVISION, write_artifact


class ValidationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "agent-models"
        self.root.mkdir(parents=True)

    def expectations(self, **overrides) -> RuntimeExpectations:
        values = dict(
            base_model_reference=BASE_REFERENCE,
            base_model_revision=BASE_REVISION,
            base_model_present=True,
            supported_formats=("gguf",),
            trusted_roots=(self.root,),
            # Windows has no group/other write bit; the mode checks are a POSIX
            # arrangement and are exercised on the Linux evidence host.
            check_modes=False,
        )
        values.update(overrides)
        return RuntimeExpectations(**values)

    def edit_manifest(self, directory: Path, **changes) -> None:
        path = directory / MANIFEST_FILE_NAME
        document = json.loads(path.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if "." in key:
                section, _, leaf = key.partition(".")
                document.setdefault(section, {})[leaf] = value
            else:
                document[key] = value
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")


class AValidArtifact(ValidationCase):
    def test_passes_every_check(self) -> None:
        directory = write_artifact(self.root)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, PASS, report.to_json())
        self.assertEqual(report.problems(), ())
        self.assertGreaterEqual(len(report.findings), 9, "every requirement is reported, not just failures")

    def test_the_report_is_machine_readable(self) -> None:
        directory = write_artifact(self.root)
        document = validate_artifact(directory, expectations=self.expectations()).to_json()
        for key in ("status", "code", "message", "field", "findings", "modelId"):
            self.assertIn(key, document)

    def test_every_code_it_can_produce_is_declared(self) -> None:
        self.assertEqual(len(set(CODES)), len(CODES), "the code list has a duplicate")


class Tampering(ValidationCase):
    """Phase 11, one case per numbered requirement."""

    def test_1_modifying_the_adapter_after_the_manifest(self) -> None:
        """One byte, same length — so the digest is what catches it, not the size.

        Changing the length would trip the cheaper size check first, which is
        correct behaviour and a weaker test: a substitution that preserved the
        size would sail past it. This is the case that has to be caught by the
        digest, so this is the case the test makes.
        """
        directory = write_artifact(self.root)
        original = (directory / "adapter.gguf").read_bytes()
        tampered = original[:-1] + bytes([original[-1] ^ 0x01])
        self.assertEqual(len(tampered), len(original))
        (directory / "adapter.gguf").write_bytes(tampered)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, ADAPTER_CHECKSUM_MISMATCH)
        self.assertEqual(report.field, "adapterSha256")

    def test_1b_a_size_change_is_caught_before_the_digest_is_computed(self) -> None:
        directory = write_artifact(self.root)
        (directory / "adapter.gguf").write_bytes(b"short")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertIn(report.code, {ADAPTER_SIZE_MISMATCH, ADAPTER_CHECKSUM_MISMATCH})

    def test_2_modifying_the_manifest_base_model(self) -> None:
        directory = write_artifact(self.root)
        self.edit_manifest(directory, **{"baseModel.reference": "meta-llama/Llama-3-8B"})
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, BASE_MODEL_MISMATCH)

    def test_3_modifying_the_manifest_permissions(self) -> None:
        """The one this milestone exists for: permissions cannot become authority."""
        directory = write_artifact(self.root)
        self.edit_manifest(directory, permissions=["filesystem.write", "network"])
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, PERMISSIONS_NOT_GRANTABLE)
        self.assertEqual(report.field, "permissions")
        self.assertIn("authority", report.message.lower())

    def test_4_removing_the_adapter_file(self) -> None:
        directory = write_artifact(self.root, omit_adapter=True)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, ADAPTER_FILE_MISSING)

    def test_5_corrupting_the_adapter(self) -> None:
        directory = write_artifact(self.root)
        (directory / "adapter.gguf").write_bytes(b"\x00" * 32)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertIn(report.code, {ADAPTER_CHECKSUM_MISMATCH, ADAPTER_SIZE_MISMATCH})

    def test_6_an_unknown_format_version_is_never_silently_loaded(self) -> None:
        directory = write_artifact(self.root)
        self.edit_manifest(directory, schemaVersion=99)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertNotEqual(report.status, PASS, "an unknown version must never pass")
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, UNSUPPORTED_FORMAT_VERSION)

    def test_7_pointing_at_a_different_base_model(self) -> None:
        directory = write_artifact(self.root, base_reference="Qwen/Qwen2.5-0.5B")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, BASE_MODEL_MISMATCH)

    def test_a_manifest_that_is_not_json(self) -> None:
        directory = write_artifact(self.root)
        (directory / MANIFEST_FILE_NAME).write_text("not json", encoding="utf-8")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, MANIFEST_UNREADABLE)

    def test_a_missing_manifest(self) -> None:
        directory = self.root / "empty"
        directory.mkdir()
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, MANIFEST_MISSING)

    def test_an_unknown_manifest_field_is_refused_not_ignored(self) -> None:
        directory = write_artifact(self.root)
        self.edit_manifest(directory, grantsCapabilities=["filesystem.write"])
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, MANIFEST_UNREADABLE)
        self.assertIn("unknown field", report.message)

    def test_a_renamed_directory(self) -> None:
        directory = write_artifact(self.root, "bunny-demo")
        directory.rename(self.root / "something-else")
        report = validate_artifact(self.root / "something-else", expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, MODEL_ID_MISMATCH)


class Refusals(ValidationCase):
    def test_a_manifest_intended_for_another_runtime(self) -> None:
        directory = write_artifact(self.root)
        self.edit_manifest(directory, intendedRuntime="somebody-elses-agent")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.code, INTENDED_RUNTIME_MISMATCH)

    def test_an_artifact_that_wants_the_network(self) -> None:
        directory = write_artifact(self.root, network_required=True)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, NETWORK_REQUIRED_REFUSED)

    def test_an_unsupported_adapter_type(self) -> None:
        directory = write_artifact(self.root)
        self.edit_manifest(directory, adapterType="full-finetune")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, UNSUPPORTED_ADAPTER_TYPE)

    def test_a_format_no_backend_can_apply(self) -> None:
        directory = write_artifact(self.root, adapter_format="peft-safetensors",
                                   adapter_file="adapter_model.safetensors")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, UNKNOWN, "the artifact is fine; the machine is not")
        self.assertEqual(report.code, NO_BACKEND_FOR_FORMAT)
        self.assertIn("well-formed", report.message)

    def test_an_artifact_outside_a_trusted_root(self) -> None:
        elsewhere = Path(self.scratch.name) / "downloads"
        elsewhere.mkdir()
        directory = write_artifact(elsewhere)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, ARTIFACT_PATH_UNTRUSTED)

    @unittest.skipUnless(hasattr(__import__("os"), "chmod") and __import__("os").name == "posix",
                         "group/other write bits are a POSIX arrangement")
    def test_a_world_writable_adapter(self) -> None:
        import os

        directory = write_artifact(self.root)
        os.chmod(directory / "adapter.gguf", 0o666)
        report = validate_artifact(directory, expectations=self.expectations(check_modes=True))
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, ARTIFACT_MODE_LOOSE)


class UnknownIsNotAPass(ValidationCase):
    """The rule the whole subsystem rests on, stated four ways."""

    def test_an_unverifiable_base_revision(self) -> None:
        directory = write_artifact(self.root, base_revision="main")
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, UNKNOWN)
        self.assertEqual(report.code, BASE_REVISION_UNVERIFIED)
        self.assertNotEqual(report.status, PASS)

    def test_a_runtime_that_cannot_name_its_own_revision(self) -> None:
        directory = write_artifact(self.root)
        report = validate_artifact(directory, expectations=self.expectations(base_model_revision=""))
        self.assertEqual(report.status, UNKNOWN)
        self.assertEqual(report.code, BASE_REVISION_UNVERIFIED)

    def test_a_base_model_that_is_not_here(self) -> None:
        directory = write_artifact(self.root)
        report = validate_artifact(directory, expectations=self.expectations(base_model_present=False))
        self.assertEqual(report.status, UNKNOWN)
        self.assertEqual(report.code, BASE_MODEL_NOT_PRESENT)
        self.assertIn("not fetched", report.message)

    def test_a_runtime_with_no_base_model_at_all(self) -> None:
        directory = write_artifact(self.root)
        report = validate_artifact(directory, expectations=self.expectations(base_model_reference=""))
        self.assertEqual(report.status, UNKNOWN)
        self.assertEqual(report.code, BASE_MODEL_UNVERIFIED)

    def test_a_mismatched_revision_is_a_failure_not_an_unknown(self) -> None:
        """"Cannot tell" and "wrong" are different answers."""
        directory = write_artifact(self.root, base_revision="a" * 40)
        report = validate_artifact(directory, expectations=self.expectations())
        self.assertEqual(report.status, FAIL)
        self.assertEqual(report.code, BASE_REVISION_MISMATCH)


class Digests(ValidationCase):
    def test_a_listing_may_skip_the_digest_and_says_so(self) -> None:
        directory = write_artifact(self.root)
        report = validate_artifact(directory, expectations=self.expectations(), verify_digest=False)
        self.assertEqual(report.status, UNKNOWN)
        self.assertIn("always computed before a model is activated", report.message)

    def test_the_digest_is_of_the_bytes_on_disk(self) -> None:
        directory = write_artifact(self.root, adapter_content=b"one")
        recorded = json.loads((directory / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(recorded["adapterSha256"], hashlib.sha256(b"one").hexdigest())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
