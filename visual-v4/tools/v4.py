#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The V4 framework-closure harness.

V4 exists to answer one question — Smithay or libmutter — and the honest answer
depends entirely on measurements that are easy to fake and expensive to make. So
the arithmetic lives here rather than in prose, and the rules that matter are
enforced structurally rather than trusted to a reader.

Three rules do the work:

* Only ``PASS`` satisfies a gate. Every other state, including the states that
  sound like excuses (``NOT_RUN``, ``NOT_AVAILABLE``), scores zero and blocks a
  mandatory gate. There is no state that means "would have passed".

* A framework cannot be selected while any mandatory gate is unsatisfied. This is
  checked before the score is even looked at, because a score is a comparison
  between two candidates and an unqualified candidate is not one.

* A gate may only claim ``PASS`` with an evidence reference attached. A pass
  without evidence is refused as malformed, not accepted and footnoted.

The result is that the only way to move this report toward a verdict is to go and
measure something.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "visual-v4" / "contract" / "shared-test-contract.json"
RESULTS = ROOT / "visual-v4" / "contract" / "measured-results.json"

SATISFYING = "PASS"


class ContractError(Exception):
    """The contract or the results are malformed. This is never a soft failure."""


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"{path.name} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"{path.name} is not valid JSON: {exc}") from exc


def validate(contract: dict, results: dict) -> None:
    """Refuse a results file that does not correspond to the contract.

    The failures this catches are the ones the evidence rules name directly:
    duplicate records, missing runs, an unknown state slipped into a matrix, and
    a ``PASS`` with nothing behind it.
    """
    states = set(contract["resultStates"])
    gate_ids = [g["id"] for g in contract["gates"]]

    duplicates = [gid for gid, n in Counter(gate_ids).items() if n > 1]
    if duplicates:
        raise ContractError(f"contract declares duplicate gates: {sorted(duplicates)}")

    if set(results["arms"]) != set(contract["arms"]):
        raise ContractError(
            f"results cover arms {sorted(results['arms'])}, contract requires {sorted(contract['arms'])}"
        )

    for arm, payload in results["arms"].items():
        rows = payload["results"]
        seen = [r["id"] for r in rows]

        dupes = [gid for gid, n in Counter(seen).items() if n > 1]
        if dupes:
            raise ContractError(f"{arm}: duplicate results for {sorted(dupes)}")

        missing = set(gate_ids) - set(seen)
        if missing:
            raise ContractError(f"{arm}: no result recorded for {sorted(missing)}")

        unknown = set(seen) - set(gate_ids)
        if unknown:
            raise ContractError(f"{arm}: results for gates not in the contract: {sorted(unknown)}")

        for row in rows:
            if row["state"] not in states:
                raise ContractError(
                    f"{arm}/{row['id']}: {row['state']!r} is not one of {sorted(states)}"
                )
            # A pass has to point at something. This is the guard that stops a
            # matrix being walked forward by editing one word.
            if row["state"] == SATISFYING and not row.get("evidence"):
                raise ContractError(
                    f"{arm}/{row['id']}: PASS recorded with no evidence reference. "
                    "A gate cannot pass on assertion."
                )


def unsatisfied_mandatory(contract: dict, results: dict, arm: str) -> list[tuple[str, str]]:
    """Mandatory gates that are not PASS, with the state they actually hold."""
    mandatory = {g["id"] for g in contract["gates"] if g["mandatory"]}
    by_id = {r["id"]: r for r in results["arms"][arm]["results"]}
    return sorted(
        (gid, by_id[gid]["state"]) for gid in mandatory if by_id[gid]["state"] != SATISFYING
    )


