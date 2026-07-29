from __future__ import annotations

from pathlib import Path
import unittest

from operations.candidate import REQUIRED_ARTIFACT_KINDS, validate_candidate


ROOT = Path(__file__).resolve().parents[2]


def candidate() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "candidateVersion": "1.0.0-stable-rc1",
        "sourceCommit": "a" * 40,
        "immutable": True,
        "artifacts": [{"kind": kind, "path": f"artifacts/{kind}", "sha256": "b" * 64, "signatureVerified": True} for kind in sorted(REQUIRED_ARTIFACT_KINDS)],
        "signedUpdateMetadata": True,
        "reviewEvidence": {"security": "PASS", "privacy": "PASS", "accessibility": "PASS"},
        "soak": {"completed": True, "hours": 72},
    }


class CandidateTests(unittest.TestCase):
    def test_complete_candidate_is_valid(self) -> None:
        self.assertEqual(validate_candidate(candidate())["immutable"], True)

    def test_missing_artifact_is_rejected(self) -> None:
        value = candidate()
        value["artifacts"] = value["artifacts"][1:]
        with self.assertRaises(ValueError):
            validate_candidate(value)

    def test_unsigned_artifact_is_rejected(self) -> None:
        value = candidate()
        value["artifacts"][0]["signatureVerified"] = False
        with self.assertRaises(ValueError):
            validate_candidate(value)

    def test_incomplete_soak_is_rejected(self) -> None:
        value = candidate()
        value["soak"] = {"completed": False, "hours": 0}
        with self.assertRaises(ValueError):
            validate_candidate(value)

    def test_artifact_path_escape_is_rejected(self) -> None:
        value = candidate()
        value["artifacts"][0]["path"] = "../outside.iso"
        with self.assertRaises(ValueError):
            validate_candidate(value)

    def test_signing_script_rejects_repository_private_key(self) -> None:
        source = (ROOT / "build/scripts/sign-stable-rc.py").read_text(encoding="utf-8")
        self.assertIn("private signing keys must not be stored in the repository", source)

    def test_build_script_checks_untracked_files_and_exact_commit(self) -> None:
        source = (ROOT / "build/scripts/build-stable-rc.sh").read_text(encoding="utf-8")
        self.assertIn("--untracked-files=all", source)
        self.assertIn("BUNNY_SOURCE_COMMIT", source)

    def test_build_script_requires_independent_recovery_iso(self) -> None:
        source = (ROOT / "build/scripts/build-stable-rc.sh").read_text(encoding="utf-8")
        self.assertIn("independently bootable recovery ISO", source)

    def test_rollback_and_recovery_use_dedicated_safe_fixtures(self) -> None:
        rollback = (ROOT / "build/scripts/vm-rollback-test.sh").read_text(encoding="utf-8")
        recovery = (ROOT / "build/scripts/vm-recovery-test.sh").read_text(encoding="utf-8")
        self.assertIn("new disposable QCOW2", rollback)
        self.assertIn("detached signature is required", recovery)


if __name__ == "__main__":
    unittest.main()
