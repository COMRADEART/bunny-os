# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The installed-evidence context resolver, exercised without a VM.

Everything here runs against temporary directories: the resolver's job is to
refuse bad authority *before* any scenario boots anything, so its refusals must
be testable on a machine that cannot boot anything.

One ordering fact matters to several tests and was confirmed by reading
``release/installed.py``: under ``verify=True`` the subject-digest check runs
*before* the ``git cat-file`` check. A digest mismatch therefore raises even in
a directory that is not a git repository, which lets those tests stay
repository-free; only the full happy-path test needs to ``git init``.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from release.installed import (
    CONTEXT_PATH,
    ContextError,
    evidence_id,
    resolve_context,
)

COMMIT = "80df25b09f6578276d18c8a82f15c47dd8959740"


def context_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schemaVersion": 1,
        "sourceCommit": COMMIT,
        "sourceArchiveDigest": "1" * 64,
        "installationArtifactDigest": "2" * 64,
        "recoveryArtifactDigest": "3" * 64,
        "installerToolchainDigest": "4" * 64,
        "scenarioVersion": "scenarios-v1",
    }
    document.update(overrides)
    return document


def write_context(root: Path, document: dict[str, object]) -> Path:
    path = root / CONTEXT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


class ContextResolution(unittest.TestCase):
    def test_a_missing_context_file_is_refused_naming_its_purpose(self) -> None:
        # The error must say what the file *is for*, not just that it is
        # absent: the person who hits this has never seen the context before.
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContextError) as raised:
                resolve_context(Path(directory), verify=False)
        message = str(raised.exception)
        self.assertIn(str(CONTEXT_PATH), message)
        self.assertIn("no authority", message)

    def test_malformed_json_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / CONTEXT_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(ContextError) as raised:
                resolve_context(root, verify=False)
        self.assertIn("not valid JSON", str(raised.exception))

    def test_a_short_source_commit_is_refused(self) -> None:
        # A truncated SHA is ambiguous, and an ambiguous authority is none.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_context(root, context_document(sourceCommit=COMMIT[:12]))
            with self.assertRaises(ContextError) as raised:
                resolve_context(root, verify=False)
        self.assertIn("40-character", str(raised.exception))

    def test_a_branch_name_is_not_a_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_context(root, context_document(sourceCommit="feature/installed-system"))
            with self.assertRaises(ContextError):
                resolve_context(root, verify=False)

    def test_a_non_hex_digest_is_refused_naming_the_field(self) -> None:
        for name in (
            "sourceArchiveDigest",
            "installationArtifactDigest",
            "installerToolchainDigest",
        ):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_context(root, context_document(**{name: "z" * 64}))
                with self.assertRaises(ContextError) as raised:
                    resolve_context(root, verify=False)
            self.assertIn(name, str(raised.exception))

    def test_a_truncated_digest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_context(root, context_document(sourceArchiveDigest="a" * 63))
            with self.assertRaises(ContextError):
                resolve_context(root, verify=False)

    def test_a_non_hex_recovery_digest_is_refused_when_present(self) -> None:
        # recoveryArtifactDigest is optional, but optional means absent or
        # right — never present and wrong.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_context(root, context_document(recoveryArtifactDigest="not-a-digest"))
            with self.assertRaises(ContextError) as raised:
                resolve_context(root, verify=False)
        self.assertIn("recoveryArtifactDigest", str(raised.exception))

    def test_an_absent_scenario_version_is_refused(self) -> None:
        # Without a scenarioVersion nothing can decide whether later evidence
        # ran under the same scenario definitions, so staleness detection dies.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = context_document()
            del document["scenarioVersion"]
            write_context(root, document)
            with self.assertRaises(ContextError) as raised:
                resolve_context(root, verify=False)
        self.assertIn("scenarioVersion", str(raised.exception))

    def test_a_present_subject_with_a_wrong_digest_is_refused(self) -> None:
        # The context claims a digest for a file sitting on the same disk and
        # the file digests to something else. This runs without a git
        # repository on purpose: the digest check precedes the git check in
        # resolve_context, so the mismatch must raise before git is consulted.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media" / "installer.iso"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"not the bytes the context describes")
            write_context(
                root,
                context_document(
                    subjects={"installationArtifactDigest": "media/installer.iso"}
                ),
            )
            with self.assertRaises(ContextError) as raised:
                resolve_context(root, verify=True)
        message = str(raised.exception)
        self.assertIn("installationArtifactDigest", message)
        self.assertIn("misdescribes", message)

    def test_the_git_check_fails_closed_outside_a_repository(self) -> None:
        # No subjects, valid shape, verify=True, but the directory is not a
        # git repository: the commit claim cannot be verified, so it is
        # refused. Unverifiable and verified must never be conflated.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_context(root, context_document())
            with self.assertRaises(ContextError) as raised:
                resolve_context(root, verify=True)
        self.assertIn("not a commit", str(raised.exception))

    def test_a_verified_context_resolves_in_a_real_repository(self) -> None:
        # The full verify=True happy path: an empty commit provides a real
        # SHA for the context to name, and an absent subject file is not an
        # error — media may live outside the repository.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                [
                    "git", "-C", str(root),
                    "-c", "user.email=test@bunny-os.invalid",
                    "-c", "user.name=Test",
                    "commit", "-q", "--allow-empty", "-m", "empty",
                ],
                check=True,
            )
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            write_context(
                root,
                context_document(
                    sourceCommit=head,
                    subjects={"installationArtifactDigest": "media/absent.iso"},
                ),
            )
            context = resolve_context(root, verify=True)
        self.assertEqual(context.sourceCommit, head)
        self.assertEqual(context.scenarioVersion, "scenarios-v1")

    def test_verify_false_returns_the_parsed_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_context(root, context_document())
            context = resolve_context(root, verify=False)
        self.assertEqual(context.sourceCommit, COMMIT)
        self.assertEqual(context.recoveryArtifactDigest, "3" * 64)
        self.assertEqual(context.as_dict()["installationArtifactDigest"], "2" * 64)


class EvidenceIdentifier(unittest.TestCase):
    def test_evidence_id_produces_the_canonical_shape(self) -> None:
        self.assertEqual(
            evidence_id("blank-disk", date="20260801", sequence=1),
            "ISQ-20260801-blank-disk-001",
        )

    def test_uppercase_and_spaces_are_slugged(self) -> None:
        # The identifier grammar is lowercase-and-hyphens; anything a human
        # typed gets normalised in the one place identifiers are minted, so
        # 'Blank Disk' and 'blank-disk' cannot become two evidence streams.
        self.assertEqual(
            evidence_id("Blank Disk", date="20260801", sequence=12),
            "ISQ-20260801-blank-disk-012",
        )

    def test_leading_and_trailing_separators_are_stripped(self) -> None:
        self.assertEqual(
            evidence_id("  wrong credential  ", date="20260801", sequence=3),
            "ISQ-20260801-wrong-credential-003",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
