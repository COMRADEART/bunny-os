#!/usr/bin/env bash
# Summarize the chronyd-after-authselect diagnostic arm: per run, chronyd
# disposition, its start time vs that boot's authselect apply window, and
# any other boot-phase failures.
cd /root/bunny-os
python3 - <<'EOF'
import json, glob
ok = failed = 0
ordering_violations = 0
for p in sorted(glob.glob(
        "qualification/display-stack/evidence/DSQ-*diag-chronyd*/record.json")):
    r = json.load(open(p))
    if r.get("status") != "COLLECTED":
        print(r["runId"], r.get("status"), r.get("reason", ""))
        continue
    a = r["analysis"]
    t = a.get("timeline", {})
    window_end = t.get("authselectApplyEnd")
    chronyd = [u for u in a["systemUnits"] if u["unit"] == "chronyd.service"]
    disp = chronyd[0]["disposition"] if chronyd else "absent"
    start = chronyd[0].get("activeEnterMono") if chronyd else None
    starting = None
    if chronyd:
        starts = [e["monotonic"] for e in chronyd[0]["events"]
                  if e["kind"] == "starting" and e["monotonic"]]
        starting = min(starts) if starts else None
    if disp == "activated-and-succeeded":
        ok += 1
    else:
        failed += 1
        print(r["runId"], disp)
    if starting is not None and window_end is not None \
            and starting < window_end:
        ordering_violations += 1
        print(f"{r['runId']}: chronyd Starting at {starting} precedes "
              f"authselect window end {window_end}")
print(f"diag runs: succeeded={ok} failed={failed} "
      f"orderingViolations={ordering_violations}")
EOF
