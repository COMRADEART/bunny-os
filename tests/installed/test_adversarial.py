# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Stage-26 rejections that are exercisable without booting anything.

Each test refuses a specific fraud by name. The pattern throughout: a record
that *says* the right things but is *about* the wrong thing — the wrong
machine class, the wrong artifact, the wrong scenario set — must be rejected
by structure, not by a reviewer noticing.

The record-binding tests run against ``release.installed.verify_record_binding``;
the schema tests assert on the schema document itself so they run on machines
without the ``jsonschema`` package, and additionally run real validation when
the package is importable. Nothing here skips silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
import unittest

from release.hardware import HardwareCollectionError, parse_guided_test
from release.installed import InstalledContext, verify_record_binding

try:  # Optional: structural assertions below cover machines without it.
    import jsonschema  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - depends on the host environment
    jsonschema = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
RECORD_SCHEMA_PATH = (
    ROOT / "qualification/installed-system/schemas/installed-qualification-record.schema.json"
)

COMMIT = "80df25b09f6578276d18c8a82f15c47dd8959740"

#: The authority every record below is measured against. Constructed directly
#: rather than through resolve_context because binding is a pure function of
#: record and context; the resolver's own refusals live in test_context.py.
CONTEXT = InstalledContext(
    schemaVersion=1,
    sourceCommit=COMMIT,
    sourceArchiveDigest="1" * 64,
    installationArtifactDigest="2" * 64,
    recoveryArtifactDigest="3" * 64,
    installerToolchainDigest="4" * 64,
    scenarioVersion="scenarios-v1",
)


def record(**overrides: object) -> dict[str, object]:
    """A record that binds cleanly, so each test tampers with exactly one thing."""
    document: dict[str, object] = {
        "evidenceId": "ISQ-20260801-blank-disk-001",
        "sourceCommit": COMMIT,
        "sourceArchiveDigest": "1" * 64,
        "installationArtifactDigest": "2" * 64,
        "recoveryArtifactDigest": "3" * 64,
        "scenarioVersion": "scenarios-v1",
        "environment": "qemu-kvm",
    }
    document.update(overrides)
    return document


class RecordBinding(unittest.TestCase):
    def test_a_faithful_record_binds_with_no_reasons(self) -> None:
        # The baseline: every refusal below must come from the one field the
        # test tampers with, not from a fixture that never bound at all.
        self.assertEqual(verify_record_binding(record(), CONTEXT), [])

    def test_vm_evidence_labelled_physical_is_refused(self) -> None:
        # The fraud: run the scenario in qemu, write environment=physical,
        # and claim a hardware qualification nobody performed. Without a
        # named hardware record the claim is indistinguishable from exactly
        # that relabelling, so it is refused.
        reasons = verify_record_binding(
            record(environment="physical"), CONTEXT
        )
        self.assertTrue(
            any("device identity" in reason for reason in reasons), reasons
        )

    def test_a_wrong_archive_digest_does_not_transfer(self) -> None:
        # The fraud: reuse a passing record from an earlier archive against a
        # newer one. Evidence does not transfer between authorities.
        reasons = verify_record_binding(
            record(sourceArchiveDigest="f" * 64), CONTEXT
        )
        self.assertTrue(
            any("does not transfer" in reason for reason in reasons), reasons
        )

    def test_an_older_installer_artifact_is_refused(self) -> None:
        # The fraud: the installer ISO was rebuilt, but the record still
        # describes the previous one. A boot of the old installer says
        # nothing about the new one.
        reasons = verify_record_binding(
            record(installationArtifactDigest="e" * 64), CONTEXT
        )
        self.assertTrue(
            any("installationArtifactDigest" in reason for reason in reasons), reasons
        )

    def test_scenario_version_drift_is_a_new_context(self) -> None:
        # The fraud: the scenario definitions changed — different markers,
        # different expected outcome — and old evidence quietly continues to
        # count. A scenario change is a new context.
        reasons = verify_record_binding(
            record(scenarioVersion="scenarios-v0"), CONTEXT
        )
        self.assertTrue(
            any("new context" in reason for reason in reasons), reasons
        )

    def test_a_malformed_evidence_id_is_refused(self) -> None:
        # The fraud is subtler here: a hand-minted identifier that no index
        # can resolve makes evidence unfindable, and unfindable evidence
        # cannot be challenged.
        reasons = verify_record_binding(
            record(evidenceId="ISQ-blank-disk-1"), CONTEXT
        )
        self.assertTrue(
            any("ISQ-YYYYMMDD" in reason for reason in reasons), reasons
        )

    def test_an_unknown_environment_is_refused(self) -> None:
        # The fraud: a third environment kind ('container', 'wsl', ...) that
        # no gate has rules for, slipped in to dodge both the VM and the
        # physical requirements at once.
        reasons = verify_record_binding(record(environment="container"), CONTEXT)
        self.assertTrue(
            any("not qemu-kvm or physical" in reason for reason in reasons), reasons
        )


