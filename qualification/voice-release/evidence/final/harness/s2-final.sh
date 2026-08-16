#!/bin/bash
# Stage 2 final acceptance on the 24168fbc artifact. Everything the matrix
# needs, with the corrected instruments, in one recorded run labelled s2b.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2b-logs
S=/mnt/c/Users/allam/AppData/Local/Temp/claude/C--Users-allam-Documents-new-bunny-os/82879418-ff81-4ca7-a938-2102d62ec84d/scratchpad
mkdir -p "$L"
cd /root/bunny-os

echo "############ waiting for the build ############"
for i in $(seq 1 240); do
  [ -f /root/bunny-ops/stage2-build.marker ] && break
  sleep 15
done
cat /root/bunny-ops/stage2-build.marker || { echo "FATAL: no build marker"; exit 2; }
grep -q "rc=0" /root/bunny-ops/stage2-build.marker || { echo "FATAL: build failed"; exit 2; }
grep -q "commit=24168fbc" /root/bunny-ops/stage2-build.marker || { echo "FATAL: wrong commit"; exit 2; }
sha256sum build/out/shell-test/bootc-fedora-44-qcow2-x86_64/bootc-fedora-44-qcow2-x86_64.qcow2 | tee "$L/qcow2.sha256"
cp build/out/shell-test/provenance.json "$L/provenance.json"

echo "############ boot s2b ############"
bash "$E/accept-boot.sh" s2b 1920 1080 || exit 1

echo "############ settle + health + rig ############"
python3 "$E/ask.py" s2b shell --root --timeout 600 "@$E/accept-settle.sh" | tail -8
python3 "$E/ask.py" s2b shell --timeout 240 "@$E/q11-voice-health.sh" | tee "$L/voice-health.log" | head -6
python3 build/scripts/qmp-screendump.py --socket "$E/runs/s2b/qmp.sock" --output "$E/runs/s2b/screens/s2b-00-desktop.ppm" >/dev/null
cp -f "$S/s2-audio-tools.py" "$E/runs/s2b/share/tools/" 2>/dev/null || true
cp -f "$E/s2-truth-check.py" "$E/" 2>/dev/null || true
tr -d '\r' < "$S/s2-truth-poller.py" > "$E/runs/s2b/share/tools/s2-truth-poller.py"
python3 "$E/ask.py" s2b shell --timeout 500 "@$E/mic-prepare.sh" | tee "$L/mic-prepare.log" | tail -12
python3 "$E/ask.py" s2b shell --timeout 240 'python3 /tmp/make-utterance.py "What can you do?" /tmp/utt-capabilities.raw kitten 2>&1 | tail -1'

arm_truth () {
  python3 "$E/ask.py" s2b shell --timeout 120 "cp -f /mnt/bunnyshare/tools/s2-truth-poller.py /tmp/
systemctl --user stop bunny-truth-poller.service 2>/dev/null || true
rm -f /mnt/bunnyshare/truth-$1.ndjson
systemd-run --user --unit=bunny-truth-poller --collect --property=StandardOutput=file:/tmp/tp.log --property=StandardError=file:/tmp/tp.log /usr/bin/python3 /tmp/s2-truth-poller.py /mnt/bunnyshare/truth-$1.ndjson 0.15
sleep 1; echo armed" >/dev/null
}
disarm_truth () {
  python3 "$E/ask.py" s2b shell --timeout 60 'systemctl --user stop bunny-truth-poller.service 2>/dev/null; echo stopped' >/dev/null
  python3 "$E/s2-truth-check.py" "$E/runs/s2b/share/states-$1.ndjson" "$E/runs/s2b/share/truth-$1.ndjson" \
    > "$L/$1-truth.json" 2>&1 || true
  python3 -c "import json;d=json.load(open('$L/$1-truth.json'));print('truth[$1]:', d['verdict'])" 2>/dev/null || echo "truth[$1]: unreadable"
}

