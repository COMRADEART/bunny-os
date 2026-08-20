#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed Phase 16 verification gate.

This verifies package presence and pins, derived receipt/status views, the
single intake door, engine composition, fixture walls, matrix reproduction,
sealed cuts, identity ceremony semantics, explicit-time discipline,
authorization refusal, register reproduction, and byte identity of every real
input around the complete exercise. A clean result is about the machinery; it
is never evidence approving the artifact.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _engine():
    spec = importlib.util.spec_from_file_location(
        "phase16_engine_for_verify", HERE / "security_review_intake_ops.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    engine = _engine()
    guarded = list(engine._phase14().REAL_IMMUTABLE_INPUTS)
    for extra in (engine.PHASE15_STATUS, engine.PHASE15_MATRIX,
                  engine.STATUS_PATH, engine.MATRIX_PATH,
                  engine.RECOVERY_PATH, engine.PINS_PATH):
        if extra.is_file() and extra not in guarded:
            guarded.append(extra)
    if engine.PHASE15_CUTS.is_dir():
        for path in sorted(engine.PHASE15_CUTS.glob("*.json")):
            if path not in guarded:
                guarded.append(path)
    before = {path: path.read_bytes() for path in guarded}

    issues = engine.verify_all()
    for path, raw in before.items():
        if not path.is_file() or path.read_bytes() != raw:
            issues.append(
                "REAL INPUT INTEGRITY FAIL: %s changed during Phase 16 "
                "verification" % path.relative_to(engine.ROOT).as_posix())

    if issues:
        for issue in issues:
            print(issue)
        print("phase 16 verification: %d issue(s)" % len(issues))
        return 2

    status = engine.load_json(engine.STATUS_PATH)
    print("phase 16 verifies clean")
    print("subject %s remains %s/%s; receipt %s; gate %s; "
          "authorization %s; candidate decision %s" % (
              status["subjectArtifact"]["identifier"],
              status["subjectArtifact"]["artifactState"],
              status["subjectArtifact"]["signingStatus"],
              status["receipt"]["boundary"]["overall"],
              status["securityGate"]["status"],
              status["authorization"]["authorizationState"],
              status["candidateDecision"]["decision"]))
    print("receipt acceptance remains distinct from assessment, gate, "
          "authorization, and candidate decision")
    return 0


if __name__ == "__main__":
    sys.exit(main())
