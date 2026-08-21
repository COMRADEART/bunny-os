#!/usr/bin/python3
"""What version range does the current database record for each advisory?

`grype db search --vuln X -o json` returns one entry per *provider*. Most of
them are Chainguard's per-image rows, which say nothing about the Go module.
The one that matters is the provider whose ecosystem is Go, because that is the
record the Go matcher uses against `golang.org/x/crypto`.
"""
import json
import pathlib

DIRECTORY = pathlib.Path("/home/bunny/p5-evidence/security-delta")
ADVISORIES = [
    "GHSA-5cgq-3rg8-m6cv", "GHSA-89gr-r52h-f8rx", "GHSA-f5wc-c3c7-36mc",
    "GHSA-jppx-rxg9-jmrx", "GHSA-rm3j-f69w-wqmq", "GHSA-vgwf-h737-ff37",
    "GHSA-x527-x647-q7gg", "GHSA-p77j-4mvh-x3m3",
]

for advisory in ADVISORIES:
    path = DIRECTORY / f"{advisory}.json"
    if not path.is_file():
        print(f"{advisory}: no result file")
        continue
    rows = json.loads(path.read_text(encoding="utf-8"))
    providers = sorted({row["vulnerability"].get("provider") for row in rows})
    go_rows = []
    for row in rows:
        for package in row.get("packages", []):
            ecosystem = (package.get("package") or {}).get("ecosystem")
            if ecosystem in ("go", "golang", "go-module"):
                go_rows.append((row["vulnerability"], package))
    print(f"=== {advisory} | providers={providers} | go rows={len(go_rows)}")
    for vulnerability, package in go_rows:
        name = package["package"]["name"]
        ranges = (package.get("detail") or {}).get("ranges", [])
        constraints = [
            (entry.get("version", {}).get("constraint"), entry.get("fix", {}).get("version"))
            for entry in ranges
        ]
        print(f"    provider={vulnerability.get('provider')} severity={vulnerability.get('severity')}"
              f" pkg={name}")
        for constraint, fix in constraints:
            print(f"      constraint: {constraint!r}  fix={fix!r}")
    print()
