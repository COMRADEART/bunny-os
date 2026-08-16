set -u
# Instrumented reproduction of the post-cancel speech stall.
# Watches the neural worker PID and voice_status recentEvents at 1 Hz while
# a cancel and then a fresh interaction happen.

echo "=== worker pid before ==="
pgrep -f bunny-voice-neural-worker || echo "no worker"

# The status watcher, in the background, writing NDJSON.
rm -f /tmp/stall-watch.ndjson
systemctl --user stop bunny-stall-watch.service 2>/dev/null || true
cat > /tmp/stall-watch.py <<'PY'
import json, subprocess, sys, time
sys.path.insert(0, "/usr/lib/bunny-os/python")
from companion.protocol import CompanionClient, default_endpoint_path
client = CompanionClient(default_endpoint_path(), timeout=10.0)
seen = set()
out = open("/tmp/stall-watch.ndjson", "a", buffering=1)
start = time.monotonic()
while time.monotonic() - start < 100:
    try:
        status = dict(client.call("voice_status", {}))
    except Exception as exc:
        out.write(json.dumps({"t": round(time.monotonic()-start,1), "error": str(exc)}) + "\n")
        time.sleep(1); continue
    pid = subprocess.run(["pgrep", "-f", "bunny-voice-neural-worker"],
                         capture_output=True, text=True).stdout.split()
    fresh = []
    for event in status.get("recentEvents", []):
        key = (event.get("kind"), event.get("requestId"), str(event.get("atMonotonic")))
        if key in seen: continue
        seen.add(key)
        fresh.append({k: event.get(k) for k in
                      ("kind", "requestId", "taskId", "providerId", "detail", "disposition")})
    record = {"t": round(time.monotonic()-start, 1), "workerPids": pid,
              "speaking": status.get("speaking"), "queueDepth": status.get("queueDepth")}
    if fresh: record["new"] = fresh
    out.write(json.dumps(record) + "\n")
    time.sleep(1)
PY
systemd-run --user --unit=bunny-stall-watch --collect \
  --property=StandardOutput=file:/tmp/stall-watch.log \
  --property=StandardError=file:/tmp/stall-watch.log \
  /usr/bin/python3 /tmp/stall-watch.py
sleep 2

echo "=== interrupt: speak, cancel mid-speech ==="
rm -f /tmp/int3.ndjson
setsid bunny-shell-assistant listen --activation-source push-to-talk-button \
  --presentation-revision 1 > /tmp/int3.ndjson 2>/dev/null &
LISTEN1=$!
for i in $(seq 1 200); do
  grep -q '"microphone"' /tmp/int3.ndjson 2>/dev/null && break
  sleep 0.25
done
sleep 0.4
cp /tmp/utt-capabilities.raw /tmp/bunny-mic-queue/int3.raw
TASK=""
for i in $(seq 1 600); do
  if grep -q '"event": "speech_started"' /tmp/int3.ndjson 2>/dev/null; then
    TASK=$(python3 - <<'PY'
import json
for line in open("/tmp/int3.ndjson"):
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
[ -n "$TASK" ] || { echo "speech never started"; exit 1; }
sleep 1.0
echo "cancelling $TASK at watcher-relative $(date +%s.%N)"
bunny-shell-assistant voice-cancel "$TASK" >/dev/null 2>&1
kill "$LISTEN1" 2>/dev/null || true

echo "=== next interaction, immediately ==="
rm -f /tmp/next3.ndjson
setsid bunny-shell-assistant listen --activation-source push-to-talk-button \
  --presentation-revision 1 > /tmp/next3.ndjson 2>/dev/null &
LISTEN2=$!
for i in $(seq 1 200); do
  grep -q '"microphone"' /tmp/next3.ndjson 2>/dev/null && break
  sleep 0.25
done
sleep 0.4
cp /tmp/utt-memory.raw /tmp/bunny-mic-queue/next3.raw
for i in $(seq 1 100); do
  grep -qE '"event": ?"(finished|error)"' /tmp/next3.ndjson 2>/dev/null && break
  sleep 1
done
kill "$LISTEN2" 2>/dev/null || true
sleep 3
systemctl --user stop bunny-stall-watch.service 2>/dev/null || true

echo "=== the stall watch (worker pids + fresh events per second) ==="
cat /tmp/stall-watch.ndjson
echo "=== next interaction's own events ==="
python3 - <<'PY'
import json
for line in open("/tmp/next3.ndjson"):
    line=line.strip()
    if not line: continue
    try: d=json.loads(line)
    except json.JSONDecodeError: continue
    e=d.pop("event","?")
    keep={k:v for k,v in d.items() if k in ("phase","text","reason","providerId","disposition","detail")}
    print(f"{e:20} {json.dumps(keep)[:160]}")
PY
