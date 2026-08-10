#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the App Capsule runtime qualification and write its evidence.

    python3 scripts/capsules/runtime_qualify.py --all
    python3 scripts/capsules/runtime_qualify.py --section isolation
    python3 scripts/capsules/runtime_qualify.py --list

Every section writes one JSON record under
``qualification/capsules/evidence/<commit>/``. A section that could not run
writes ``BLOCKED`` or ``NOT_RUN`` — never ``PASS`` — because the failure mode of
a qualification run is a green tick attached to a check that did not happen.

The exit code is 0 only when every requested section reported ``PASS``. A
``BLOCKED`` section exits 2, which is distinguishable from a ``FAIL``'s 1: one
means this host could not answer, the other means it answered badly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.capsules.harness import (  # noqa: E402
    EVIDENCE_ROOT,
    Evidence,
    Harness,
    host_record,
    write_evidence,
)
from scripts.capsules.sections import SECTIONS  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--section", action="append", choices=sorted(SECTIONS), help="run one section")
    parser.add_argument("--all", action="store_true", help="run every section")
    parser.add_argument("--list", action="store_true", help="list the sections and exit")
    parser.add_argument("--evidence-root", type=Path, default=EVIDENCE_ROOT)
    arguments = parser.parse_args(argv)

    if arguments.list:
        for name in SECTIONS:
            print(name)
        return 0
    wanted = list(SECTIONS) if arguments.all else (arguments.section or ["host"])

    host = host_record()
    directory = Path(arguments.evidence_root) / host["commit"][:12]
    print(f"commit    {host['commit'][:12]}")
    print(f"user      {host['user']['name']} (uid {host['user']['uid']})")
    print(f"kernel    {host['versions'].get('kernel')}")
    print(f"selinux   {host['selinux']}   virt {host['virtualization']}   fs {host['homeFilesystem']}")
    print(f"backends  {host['availableBackends']}")
    print(f"evidence  {directory}")
    print()

    verdicts: dict[str, str] = {}
    for name in wanted:
        harness: Harness | None = None
        try:
            if name != "host":
                harness = Harness.build()
            evidence = SECTIONS[name](harness, host)
        except Exception:  # noqa: BLE001 - a section that explodes is a FAIL, not a crash
            evidence = Evidence(section=name)
            evidence.findings.append(traceback.format_exc()[-2000:])
            evidence.settle("FAIL", "the section raised before it could settle")
        finally:
            if harness is not None:
                harness.close()
        path = write_evidence(evidence, host, directory)
        verdicts[name] = evidence.verdict
        marker = {"PASS": "PASS ", "FAIL": "FAIL ", "BLOCKED": "BLOCK", "NOT_RUN": "SKIP "}[evidence.verdict]
        print(f"[{marker}] {name:12} {evidence.explanation[:150]}")
        for finding in evidence.findings:
            print(f"          - {finding[:200]}")
        print(f"          -> {path.relative_to(ROOT)}")

    print()
    print("summary:", json.dumps(verdicts))
    if any(verdict == "FAIL" for verdict in verdicts.values()):
        return 1
    if any(verdict in ("BLOCKED", "NOT_RUN") for verdict in verdicts.values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
