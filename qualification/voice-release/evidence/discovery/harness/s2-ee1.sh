#!/bin/bash
# Stage 2 EE-1 primary gate: pointer press on the microphone button, spoken
# "Open Files", real approval, spoken reply — with the truth poller running.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

cp -f /mnt/c/Users/allam/AppData/Local/Temp/claude/C--Users-allam-Documents-new-bunny-os/82879418-ff81-4ca7-a938-2102d62ec84d/scratchpad/s2-truth-poller.py "$E/runs/s2/share/tools/s2-truth-poller.py"
python3 - "$E/runs/s2/share/tools/s2-truth-poller.py" <<'PY'
import sys
p = sys.argv[1]
data = open(p, 'rb').read().replace(b'\r\n', b'\n')
open(p, 'wb').write(data)
PY

echo "############ truth poller up ############"
python3 "$E/ask.py" s2 shell --timeout 120 'cp -f /mnt/bunnyshare/tools/s2-truth-poller.py /tmp/
systemctl --user stop bunny-truth-poller.service 2>/dev/null || true
rm -f /mnt/bunnyshare/truth-ee1.ndjson
systemd-run --user --unit=bunny-truth-poller --collect --property=StandardOutput=file:/tmp/truth-poller.log --property=StandardError=file:/tmp/truth-poller.log /usr/bin/python3 /tmp/s2-truth-poller.py /mnt/bunnyshare/truth-ee1.ndjson 0.15
sleep 2
head -2 /tmp/truth-poller.log 2>/dev/null || true
echo poller-armed'

echo "############ voice-drive: button press, Open Files ############"
python3 "$E/voice-drive.py" --run s2 --utterance /tmp/utt-open-files.raw \
  --tag ee1 --approve --activation button --width 1920 --height 1080 \
  | tee "$L/ee1-drive.log"

echo "############ what opened, and which engine spoke ############"
python3 "$E/ask.py" s2 shell --timeout 240 "@$E/q19-verify-openfiles.sh" | tee "$L/ee1-verify.log" | head -40

echo "############ truth poller down ############"
python3 "$E/ask.py" s2 shell --timeout 60 'systemctl --user stop bunny-truth-poller.service 2>/dev/null; echo poller-stopped'

echo "############ speaker recording, read back ############"
mkdir -p "$E/runs/s2/share/played"
cp "$E/runs/s2"/played*.wav "$E/runs/s2/share/played/" 2>/dev/null || true
ls -la "$E/runs/s2/share/played/" 2>/dev/null | tail -3
python3 "$E/ask.py" s2 shell --timeout 300 "@$E/recognise-played.sh" | tee "$L/ee1-recognise.log" | tail -12

echo "############ EE1 DONE ############"
