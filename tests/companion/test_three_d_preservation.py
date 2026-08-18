# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The earlier phases' records are immutable, and this is what says so.

This phase adds a capability. It corrects no earlier phase, supersedes no
earlier claim, and therefore owes the earlier records exactly one thing: that
they are still there, byte for byte. A sentence promising that is worth nothing
a year from now; a test that reads the digests is worth the same in five.

The digests come from
``qualification/companion-3d-renderer/preserved-evidence.json``, written once
when this branch was cut from ``fa49380``. A file that changed, disappeared or
was added under a *prior* phase's tree fails here — including a change that
looks harmless, because "harmless" is a judgement the digest is not asking for.

``qualification/**`` is ``-text`` in ``.gitattributes``, which is what makes the
comparison meaningful across the two hosts this phase used: without it a Windows
checkout would renormalise line endings and every digest would fail for a reason
that has nothing to do with the evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_RECORD = _ROOT / "qualification" / "companion-3d-renderer" / "preserved-evidence.json"

#: Phase trees that did not exist when the record was written. They are excluded
#: from the "nothing was added" check rather than added to the record — a record
#: that included them would have to be rewritten every time a gate ran, which is
#: the opposite of an immutable one.
#:
#: The property being defended is that an *earlier* phase's evidence is
#: immutable. A phase that came after the record is not an earlier phase, and
#: recording it would freeze a tree that is still being written to.
#:
#: Listed explicitly rather than derived, so that a new phase tree fails here
#: until somebody declares it deliberately — the same rule
#: ``GENERATOR_FUNCTIONS`` applies to install helpers. Adding a file to any tree
#: the record *does* cover still fails, which is the whole point.
_PHASES_AFTER_THE_RECORD = (
    # This phase's own tree.
    "qualification/companion-3d-renderer/",
    # Public Alpha ran after this record was cut from fa49380 and committed its
    # gate evidence under its own name. It is a later phase, not an earlier one.
    "qualification/public-alpha/",
    # The App Capsule runtime qualification, later still: the probe and stress
    # fixtures it launches, and one evidence directory per commit it ran at.
    # Declared here rather than added to the record for the reason above — a
    # record that covered a tree still being written to would have to be
    # rewritten on every run, which is the opposite of immutable.
    "qualification/capsules/",
    # The design-system phase (Orca and screenshot evidence), the installer
    # phase (journey evidence and the installed-system context), and Stage 2's
    # voice release each committed their own trees after the record. Declared
    # when Phase 3 classified the two preservation failures they caused: the
    # failures fired because later phases existed, not because earlier
    # evidence changed.
    "qualification/design/",
    "qualification/installer/",
    "qualification/installer-journeys/",
    "qualification/voice-release/",
    # Phase 3's own tree.
    "qualification/phase3/",
    # Phase 4's, for the same reason: the Alpha hardening phase committed the
    # power-key investigation and the release-candidate qualification under
    # its own name. A later phase existing is not an earlier phase changing.
    "qualification/phase4/",
    # Phase 5's baseline record and evidence.
    "qualification/phase5/",
    # Phase 6's, for the same reason. Its tree is where the external-gate work
    # lives: the baseline freeze, the blocking conditions, the update-refusal
    # qualification and its negative control, the security review package, and
    # three hardware journeys whose expectations were written before any machine
    # existed. Note that Phase 6 also carries a *correction* to Phase 5's
    # security evidence — and it is a correction record under this prefix, not
    # an edit to Phase 5's files, which is why the byte-identity check above
    # still passes unchanged.
    "qualification/phase6/",
    # The grader is not evidence at all — it is the instrument, extracted from
    # ``build/scripts/vm-login-story.sh`` so that it can be unit-tested against
    # recorded runs. It lives under ``qualification/`` because that directory is
    # not a ``COPY`` root in ``build/Containerfile``: nothing here reaches the
    # image, so correcting a check does not require a rebuild and a new artifact
    # identity. Its ``fixtures/`` hold manifests that *point at* earlier phases'
    # evidence rather than copying it, so this declaration adds a tool, not a
    # second copy of a record.
    "qualification/grader/",
)

#: Maintained tooling that lives under an earlier phase's directory but is not
#: a record: the matrix importer is edited by every phase that writes matrix
#: rows (the installer phase grew its ``journey:`` evidence kind), and pinning
#: it byte-for-byte makes evidence immutability fail whenever the *tooling*
#: legitimately improves. Evidence stays pinned; the one named script does not.
#: Named singly rather than as a directory, so a new file appearing beside it
#: still fails the added-files check until somebody declares it.
_MAINTAINED_TOOLING = frozenset({
    "qualification/installed-system/scripts/import_matrix_results.py",
    # Phase 5 made ``qualification/`` a Python package so that
    # ``qualification.grader`` — the extracted VM journey grader — is
    # importable. The file is a docstring and nothing else; it is tooling, not
    # a record, and it sits at the top of the tree rather than inside any
    # phase's directory, so no prefix in ``_PHASES_AFTER_THE_RECORD`` covers it.
    #
    # Named singly, like the importer above, and for the same reason: another
    # file appearing beside it still fails the added-files check until somebody
    # declares it deliberately.
    "qualification/__init__.py",
})

#: Build residue, which is not evidence and is not in the repository.
#:
#: ``qualification/display-stack/scripts/`` holds importable helpers, so running
#: the suite once writes ``__pycache__`` beside them — twenty-three ``.pyc``
#: files that are ignored by ``.gitignore`` and invisible to every other check
#: in this project. The walk below asks the *filesystem* rather than git, so it
#: counted them as files added to an earlier phase's evidence tree and the test
#: failed on every run after the first. Found on the Public Alpha branch, where
#: the gates run the suite repeatedly against one checkout.
#:
#: Excluded by directory name, matching ``TREE_EXCLUDED`` and ``PACKAGE_EXCLUDED``
#: in ``build/scripts/install_routes.py``, which drop the same directory for the
#: same reason: bytecode embeds the source path and the mtime of the machine
#: that produced it, so it is never content anybody meant to keep.
_RESIDUE = ("__pycache__",)


def _digest(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _is_residue(name: str) -> bool:
    return any(part in _RESIDUE for part in name.split("/"))


def _tracked_qualification_files() -> set[str] | None:
    """Every committed path under ``qualification/``, or ``None`` without git."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(_ROOT), "ls-files", "-z", "--", "qualification"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return {name for name in result.stdout.split("\0") if name}


class PreservedEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = json.loads(_RECORD.read_text(encoding="utf-8"))

    def test_the_record_names_the_base_commit_this_branch_was_cut_from(self) -> None:
        self.assertEqual(
            self.record["baseCommit"], "fa49380dadf0aa90690c4f2be5b483b16a56c0db"
        )
        self.assertEqual(self.record["phase"], "companion-3d-renderer")

    def test_every_prior_evidence_file_is_byte_identical(self) -> None:
        mismatched: list[str] = []
        missing: list[str] = []
        for name, expected in sorted(self.record["preservedEvidence"].items()):
            if _is_residue(name) or name in _MAINTAINED_TOOLING:
                continue
            path = _ROOT / name
            if not path.is_file():
                missing.append(name)
                continue
            size, digest = _digest(path)
            if size != expected["bytes"] or digest != expected["sha256"]:
                mismatched.append(name)
        self.assertEqual(missing, [], "prior evidence files disappeared")
        self.assertEqual(mismatched, [], "prior evidence files changed")

    def test_no_file_was_added_to_an_earlier_phase_tree(self) -> None:
        """Added means *committed*, so the question is asked of git.

        It used to be asked of the filesystem, and the filesystem answers a
        different question: it reports every file that is *present*, including
        the ones no commit ever contained. On a builder where an earlier phase
        has actually run, that is twenty untracked VM working files —
        ``OVMF_VARS.qcow2`` and friends under
        ``qualification/installed-system/evidence/*/work/`` — plus whatever
        bytecode the last suite wrote. None of them was added to the evidence
        tree; they were left in a directory beside it.

        The distinction matters because the property being defended is about
        the *repository*: an earlier phase's evidence is immutable, so no commit
        may add to it. A scratch file in a working directory is not a commit.
        """
        tracked = _tracked_qualification_files()
        if tracked is None:
            self.skipTest("git is not available, so 'added' cannot be distinguished from 'present'")
        recorded = set(self.record["preservedEvidence"])
        added = [
            name for name in sorted(tracked)
            if name not in recorded
            and not name.startswith(_PHASES_AFTER_THE_RECORD)
            and not _is_residue(name)
            and name not in _MAINTAINED_TOOLING
        ]
        self.assertEqual(added, [], "a file was added to an earlier phase's evidence tree")

    def test_the_record_covers_every_earlier_phase(self) -> None:
        phases = {
            name.split("/")[1] for name in self.record["preservedEvidence"]
            if name.startswith("qualification/")
        }
        for earlier in (
            "companion-agent-providers", "companion-desktop-actions", "companion-linux",
            "companion-speech-input", "companion-voice", "companion-voice-closure",
            "display-stack", "first-login", "hardware", "installed-system",
            "reproducibility", "tpm",
        ):
            self.assertIn(earlier, phases, f"{earlier} is not covered by the record")


if __name__ == "__main__":
    unittest.main()