def _load_record_schema() -> dict[str, Any]:
    return json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))


def _conditional_branch(schema: Mapping[str, Any], prop: str, const: str) -> Mapping[str, Any]:
    """The allOf branch whose if-condition pins ``prop`` to ``const``."""
    for branch in schema.get("allOf", []):
        condition = branch.get("if", {}).get("properties", {}).get(prop, {})
        if condition.get("const") == const:
            return branch
    raise AssertionError(f"schema has no if/then branch on {prop} == {const!r}")


def schema_instance(**overrides: object) -> dict[str, object]:
    """An instance the record schema accepts, for tamper-one-field tests."""
    document: dict[str, object] = {
        "schemaVersion": 1,
        "evidenceId": "ISQ-20260801-blank-disk-001",
        "sourceCommit": COMMIT,
        "sourceArchiveDigest": "1" * 64,
        "installationArtifactDigest": "2" * 64,
        "environment": "qemu-kvm",
        "firmwareMode": "uefi",
        "secureBootState": "not-tested",
        "tpmState": "swtpm",
        "encryptionState": "luks2-passphrase",
        "scenario": "blank-disk",
        "scenarioVersion": "scenarios-v1",
        "startedAt": "2026-08-01T10:00:00Z",
        "completedAt": "2026-08-01T10:20:00Z",
        "result": "PASS",
        "assertions": [
            {
                "name": "root-filesystem-mounted",
                "expected": "/dev/mapper/luks-root mounted on /",
                "observed": "/dev/mapper/luks-root mounted on /",
                "result": "PASS",
            }
        ],
        "evidenceFiles": [
            {
                "path": "evidence/console.log",
                "sha256": "5" * 64,
                "createdAt": "2026-08-01T10:19:00Z",
                "collectionCommand": "virsh console --logfile",
                "redactionStatus": "verified-clean",
                "retentionClass": "evidence",
            }
        ],
        "operator": "operator-1",
        "limitations": [],
    }
    document.update(overrides)
    return document


def _validator() -> Any:
    """A draft 2020-12 validator when the environment can provide one.

    Returns None otherwise. The callers below always run the structural
    assertions first, so a missing package weakens nothing — it only drops
    the second, redundant layer of checking.
    """
    if jsonschema is None:
        return None
    cls = getattr(jsonschema, "Draft202012Validator", None)
    if cls is None:  # a jsonschema too old for draft 2020-12
        return None
    return cls(_load_record_schema())


