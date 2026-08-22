# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phases 4–6 are frozen now, and this is what says so.

Phase 6 measured the evidence-immutability guard and recorded that its record
ends at ``fa49380``: every phase tree declared after that commit — the design
system, the installer, phases 3 through 6, the capsule and Public Alpha
evidence — was pinned by nothing except the observation that ``git diff``
happened to be empty. An observation about the current checkout is not a guard
against the next commit.

This is the successor guard. Its record —
``qualification/phase7/immutability/frozen-evidence.json``, cut by
``build-record.py`` in the same directory — pins every tracked file under
``qualification/`` except the two prefixes that are not frozen evidence:
``qualification/phase7/`` (the tree still being written to) and
``qualification/grader/`` (the instrument, not a record). The elder guard,
``tests/companion/test_three_d_preservation.py``, keeps enforcing its own
fa49380 record unchanged; nothing here supersedes a passing test.

The checker is a function of (root, record, tracked) rather than a walk over
module globals, so this file also carries its own negative controls: a
constructed tree in which a pinned byte changes MUST fail, and a constructed
tracked set with an extra committed name MUST fail. A guard whose failure
branch has never executed is how ``grep -q`` under ``pipefail`` shipped a test
with no true-positive path, and how three rollback runs passed without rolling
back.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_RECORD = _ROOT / "qualification" / "phase7" / "immutability" / "frozen-evidence.json"

#: Must match ``build-record.py`` — asserted below, so the script and the test
#: cannot drift apart silently. This is the CUT-TIME policy and never grows:
#: a record whose exemptions move afterwards is not a record.
EXEMPT_PREFIXES = (
    "qualification/phase7/",
    "qualification/grader/",
)

