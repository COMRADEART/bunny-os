set -u
# The definitive cancel test: what does voice_cancel ANSWER, does a
# speech_cancelled event land, and does the playback stream actually stop?

rm -f /tmp/int6.ndjson
setsid bunny-shell-assistant listen --activation-source push-to-talk-button \
  --presentation-revision 1 > /tmp/int6.ndjson 2>/dev/null &
LISTEN=$!
for i in $(seq 1 200); do
  grep -q '"microphone"' /tmp/int6.ndjson 2>/dev/null && break
  sleep 0.25
done
sleep 0.4
cp /tmp/utt-capabilities.raw /tmp/bunny-mic-queue/int6.raw
TASK=""
for i in $(seq 1 600); do
  if grep -q '"event": "speech_started"' /tmp/int6.ndjson 2>/dev/null; then
    TASK=$(python3 - <<'PY'
import json
for line in open("/tmp/int6.ndjson"):
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
[ -n "$TASK" ] || { echo "speech never started"; kill $LISTEN 2>/dev/null; exit 1; }

echo "=== sink-inputs BEFORE cancel (audio playing?) ==="
pactl list sink-inputs short | cut -c1-100
pactl list sinks short | awk '{print "sink:", $NF}'

sleep 0.5
echo "=== the voice_cancel answer, verbatim ==="
bunny-shell-assistant voice-cancel "$TASK" 2>&1

echo "=== events + sink-inputs for the next 12s ==="
python3 - "$TASK" <<'PY'
import json, subprocess, sys, time
sys.path.insert(0, "/usr/lib/bunny-os/python")
from companion.protocol import CompanionClient, default_endpoint_path
client = CompanionClient(default_endpoint_path(), timeout=10.0)
seen = set()
start = time.monotonic()
while time.monotonic() - start < 12:
    status = dict(client.call("voice_status", {}))
    fresh = []
    for event in status.get("recentEvents", []):
        key = (event.get("kind"), event.get("requestId"), str(event.get("atMonotonic")))
        if key in seen: continue
        seen.add(key)
        if time.monotonic() - start > 0.5 or True:
            fresh.append((event.get("kind"), str(event.get("requestId"))[:24],
                          str(event.get("detail"))[:60]))
    inputs = subprocess.run(["pactl", "list", "sink-inputs", "short"],
                            capture_output=True, text=True).stdout.strip()
    t = round(time.monotonic() - start, 1)
    if fresh:
        for kind, rid, detail in fresh:
            print(f"t={t} EVENT {kind} {rid} {detail}")
    print(f"t={t} sinkInputs={len(inputs.splitlines()) if inputs else 0} queueDepth={status.get('queueDepth')}")
    time.sleep(1)
PY
kill "$LISTEN" 2>/dev/null || true
