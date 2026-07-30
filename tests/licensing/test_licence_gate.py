"""Licence decision and gate.

One of the fourteen mandated adversarial cases lives here: an unsigned licence
approval. An approval carrying neither a signature nor an attestation reference
is an assumption wearing a decision's clothes, and assuming a licence is exactly
what this gate exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from release.licensing import (
    LICENCE_MODELS,
    PROJECT_SPDX,
    SPLIT_LAYOUT,
    LicenceError,
    evaluate_licence_gate,
    parse_decision,
    scan_spdx_headers,
)

ROOT = Path(__file__).resolve().parents[2]


def decision(**overrides):
    base = {
        "model": "gpl-os-apache-clients-split",
        "decidedBy": "Project owner",
        "decidedAt": "2026-07-29T00:00:00Z",
        "rationale": "matches the trust boundary",
        "layout": dict(SPLIT_LAYOUT),
        "attestationReference": "docs/LICENCE_DECISION.md#owner-decision",
    }
    base.update(overrides)
    return base


class DecisionTests(unittest.TestCase):
    def test_undecided_is_a_valid_state(self):
        parsed = parse_decision({"model": "undecided", "layout": {}})
        self.assertFalse(parsed.decided)

    def test_unknown_model_is_refused(self):
        with self.assertRaises(LicenceError):
            parse_decision(decision(model="mit-because-it-is-short"))

    def test_every_documented_model_is_accepted(self):
        for model in LICENCE_MODELS:
            payload = decision(model=model)
            if model == "undecided":
                payload = {"model": model, "layout": {}}
            parse_decision(payload)

    def test_layout_may_only_use_project_licences(self):
        with self.assertRaises(LicenceError) as caught:
            parse_decision(decision(layout={"services": "MIT"}))
        self.assertIn("not one of", str(caught.exception))
        self.assertEqual(PROJECT_SPDX, ("GPL-3.0-or-later", "Apache-2.0"))

    # --- adversarial: unsigned licence approval ---
    def test_decision_without_signature_or_attestation_is_refused(self):
        payload = decision()
        del payload["attestationReference"]
        with self.assertRaises(LicenceError) as caught:
            parse_decision(payload)
        self.assertIn("signature or an attestation reference", str(caught.exception))

    def test_decision_with_a_null_attestation_is_refused(self):
        with self.assertRaises(LicenceError):
            parse_decision(decision(attestationReference=None, signature=None))

    def test_decision_with_an_incomplete_signature_is_refused(self):
        with self.assertRaises(LicenceError) as caught:
            parse_decision(decision(signature={"keyId": "owner-1", "algorithm": "ed25519"}))
        self.assertIn("signature missing value", str(caught.exception))

    def test_decision_with_a_complete_signature_is_accepted(self):
        payload = decision(signature={"keyId": "owner-1", "algorithm": "ed25519", "value": "AAAA"})
        del payload["attestationReference"]
        parsed = parse_decision(payload)
        self.assertTrue(parsed.attributed)

    def test_decided_record_requires_a_decider(self):
        payload = decision()
        del payload["decidedBy"]
        with self.assertRaises(LicenceError):
            parse_decision(payload)


class GateTests(unittest.TestCase):
    def test_undecided_licence_blocks_the_gate(self):
        parsed = parse_decision({"model": "undecided", "layout": {}})
        with tempfile.TemporaryDirectory() as raw:
            result = evaluate_licence_gate(parsed, root=Path(raw), licenceScanResult="PASS")
        self.assertFalse(result.passed)
        self.assertTrue(any("owner-decision" in name for name in result.unmet))

    def test_missing_root_licence_blocks_the_gate(self):
        parsed = parse_decision(decision())
        with tempfile.TemporaryDirectory() as raw:
            result = evaluate_licence_gate(parsed, root=Path(raw), licenceScanResult="PASS")
        self.assertFalse(result.passed)
        self.assertTrue(any("root-licence" in name for name in result.unmet))

    def test_missing_licence_scan_blocks_the_gate(self):
        parsed = parse_decision(decision())
        result = evaluate_licence_gate(parsed, root=ROOT, licenceScanResult=None)
        self.assertFalse(result.passed)
        self.assertTrue(any("licence-scan" in name for name in result.unmet))

    def test_failing_licence_scan_blocks_the_gate(self):
        parsed = parse_decision(decision())
        result = evaluate_licence_gate(parsed, root=ROOT, licenceScanResult="FAIL")
        self.assertFalse(result.passed)

    def test_repository_satisfies_the_gate_as_configured(self):
        """The real record and the real tree, together, must pass."""
        record = json.loads((ROOT / "operations/data/licence-decision.json").read_text(encoding="utf-8"))
        parsed = parse_decision(record)
        result = evaluate_licence_gate(parsed, root=ROOT, licenceScanResult=record.get("licenceScanResult"))
        self.assertTrue(result.passed, f"unmet: {result.unmet}")


class RepositoryLayoutTests(unittest.TestCase):
    def test_root_licence_exists_and_names_both_licences(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("GPL-3.0-or-later", text)
        self.assertIn("Apache-2.0", text)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)

    def test_full_licence_texts_are_present(self):
        gpl = (ROOT / "LICENSES/GPL-3.0-or-later.txt").read_text(encoding="utf-8")
        apache = (ROOT / "LICENSES/Apache-2.0.txt").read_text(encoding="utf-8")
        self.assertIn("Version 3, 29 June 2007", gpl)
        self.assertIn("Version 2.0, January 2004", apache)
        self.assertIn("APPENDIX: How to apply the Apache License", apache)

    def test_every_split_directory_has_a_licence_file(self):
        for directory in SPLIT_LAYOUT:
            self.assertTrue((ROOT / directory / "LICENSE").is_file(), f"{directory}/LICENSE missing")

    def test_directory_licence_declares_the_right_identifier(self):
        for directory, expected in SPLIT_LAYOUT.items():
            text = (ROOT / directory / "LICENSE").read_text(encoding="utf-8")
            self.assertIn(f"SPDX-License-Identifier: {expected}", text)

    def test_spdx_headers_match_the_declared_split(self):
        summary = scan_spdx_headers(ROOT, SPLIT_LAYOUT.keys())
        for directory, expected in SPLIT_LAYOUT.items():
            counts = summary.get(directory, {})
            if not counts:
                continue
            self.assertNotIn("<missing>", counts, f"{directory} has files without an SPDX header")
            self.assertEqual(
                set(counts), {expected}, f"{directory} declares {set(counts)}, expected {expected}"
            )

    def test_third_party_notices_exist(self):
        self.assertTrue((ROOT / "THIRD_PARTY_NOTICES.md").is_file())


if __name__ == "__main__":
    unittest.main()
