#!/usr/bin/env bash
# One-off repair of the retention path collision between the invalidated
# dsq-failed-units-1 tree and its rerun (shared run IDs, flat trace layout).
#
# For every file under /root/dsq-traces/<run-id>/ whose bytes match the
# INVALIDATED run's attested digest, the file is v1's retained copy sitting
# at v2's path: move it to the invalidated subtree and point v1's retention
# manifest at it. Where v2's attested bytes were overwritten by that
# collision they are unrecoverable: the v2 retention manifest entry loses
# its retainedAt and gains an explicit loss note — the sha256 attestation
# stands, the bytes do not.
set -u
cd /root/bunny-os
python3 - <<'EOF'
import hashlib, json, shutil
from pathlib import Path

TRACES = Path("/root/dsq-traces")
EV = Path("qualification/display-stack/evidence")
INV = EV / "invalidated/dsq-failed-units-1"

def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

moved = lost = kept = 0
for run in sorted(EV.iterdir()):
    rm_path = run / "retention-manifest.json"
    if not run.is_dir() or not rm_path.is_file():
        continue
    inv_run = INV / run.name
    inv_manifest = {}
    inv_rm_path = inv_run / "retention-manifest.json"
    if inv_rm_path.is_file():
        inv_data = json.loads(inv_rm_path.read_text())
        inv_manifest = {e["path"]: e for e in inv_data.get("files", [])}
    else:
        inv_data = None
    rm = json.loads(rm_path.read_text())
    changed = inv_changed = False
    for entry in rm.get("files", []):
        kept_path = Path(entry.get("retainedAt", ""))
        if not kept_path.is_file():
            continue
        actual = sha(kept_path)
        if actual == entry["sha256"]:
            kept += 1
            continue
        inv_entry = inv_manifest.get(entry["path"])
        if inv_entry and actual == inv_entry["sha256"]:
            # v1's bytes at v2's path: relocate to the invalidated subtree
            dest = TRACES / "invalidated/dsq-failed-units-1" / run.name / entry["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(kept_path), str(dest))
            inv_entry["retainedAt"] = str(dest)
            inv_changed = True
            moved += 1
        else:
            print(f"UNEXPLAINED: {kept_path} digests to {actual[:12]}, "
                  f"matches neither v2 ({entry['sha256'][:12]}) nor v1")
            continue
        # v2's bytes at this path were overwritten before the layout fix
        entry.pop("retainedAt", None)
        entry["lost"] = ("overwritten by the retention path collision with "
                         "the invalidated dsq-failed-units-1 run of the "
                         "same ID (flat trace layout, fixed in "
                         "retain_bulky_evidence.py); sha256 attestation "
                         "stands, bytes unrecoverable")
        lost += 1
        changed = True
    if changed:
        rm_path.write_text(json.dumps(rm, indent=2) + "\n")
    if inv_changed and inv_data is not None:
        inv_rm_path.write_text(json.dumps(inv_data, indent=2) + "\n")
print(f"kept={kept} relocated-to-invalidated={moved} recorded-lost={lost}")
EOF