def score(contract: dict, results: dict, arm: str) -> tuple[float, dict[str, float]]:
    """Weighted score, counting only PASS.

    The score is reported even when the arm is disqualified, because hiding it
    would make the disqualification look like the whole story. It carries no
    authority: ``verdict`` never consults it unless the mandatory gates are met.
    """
    weights = contract["scorecard"]
    by_id = {r["id"]: r for r in results["arms"][arm]["results"]}

    grouped: dict[str, list[str]] = {}
    for gate in contract["gates"]:
        grouped.setdefault(gate["group"], []).append(gate["id"])

    # Contract groups map onto scorecard categories by name where they match;
    # anything unmapped scores zero rather than being silently redistributed.
    mapping = {
        "accessibility": "accessibility",
        "input-methods": "input-methods",
        "screen-sharing": "screen-sharing-and-portals",
        "session-lock": "session-lock-and-authentication",
        "compat": "application-compatibility",
        "rendering": "rendering-and-frame-pacing",
        "display": "multi-display-and-scaling",
    }

    breakdown: dict[str, float] = {}
    for group, gate_ids in grouped.items():
        category = mapping.get(group)
        if category is None:
            continue
        passed = sum(1 for gid in gate_ids if by_id[gid]["state"] == SATISFYING)
        breakdown[category] = round(weights[category] * passed / len(gate_ids), 2)

    # Categories with no measurable gate in the contract stay explicitly zero.
    for category in weights:
        breakdown.setdefault(category, 0.0)

    return round(sum(breakdown.values()), 2), breakdown


def verdict(contract: dict, results: dict) -> tuple[str, list[str]]:
    """The allowed verdict, derived rather than chosen.

    A selection verdict requires an arm whose every mandatory gate is PASS. When
    no arm qualifies the verdict is withheld, and the reasons are the gates.
    """
    reasons: list[str] = []
    qualified = []
    for arm in contract["arms"]:
        outstanding = unsatisfied_mandatory(contract, results, arm)
        if outstanding:
            reasons.append(
                f"{arm}: {len(outstanding)} mandatory gate(s) unsatisfied — "
                + ", ".join(f"{gid}={state}" for gid, state in outstanding)
            )
        else:
            qualified.append(arm)

    if not qualified:
        return "WITHHELD", reasons
    if len(qualified) > 1:
        return "CONTINUE_DUAL_TRACK", reasons
    return {"smithay": "SELECT_SMITHAY", "libmutter": "SELECT_LIBMUTTER"}[qualified[0]], reasons


def report(contract: dict, results: dict) -> str:
    lines = [
        f"V4 framework closure — contract {contract['contract']}",
        f"environment: {results['environment']}",
        "",
    ]
    for arm in contract["arms"]:
        rows = results["arms"][arm]["results"]
        counts = Counter(r["state"] for r in rows)
        total, _ = score(contract, results, arm)
        lines.append(f"  {arm}:")
        lines.append(
            "    states: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
        lines.append(f"    score:  {total} of 100 (PASS gates only)")
        outstanding = unsatisfied_mandatory(contract, results, arm)
        lines.append(f"    mandatory unsatisfied: {len(outstanding)} of 8")
    lines.append("")

    decision, reasons = verdict(contract, results)
    lines.append(f"VERDICT: {decision}")
    for reason in reasons:
        lines.append(f"  {reason}")
    if decision == "WITHHELD":
        lines.append("")
        lines.append(
            "No framework may be selected. A numeric score does not override an "
            "unsatisfied mandatory gate, and no gate has been measured."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("validate", "report", "verdict"), help="what to do"
    )
    args = parser.parse_args()

    try:
        contract = load(CONTRACT)
        results = load(RESULTS)
        validate(contract, results)
    except ContractError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    if args.command == "validate":
        print(
            f"contract valid: {len(contract['gates'])} gates, "
            f"{sum(g['mandatory'] for g in contract['gates'])} mandatory, "
            f"{len(contract['arms'])} arms"
        )
        return 0

    print(report(contract, results))
    decision, _ = verdict(contract, results)
    # A withheld verdict is not a success. Exiting zero here would let a caller
    # treat "nothing measured" as "nothing wrong".
    return 0 if decision != "WITHHELD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
