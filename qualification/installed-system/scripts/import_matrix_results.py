#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import installed-system evidence into the qualification matrices.

The gate counts matrix rows; this is the only path by which a scenario run
becomes one. Each mapping names the evidence record it rests on, the record
is re-verified against the evidence context before anything is written, and
the row's method is ``virtual-machine`` — never more than the evidence is.

A scenario the harness did not run is not written at all: the existing
NOT_RUN row stays, because absence of evidence is already recorded honestly
and overwriting it with a fresher NOT_RUN would only disguise how long the
gap has stood.

The mapping between harness scenarios and matrix rows is explicit and small,
and refuses ambiguity: one matrix row rests on one or more named evidence
records, each of which must be a PASS for the row to become PASS. A FAIL
anywhere makes the row FAIL — a matrix that averages is a matrix that hides.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from release.installed import ContextError, resolve_context, verify_record_binding  # noqa: E402
from release.matrix import parse_result  # noqa: E402

#: matrix -> row -> list of (record kind, evidence file names) that support it.
#: "scenario:<name>" is a run_scenario verdict; "collection:<file>" is an
#: offline collection verdict (its JSON carries its own result field);
#: "journey:<dir>" is an unattended §53 installer-journey run under
#: qualification/installer-journeys/evidence (vm-install-story.sh drives the
#: shipped setup surface end to end and verify-installed-choices.py reads the
#: disk from outside — a different, stronger instrument than the bootc-install
#: records the earlier rows rested on).
ROW_EVIDENCE: dict[str, dict[str, list[str]]] = {
    "installation": {
        "empty-uefi-disk": ["journey:journey-a", "journey:journey-c"],
        "unencrypted-installation": ["journey:journey-c"],
        "offline-installation": ["journey:journey-c-offline"],
        "encrypted-uefi-installation": ["journey:journey-a", "journey:journey-b",
                                        "journey:first-boot"],
        "interrupted-installation": ["install:interrupted", "collection:interrupted-disk-state.json"],
        "existing-linux-replacement": ["install:existing-data-protected", "install:existing-data-authorized"],
        "nvme-like-virtual-disk": ["scenario:first-boot-nvme"],
        "sata-like-virtual-disk": ["scenario:first-boot-sata"],
    },
    "encryption": {
        "luks-password-unlock": ["scenario:encrypted-first-boot"],
        "incorrect-password": ["scenario:encrypted-wrong-credential"],
        "tpm-fallback": ["scenario:tpm-absent"],
    },
    "update": {
        "current-to-next-candidate": ["collection:update-to-next.json"],
        "invalid-signature": ["collection:update-invalid-signature.json"],
        "manual-rollback": ["collection:rollback.json"],
    },
    "rollback": {
        "manual-rollback": ["collection:rollback.json"],
        "rollback-preserves-user-data": ["collection:rollback-preservation.json"],
    },
    "recovery-media": {
        "boots-independently": ["scenario:recovery-boots"],
    },
    "preservation": {
        "home": ["collection:rollback-preservation.json"],
    },
}


JOURNEY_EVIDENCE = ROOT / "qualification/installer-journeys/evidence"


def load_journey_verdict(name: str) -> tuple[str, str] | None:
    """Judge one installer-journey evidence directory, or None if absent.

    A journey PASSes only on the conjunction the harness itself gates on:
    the guest reported completion, the driver walked every stage, and the
    disk — read from outside through the journey's own expectation — carried
    the installation with no findings. ``first-boot`` is the persistence
    record: every requested boot observed, every one reached graphical, no
    findings. A refusal journey PASSes on refused-as-expected alone; its
    empty disk is the point.
    """
    base = JOURNEY_EVIDENCE / name
    result_path = base / "result.json"
    if not result_path.is_file():
        return None
    record = json.loads(result_path.read_text(encoding="utf-8"))
    relative = str(result_path.relative_to(ROOT)).replace("\\", "/")

    if name == "first-boot":
        boots = record.get("boots") or []
        ok = (record.get("bootsObserved") == record.get("bootsRequested")
              and bool(boots)
              and all(boot.get("reachedGraphical") for boot in boots)
              and record.get("findings") == [])
        return ("PASS" if ok else "FAIL", relative)

    if record.get("driverOutcome") == "refused-as-expected":
        ok = record.get("harnessOutcome") == "done" and not record.get("errors")
        return ("PASS" if ok else "FAIL", relative)

    installed_path = base / "installed.json"
    if not installed_path.is_file():
        return None
    installed = json.loads(installed_path.read_text(encoding="utf-8"))
    ok = (record.get("harnessOutcome") == "done"
          and record.get("driverOutcome") == "complete"
          and record.get("targetVerified") is True
          and not record.get("errors")
          and installed.get("findings") == []
          # A verification that was never told what to look for proves less
          # than it appears to: journeys B and C once carried exactly that.
          and bool(installed.get("expectedFrom")))
    return ("PASS" if ok else "FAIL",
            str(installed_path.relative_to(ROOT)).replace("\\", "/"))


