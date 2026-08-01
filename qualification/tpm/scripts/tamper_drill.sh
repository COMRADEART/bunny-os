#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prove the fraud checks fire in the gate that actually runs, not only in
# the unit tests.
#
# tests/tpm/ exercises verify_record_binding and verify_internal_consistency
# directly and the importer through synthetic trees. That leaves one gap a
# reviewer should not have to take on trust: whether the production gate,
# reading real evidence produced by the real runner, still refuses a
# relabelled record. This drill closes it — copy one completed run, relabel
# it four ways, and require the gate to report more problems each time.
#
# It is a drill, not evidence: it writes nothing into the evidence tree and
# its staging directory is removed on exit.
set -eu

EVIDENCE="${1:?usage: tamper_drill.sh <evidence-root> [run-id]}"
RUN="${2:-}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
STAGE=$(mktemp -d /tmp/tpmq-tamper-XXXX)
trap 'rm -rf "$STAGE"' EXIT

if [ -z "$RUN" ]; then
  RUN=$(for d in "$EVIDENCE"/TPMQ-*; do
          [ -f "$d/record.json" ] && basename "$d" && break
        done)
fi
[ -n "$RUN" ] || { echo "BLOCKED: no completed run in $EVIDENCE" >&2; exit 2; }

mkdir -p "$STAGE/qualification/tpm/evidence"
cp "$ROOT/qualification/tpm/evidence-context.json" "$STAGE/qualification/tpm/"
cp -r "$ROOT/qualification/tpm/schemas" "$STAGE/qualification/tpm/"
cp -r "$EVIDENCE/$RUN" "$STAGE/qualification/tpm/evidence/"
rm -rf "$STAGE/qualification/tpm/evidence/$RUN/state" \
       "$STAGE/qualification/tpm/evidence/$RUN/work"
RECORD="$STAGE/qualification/tpm/evidence/$RUN/record.json"
PRISTINE="$STAGE/pristine.json"
cp "$RECORD" "$PRISTINE"

problems() {
  python3 "$ROOT/qualification/tpm/scripts/import_tpm_results.py" \
    --root "$STAGE" --dry-run --skip-file-hashes 2>&1 | grep -c 'problem:' || true
}

relabel() {
  python3 - "$RECORD" "$1" <<'PY'
import json, sys
path, kind = sys.argv[1], sys.argv[2]
record = json.load(open(path))
if kind == "interface-crb-as-tis":
    record["tpmInterface"] = "tis"
elif kind == "tpm-run-as-no-tpm":
    record["tpmInterface"] = "none"; record["tpmState"] = "none"
elif kind == "kvm-as-tcg":
    record["acceleration"] = "tcg"; record["environment"] = "qemu-tcg"
elif kind == "fresh-vars-as-reused":
    record["ovmfVarsState"] = "reused"
else:
    raise SystemExit(f"unknown relabelling {kind}")
json.dump(record, open(path, "w"))
PY
}

BASE=$(problems)
echo "baseline ($RUN, untampered): $BASE problem(s)"

status=0
for kind in interface-crb-as-tis tpm-run-as-no-tpm kvm-as-tcg fresh-vars-as-reused; do
  cp "$PRISTINE" "$RECORD"
  relabel "$kind"
  count=$(problems)
  if [ "$count" -gt "$BASE" ]; then
    echo "  REFUSED  $kind ($count problems, baseline $BASE)"
  else
    echo "  ACCEPTED $kind — the gate did not refuse a relabelled record" >&2
    status=2
  fi
done
cp "$PRISTINE" "$RECORD"
exit "$status"
