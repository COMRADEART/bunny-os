#!/bin/bash
# Stage 2 phase 3b (after the probe fix + reboot): re-arm rig, reproduce the
# post-interrupt stall in a controlled pair, then the no-TTS case, restore,
# settings photograph.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ re-arm mic rig (fresh boot) ############"
python3 "$E/ask.py" s2 shell --timeout 500 "@$E/mic-prepare.sh" | tail -8
python3 "$E/ask.py" s2 shell --timeout 240 'python3 /tmp/make-utterance.py "What can you do?" /tmp/utt-capabilities.raw kitten 2>&1 | tail -1'

echo "############ repro A: CLI cancel, leftover listen client left alive ############"
python3 "$E/ask.py" s2 shell --timeout 400 "@$E/accept-interrupt2.sh" | tee "$L/repro-a-int.log" | grep -E "audio stopped|did not stop" | head -2
echo "--- immediately: next spoken interaction (is the reply spoken?) ---"
date -u +%H:%M:%S.%3N
bash "$E/speak.sh" s2 /tmp/utt-memory.raw reproA 1 | tee "$L/repro-a-next.log" | grep -E "speech_started|speech_error|speech_finished|reply|finished|warning|error" | head -10
date -u +%H:%M:%S.%3N
python3 "$E/ask.py" s2 shell --timeout 60 'pgrep -af "bunny-shell-assistant listen" | head -5; journalctl --user -o cat --since "-4min" 2>/dev/null | grep -i "could not speak" | tail -3 || true'

echo "############ repro B: CLI cancel, then the leftover client is killed ############"
python3 "$E/ask.py" s2 shell --timeout 60 'pkill -f "bunny-shell-assistant listen" 2>/dev/null; sleep 1; pgrep -af "bunny-shell-assistant listen" || echo "no leftover listen clients"'
python3 "$E/ask.py" s2 shell --timeout 400 "@$E/accept-interrupt2.sh" | tee "$L/repro-b-int.log" | grep -E "audio stopped|did not stop" | head -2
python3 "$E/ask.py" s2 shell --timeout 60 'pkill -f "bunny-shell-assistant listen" 2>/dev/null; sleep 1; pgrep -af "bunny-shell-assistant listen" || echo "leftover killed"'
echo "--- next spoken interaction after the kill ---"
date -u +%H:%M:%S.%3N
bash "$E/speak.sh" s2 /tmp/utt-memory.raw reproB 1 | tee "$L/repro-b-next.log" | grep -E "speech_started|speech_error|speech_finished|reply|finished|warning|error" | head -10
date -u +%H:%M:%S.%3N
python3 "$E/ask.py" s2 shell --timeout 60 'journalctl --user -o cat --since "-3min" 2>/dev/null | grep -i "could not speak" | tail -3 || echo "no could-not-speak warning"'

echo "############ every provider hidden -> text must survive ############"
python3 "$E/ask.py" s2 shell --root --timeout 300 "@$E/hide-all-tts.sh" | tail -4
bash "$E/speak.sh" s2 /tmp/utt-memory.raw notts 1 | tee "$L/notts.log" | grep -E "reply|speech_started|speech_error|warning|finished|error|phase" | head -16

echo "############ providers restored ############"
python3 "$E/ask.py" s2 shell --root --timeout 300 "@$E/restore-tts.sh" | tail -4
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-provider-status.sh" | tail -6

echo "############ voice settings photograph ############"
python3 "$E/settings-capture.py" --run s2 --tag s2-1920 --width 1920 --height 1080 | tail -12

echo "############ PHASE3B DONE ############"