#: Phase trees created after the record was cut at 7db5962b. Declared
#: explicitly, one per phase, exactly as the elder guard's
#: ``_PHASES_AFTER_THE_RECORD`` does it — a new tree fails the added-files
#: check until somebody writes it here deliberately. These are NOT folded
#: into ``EXEMPT_PREFIXES``: that tuple is frozen with the record; this one
#: is maintenance, and the diff of this file is its audit trail.
PHASES_AFTER_THE_RECORD = (
    # Phase 8's tree: external-validation governance — blocking conditions
    # committed before any tester existed, the review package, the hardware
    # matrix and protocol, signing readiness, and the Alpha program
    # operations. Still being written to.
    "qualification/phase8/",
    # Phase 9's tree: the external-evidence intake boundary. Its interior is
    # not unguarded like the other exempt prefixes — the intake ledger pins
    # its own evidence bytes and seals its own entries, enforced by
    # tests/release/test_phase9_intake.py — but *this* record does not pin
    # it, because evidence is still arriving. Declared after both guards
    # refused the tree's files as additions, exactly as designed.
    "qualification/phase9/",
    # Phase 10's tree: candidate operations. The artifact graph and
    # candidate status are live operational records — the graph gains a row
    # when a real successor artifact exists, the status re-derives as
    # evidence arrives — so the tree cannot be pinned while the candidate
    # is being operated. Its own reproducibility guard is
    # tests/release/test_phase10_operations.py: the committed status must
    # recompute from immutable inputs. Declared after both guards refused
    # the tree's files, exactly as designed.
    "qualification/phase10/",
    # Phase 11's tree: independent-security-review operations — the
    # commissioning package (scope frozen at SCOPE-1, baseline pinned to
    # the Phase 8 package by sha256), the submission contract and its
    # validator, and the derived finding register, which re-derives as
    # accepted review evidence arrives and so cannot be pinned while the
    # review is open. Its own reproducibility guard is
    # tests/release/test_phase11_security_review.py. Declared after both
    # guards refused the tree's files, exactly as designed.
    "qualification/phase11/",
    # Phase 12's tree: Alpha tester program operations — the canonical
    # tester package (its Phase 7/8 sources pinned by sha256 inside the
    # tree), the recorded dedup decisions and reproduction attempts, the
    # sufficiency policy, and the derived Alpha finding register, which
    # re-derives as accepted tester evidence arrives and so cannot be
    # pinned while the program is open. Its own reproducibility guard is
    # tests/release/test_phase12_alpha_operations.py. Declared after both
    # guards refused the tree's files, exactly as designed.
    "qualification/phase12/",
    # Phase 13's tree: release authority and decision governance — the
    # authority model with its sealed assignment records, the
    # owner-controlled sufficiency threshold registry (undefined until a
    # real owner decides), the blocking-condition registry pinned to the
    # Phase 8 source by sha256, the sealed decision registries (risk
    # acceptance, authorization, revocation, conflict resolution), and
    # the derived authorization status, which re-derives as authority
    # records and evidence arrive and so cannot be pinned while the
    # decision is open. Its own reproducibility guard is
    # tests/release/test_phase13_release_authority.py. Declared after
    # both guards refused the tree's files, exactly as designed.
    "qualification/phase13/",
    # Phase 14's tree: external-evidence execution and decision rehearsal
    # — the evidence router, sealed evidence cuts, and the decision
    # assembler, exercised only on TEST_FIXTURE_ONLY material in scratch
    # universes. MATRIX.json is derived by re-executing all 72 scenarios
    # against the live phase 9-13 inputs it pins by sha256, so it re-derives
    # when real evidence arrives and the tree cannot be pinned here. Its own
    # reproducibility guards are tests/release/test_phase14_evidence_execution.py
    # and tests/release/test_phase14_decision_rehearsal.py. Declared after
    # both guards refused the tree's files, exactly as designed.
    "qualification/phase14/",
    # Phase 15's tree: the first-production-use operational layer for the
    # independent security review — the reviewer handoff package, the
    # derived receipt register (no favorable state exists), append-only
    # sealed evidence cuts under cuts/, and the derived EXTERNAL_STATUS.json
    # and FAILURE_RECOVERY_MATRIX.json, which re-derive from the live
    # phase 9-14 inputs as evidence arrives and so cannot be pinned while
    # the review is open. Its own reproducibility guards are
    # tests/release/test_phase15_review_execution.py and
    # tests/release/test_phase15_evidence_activation.py. Declared after
    # both guards refused the tree's files, exactly as designed.
    "qualification/phase15/",
    # Phase 16's tree: the external-security-review receipt and gate
    # execution layer — reviewer handoff, identity ceremony, one-door intake
    # composition, reconciliation, evidence-cut execution, derived status,
    # executable matrices, and their verifier. The tree remains live as real
    # evidence arrives, so it cannot be pinned by the Phase 7 cut. Both guards
    # refused all twenty committed files before this deliberate declaration.
    "qualification/phase16/",
    # Phase 17's tree: multi-source external-floor operations — the closed
    # five-source registry, explicit operator, source-specific evaluation,
    # unified reference cuts, derived floor/status/dashboard, 70-scenario
    # matrix, and marked scratch fixtures. Real evidence can advance the
    # derived views, so the Phase 7 cut cannot pin this live tree. Both guards
    # refused the same twenty-six committed paths at feff1527 before this
    # declaration; neither historical cut-time exemption changed.
    "qualification/phase17/",
    # The capability-integration phase's evidence tree: the companion
    # runtime's capability-route records, whose last writer on this line was
    # 9d3b0ade, merged through the Phase 17 external-floor pull request after
    # this record was cut at 7db5962b. Both guards refused exactly the six
    # committed paths before this deliberate declaration; EXEMPT_PREFIXES is
    # unchanged and the record itself is untouched.
    "qualification/capability-integration/",
)

MAINTAINED_TOOLING = frozenset({
    "qualification/installed-system/scripts/import_matrix_results.py",
    "qualification/__init__.py",
})

_RESIDUE = ("__pycache__",)


def _is_residue(name: str) -> bool:
    return any(part in _RESIDUE for part in name.split("/"))


def verify_frozen(root: Path, frozen: dict, tracked: set[str] | None):
    """Return (missing, mismatched, added) for a frozen-evidence record.

    ``tracked`` is the set of committed paths under ``qualification/``; pass
    ``None`` when git cannot answer, and the added-files half is skipped by
    the caller rather than silently passed here.
    """
    missing: list[str] = []
    mismatched: list[str] = []
    for name, expected in sorted(frozen.items()):
        path = root / name
        if not path.is_file():
            missing.append(name)
            continue
        raw = path.read_bytes()
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            mismatched.append(name)
    added: list[str] = []
    if tracked is not None:
        added = [
            name for name in sorted(tracked)
            if name not in frozen
            and not name.startswith(EXEMPT_PREFIXES + PHASES_AFTER_THE_RECORD)
            and name not in MAINTAINED_TOOLING
            and not _is_residue(name)
        ]
    return missing, mismatched, added