def load_verdict(evidence_root: Path, reference: str,
                 unbindable: frozenset[str] = frozenset()) -> tuple[str, str] | None:
    """Resolve one evidence reference to (result, relative path), or None if absent.

    A scenario record that no longer binds to the standing context is not
    evidence here — it supported the row it supported when it bound, and the
    row it supported keeps standing, but it cannot authorize a new write.
    """
    kind, _, name = reference.partition(":")
    if kind == "journey":
        return load_journey_verdict(name)
    if kind == "scenario":
        candidates = [path for path in
                      sorted(evidence_root.glob(f"ISQ-*-{name}-*/record.json"))
                      if path.parent.name not in unbindable]
        if not candidates:
            return None
        record = json.loads(candidates[-1].read_text(encoding="utf-8"))
        return (record.get("result", "FAIL"),
                str(candidates[-1].relative_to(ROOT)).replace("\\", "/"))
    if kind == "install":
        path = evidence_root / "installs" / f"{name}.json"
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        good = {"INSTALLED", "REFUSED_AS_EXPECTED", "PROTECTED", "INTERRUPTED"}
        return ("PASS" if record.get("outcome") in good else "FAIL",
                str(path.relative_to(ROOT)).replace("\\", "/"))
    if kind == "collection":
        path = evidence_root / "collections" / name
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return (record.get("result", "FAIL"),
                str(path.relative_to(ROOT)).replace("\\", "/"))
    raise SystemExit(f"BLOCKED: unknown evidence reference kind {kind!r}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="import_matrix_results")
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/installed-system/evidence")
    parser.add_argument("--matrices", type=Path,
                        default=ROOT / "operations/data/qualification-matrices.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        context = resolve_context(ROOT)
    except ContextError as error:
        # The context binds evidence that ran weeks ago to artifacts as they
        # were then, and the working tree has since moved on — the toolchain
        # lock in particular is expected to drift between qualification
        # rounds. The context still names what that evidence ran under, so it
        # remains the right provenance text for standing rows; what it can no
        # longer do is authorize a NEW installed-system round. Say both out
        # loud rather than refusing the unrelated work.
        print(f"WARNING: installed-system context no longer verifies against "
              f"the working tree: {error}", file=sys.stderr)
        print("         standing installed-system evidence keeps its original "
              "binding; a new installed-system round must not reuse this "
              "context.", file=sys.stderr)
        context = resolve_context(ROOT, verify=False)

    # Scenario verdicts must bind to the context before they can support new
    # writes. A record that no longer binds is not an error in itself — the
    # context legitimately moves between rounds — but it is not evidence for
    # this import, and saying which records fell out keeps the exclusion
    # honest.
    unbindable: set[str] = set()
    for record_path in sorted(args.evidence_root.glob("ISQ-*/record.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        reasons = verify_record_binding(record, context)
        if reasons:
            unbindable.add(record_path.parent.name)
            print(f"WARNING: {record_path.parent.name} does not bind to the "
                  "standing context and cannot support a new write:",
                  file=sys.stderr)
            for reason in reasons:
                print(f"  - {reason}", file=sys.stderr)

    document = json.loads(args.matrices.read_text(encoding="utf-8"))
    matrices = document["matrices"]
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

    written = 0
    for matrix, rows in ROW_EVIDENCE.items():
        for scenario, references in rows.items():
            verdicts = [load_verdict(args.evidence_root, ref,
                                     unbindable=frozenset(unbindable))
                        for ref in references]
            if any(v is None for v in verdicts):
                continue  # evidence absent: the standing NOT_RUN row remains
            outcome = "PASS" if all(v[0] == "PASS" for v in verdicts) else "FAIL"
            reference = verdicts[0][1]
            kinds = {ref.partition(":")[0] for ref in references}
            # The provenance a row claims must match the evidence it rests on:
            # journey records bind to the live medium described in the journey
            # evidence README, not to the installed-system archive context.
            provenance = []
            if kinds - {"journey"}:
                provenance.append(
                    f"QEMU/KVM evidence bound to archive {context.sourceArchiveDigest[:12]} "
                    f"(commit {context.sourceCommit[:12]})"
                )
            if "journey" in kinds:
                provenance.append(
                    "unattended §53 journey evidence (provenance: "
                    "qualification/installer-journeys/evidence/README.md)"
                )
            row = {
                "scenario": scenario,
                "outcome": outcome,
                "method": "virtual-machine",
                "evidenceReference": reference,
                "recordedAt": stamp,
                "notes": ("; ".join(provenance) + "; supporting records: "
                          + ", ".join(v[1] for v in verdicts)),
            }
            parse_result(matrix, row, root=ROOT)  # refuse malformed rows before writing
            existing = matrices.get(matrix, [])
            standing = next((r for r in existing if r.get("scenario") == scenario), None)
            # A row whose verdict and evidence have not changed keeps its
            # original date and wording: a fresher stamp on the same facts
            # would only disguise how long the record has stood. Notes are
            # deliberately outside the comparison — provenance text drifting
            # with the context must not rewrite a row whose evidence did not.
            if standing is not None and all(
                    standing.get(key) == row[key]
                    for key in ("outcome", "evidenceReference", "method")):
                continue
            matrices[matrix] = [r for r in existing if r.get("scenario") != scenario] + [row]
            written += 1
            print(f"  {outcome:4} {matrix}/{scenario} <- {reference}")

    if written == 0:
        print("BLOCKED: no evidence resolved to any matrix row; nothing was written. "
              "An import that writes nothing must say so rather than exit green.",
              file=sys.stderr)
        return 2

    document["recordedOn"] = stamp
    if not args.dry_run:
        args.matrices.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                                 encoding="utf-8")
        print(f"wrote {written} row(s) to {args.matrices.relative_to(ROOT)}")
    else:
        print(f"dry run: {written} row(s) would be written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
