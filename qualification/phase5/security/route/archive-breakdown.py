#!/usr/bin/python3
"""Four routes, one candidate, one database: which variable actually moved?

The oci-archive scan is the control that was missing. It is the release gate's
own route, run against the same candidate with the same database as the two
Phase 5 routes -- so if it agrees with the filesystem route, the route is not
what changed the Critical count, and the database is.
"""
import json
from collections import Counter, defaultdict

RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Negligible": 4, "Unknown": 5}

ROUTES = [
    ("phase 4 archive, JULY db, beta image",
     "/mnt/c/Users/allam/Documents/new/bunny-os/evidence/vulnerability/beta-grype.json"),
    ("phase 5 archive, AUG db, candidate",
     "/home/bunny/p5-evidence/security-archive/archive-fixed.json"),
    ("phase 5 filesystem, AUG db, candidate",
     "/home/bunny/p5-evidence/security/candidate-fixed.json"),
    ("phase 5 sbom, AUG db, candidate",
     "/home/bunny/p5-evidence/security-sbom/sbom-fixed.json"),
]

summaries = {}
for label, path in ROUTES:
    try:
        matches = json.load(open(path, encoding="utf-8")).get("matches", [])
    except Exception as error:  # noqa: BLE001
        print(f"{label}: unreadable: {error}")
        continue
    worst, by_type = {}, defaultdict(set)
    for match in matches:
        identifier = match["vulnerability"]["id"]
        severity = match["vulnerability"]["severity"]
        if identifier not in worst or RANK.get(severity, 9) < RANK.get(worst[identifier], 9):
            worst[identifier] = severity
        by_type[match["artifact"]["type"]].add(identifier)
    counts = Counter(worst.values())
    summaries[label] = set(worst)
    ordered = {n: counts[n] for n in ("Critical", "High", "Medium", "Low", "Unknown") if counts[n]}
    types = {t: len(v) for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))}
    print(f"\n=== {label}")
    print(f"    raw {len(matches):4d}  distinct {len(worst):4d}  {ordered}")
    print(f"    distinct by artifact type: {types}")

print("\n=== do the two symbol-capable Phase 5 routes agree? ===")
archive = summaries.get("phase 5 archive, AUG db, candidate", set())
filesystem = summaries.get("phase 5 filesystem, AUG db, candidate", set())
sbom = summaries.get("phase 5 sbom, AUG db, candidate", set())
print(f"    archive vs filesystem: identical={archive == filesystem} "
      f"(archive-only {len(archive - filesystem)}, filesystem-only {len(filesystem - archive)})")
print(f"    sbom minus archive: {len(sbom - archive)} advisories the archive route does not report")
