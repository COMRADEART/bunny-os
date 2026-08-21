#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed Phase 17 verifier."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _engine():
    spec = importlib.util.spec_from_file_location(
        "phase17_engine_for_verify", HERE / "external_floor_ops.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    engine = _engine()
    guarded = [path for path in engine.REAL_IMMUTABLE_INPUTS if path.is_file()]
    for path in (engine.FLOOR_PATH, engine.MATRIX_PATH, engine.RECOVERY_PATH,
                 engine.DASHBOARD_PATH, engine.REGISTRY_PATH):
        if path.is_file() and path not in guarded:
            guarded.append(path)
    for path in sorted(engine.CUTS.glob("*.json")) if engine.CUTS.is_dir() else []:
        if path not in guarded:
            guarded.append(path)
    before = {path: path.read_bytes() for path in guarded}

    issues = engine.verify_all()
    for path, raw in before.items():
        if not path.is_file() or path.read_bytes() != raw:
            issues.append(
                "REAL INPUT INTEGRITY FAIL: %s changed during Phase 17 verification"
                % path.relative_to(engine.ROOT).as_posix()
            )

    if issues:
        for issue in issues:
            print(issue)
        print("phase 17 verification: %d issue(s)" % len(issues))
        return 2

    status = engine.load_json(engine.FLOOR_PATH)
    print("phase 17 verifies clean")
    print("subject %s remains %s/%s; floor %d/5; authorization %s; candidate %s" % (
        status["subjectArtifact"]["identifier"],
        status["subjectArtifact"]["relationship"],
        status["subjectArtifact"]["signingStatus"],
        status["convergence"]["count"],
        status["authorizationState"], status["candidateDecision"],
    ))
    print("operational readiness remains distinct from evidence satisfaction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
