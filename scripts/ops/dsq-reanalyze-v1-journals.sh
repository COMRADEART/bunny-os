#!/usr/bin/env bash
# Diagnostic preview: run the v2 analyzer over every retained v1 binary
# journal. Informs hypotheses only; fills no dsq-1 cell.
cd /root/bunny-os || exit 1
python3 - <<'EOF'
import sys, glob
sys.path.insert(0, "qualification/display-stack/scripts")
from journal_analysis import analyze_boot, list_boots
from collections import Counter

fail_counter = Counter()
shutdown_counter = Counter()
boots = 0
for jd in sorted(glob.glob("/root/dsq-traces/DSQ-*/journal")):
    try:
        ids = list_boots(jd)
        a = analyze_boot(jd, ids[-1]["boot_id"])
    except Exception as exc:
        print(f"{jd}: FAILED {exc}")
        continue
    boots += 1
    for u in a["failedSystemUnits"]:
        fail_counter[f"system:{u}"] += 1
    for u in a["failedUserUnits"]:
        fail_counter[f"user:{u}"] += 1
    for u in a["shutdownFailedSystemUnits"]:
        shutdown_counter[f"system:{u}"] += 1
    for u in a["shutdownFailedUserUnits"]:
        shutdown_counter[f"user:{u}"] += 1
print(f"boots analyzed: {boots}")
print("boot-phase failures:")
for name, count in fail_counter.most_common():
    print(f"  {name}: {count}/{boots}")
print("shutdown-phase failures:")
for name, count in shutdown_counter.most_common():
    print(f"  {name}: {count}/{boots}")
EOF
