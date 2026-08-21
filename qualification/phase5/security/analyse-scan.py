#!/usr/bin/python3
"""Is a `dir:` scan comparable to the `oci-archive:` scan Phase 4 used?

Phase 4 reports "59 fixable findings (8 Critical, 28 High)" for the candidate.
A `dir:` scan of the same image reports 183 (2 Critical, 106 High). Before that
difference can be attributed to anything, it has to be established whether the
two methods count the same things.

The obvious suspect: a directory scan catalogs each *binary* it finds, so one Go
module vulnerability linked into podman, skopeo, bootc and toolbox is four
matches, where an image scan that resolved to a single package is one. The
July disposition record recorded `golang.org/x/crypto` as 13 findings for
exactly four binaries.

This counts distinct advisories, distinct (advisory, package) pairs, and the
artifact types they were found in, so the question is answered rather than
guessed.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

path = sys.argv[1]
document = json.load(open(path, encoding="utf-8"))
matches = document["matches"]

print(f"raw matches: {len(matches)}")

advisories = {m["vulnerability"]["id"] for m in matches}
print(f"distinct advisory ids: {len(advisories)}")

pairs = {(m["vulnerability"]["id"], m["artifact"]["name"]) for m in matches}
print(f"distinct (advisory, package) pairs: {len(pairs)}")

print("\nby artifact type:")
for kind, count in Counter(m["artifact"]["type"] for m in matches).most_common():
    print(f"  {kind:18s} {count}")

print("\nseverity, counting distinct advisories once:")
severity_of: dict[str, str] = {}
for m in matches:
    identifier = m["vulnerability"]["id"]
    severity_of.setdefault(identifier, m["vulnerability"]["severity"])
for name in ("Critical", "High", "Medium", "Low", "Negligible", "Unknown"):
    n = sum(1 for s in severity_of.values() if s == name)
    if n:
        print(f"  {name}: {n}")

print("\nmost duplicated advisories (same id, many locations):")
for identifier, count in Counter(m["vulnerability"]["id"] for m in matches).most_common(6):
    locations = {
        loc.get("path", "")
        for m in matches
        if m["vulnerability"]["id"] == identifier
        for loc in m["artifact"].get("locations", [])
    }
    print(f"  {identifier:24s} x{count}  in {len(locations)} location(s)")
    for location in sorted(locations)[:5]:
        print(f"        {location}")

print("\npackages carrying the most matches:")
for name, count in Counter(m["artifact"]["name"] for m in matches).most_common(8):
    print(f"  {name:42s} {count}")
