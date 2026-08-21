#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 15 verification gate: exit 0 clean, exit 2 on any issue.

One command that answers "is the first real external evidence path still
operational and fail-closed?" by running the full engine verification:

* the track documents and the reviewer handoff exist, and the handoff
  still states that an unfavorable result cannot be converted;
* the receipt vocabulary carries no favorable state and its transition
  table cannot leave the vocabulary;
* every fixture carries all three markers and no marker exists anywhere
  in the real intake tree;
* the subject artifact is UNSIGNED, frozen, and consistently identified;
* every failure/recovery scenario re-executes AS_EXPECTED against the
  real engines in scratch universes, and the committed matrix reproduces
  byte-for-byte from that execution;
* the committed EXTERNAL_STATUS.json reproduces from its live inputs;
* every committed evidence cut's seal verifies;
* assembling the real universe derives exactly the state Phase 13
  committed;
* every real immutable input is byte-identical before and after all of
  the above.

This gate passing is a statement about the machinery, never about the
artifact: the candidate decision it confirms is REQUIRES_MORE_EVIDENCE,
and only real external evidence through the Phase 9 intake can change
that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _engine():
    spec = importlib.util.spec_from_file_location(
        "phase15_engine_for_verify", HERE / "tools" / "review_execution_ops.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    engine = _engine()
    guarded = list(engine._phase14().REAL_IMMUTABLE_INPUTS)
    real_before = {path: path.read_bytes() for path in guarded}
    issues = engine.verify_all()
    for path, raw in real_before.items():
        if path.read_bytes() != raw:
            issues.append("REAL LEDGER INTEGRITY FAIL: %s changed during "
                          "verification" % path.name)
    if issues:
        for issue in issues:
            print(issue)
        print("phase 15 verification: %d issue(s)" % len(issues))
        return 2
    status = engine.load_json(engine.STATUS_PATH)
    print("phase 15 verifies clean")
    print("subject artifact %s remains %s; receipt %s; gate %s; "
          "candidate decision %s"
          % (status["subjectArtifact"]["identifier"],
             status["subjectArtifact"]["signingStatus"],
             status["securityReview"]["receiptState"],
             status["securityReview"]["gate"]["status"],
             status["authorization"]["candidateDecision"]))
    print("every favorable scenario row is FIXTURE_DEMONSTRATION_ONLY; "
          "the evidence is still external")
    return 0


if __name__ == "__main__":
    sys.exit(main())
