#!/bin/bash
# Stage 2 phase 3c: finish what the swept 3b left — no-TTS case, restore,
# provider status, settings photograph.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ every provider hidden -> text must survive ############"
python3 "$E/ask.py" s2 shell --root --timeout 120 'mountpoint -q /usr/share/bunny-os/voice/pocket && echo pocket-hidden; mountpoint -q /usr/share/bunny-os/voice/kitten && echo kitten-hidden; true'
bash "$E/speak.sh" s2 /tmp/utt-memory.raw notts 1 | tee "$L/notts.log" | grep -E "reply|speech_started|speech_error|warning|finished|error" | head -12

echo "############ providers restored ############"
python3 "$E/ask.py" s2 shell --root --timeout 300 "@$E/restore-tts.sh" | tail -4
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-provider-status.sh" | tail -6

echo "############ a normal spoken flow works again (recovery) ############"
bash "$E/speak.sh" s2 /tmp/utt-memory.raw restored 1 | tee "$L/restored.log" | grep -E "speech_started|speech_finished|reply|finished|error" | head -8

echo "############ voice settings photograph ############"
python3 "$E/settings-capture.py" --run s2 --tag s2-1920 --width 1920 --height 1080 | tail -12

echo "############ PHASE3C DONE ############"
