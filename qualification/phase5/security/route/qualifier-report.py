#!/usr/bin/python3
"""List the go_imports qualifier the database carries for each advisory."""
import json
import pathlib
import sys

DIRECTORY = pathlib.Path(sys.argv[1])
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
    printed = False
    for row in rows:
        for package in row.get("packages", []):
            if (package.get("package") or {}).get("ecosystem") not in ("go", "golang", "go-module"):
                continue
            detail = package.get("detail") or {}
            qualifiers = (detail.get("qualifiers") or {}).get("go_imports") or []
            cves = detail.get("cves") or []
            name = package["package"]["name"]
            print(f"{advisory}  {name}  cves={','.join(cves) or '-'}")
            if not qualifiers:
                print("    go_imports: NONE -- nothing for a symbol matcher to narrow on")
            for qualifier in qualifiers:
                symbols = ", ".join(qualifier.get("symbols") or []) or "<no symbols listed>"
                print(f"    import {qualifier.get('path')}")
                print(f"      symbols: {symbols}")
            printed = True
    if not printed:
        print(f"{advisory}: no go row")
