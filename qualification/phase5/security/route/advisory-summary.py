#!/usr/bin/python3
"""Summarise one `grype db search -o json` result.

Kept separate from the shell script so the shell script has no embedded Python
and stays readable to shellcheck.
"""
import json
import sys
from collections import Counter

path = sys.argv[1]
package_mode = "--package" in sys.argv[2:]

try:
    with open(path, encoding="utf-8") as handle:
        text = handle.read().strip()
except OSError as error:
    print("    unreadable:", error)
    raise SystemExit(0)

if not text:
    print("    NO ROWS -- the database returns nothing for this identifier")
    raise SystemExit(0)

try:
    document = json.loads(text)
except json.JSONDecodeError as error:
    print("    not JSON:", error, "|", text[:120])
    raise SystemExit(0)

rows = document if isinstance(document, list) else document.get("matches", document)
if not isinstance(rows, list):
    rows = [rows]

if not rows:
    print("    NO ROWS -- the database returns nothing for this identifier")
    raise SystemExit(0)

if package_mode:
    versions = Counter()
    for row in rows:
        vuln = row.get("vulnerability", row)
        versions[(vuln.get("id"), str(row.get("package", {}).get("name", "")))] += 1
    print(f"    {len(rows)} rows, {len(versions)} distinct (advisory, package)")
    for (identifier, package), count in sorted(versions.items())[:40]:
        print(f"      {identifier:26s} {package} x{count}")
    raise SystemExit(0)

for row in rows[:6]:
    vuln = row.get("vulnerability", row)
    package = row.get("package", {})
    print(
        f"    id={vuln.get('id')} severity={vuln.get('severity')} "
        f"status={vuln.get('status')} pkg={package.get('name')} "
        f"ecosystem={package.get('ecosystem')}"
    )
    ranges = row.get("ranges") or vuln.get("ranges") or []
    for entry in ranges[:3]:
        print(f"       range: {json.dumps(entry)[:200]}")
if len(rows) > 6:
    print(f"    ... {len(rows) - 6} more rows")
