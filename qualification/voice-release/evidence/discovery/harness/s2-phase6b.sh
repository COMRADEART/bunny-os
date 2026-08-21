#!/bin/bash
# Stage 2 phase 6b: the two phase-6 retries — renderer slice with the session
# companion stopped, and the active-CPU sample without the pipe-holding trap.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ slice commands the installed CLI offers ############"
cat > "$E/s2-cli-slices.sh" <<'EOS'
set -u
bunny-os companion --help 2>&1 | grep -iE "slice|render" | head -10
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-cli-slices.sh"

echo "############ renderer slice with the session companion stopped ############"
cat > "$E/s2-slice-solo.sh" <<'EOS'
set -u
systemctl --user stop bunny-companion.service
sleep 2
export XDG_RUNTIME_DIR=/run/user/1000
timeout 600 bunny-os --json companion run-voice-renderer-slice > /tmp/slice-vr.json 2>/tmp/slice-vr.err
echo "voice-renderer slice exit: $?"
python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/slice-vr.json"))
except Exception as exc:
    print("unreadable:", exc)
    print(open("/tmp/slice-vr.err").read()[:600])
    raise SystemExit
steps = d.get("steps", [])
passed = sum(1 for s in steps if s.get("outcome") == "pass")
notrun = [s.get("step") for s in steps if s.get("outcome") not in ("pass", None)]
print(f"steps={len(steps)} pass={passed} other={notrun}")
for key in ("outcome", "renderer", "mode", "presentation", "recommendation"):
    if key in d: print(f"{key}: {d[key]}")
PY
systemctl --user start bunny-companion.service
sleep 5
systemctl --user is-active bunny-companion.service
EOS
python3 "$E/ask.py" s2 shell --timeout 700 "@$E/s2-slice-solo.sh" | tee "$L/slice-solo.log" | tail -20

echo "############ active-CPU sample, sampler as a transient unit ############"
cat > "$E/s2-cpu-active2.sh" <<'EOS'
set -u
cat > /tmp/cpu-sampler.py <<'PY'
import json, os, time

def find(needle):
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                if needle.encode() in handle.read():
                    return int(pid)
        except OSError:
            continue
    return None

def cpu(pid):
    try:
        with open(f"/proc/{pid}/stat") as handle:
            parts = handle.read().split()
        return (int(parts[13]) + int(parts[14])) / os.sysconf("SC_CLK_TCK")
    except OSError:
        return None

companion = find("bunny-companion-service")
samples = []
start = time.monotonic()
prev = {"companion": cpu(companion)}
worker = None
while time.monotonic() - start < 75:
    time.sleep(1.0)
    if worker is None:
        worker = find("neural_worker.py")
        if worker is not None:
            prev["worker"] = cpu(worker)
    now = {"companion": cpu(companion)}
    if worker is not None:
        now["worker"] = cpu(worker)
    row = {"t": round(time.monotonic() - start, 1)}
    for key, value in now.items():
        if prev.get(key) is not None and value is not None:
            row[key] = round(value - prev[key], 3)
    samples.append(row)
    prev = now
open("/tmp/cpu-active.json", "w").write(json.dumps(samples))
PY
systemctl --user stop bunny-cpu-sampler.service 2>/dev/null || true
rm -f /tmp/cpu-active.json
systemd-run --user --unit=bunny-cpu-sampler --collect /usr/bin/python3 /tmp/cpu-sampler.py
echo sampler-armed
EOS
python3 "$E/ask.py" s2 shell --timeout 60 "@$E/s2-cpu-active2.sh"
bash "$E/speak.sh" s2 /tmp/utt-memory.raw cpuflow2 1 | grep -E "transcript|speech_started|speech_finished|finished" | head -4
sleep 20
python3 "$E/ask.py" s2 shell --timeout 60 'python3 -c "
import json
rows = json.load(open(\"/tmp/cpu-active.json\"))
busy = [r for r in rows if any(v > 0.05 for k, v in r.items() if k != \"t\")]
print(\"samples:\", len(rows), \"busy:\", len(busy))
for r in busy[:25]: print(r)
"' | tee "$L/cpu-active2.json"

echo "############ PHASE6B DONE ############"
