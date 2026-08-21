#!/bin/bash
# Stage 2 phase 3: interruption + immediate re-use, provider fallback,
# all-providers-gone, restore, settings photograph.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ long utterance for interruption ############"
python3 "$E/ask.py" s2 shell --timeout 240 'python3 /tmp/make-utterance.py "What can you do?" /tmp/utt-capabilities.raw kitten 2>&1 | tail -1'

echo "############ interruption (audio-stop latency) ############"
python3 "$E/ask.py" s2 shell --timeout 400 "@$E/accept-interrupt2.sh" | tee "$L/interrupt.log" | tail -22

echo "############ immediately speak again after the interrupt ############"
python3 "$E/voice-drive.py" --run s2 --utterance /tmp/utt-memory.raw --tag postint \
  --approve --activation button --width 1920 --height 1080 \
  | tee "$L/postint-drive.log" | grep -E "state:|says|final" | head -12

echo "############ on-screen stop control (UI interruption) ############"
python3 "$E/voice-drive.py" --run s2 --utterance /tmp/utt-capabilities.raw --tag uistop \
  --approve --activation button --stop-after 0.7 --width 1920 --height 1080 \
  | tee "$L/uistop-drive.log" | grep -E "state:|says|final|stop|clicked" | head -16

echo "############ Pocket hidden -> who speaks? ############"
python3 "$E/ask.py" s2 shell --root --timeout 300 "@$E/hide-pocket.sh" | tail -4
bash "$E/speak.sh" s2 /tmp/utt-open-files.raw fallback 1 | tee "$L/fallback.log" | grep -E "speech_started|audio_started|providerId|reply|finished|error" | head -12

echo "############ every provider hidden -> text must survive ############"
python3 "$E/ask.py" s2 shell --root --timeout 300 "@$E/hide-all-tts.sh" | tail -4
bash "$E/speak.sh" s2 /tmp/utt-memory.raw notts 1 | tee "$L/notts.log" | grep -E "reply|speech_started|speech_error|warning|finished|error|phase" | head -16

echo "############ providers restored ############"
python3 "$E/ask.py" s2 shell --root --timeout 300 "@$E/restore-tts.sh" | tail -4
cat > "$E/s2-provider-status.sh" <<'EOS'
set -u
python3 - <<'PY'
import sys
sys.path.insert(0, "/usr/lib/bunny-os/python")
from companion.protocol import CompanionClient, default_endpoint_path
client = CompanionClient(default_endpoint_path(), timeout=20.0)
state = dict(client.call("settings_voice_get", {}))
for item in state.get("ttsProviders", []):
    print("  %-18s ready=%-5s status=%s" % (
        item.get("providerId"), item.get("ready"), item.get("status")))
PY
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-provider-status.sh" | tail -6

echo "############ voice settings photograph ############"
python3 "$E/settings-capture.py" --run s2 --tag s2-1920 --width 1920 --height 1080 | tail -10

echo "############ PHASE3 DONE ############"
