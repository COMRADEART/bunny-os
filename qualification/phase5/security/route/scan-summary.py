#!/usr/bin/python3
"""Summarise grype JSON results: raw matches, distinct advisories, severities.

Distinct-by-advisory is the number that survives the hardlink problem. A bootc
deployment exposes the same binary at /usr/bin/<name> and at
/sysroot/ostree/repo/objects/<hash>.file, so every finding against a Go binary
appears twice in a filesystem scan. Raw match counts are inflated by that;
advisory identity is not.
"""
import json
import sys
from collections import Counter

RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Negligible": 4, "Unknown": 5}

for path in sys.argv[1:]:
    try:
        document = json.load(open(path, encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - a summary must not mask the reason
        print(f"\n=== {path}: unreadable: {error}")
        continue
    matches = document.get("matches", [])
    by_advisory = {}
    for match in matches:
        by_advisory.setdefault(match["vulnerability"]["id"], []).append(match)
    raw = Counter(m["vulnerability"]["severity"] for m in matches)
    distinct = Counter(
        min((m["vulnerability"]["severity"] for m in rows), key=lambda s: RANK.get(s, 9))
        for rows in by_advisory.values()
    )
    print(f"\n=== {path}")
    print(f"    raw matches: {len(matches)}  {dict(raw)}")
    print(f"    distinct advisories: {len(by_advisory)}  {dict(distinct)}")
    criticals = sorted(
        identifier for identifier, rows in by_advisory.items()
        if any(m["vulnerability"]["severity"] == "Critical" for m in rows)
    )
    print(f"    Critical advisories ({len(criticals)}):")
    for identifier in criticals:
        packages = sorted({
            f"{m['artifact']['name']}@{m['artifact'].get('version')}"
            for m in by_advisory[identifier]
        })
        print(f"      {identifier:26s} {', '.join(packages)}")
