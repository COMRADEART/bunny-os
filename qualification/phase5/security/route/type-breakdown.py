#!/usr/bin/python3
"""Distinct advisories by artifact type, for each scan route.

The point of the breakdown is one question: which routes can see RPM-packaged
software at all?
"""
import json
from collections import Counter, defaultdict

RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Negligible": 4, "Unknown": 5}

ROUTES = [
    ("phase 4, oci-archive, only-fixed",
     "/mnt/c/Users/allam/Documents/new/bunny-os/evidence/vulnerability/beta-grype.json"),
    ("phase 5, mounted filesystem, only-fixed",
     "/home/bunny/p5-evidence/security/candidate-fixed.json"),
    ("phase 5, sbom, only-fixed",
     "/home/bunny/p5-evidence/security-sbom/sbom-fixed.json"),
]

for label, path in ROUTES:
    try:
        document = json.load(open(path, encoding="utf-8"))
    except Exception as error:  # noqa: BLE001
        print(f"\n=== {label}: unreadable: {error}")
        continue
    matches = document.get("matches", [])
    by_type = defaultdict(set)
    severity_by_type = defaultdict(Counter)
    for match in matches:
        artifact_type = match["artifact"]["type"]
        identifier = match["vulnerability"]["id"]
        by_type[artifact_type].add(identifier)
        severity_by_type[artifact_type][match["vulnerability"]["severity"]] += 1
    print(f"\n=== {label}")
    print(f"    raw matches {len(matches)}")
    for artifact_type in sorted(by_type, key=lambda t: -len(by_type[t])):
        worst = min(
            (s for s in severity_by_type[artifact_type]),
            key=lambda s: RANK.get(s, 9),
        )
        print(f"    {artifact_type:14s} distinct={len(by_type[artifact_type]):3d} "
              f"worst={worst}  {dict(severity_by_type[artifact_type])}")
