#!/bin/bash
# Stage 2 phase 2: spoken telemetry + file search (with truth poller),
# interruption, performance.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
S=/mnt/c/Users/allam/AppData/Local/Temp/claude/C--Users-allam-Documents-new-bunny-os/82879418-ff81-4ca7-a938-2102d62ec84d/scratchpad
mkdir -p "$L"
cd /root/bunny-os

tr -d '\r' < "$S/s2-truth-poller.py" > "$E/runs/s2/share/tools/s2-truth-poller.py"
tr -d '\r' < "$S/s2-truth-check.py"  > "$E/s2-truth-check.py"

echo "############ PDF fixtures ############"
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/make-pdfs.sh" | tail -5

drive_with_truth () {
  TAG="$1"; UTT="$2"; EXTRA="${3:-}"
  echo "############ spoken: ${TAG} ############"
  python3 "$E/ask.py" s2 shell --timeout 120 "cp -f /mnt/bunnyshare/tools/s2-truth-poller.py /tmp/
systemctl --user stop bunny-truth-poller.service 2>/dev/null || true
rm -f /mnt/bunnyshare/truth-${TAG}.ndjson
systemd-run --user --unit=bunny-truth-poller --collect --property=StandardOutput=file:/tmp/truth-poller.log --property=StandardError=file:/tmp/truth-poller.log /usr/bin/python3 /tmp/s2-truth-poller.py /mnt/bunnyshare/truth-${TAG}.ndjson 0.15
sleep 1; echo poller-armed" >/dev/null
  python3 "$E/voice-drive.py" --run s2 --utterance "$UTT" --tag "$TAG" \
    --approve --activation button --width 1920 --height 1080 $EXTRA \
    | tee "$L/${TAG}-drive.log" | grep -E "state:|says|final|listening|talking|allowed" | head -20
  python3 "$E/ask.py" s2 shell --timeout 60 'systemctl --user stop bunny-truth-poller.service 2>/dev/null; echo poller-stopped' >/dev/null
  echo "--- truth check ${TAG} ---"
  python3 "$E/s2-truth-check.py" "$E/runs/s2/share/states-${TAG}.ndjson" \
    "$E/runs/s2/share/truth-${TAG}.ndjson" \
    | tee "$L/${TAG}-truth.json" | python3 -c "import json,sys; d=json.load(sys.stdin); print('verdict:', d['verdict']); [print(' ', i) for i in d['intervals']]"
}

drive_with_truth mem  /tmp/utt-memory.raw
drive_with_truth pdfs /tmp/utt-pdfs.raw

echo "############ memory number cross-check ############"
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/check-telemetry.sh" | tee "$L/telemetry.log" | tail -12

echo "############ downloads listing (pdf ground truth) ############"
python3 "$E/ask.py" s2 shell --timeout 60 "@$E/ls-downloads.sh" | tail -8

echo "############ interruption ############"
python3 "$E/ask.py" s2 shell --timeout 400 "@$E/accept-interrupt2.sh" | tee "$L/interrupt.log" | tail -25

echo "############ performance: synthesis ############"
python3 "$E/ask.py" s2 shell --timeout 900 "@$E/accept-perf.sh" | tee "$L/perf.log" | tail -45

echo "############ PHASE2 DONE ############"
