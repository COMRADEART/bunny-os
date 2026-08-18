#!/usr/bin/python3
"""Why did the filesystem scan miss seven Critical findings the SBOM scan makes?

Three things to look at:

  1. what the filesystem scan wrote to stderr -- grype warns when Go binaries
     carry no function symbols, and the presence or absence of that warning
     tells you which matching granularity it used;
  2. the matchDetails grype attaches to a finding both scans agree on
     (GHSA-p77j-4mvh-x3m3 against grpc), because the matcher name is recorded
     there;
  3. whether the filesystem scan catalogued the skopeo binary at all.
"""
import json
import pathlib

DIR_SCAN = pathlib.Path("/home/bunny/p5-evidence/security")
SBOM_SCAN = pathlib.Path("/home/bunny/p5-evidence/security-sbom")

print("=== stderr from the filesystem scan ===")
for name in ("candidate-fixed.err", "candidate-all.err"):
    path = DIR_SCAN / name
    print(f"--- {name} ({path.stat().st_size if path.exists() else 'missing'} bytes)")
    if path.exists():
        print("   ", path.read_text(encoding="utf-8", errors="replace").strip()[:800])

print("\n=== stderr from the SBOM scan ===")
for name in ("sbom-fixed.err",):
    path = SBOM_SCAN / name
    print(f"--- {name}")
    if path.exists():
        print("   ", path.read_text(encoding="utf-8", errors="replace").strip()[:800])

def details(path, advisory):
    document = json.load(open(path, encoding="utf-8"))
    out = []
    for match in document.get("matches", []):
        if match["vulnerability"]["id"] == advisory:
            out.append({
                "artifact": f"{match['artifact']['name']}@{match['artifact'].get('version')}",
                "locations": [l.get("path") for l in match["artifact"].get("locations", [])],
                "matchDetails": match.get("matchDetails"),
            })
    return out

print("\n=== GHSA-p77j-4mvh-x3m3 (grpc) as each scan records it ===")
for label, path in (
    ("filesystem", DIR_SCAN / "candidate-all.json"),
    ("sbom", SBOM_SCAN / "sbom-all.json"),
):
    print(f"--- {label}")
    for row in details(path, "GHSA-p77j-4mvh-x3m3")[:2]:
        print("    artifact:", row["artifact"], row["locations"])
        for detail in row["matchDetails"] or []:
            print("      type:", detail.get("type"), "matcher:", detail.get("matcher"))
            searched = detail.get("searchedBy") or {}
            print("      searchedBy:", json.dumps(searched)[:220])

print("\n=== every artifact the filesystem scan matched that lives in /usr/bin ===")
document = json.load(open(DIR_SCAN / "candidate-all.json", encoding="utf-8"))
seen = set()
for match in document.get("matches", []):
    for location in match["artifact"].get("locations", []):
        path = location.get("path", "")
        if path.startswith("/usr/bin/"):
            seen.add((path, match["artifact"]["name"], match["artifact"].get("version")))
for row in sorted(seen):
    print("   ", row)
