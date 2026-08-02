#!/usr/bin/env bash
# One-line-per-run summary of every dsq record so far.
cd /root/bunny-os
python3 - <<'EOF'
import json, glob
rows = []
for p in sorted(glob.glob("qualification/display-stack/evidence/DSQ-*/record.json")):
    r = json.load(open(p))
    a = r.get("analysis") or {}
    gdm = a.get("gdm") or {}
    rows.append((r["runId"], r.get("status"), r.get("liveOutcome"),
                 r.get("guestResetCount"),
                 a.get("graphicalTargetReachedMono"),
                 a.get("failedSystemUnits"), a.get("failedUserUnits"),
                 a.get("recoveredSystemUnits"),
                 gdm.get("gdmFailures"), len(a.get("coredumps") or [])))
for row in rows:
    print(row)
print(f"total: {len(rows)}")
EOF
