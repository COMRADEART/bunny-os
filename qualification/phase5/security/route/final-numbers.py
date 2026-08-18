#!/usr/bin/python3
"""The numbers the Phase 5 security section needs, each one measured.

Two comparisons are made, and they are kept apart on purpose:

  * go-module only, module granularity, Phase 4 against Phase 5. Same package
    type, same matching granularity, nineteen days apart. This is the only
    like-for-like comparison available.
  * everything, Phase 5 only. Phase 4 has no counterpart because its scan
    catalogued no RPM at all.
"""
import json
from collections import Counter, defaultdict

RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Negligible": 4, "Unknown": 5}

def load(path):
    return json.load(open(path, encoding="utf-8")).get("matches", [])

def distinct_by_severity(matches, artifact_type=None):
    worst = {}
    for match in matches:
        if artifact_type and match["artifact"]["type"] != artifact_type:
            continue
        identifier = match["vulnerability"]["id"]
        severity = match["vulnerability"]["severity"]
        if identifier not in worst or RANK.get(severity, 9) < RANK.get(worst[identifier], 9):
            worst[identifier] = severity
    counts = Counter(worst.values())
    ordered = {name: counts[name] for name in
               ("Critical", "High", "Medium", "Low", "Negligible", "Unknown") if counts[name]}
    return len(worst), ordered, set(worst)

PHASE4 = "/mnt/c/Users/allam/Documents/new/bunny-os/evidence/vulnerability/beta-grype.json"
SBOM = "/home/bunny/p5-evidence/security-sbom/sbom-fixed.json"
FILESYSTEM = "/home/bunny/p5-evidence/security/candidate-fixed.json"

p4, p5s, p5f = load(PHASE4), load(SBOM), load(FILESYSTEM)

print("== go-module only, module granularity, like for like ==")
for label, matches in (("phase 4 (beta, oci-archive)", p4), ("phase 5 (candidate, sbom)", p5s)):
    total, counts, _ = distinct_by_severity(matches, "go-module")
    print(f"  {label:34s} distinct={total:3d}  {counts}")

print()
print("== the whole candidate, module granularity (sbom route) ==")
total, counts, _ = distinct_by_severity(p5s)
print(f"  all types                          distinct={total:3d}  {counts}")
for artifact_type in ("go-module", "rpm", "python", "UnknownPackage"):
    total, counts, _ = distinct_by_severity(p5s, artifact_type)
    if total:
        print(f"  {artifact_type:34s} distinct={total:3d}  {counts}")

print()
print("== the same candidate, function granularity (filesystem route) ==")
total, counts, _ = distinct_by_severity(p5f)
print(f"  all types                          distinct={total:3d}  {counts}")
for artifact_type in ("go-module", "rpm", "python", "linux-kernel"):
    total, counts, _ = distinct_by_severity(p5f, artifact_type)
    if total:
        print(f"  {artifact_type:34s} distinct={total:3d}  {counts}")

print()
print("== what the two Phase 5 routes disagree about ==")
_, _, sbom_ids = distinct_by_severity(p5s)
_, _, fs_ids = distinct_by_severity(p5f)
only_sbom = sorted(sbom_ids - fs_ids)
only_fs = sorted(fs_ids - sbom_ids)
print(f"  reported by the sbom route only: {len(only_sbom)}")
print(f"  reported by the filesystem route only: {len(only_fs)}")
severities = {}
for match in p5s:
    identifier = match["vulnerability"]["id"]
    severity = match["vulnerability"]["severity"]
    if identifier not in severities or RANK.get(severity, 9) < RANK.get(severities[identifier], 9):
        severities[identifier] = severity
blocking = [i for i in only_sbom if severities.get(i) in ("Critical", "High")]
print(f"  of those, Critical or High: {len(blocking)}")
for identifier in blocking:
    packages = sorted({
        f"{m['artifact']['name']}@{m['artifact'].get('version')}"
        for m in p5s if m["vulnerability"]["id"] == identifier
    })
    print(f"    {severities[identifier]:8s} {identifier:26s} {', '.join(packages)[:70]}")

print()
print("== raw-match inflation from the ostree hardlink ==")
for label, matches in (("phase 5 sbom", p5s), ("phase 5 filesystem", p5f)):
    ostree = sum(
        1 for m in matches
        for location in (m["artifact"].get("locations") or [])
        if str(location.get("path", "")).startswith("/sysroot/ostree/repo/objects/")
    )
    print(f"  {label:20s} raw={len(matches):4d} of which matched via an ostree object path: {ostree}")
