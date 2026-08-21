#!/bin/bash
# Stage 2 phase 4: microphone qualification matrix + STT breadth.
# Order: benign cases first, device-removal cases after, recovery last —
# so a wedged case cannot poison the benign evidence.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ fixtures: noise, mixed, long, foreign ############"
cat > "$E/s2-fixtures.sh" <<'EOS'
set -u
cp -f /mnt/bunnyshare/tools/s2-audio-tools.py /tmp/
python3 /tmp/s2-audio-tools.py noise /tmp/utt-noise.raw 4 1500
python3 /tmp/make-utterance.py "Please tell me how much memory I am using right now, and also tell me whether everything on this computer is healthy today." /tmp/utt-long.raw kitten 2>&1 | tail -1
python3 /tmp/s2-audio-tools.py mix /tmp/utt-memory.raw /tmp/utt-noise.raw /tmp/utt-memory-noisy.raw 1.0 0.6
python3 /tmp/s2-audio-tools.py espeak "Guten Morgen, wie geht es dir heute? Ich spreche kein Englisch." /tmp/utt-german.raw de
python3 /tmp/s2-audio-tools.py info /tmp/utt-noise.raw
python3 /tmp/s2-audio-tools.py info /tmp/utt-memory-noisy.raw
python3 /tmp/s2-audio-tools.py info /tmp/utt-german.raw
EOS
python3 "$E/ask.py" s2 shell --timeout 300 "@$E/s2-fixtures.sh" | tail -8

echo "############ ST-3 long phrase ############"
bash "$E/speak.sh" s2 /tmp/utt-long.raw long 1 | tee "$L/st-long.log" | grep -E "transcript|reply|finished|error|warning" | head -8

echo "############ ST-4 unknown speech (German) ############"
bash "$E/speak.sh" s2 /tmp/utt-german.raw german 1 | tee "$L/st-german.log" | grep -E "transcript|reply|finished|error|warning" | head -8

echo "############ VI-10a noise only ############"
bash "$E/speak.sh" s2 /tmp/utt-noise.raw noise 1 | tee "$L/vi-noise.log" | grep -E "transcript|reply|finished|error|warning" | head -8

echo "############ VI-10b speech over noise ############"
bash "$E/speak.sh" s2 /tmp/utt-memory-noisy.raw noisy 1 | tee "$L/vi-noisy.log" | grep -E "transcript|reply|finished|error|warning" | head -8

echo "############ ST-7 three consecutive requests ############"
for tag in c1 c2 c3; do
  case $tag in
    c1) UTT=/tmp/utt-memory.raw;;
    c2) UTT=/tmp/utt-pdfs.raw;;
    c3) UTT=/tmp/utt-capabilities.raw;;
  esac
  bash "$E/speak.sh" s2 "$UTT" "$tag" 1 | tee "$L/st-$tag.log" | grep -E "transcript|reply|finished|error" | head -5
done

echo "############ VI-9 silent-but-present microphone (HDA default) ############"
cat > "$E/s2-hda-default.sh" <<'EOS'
set -u
pactl set-default-source alsa_input.pci-0000_00_04.0.analog-stereo
pactl get-default-source
EOS
python3 "$E/ask.py" s2 shell --timeout 60 "@$E/s2-hda-default.sh" | tail -2
bash "$E/speak.sh" s2 /tmp/utt-memory.raw hda-silent 1 | tee "$L/vi-hda-silent.log" | grep -E "microphone|transcript|reply|finished|error|warning" | head -8
cat > "$E/s2-virt-default.sh" <<'EOS'
set -u
pactl set-default-source bunny-virtual-microphone
pactl get-default-source
EOS
python3 "$E/ask.py" s2 shell --timeout 60 "@$E/s2-virt-default.sh" | tail -2

echo "############ VI-6 device lost mid-capture ############"
cat > "$E/s2-disconnect.sh" <<'EOS'
set -u
rm -f /tmp/listen-disconnect.ndjson
setsid bunny-shell-assistant listen --activation-source push-to-talk-button \
  --presentation-revision 1 > /tmp/listen-disconnect.ndjson 2>/tmp/listen-disconnect.err &
LISTENPID=$!
for i in $(seq 1 120); do
  grep -q '"microphone"' /tmp/listen-disconnect.ndjson 2>/dev/null && break
  sleep 0.25
done
sleep 0.5
echo "--- unloading the source out from under the capture ---"
systemctl --user stop bunny-mic-daemon.service 2>/dev/null || true
pactl unload-module module-pipe-source 2>/dev/null || echo "unload failed"
for i in $(seq 1 80); do
  grep -qE '"event": ?"(finished|error)"' /tmp/listen-disconnect.ndjson 2>/dev/null && break
  sleep 0.25
done
sleep 1
kill "$LISTENPID" 2>/dev/null || true
echo "--- events ---"
cat /tmp/listen-disconnect.ndjson
echo "--- stderr ---"
head -3 /tmp/listen-disconnect.err
EOS
python3 "$E/ask.py" s2 shell --timeout 240 "@$E/s2-disconnect.sh" | tee "$L/vi-disconnect.log" | tail -20

echo "############ VI-5 selected device absent at start ############"
bash "$E/speak.sh" s2 /tmp/utt-memory.raw novirt 1 | tee "$L/vi-novirt.log" | grep -E "microphone|voice_phase|transcript|reply|finished|error|warning" | head -10

echo "############ VI-7 device returns; recovery ############"
python3 "$E/ask.py" s2 shell --timeout 500 "@$E/mic-prepare.sh" | tail -8
bash "$E/speak.sh" s2 /tmp/utt-memory.raw reconnect 1 | tee "$L/vi-reconnect.log" | grep -E "transcript|reply|finished|error" | head -6

echo "############ PHASE4 DONE ############"
