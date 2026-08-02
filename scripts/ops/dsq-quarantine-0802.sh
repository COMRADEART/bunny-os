#!/usr/bin/env bash
# Move the accidental 20260802 cell-A runs (started by a non-idempotent
# `make display-stack-matrix` after the date rolled) into
# evidence/supplementary/, retained in full with an explicit note.
set -eu
cd /root/bunny-os/qualification/display-stack/evidence || exit 1
DEST=supplementary/accidental-20260802-cellA
mkdir -p "$DEST"
moved=0
for d in DSQ-20260802-cellA-*; do
  [ -d "$d" ] || continue
  mv "$d" "$DEST/"
  moved=$((moved+1))
done
cat > "$DEST/SUPPLEMENTARY.json" <<'EOF'
{
  "reason": "run_matrix.py defaulted its date tag to the current date, so a gate-ladder invocation of `make display-stack-matrix` after local midnight started a fresh cell-A sweep under 20260802 instead of recognising the complete 20260801 matrix. The runs are ordinary boots of the same artifact under the same authority; they are retained here in full, but they fill no matrix cell: the dsq-1 quotas were already met by the 20260801 records, and duplicate per-cell sequence numbers across date tags would break the contiguity the evidence gate enforces. The last run (cellA-020) was terminated mid-boot when the mistake was caught. run_matrix.py now continues the newest existing matrix date rather than starting a new one.",
  "quarantinedAt": "2026-08-02T06:15:00Z",
  "fillsCells": false
}
EOF
echo "moved $moved runs to $DEST"
