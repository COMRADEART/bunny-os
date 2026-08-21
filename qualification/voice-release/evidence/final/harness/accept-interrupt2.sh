set -u
# The number the target is about is when the *audio* stops, not when the
# character changes. So the speech is started through the voice path (the only
# path that speaks), and the stop is timed against the player process and the
# sink's own state, polled at 10 ms.
#
# Stage 2 corrections, each of which had made the old number fiction:
#   - the player list now includes pw-play, which is what the PipeWire backend
#     actually spawns; without it PLAYERS was always zero and the "stop" was
#     measured against nothing.
#   - the sink state is the LAST column of `pactl list sinks short`; column 5
#     is the middle of the sample spec ("2ch"), so the RUNNING check was
#     vacuously true.
#   - the background listen client is killed at the end; leaving it alive
#     confused every later diagnosis of this scenario.
rm -f /tmp/int.ndjson
setsid bunny-shell-assistant listen --activation-source push-to-talk-button \
  --presentation-revision 1 > /tmp/int.ndjson 2>/dev/null &
LISTENPID=$!

for i in $(seq 1 200); do
  grep -q '"microphone"' /tmp/int.ndjson 2>/dev/null && break
  sleep 0.25
done
sleep 0.4
cp /tmp/utt-capabilities.raw /tmp/bunny-mic-queue/interrupt.raw

TASK=""
for i in $(seq 1 600); do
  if grep -q '"event": "speech_started"' /tmp/int.ndjson 2>/dev/null; then
    TASK=$(python3 - <<'PY'
import json
for line in open("/tmp/int.ndjson"):
    line=line.strip()
    if not line: continue
    try: d=json.loads(line)
    except json.JSONDecodeError: continue
    if d.get("event")=="speech_started":
        print(d.get("taskId","")); break
PY
)
    break
  fi
  sleep 0.1
done
[ -n "$TASK" ] || { echo "speech never started"; tail -4 /tmp/int.ndjson; kill "$LISTENPID" 2>/dev/null; exit 1; }
echo "speech started for $TASK"

count_players() {
  local total=0
  for name in paplay pacat pw-cat pw-play aplay; do
    total=$((total + $(pgrep -x -u bunny "$name" 2>/dev/null | wc -l)))
  done
  echo "$total"
}

echo "players before the cancel: $(count_players)  sink: $(pactl list sinks short | awk '{print $NF}' | head -1)"

# A second of it, so this is an interruption and not a race with the start.
sleep 1.0
START=$(date +%s.%N)
CANCEL_ANSWER=$(bunny-shell-assistant voice-cancel "$TASK" 2>&1)
echo "cancel answered: ${CANCEL_ANSWER:0:160}"
STOPPED=""
for i in $(seq 1 600); do
  PLAYERS=$(count_players)
  SINK=$(pactl list sinks short 2>/dev/null | awk '{print $NF}' | head -1)
  if [ "$PLAYERS" = "0" ] && [ "$SINK" != "RUNNING" ]; then
    STOPPED=$(date +%s.%N); break
  fi
  sleep 0.01
done
if [ -n "$STOPPED" ]; then
  python3 -c "print('audio stopped %.0f ms after the cancel' % (($STOPPED - $START)*1000))"
else
  echo "the audio did not stop within six seconds"
fi

sleep 2
echo "--- did anything play afterwards? ---"
sleep 3
pactl list sinks short | awk '{print "sink state:", $NF}'
echo "players now: $(count_players)"
echo "--- events ---"
python3 - <<'PY'
import json
for line in open("/tmp/int.ndjson"):
    line=line.strip()
    if not line: continue
    try: d=json.loads(line)
    except json.JSONDecodeError: continue
    e=d.pop("event","?")
    keep={k:v for k,v in d.items() if k in ("phase","text","reason","disposition","providerId","detail")}
    print(f"{e:20} {json.dumps(keep)[:140]}")
PY
kill "$LISTENPID" 2>/dev/null || true
echo "listen client reaped"
