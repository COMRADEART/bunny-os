#!/usr/bin/env bash
# Move every dsq-failed-units-1 run into evidence/invalidated/, retained in
# full with an explicit invalidation note. Nothing is deleted.
set -eu
cd /root/bunny-os/qualification/display-stack/evidence || exit 1
DEST=invalidated/dsq-failed-units-1
mkdir -p "$DEST"
moved=0
for d in DSQ-20260801-*; do
  [ -d "$d" ] || continue
  mv "$d" "$DEST/"
  moved=$((moved+1))
done
cat > "$DEST/INVALIDATED.json" <<'EOF'
{
  "invalidatedAt": "2026-08-01T23:55:00Z",
  "reason": "failed-unit collector dsq-failed-units-1 read only the UNIT journal field, so every user-manager unit event (including the org.gnome.Shell.Screencast transient unit this pass exists to measure) was invisible to the analysis. The defect was found during the first partial cell-A sweep, before any record was committed or imported. The collector is fixed as dsq-failed-units-2, which also phase-classifies failures against the recorded shutdown initiation. These records are retained in full; their binary journals remain under /root/dsq-traces/. They are stale against the dsq-1 authority (failedUnitCollectorVersion mismatch) and can fill no matrix cell.",
  "supersededBy": "the complete dsq-failed-units-2 matrix in the parent evidence directory"
}
EOF
echo "moved $moved run directories to $DEST"
