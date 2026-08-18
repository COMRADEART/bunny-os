#!/usr/bin/python3
"""Do the seven Criticals appear in the unfiltered scan?

`--only-fixed` drops any finding the database has no fix version for. If the
advisory data changed such that these no longer carry a fix, they would vanish
from a --only-fixed scan while still being live Critical findings against the
image. That is the difference between "gone" and "no longer counted", and only
the unfiltered scan can tell them apart.
"""
import json
from collections import Counter

CRITICALS = [
    "GHSA-5cgq-3rg8-m6cv", "GHSA-89gr-r52h-f8rx", "GHSA-f5wc-c3c7-36mc",
    "GHSA-jppx-rxg9-jmrx", "GHSA-rm3j-f69w-wqmq", "GHSA-vgwf-h737-ff37",
    "GHSA-x527-x647-q7gg", "GHSA-p77j-4mvh-x3m3",
]

for label, path in (
    ("candidate --only-fixed", "/home/bunny/p5-evidence/security/candidate-fixed.json"),
    ("candidate unfiltered", "/home/bunny/p5-evidence/security/candidate-all.json"),
):
    document = json.load(open(path, encoding="utf-8"))
    matches = document.get("matches", [])
    by_id = {}
    for match in matches:
        by_id.setdefault(match["vulnerability"]["id"], []).append(match)
    severities = Counter(m["vulnerability"]["severity"] for m in matches)
    print(f"=== {label}: {len(matches)} matches, {len(by_id)} distinct, {dict(severities)}")
    for identifier in CRITICALS:
        rows = by_id.get(identifier)
        if not rows:
            print(f"    {identifier:24s} absent")
        else:
            for row in rows:
                artifact = row["artifact"]
                vuln = row["vulnerability"]
                print(
                    f"    {identifier:24s} PRESENT sev={vuln['severity']} "
                    f"fix={vuln.get('fix', {}).get('versions')} "
                    f"state={vuln.get('fix', {}).get('state')} "
                    f"pkg={artifact['name']}@{artifact.get('version')}"
                )
    print()

# What does the unfiltered scan say about x/crypto at all?
document = json.load(open("/home/bunny/p5-evidence/security/candidate-all.json", encoding="utf-8"))
rows = [m for m in document.get("matches", []) if "x/crypto" in m["artifact"]["name"]]
print(f"=== unfiltered scan, golang.org/x/crypto matches: {len(rows)}")
for row in rows[:20]:
    print("   ", row["vulnerability"]["id"], row["vulnerability"]["severity"],
          row["artifact"].get("version"),
          row["vulnerability"].get("fix", {}).get("state"))
