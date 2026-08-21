#!/usr/bin/python3
"""Negative control for the seven vanished Criticals.

The database says GHSA-5cgq-3rg8-m6cv is Critical and applies to
`golang.org/x/crypto <0.52.0`. The SBOM says the candidate contains
`golang.org/x/crypto v0.46.0` in /usr/bin/skopeo. 0.46.0 < 0.52.0. The scan of
that image reported none of the seven.

Either the matcher will not match this package, or something about the full
scan suppressed it. This takes the *exact* package records out of the
candidate's own SBOM, writes them into a minimal SPDX document, and scans that.

  reports the seven  -> the matcher is fine; the full scan lost them
  reports none       -> the matcher will not match this package at all

Writing a tiny JSON file is the only disk this touches.
"""
import json
import pathlib
import subprocess
import sys

SOURCE = pathlib.Path("/home/bunny/p5-evidence/sbom/candidate.spdx.json")
OUT = pathlib.Path("/home/bunny/p5-evidence/security-delta")
OUT.mkdir(parents=True, exist_ok=True)

document = json.loads(SOURCE.read_text(encoding="utf-8"))
wanted = [
    package for package in document.get("packages", [])
    if package.get("name") in ("golang.org/x/crypto", "google.golang.org/grpc")
]
print(f"lifted {len(wanted)} package records out of the candidate SBOM")
for package in wanted:
    print("   ", package.get("name"), package.get("versionInfo"), "|",
          (package.get("sourceInfo") or "")[:70])

minimal = {
    "spdxVersion": document.get("spdxVersion", "SPDX-2.3"),
    "dataLicense": document.get("dataLicense", "CC0-1.0"),
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "crypto-control",
    "documentNamespace": "https://bunny-os.invalid/phase5/crypto-control",
    "creationInfo": document.get("creationInfo", {"created": "2026-08-17T00:00:00Z",
                                                  "creators": ["Tool: bunny-os-phase5"]}),
    "packages": wanted,
    "relationships": [
        {"spdxElementId": "SPDXRef-DOCUMENT",
         "relatedSpdxElement": package["SPDXID"],
         "relationshipType": "DESCRIBES"}
        for package in wanted if package.get("SPDXID")
    ],
}
control = OUT / "crypto-control.spdx.json"
control.write_text(json.dumps(minimal, indent=1), encoding="utf-8")
print("wrote", control, control.stat().st_size, "bytes")

result = subprocess.run(
    ["grype", f"sbom:{control}", "--output", "json"],
    capture_output=True, text=True,
)
print("grype exit:", result.returncode)
if result.returncode != 0:
    print(result.stderr[:1500])
    sys.exit(0)

scan = json.loads(result.stdout)
matches = scan.get("matches", [])
print(f"matches: {len(matches)}")
for match in matches:
    vulnerability = match["vulnerability"]
    artifact = match["artifact"]
    print(f"    {vulnerability['id']:24s} {vulnerability['severity']:9s} "
          f"{artifact['name']}@{artifact.get('version')} "
          f"fix={vulnerability.get('fix', {}).get('versions')}")
(OUT / "crypto-control-scan.json").write_text(result.stdout, encoding="utf-8")
