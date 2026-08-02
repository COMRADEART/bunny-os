#!/usr/bin/env bash
# For every failed unit in every dsq record: when did it fail, relative to
# graphical.target and to the shutdown request (powerdown begins after the
# observation window; "Stopping" from PID1 marks teardown start)?
cd /root/bunny-os || exit 1
python3 - <<'EOF'
import json, glob
for p in sorted(glob.glob("qualification/display-stack/evidence/DSQ-*cell*/record.json")):
    r = json.load(open(p))
    a = r.get("analysis") or {}
    failed = a.get("failedSystemUnits") or []
    if not failed:
        continue
    graphical = a.get("graphicalTargetReachedMono")
    window = r.get("observationWindowSeconds", 75)
    for unit in a.get("systemUnits", []):
        if unit["unit"] in failed:
            fail_events = [e for e in unit["events"] if e["kind"] == "failed"]
            stop_events = [e for e in unit["events"] if e["kind"] == "stopped"]
            first_stop = min((e["monotonic"] for e in stop_events
                              if e["monotonic"]), default=None)
            for e in fail_events:
                after_window = (e["monotonic"] or 0) > (graphical or 0) + window
                print(f'{r["runId"]} {unit["unit"]}: active@{unit["activeEnterMono"]} '
                      f'failed@{e["monotonic"]} stop-began@{first_stop} '
                      f'graphical@{graphical} afterObservationWindow={after_window} '
                      f'result={unit["result"]} mainExit={unit["mainExit"]}')
EOF
