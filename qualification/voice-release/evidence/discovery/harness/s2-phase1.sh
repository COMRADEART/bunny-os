#!/bin/bash
# Stage 2 phase 1: settle the s2 guest, snapshot health, stand up the mic rig.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

cp -f /mnt/c/Users/allam/AppData/Local/Temp/claude/C--Users-allam-Documents-new-bunny-os/82879418-ff81-4ca7-a938-2102d62ec84d/scratchpad/s2-audio-tools.py "$E/runs/s2/share/tools/s2-audio-tools.py" 2>/dev/null && echo "s2-audio-tools staged" || echo "WARN: could not stage s2-audio-tools"
tr -d '\r' < "$E/runs/s2/share/tools/s2-audio-tools.py" > /tmp/s2at && mv /tmp/s2at "$E/runs/s2/share/tools/s2-audio-tools.py"

echo "############ settle ############"
python3 "$E/ask.py" s2 shell --root --timeout 600 "@$E/accept-settle.sh" | tee "$L/settle.log" | tail -12

echo "############ audio devices ############"
python3 "$E/ask.py" s2 shell --timeout 240 "@$E/q2-audio.sh" | tee "$L/audio.log" | head -30

echo "############ voice + speech health ############"
python3 "$E/ask.py" s2 shell --timeout 240 "@$E/q11-voice-health.sh" | tee "$L/voice-health.log" | head -40

echo "############ desktop photograph ############"
python3 build/scripts/qmp-screendump.py --socket "$E/runs/s2/qmp.sock" \
  --output "$E/runs/s2/screens/s2-00-desktop.ppm" && \
python3 build/scripts/ppm-to-png.py "$E/runs/s2/screens" >/dev/null && \
ls -la "$E/runs/s2/screens/" | tail -3

echo "############ microphone rig + utterances ############"
python3 "$E/ask.py" s2 shell --timeout 500 "@$E/mic-prepare.sh" | tee "$L/mic-prepare.log" | tail -30

echo "############ PHASE1 DONE ############"
