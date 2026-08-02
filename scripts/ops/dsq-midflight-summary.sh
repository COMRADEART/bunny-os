#!/usr/bin/env bash
# Mid-flight sanity: per-cell tallies of resets, boot-phase and
# shutdown-phase failures across collected records so far.
cd /root/bunny-os
python3 - <<'EOF'
import json, glob
from collections import Counter, defaultdict

cells = defaultdict(lambda: {"n": 0, "resetsBad": 0,
                             "boot": Counter(), "shutdown": Counter(),
                             "recovered": Counter(), "notReady": 0})
for p in sorted(glob.glob("qualification/display-stack/evidence/DSQ-*cell*/record.json")):
    r = json.load(open(p))
    if r.get("status") != "COLLECTED":
        print("NOT COLLECTED:", r["runId"], r.get("status"))
        continue
    c = cells[r["cell"]]
    c["n"] += 1
    if r.get("guestResetCount") != r.get("expectedResets"):
        c["resetsBad"] += 1
        print("RESET MISMATCH:", r["runId"], r.get("guestResetCount"))
    a = r["analysis"]
    for u in a.get("failedSystemUnits", []):
        c["boot"][u] += 1
    for u in a.get("failedUserUnits", []):
        c["boot"][u] += 1
    for u in a.get("shutdownFailedSystemUnits", []):
        c["shutdown"][u] += 1
    for u in a.get("shutdownFailedUserUnits", []):
        c["shutdown"][u] += 1
    for u in a.get("recoveredSystemUnits", []):
        c["recovered"][u] += 1
    if a.get("graphicalTargetReachedMono") is None or \
            not r.get("observationWindowCompleted"):
        c["notReady"] += 1
        print("NOT READY:", r["runId"])
for cell in sorted(cells):
    c = cells[cell]
    print(f"cell {cell}: n={c['n']} resetMismatch={c['resetsBad']} notReady={c['notReady']}")
    for name, cnt in c["boot"].most_common():
        print(f"   boot-phase {name}: {cnt}/{c['n']}")
    for name, cnt in c["shutdown"].most_common():
        print(f"   shutdown   {name}: {cnt}/{c['n']}")
    for name, cnt in c["recovered"].most_common():
        print(f"   recovered  {name}: {cnt}/{c['n']}")
EOF