echo "############ EE-1 primary gate ############"
arm_truth ee1
python3 "$E/voice-drive.py" --run s2b --utterance /tmp/utt-open-files.raw --tag ee1 \
  --approve --activation button --width 1920 --height 1080 | tee "$L/ee1-drive.log" | grep -E "state:|says|allowed" | head -12
disarm_truth ee1
python3 "$E/ask.py" s2b shell --timeout 240 "@$E/q19-verify-openfiles.sh" | tee "$L/ee1-verify.log" | grep -E "process|frame=|configured|fallback" | head -8
mkdir -p "$E/runs/s2b/share/played"
cp "$E/runs/s2b"/played*.wav "$E/runs/s2b/share/played/" 2>/dev/null || true
python3 "$E/ask.py" s2b shell --timeout 300 "@$E/recognise-played.sh" | tee "$L/ee1-recognise.log" | tail -4

echo "############ spoken telemetry + files, with truth ############"
arm_truth mem
python3 "$E/voice-drive.py" --run s2b --utterance /tmp/utt-memory.raw --tag mem \
  --approve --activation button | tee "$L/mem-drive.log" | grep -E "state:|says" | head -8
disarm_truth mem
python3 "$E/ask.py" s2b shell --timeout 120 "@$E/make-pdfs.sh" | tail -2
arm_truth pdfs
python3 "$E/voice-drive.py" --run s2b --utterance /tmp/utt-pdfs.raw --tag pdfs \
  --approve --activation button | tee "$L/pdfs-drive.log" | grep -E "state:|says" | head -8
disarm_truth pdfs

echo "############ AG-5 deny (before any terminal exists) ############"
sed 's/"$REQID" allow/"$REQID" deny/' "$E/speak-template.sh" > "$E/s2-deny-template.sh"
sed -e "s#__UTTERANCE__#/tmp/utt-terminal.raw#" -e "s#__TAG__#deny#" -e "s#__APPROVE__#1#" \
  "$E/s2-deny-template.sh" > "$E/speak-deny.sh"
python3 "$E/ask.py" s2b shell --timeout 500 "@$E/speak-deny.sh" | tee "$L/deny.log" | grep -E "approval_resolved|blocked|declined|finished" | head -6
python3 "$E/ask.py" s2b shell --timeout 60 'pgrep -a -u bunny -f "ptyxis|gnome-terminal|kgx" || echo "no terminal process"'

echo "############ TT-4 interruption, corrected instruments ############"
python3 "$E/ask.py" s2b shell --timeout 400 "@$E/accept-interrupt2.sh" | tee "$L/interrupt.log" | grep -E "cancel answered|audio stopped|did not stop|players|sink state" | head -8

echo "############ EE-5 the very next interaction speaks ############"
T0=$(date +%s)
bash "$E/speak.sh" s2b /tmp/utt-memory.raw postint 1 | tee "$L/postint.log" | grep -E "speech_started|speech_error|reply|finished|warning" | head -6
echo "postint wall seconds: $(( $(date +%s) - T0 ))"

echo "############ UI stop control, with truth ############"
arm_truth uistop
python3 "$E/voice-drive.py" --run s2b --utterance /tmp/utt-capabilities.raw --tag uistop \
  --approve --activation button --stop-after 0.7 | tee "$L/uistop-drive.log" | grep -E "state:|clicked-stop|says" | head -10
disarm_truth uistop

echo "############ TT-5 fallback ############"
python3 "$E/ask.py" s2b shell --root --timeout 300 "@$E/hide-pocket.sh" | tail -2
bash "$E/speak.sh" s2b /tmp/utt-open-files.raw fallback 1 | tee "$L/fallback.log" | grep -E "speech_started|providerId|finished" | head -4

