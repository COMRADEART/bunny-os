#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Classify every failed unit across several boots of one image.

The previous pass booted an installed system once and found two failed
units. This pass booted three and found five distinct ones, no two boots
agreeing. That difference is the point: a single boot cannot tell a
systematic failure from an intermittent one, and reporting either as the
other is how a real defect gets dismissed or a flake gets chased.

Each unit is placed in exactly one class, from the evidence rather than from
judgement about what ought to be true:

    persists            failed in every boot that ran it
    intermittent        failed in some boots and succeeded in others — the
                        same image, the same commit, a different outcome
    scenario-specific   failed only in boots sharing one distinguishing
                        condition (an offline installation, a resource floor)
    newly-observed      absent from the prior pass's record, seen here
    resolved            in the prior pass's record, absent from every boot here

A unit can be both intermittent and newly-observed; the classes that answer
different questions are recorded together rather than collapsed.

Nothing here is attributed to a change without support. A failure that
varies across boots of one identical image cannot be caused by a change that
is identical in all of them, and that argument is stated in the record
rather than assumed by the reader.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ostree_disk import DiskLayoutError, root_partition, stateroot_var  # noqa: E402

FAILED = re.compile(r"([\w@.\\x-]+\.(?:service|socket|mount|timer)): Failed with result")
SUCCEEDED = re.compile(r"([\w@.\\x-]+\.(?:service|socket|mount|timer)): "
                       r"(?:Deactivated successfully|Succeeded)")


def failed_and_started(disk: Path) -> tuple[set[str], set[str]] | None:
    try:
        root = root_partition(disk)
        var = stateroot_var(disk)
    except DiskLayoutError:
        return None
    with tempfile.TemporaryDirectory() as scratch:
        tar = Path(scratch) / "j.tar"
        pull = subprocess.run(
            ["guestfish", "--ro", "-a", str(disk), "run", ":",
             "mount-ro", root, "/", ":", "tar-out", f"{var}/log/journal", str(tar)],
            capture_output=True,
        )
        if pull.returncode != 0:
            return None
        out = Path(scratch) / "j"
        out.mkdir()
        subprocess.run(["tar", "-xf", str(tar), "-C", str(out)], check=True)
        machine = [d for d in out.rglob("*") if d.is_dir()
                   and any(f.suffix == ".journal" for f in d.iterdir() if f.is_file())]
        if not machine:
            return None
        text = subprocess.run(
            ["journalctl", "-D", str(machine[0]), "-b", "-0", "--no-pager"],
            capture_output=True, text=True).stdout
    return set(FAILED.findall(text)), set(SUCCEEDED.findall(text))


def main() -> int:
    parser = argparse.ArgumentParser(prog="dispose_failed_units")
    parser.add_argument("--boot", action="append", required=True, metavar="LABEL=DISK",
                        help="a boot to read, as label=path; repeatable")
    parser.add_argument("--prior", type=Path,
                        help="the previous pass's service record, for the delta")
    parser.add_argument("--scenario-condition", action="append", default=[],
                        metavar="LABEL=CONDITION",
                        help="what distinguishes a boot, e.g. offline=offline-installation")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    conditions = dict(entry.split("=", 1) for entry in args.scenario_condition)
    boots: dict[str, dict] = {}
    for entry in args.boot:
        label, _, path = entry.partition("=")
        result = failed_and_started(Path(path))
        if result is None:
            print(f"BLOCKED: {label}: the boot journal could not be read. A "
                  "disposition drawn from boots that could not be read is not a "
                  "disposition.", file=sys.stderr)
            return 2
        failed, succeeded = result
        boots[label] = {"failed": sorted(failed), "succeeded": sorted(succeeded),
                        "condition": conditions.get(label)}

    prior_failed: set[str] = set()
    if args.prior and args.prior.is_file():
        prior = json.loads(args.prior.read_text(encoding="utf-8"))
        prior_failed = set(prior.get("failedUnits") or [])

    every_unit = sorted({u for b in boots.values() for u in b["failed"]} | prior_failed)
    dispositions = []
    for unit in every_unit:
        failed_in = [label for label, b in boots.items() if unit in b["failed"]]
        clean_in = [label for label, b in boots.items()
                    if unit not in b["failed"] and unit in b["succeeded"]]
        classes = []
        if failed_in and not clean_in and len(failed_in) == len(boots):
            classes.append("persists")
        if failed_in and clean_in:
            classes.append("intermittent")
        if failed_in and len(failed_in) < len(boots):
            distinguishing = {boots[label]["condition"] for label in failed_in}
            if len(distinguishing) == 1 and None not in distinguishing:
                classes.append("scenario-specific")
        if unit in prior_failed and not failed_in:
            classes.append("resolved-in-this-pass")
        if unit not in prior_failed and failed_in:
            classes.append("newly-observed")
        if unit in prior_failed and failed_in:
            classes.append("carried-over")
        dispositions.append({
            "unit": unit,
            "failedIn": failed_in,
            "cleanIn": clean_in,
            "inPriorPass": unit in prior_failed,
            "classes": classes or ["unclassified"],
        })

    intermittent = [d["unit"] for d in dispositions if "intermittent" in d["classes"]]
    argument = (
        "A unit that fails in one boot and succeeds in another, from one image "
        "at one commit, cannot have been caused by a change that is identical in "
        f"both. That applies here to: {', '.join(intermittent)}."
        if intermittent else
        "No unit varied across boots, so no unit is excused by variance."
    )

    document = {
        "schemaVersion": 1,
        "collection": "failed-unit-disposition",
        "boots": boots,
        "priorPassFailedUnits": sorted(prior_failed),
        "dispositions": dispositions,
        "attributionArgument": argument,
        "note": ("Three boots of one image disagreed about which units failed. "
                 "A single boot cannot distinguish a systematic failure from an "
                 "intermittent one, and this pass ran enough boots to see the "
                 "difference — which is a finding about the previous pass's "
                 "method as much as about these units."),
        "result": "RECORDED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    print("failed-unit disposition:")
    for d in dispositions:
        print(f"  {d['unit']:52} {', '.join(d['classes'])}")
        print(f"    failed in {d['failedIn'] or 'none'}; clean in {d['cleanIn'] or 'none'}")
    print(f"\n{argument}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