class SchemaEncodesTheRefusals(unittest.TestCase):
    """The record schema must refuse structurally, not by convention.

    These tests assert on the parsed schema document itself so they run on
    every machine; when jsonschema is importable they additionally prove the
    encoded constraints actually reject the fraudulent instances.
    """

    def test_physical_without_a_hardware_record_violates_the_schema(self) -> None:
        # The same 'VM evidence labelled physical' fraud as above, refused a
        # second time at the schema layer so a validator-only consumer is
        # protected too.
        schema = _load_record_schema()
        branch = _conditional_branch(schema, "environment", "physical")
        self.assertIn("hardwareRecord", branch["then"]["required"])
        # The if must pin the property as *present and physical*; without
        # 'required' the condition would vacuously match records with no
        # environment at all.
        self.assertIn("environment", branch["if"]["required"])

        validator = _validator()
        if validator is not None:
            physical = schema_instance(environment="physical")
            self.assertTrue(list(validator.iter_errors(physical)), "schema accepted a physical record with no hardwareRecord")
            physical["hardwareRecord"] = "HWQ-2026-001"
            self.assertEqual(list(validator.iter_errors(physical)), [])

    def test_a_pass_with_no_assertions_is_screenshot_only_evidence(self) -> None:
        # The fraud: 'it looked fine'. A PASS carrying zero measured
        # assertions is a screenshot with a caption, and the schema itself
        # must refuse it.
        schema = _load_record_schema()
        branch = _conditional_branch(schema, "result", "PASS")
        self.assertGreaterEqual(branch["then"]["properties"]["assertions"]["minItems"], 1)
        self.assertIn("result", branch["if"]["required"])

        validator = _validator()
        if validator is not None:
            empty_pass = schema_instance(assertions=[])
            self.assertTrue(list(validator.iter_errors(empty_pass)), "schema accepted a PASS with no assertions")
            # A FAIL with no assertions is legitimate — the scenario may have
            # died before anything could be measured.
            failed = schema_instance(result="FAIL", assertions=[])
            self.assertEqual(list(validator.iter_errors(failed)), [])

    def test_a_valid_record_is_accepted(self) -> None:
        # Guard against a schema so strict nothing satisfies it: a schema
        # that rejects everything also 'passes' every refusal test above.
        validator = _validator()
        if validator is None:
            # Structural stand-in: the happy-path fixture at least carries
            # every field the schema names as required.
            schema = _load_record_schema()
            instance = schema_instance()
            for name in schema["required"]:
                self.assertIn(name, instance)
            return
        self.assertEqual(list(validator.iter_errors(schema_instance())), [])

    def test_the_schema_rejects_unknown_top_level_fields(self) -> None:
        schema = _load_record_schema()
        self.assertIs(schema["additionalProperties"], False)
        validator = _validator()
        if validator is not None:
            smuggled = schema_instance(certification="totally certified")
            self.assertTrue(list(validator.iter_errors(smuggled)))

    def test_the_schema_documents_the_environment_and_tpm_boundaries(self) -> None:
        # The two $comments are load-bearing documentation: they state which
        # substitutions can never satisfy which requirements. Losing them in
        # an edit would silently orphan the rule they explain.
        schema = _load_record_schema()
        tpm_comment = schema["properties"]["tpmState"]["$comment"]
        self.assertIn("swtpm", tpm_comment)
        self.assertIn("physical", tpm_comment)
        environment_comment = schema["properties"]["environment"]["$comment"]
        self.assertIn("physical prerequisite", environment_comment)


class NotRunConversion(unittest.TestCase):
    """Invariant chosen: release/hardware.py's parse_guided_test refusal.

    Chosen over release/matrix.py because parse_guided_test refuses the
    NOT_RUN-carrying-a-result conversion *directly* — the exact Stage-26
    fraud — with a one-dict fixture, whereas matrix.py's nearest refusal
    (a PASS without evidence) is a different invariant.
    """

    def test_not_run_carrying_an_actual_result_is_refused(self) -> None:
        # The fraud: a test recorded NOT_RUN quietly acquires an
        # actualResult, one edit away from becoming a PASS. A test that
        # produced a result was run; the record is lying about one of the
        # two, and either lie is disqualifying.
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_guided_test(
                {
                    "test": "boot",
                    "outcome": "NOT_RUN",
                    "actualResult": "booted to the greeter in 14s",
                }
            )
        self.assertIn("never be converted to PASS", str(raised.exception))

    def test_not_run_carrying_an_evidence_reference_is_refused(self) -> None:
        # Same conversion, other half: evidence attached to a test that
        # claims it never ran is evidence of the run it denies.
        with self.assertRaises(HardwareCollectionError) as raised:
            parse_guided_test(
                {
                    "test": "boot",
                    "outcome": "NOT_RUN",
                    "evidenceReference": "boot/console.log",
                }
            )
        self.assertIn("NOT_RUN", str(raised.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
