# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 7: a model cannot acquire authority, by any of the routes it might try.

There are exactly three surfaces through which a model could plausibly try to
grant itself something, and each gets its own class here:

* the **artifact** it shipped in — a manifest field claiming permissions;
* the **proposal** it emits — a key claiming approval, capability or trust;
* the **type** that carries an admitted proposal onward — a field somebody
  downstream might read.

The third is the one that cannot be fixed later. The first two are checks, and
a check can be removed; :class:`~companion.models.proposal.AdmittedProposal`
having no authority field is a property of the shape, and a caller that wanted
to read ``proposal.approved`` would not run at all.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import tempfile
import unittest

from companion.models.proposal import (
    AUTHORITY_CLAIMED,
    AUTHORITY_KEYS,
    AdmittedProposal,
    MALFORMED_PROPOSAL,
    UNKNOWN_OPERATION,
    admit_proposal,
)
from companion.models.validation import (
    FAIL,
    PERMISSIONS_NOT_GRANTABLE,
    RuntimeExpectations,
    validate_artifact,
)
from tests.model_bridge.support import BASE_REFERENCE, BASE_REVISION, write_artifact


class TheArtifactCannotGrant(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def _expectations(self) -> RuntimeExpectations:
        return RuntimeExpectations(
            base_model_reference=BASE_REFERENCE, base_model_revision=BASE_REVISION,
            base_model_present=True, supported_formats=("gguf",),
            trusted_roots=(self.root,), check_modes=False,
        )

    def test_a_manifest_claiming_permissions_is_refused(self) -> None:
        for claim in (
            ["filesystem.write"],
            ["network"],
            ["files", "camera", "microphone"],
            ["*"],
        ):
            with self.subTest(claim=claim):
                directory = write_artifact(self.root, "claimer", permissions=claim)
                report = validate_artifact(directory, expectations=self._expectations())
                self.assertEqual(report.status, FAIL)
                self.assertEqual(report.code, PERMISSIONS_NOT_GRANTABLE)

    def test_the_refusal_names_authority_so_a_reader_knows_why(self) -> None:
        directory = write_artifact(self.root, "claimer", permissions=["filesystem.write"])
        report = validate_artifact(directory, expectations=self._expectations())
        self.assertIn("authority", report.message.lower())
        self.assertIn("person", report.message.lower())

    def test_an_empty_permissions_array_is_what_a_real_artifact_has(self) -> None:
        directory = write_artifact(self.root, "honest", permissions=[])
        report = validate_artifact(directory, expectations=self._expectations())
        self.assertEqual(report.status, "PASS", report.to_json())


class TheProposalCannotGrant(unittest.TestCase):
    """Every shape of "I am allowed" a model might emit."""

    def test_the_briefs_own_example_is_refused(self) -> None:
        result = admit_proposal({"action": "delete_file", "path": "/important/file"})
        self.assertFalse(result.admitted)
        self.assertEqual(result.code, UNKNOWN_OPERATION)
        self.assertIn("closed table", result.message)

    def test_each_authority_claim_named_in_the_brief(self) -> None:
        for claim in (
            {"permission": True},
            {"trusted": True},
            {"approved": True},
            {"capability": "filesystem.write"},
        ):
            with self.subTest(claim=claim):
                result = admit_proposal({"operation": "image.resize", "width": 512, **claim})
                self.assertFalse(result.admitted)
                self.assertEqual(result.code, AUTHORITY_CLAIMED)

    def test_evasion_by_spelling(self) -> None:
        """Matching is on the normalised key, so separators and case do not help."""
        for key in ("is_approved", "isApproved", "IS-APPROVED", "skip_approval",
                    "preApproved", "auto_approve", "no_prompt", "run_as", "as_root"):
            with self.subTest(key=key):
                result = admit_proposal({"operation": "image.resize", "width": 512, key: True})
                self.assertFalse(result.admitted, f"{key} was admitted")
                self.assertEqual(result.code, AUTHORITY_CLAIMED)

    def test_evasion_by_nesting(self) -> None:
        result = admit_proposal({
            "operation": "image.resize",
            "parameters": {"width": 512, "context": {"security": {"approved": True}}},
        })
        self.assertFalse(result.admitted)
        self.assertEqual(result.code, AUTHORITY_CLAIMED)

    def test_the_refusal_is_loud_not_a_silent_strip(self) -> None:
        """A stripped key is a model quietly learning that the field is ignored."""
        result = admit_proposal({"operation": "image.resize", "width": 512, "approved": True})
        self.assertFalse(result.admitted)
        self.assertEqual(result.keys, ("approved",))
        self.assertIn("approved", result.message)

    def test_a_clean_proposal_is_admitted_and_validated(self) -> None:
        result = admit_proposal({"operation": "image.resize", "parameters": {"width": 512}})
        self.assertTrue(result.admitted)
        self.assertEqual(result.operation_id, "image.resize")
        self.assertEqual(dict(result.parameters), {"width": 512})

    def test_an_operation_outside_the_table_cannot_be_added(self) -> None:
        for operation in ("shell.run", "file.delete", "system.exec", "image.resize.force"):
            with self.subTest(operation=operation):
                result = admit_proposal({"operation": operation, "width": 512})
                self.assertFalse(result.admitted)
                self.assertEqual(result.code, UNKNOWN_OPERATION)

    def test_parameters_outside_the_declared_set_are_refused(self) -> None:
        result = admit_proposal({"operation": "image.resize",
                                 "parameters": {"width": 512, "output": "/etc/passwd"}})
        self.assertFalse(result.admitted)

    def test_a_proposal_that_is_not_an_object(self) -> None:
        for raw in ("image.resize", ["image.resize"], 7, None):
            with self.subTest(raw=raw):
                result = admit_proposal(raw)
                self.assertFalse(result.admitted)
                self.assertEqual(result.code, MALFORMED_PROPOSAL)


class TheTypeCannotCarryAuthority(unittest.TestCase):
    """The property that cannot be removed by deleting a check."""

    def test_the_admitted_type_has_no_authority_field(self) -> None:
        fields = {field.name for field in dataclasses.fields(AdmittedProposal)}
        self.assertEqual(fields, {"operation_id", "parameters", "source"})
        normalised = {"".join(c for c in name.lower() if c.isalnum()) for name in fields}
        self.assertEqual(normalised & AUTHORITY_KEYS, set(),
                         "the admitted proposal type must not have a field that could "
                         "be read as authority")

    def test_it_is_frozen_so_authority_cannot_be_attached_afterwards(self) -> None:
        proposal = AdmittedProposal(operation_id="image.resize", parameters={"width": 512})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            proposal.operation_id = "shell.run"  # type: ignore[misc]

    def test_its_json_form_carries_no_authority_either(self) -> None:
        document = AdmittedProposal(operation_id="image.resize", parameters={"width": 512}).to_json()
        normalised = {"".join(c for c in key.lower() if c.isalnum()) for key in document}
        self.assertEqual(normalised & AUTHORITY_KEYS, set())

    def test_the_authority_vocabulary_covers_the_words_the_brief_names(self) -> None:
        for word in ("permission", "trusted", "approved", "capability"):
            self.assertIn(word, AUTHORITY_KEYS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