echo "############ TT-6 all providers gone: fast, honest, text intact ############"
python3 "$E/ask.py" s2b shell --root --timeout 300 "@$E/hide-all-tts.sh" | tail -2
T0=$(date +%s)
bash "$E/speak.sh" s2b /tmp/utt-memory.raw notts 1 | tee "$L/notts.log" | grep -E "reply|warning|speech_finished|speech_error|finished" | head -8
echo "notts wall seconds: $(( $(date +%s) - T0 ))"

echo "############ restore + recovery ############"
python3 "$E/ask.py" s2b shell --root --timeout 300 "@$E/restore-tts.sh" | tail -2
bash "$E/speak.sh" s2b /tmp/utt-memory.raw restored 1 | tee "$L/restored.log" | grep -E "speech_started|finished" | head -3

echo "############ EE-4 offline ############"
python3 "$E/ask.py" s2b shell --root --timeout 120 "@$E/go-offline.sh" | tail -3
bash "$E/speak.sh" s2b /tmp/utt-terminal.raw offline 1 | tee "$L/offline.log" | grep -E "approval_resolved|reply|speech_started|finished" | head -5
python3 "$E/ask.py" s2b shell --timeout 60 'pgrep -a -u bunny -f "gnome-terminal|ptyxis|kgx" | head -2 || echo none'
python3 "$E/ask.py" s2b shell --root --timeout 120 "@$E/go-online.sh" | tail -2

echo "############ VI matrix: loss, absence, return ############"
python3 "$E/ask.py" s2b shell --timeout 240 "@$E/s2-disconnect.sh" | tee "$L/vi-disconnect.log" | grep -E "input device was lost|error" | head -3
bash "$E/speak.sh" s2b /tmp/utt-memory.raw novirt 1 | tee "$L/vi-novirt.log" | grep -E "error|warning" | head -2
python3 "$E/ask.py" s2b shell --timeout 500 "@$E/mic-prepare.sh" | tail -3
bash "$E/speak.sh" s2b /tmp/utt-memory.raw reconnect 1 | tee "$L/vi-reconnect.log" | grep -E "transcript|finished" | head -3

echo "############ ST-7 consecutive ############"
for tag in c1 c2 c3; do
  case $tag in c1) UTT=/tmp/utt-memory.raw;; c2) UTT=/tmp/utt-pdfs.raw;; c3) UTT=/tmp/utt-capabilities.raw;; esac
  bash "$E/speak.sh" s2b "$UTT" "$tag" 1 | grep -E "transcript|finished" | head -2
done | tee "$L/consecutive.log"

echo "############ session parity ############"
python3 "$E/ask.py" s2b shell --timeout 300 'bunny-shell-assistant ask "What time is it?" 2>/dev/null | grep -E "accepted|finished" | head -2'
python3 "$E/ask.py" s2b shell --timeout 120 "@$E/s2-sessions.sh" | tee "$L/sessions.log" | tail -5

echo "############ renderer slice, solo ############"
python3 "$E/ask.py" s2b shell --timeout 700 "@$E/s2-slice-solo.sh" | tee "$L/slice-solo.log" | tail -8

echo "############ idle CPU + RSS (60s) ############"
python3 "$E/ask.py" s2b shell --timeout 180 "@$E/s2-cpu-idle.sh" | tee "$L/cpu-idle.json" | tail -20

echo "############ settings page ############"
python3 "$E/settings-capture.py" --run s2b --tag s2b-1920 --width 1920 --height 1080 | tail -6

echo "############ latency table ############"
sed 's#/runs/s2#/runs/s2b#' "$E/s2-latency.py" > "$E/s2-latency-b.py"
python3 "$E/s2-latency-b.py" | tee "$L/latency.json"

echo "############ collect ############"
python3 build/scripts/ppm-to-png.py "$E/runs/s2b/screens" >/dev/null 2>&1 || true
ls "$E/runs/s2b/screens/"*.png 2>/dev/null | tail -6
echo "############ S2B-FINAL DONE ############"
