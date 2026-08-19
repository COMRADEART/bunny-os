#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 14 verification gate: exit 0 clean, exit 2 on any issue.

One command that answers "does the external-evidence execution layer
still hold?" by running the full engine verification:

* the package documents exist;
* every fixture carries all three markers and no marker exists in the
  real intake tree;
* the subject artifact is UNSIGNED, frozen, and consistently identified;
* every rehearsal scenario re-executes AS_EXPECTED in scratch universes;
* the committed MATRIX.json reproduces byte-for-byte from that
  execution;
* every real immutable input is byte-identical before and after the
  rehearsals;
* assembling the real universe derives exactly the state Phase 13
  committed.

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
        "phase14_engine_for_verify", HERE / "evidence_execution_ops.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    engine = _engine()
    real_before = {path: path.read_bytes()
                   for path in engine.REAL_IMMUTABLE_INPUTS}
    issues = engine.verify_all()
    for path, raw in real_before.items():
        if path.read_bytes() != raw:
            issues.append("REAL LEDGER INTEGRITY FAIL: %s changed during "
                          "verification" % path.name)
    if issues:
        for issue in issues:
            print(issue)
        print("phase 14 verification: %d issue(s)" % len(issues))
        return 2
    status = engine.load_json(engine.PHASE13_STATUS)
    print("phase 14 verifies clean")
    print("subject artifact %s remains %s; candidate decision %s"
          % (status["subjectArtifact"],
             engine.load_json(engine.PHASE9_LEDGER)["subjectArtifact"]
             ["signingStatus"],
             status["candidateDecision"]))
    print("every favorable rehearsal row is FIXTURE_DEMONSTRATION_ONLY; "
          "the evidence is still external")
    return 0


if __name__ == "__main__":
    sys.exit(main())