def _tracked_qualification_files() -> set[str] | None:
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


class FrozenEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = json.loads(_RECORD.read_text(encoding="utf-8"))

    def test_the_record_names_its_cut_commit(self) -> None:
        self.assertEqual(self.record["phase"], "phase7")
        self.assertEqual(
            self.record["recordCommit"],
            "7db5962bcfec55ab7a15ca96d37c0393d897ed9a",
        )

    def test_the_record_and_the_builder_agree_on_the_policy(self) -> None:
        self.assertEqual(tuple(self.record["exemptPrefixes"]), EXEMPT_PREFIXES)
        self.assertEqual(set(self.record["maintainedTooling"]), MAINTAINED_TOOLING)

    def test_the_record_covers_every_frozen_phase(self) -> None:
        """The Phase 6 finding, inverted into an assertion.

        The trees the elder guard declares-and-does-not-pin are exactly the
        trees this record must pin. ``phase7`` and ``grader`` are the two
        deliberate exceptions, named in ``EXEMPT_PREFIXES`` with their
        reasons.
        """
        phases = {
            name.split("/")[1] for name in self.record["frozenEvidence"]
            if name.startswith("qualification/")
        }
        for frozen in (
            # The thirteen trees the fa49380 record already pins.
            "companion-agent-providers", "companion-desktop-actions", "companion-linux",
            "companion-speech-input", "companion-voice", "companion-voice-closure",
            "display-stack", "first-login", "hardware", "installed-system",
            "reproducibility", "tpm",
            # The trees pinned by nothing until this record.
            "companion-3d-renderer", "public-alpha", "capsules", "design",
            "installer", "installer-journeys", "voice-release",
            "phase3", "phase4", "phase5", "phase6",
        ):
            self.assertIn(frozen, phases, f"{frozen} is not covered by the record")

    def test_every_frozen_file_is_byte_identical_and_none_was_added(self) -> None:
        tracked = _tracked_qualification_files()
        missing, mismatched, added = verify_frozen(
            _ROOT, self.record["frozenEvidence"], tracked
        )
        self.assertEqual(missing, [], "frozen evidence files disappeared")
        self.assertEqual(mismatched, [], "frozen evidence files changed")
        if tracked is None:
            self.skipTest("git is not available, so 'added' cannot be distinguished from 'present'")
        self.assertEqual(added, [], "a file was added to a frozen evidence tree")


class FrozenEvidenceNegativeControls(unittest.TestCase):
    """The failure branches, executed on every run against a constructed tree."""

    def _scratch(self) -> tuple[Path, dict]:
        tmp = Path(tempfile.mkdtemp(prefix="frozen-control-"))
        target = tmp / "qualification" / "phase5" / "control.log"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"the recorded bytes\n")
        record = {
            "qualification/phase5/control.log": {
                "bytes": 19,
                "sha256": hashlib.sha256(b"the recorded bytes\n").hexdigest(),
            }
        }
        return tmp, record

    def test_unchanged_evidence_passes(self) -> None:
        root, record = self._scratch()
        self.assertEqual(
            verify_frozen(root, record, set(record)), ([], [], []),
        )

    def test_a_modified_byte_fails(self) -> None:
        root, record = self._scratch()
        (root / "qualification" / "phase5" / "control.log").write_bytes(
            b"the recorded bytes.\n"
        )
        missing, mismatched, added = verify_frozen(root, record, set(record))
        self.assertEqual(mismatched, ["qualification/phase5/control.log"])

    def test_a_deleted_file_fails(self) -> None:
        root, record = self._scratch()
        (root / "qualification" / "phase5" / "control.log").unlink()
        missing, mismatched, added = verify_frozen(root, record, set(record))
        self.assertEqual(missing, ["qualification/phase5/control.log"])

    def test_a_file_added_to_a_frozen_tree_fails(self) -> None:
        root, record = self._scratch()
        tracked = set(record) | {"qualification/phase6/added.log"}
        missing, mismatched, added = verify_frozen(root, record, tracked)
        self.assertEqual(added, ["qualification/phase6/added.log"])

    def test_an_addition_under_an_exempt_prefix_does_not_fail(self) -> None:
        root, record = self._scratch()
        tracked = set(record) | {"qualification/phase7/rollback/expectation.json"}
        missing, mismatched, added = verify_frozen(root, record, tracked)
        self.assertEqual(added, [])


if __name__ == "__main__":
    unittest.main()
