#!/bin/bash
# Stage 2 phase 6: renderer-mode evidence on the artifact, quiescence/CPU
# measurements, RSS snapshot.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ session units and renderer surface inventory ############"
cat > "$E/s2-units.sh" <<'EOS'
set -u
systemctl --user list-units --all --no-legend --plain 'bunny*' | cut -c1-110
echo "--- window/renderer processes ---"
pgrep -a -u bunny -f "gtk_shell|companion.window|character" | cut -c1-140 || echo "none"
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-units.sh" | tee "$L/units.log"

echo "############ renderer slice: what the installed CLI offers ############"
cat > "$E/s2-slice-help.sh" <<'EOS'
set -u
bunny-os companion run-voice-renderer-slice --help 2>&1 | head -40
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-slice-help.sh" | tee "$L/slice-help.log"

echo "############ voice-renderer slice (installed, default mode) ############"
cat > "$E/s2-slice-run.sh" <<'EOS'
set -u
export XDG_RUNTIME_DIR=/run/user/1000
timeout 600 bunny-os --json companion run-voice-renderer-slice 2>&1 | tail -40
EOS
python3 "$E/ask.py" s2 shell --timeout 700 "@$E/s2-slice-run.sh" | tee "$L/slice-default.log" | tail -25

echo "############ quiescence + CPU: 60s idle sample ############"
cat > "$E/s2-cpu-idle.sh" <<'EOS'
set -u
python3 - <<'PY'
import json, os, time

def find(needle_list):
    hits = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmd = handle.read().decode("utf-8", "replace").replace("\x00", " ")
        except OSError:
            continue
        for name, needle in needle_list:
            if needle in cmd and name not in hits:
                hits[name] = int(pid)
    return hits

def cpu_seconds(pid):
    try:
        with open(f"/proc/{pid}/stat") as handle:
            parts = handle.read().split()
        return (int(parts[13]) + int(parts[14])) / os.sysconf("SC_CLK_TCK")
    except OSError:
        return None

def rss_mib(pid):
    try:
        with open(f"/proc/{pid}/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None

targets = find([
    ("companion", "bunny-companion-service"),
    ("neuralWorker", "bunny-voice-neural-worker"),
    ("gnomeShell", "/usr/bin/gnome-shell"),
])
before = {name: cpu_seconds(pid) for name, pid in targets.items()}
time.sleep(60)
after = {name: cpu_seconds(pid) for name, pid in targets.items()}
report = {"windowSeconds": 60, "processes": {}}
for name, pid in targets.items():
    if before.get(name) is None or after.get(name) is None:
        continue
    report["processes"][name] = {
        "pid": pid,
        "cpuSecondsOver60s": round(after[name] - before[name], 3),
        "cpuPercent": round((after[name] - before[name]) / 60 * 100, 2),
        "rssMiB": rss_mib(pid),
    }
print(json.dumps(report, indent=1))
PY
EOS
python3 "$E/ask.py" s2 shell --timeout 180 "@$E/s2-cpu-idle.sh" | tee "$L/cpu-idle.json"

echo "############ CPU during a spoken flow ############"
cat > "$E/s2-cpu-active.sh" <<'EOS'
set -u
python3 - <<'PY' &
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
worker = find("bunny-voice-neural-worker")
samples = []
start = time.monotonic()
prev = {"companion": cpu(companion), "worker": cpu(worker) if worker else None}
while time.monotonic() - start < 45:
    time.sleep(1.0)
    now = {"companion": cpu(companion), "worker": cpu(worker) if worker else None}
    row = {"t": round(time.monotonic() - start, 1)}
    for key in ("companion", "worker"):
        if prev.get(key) is not None and now.get(key) is not None:
            row[key] = round(now[key] - prev[key], 3)
    samples.append(row)
    prev = now
open("/tmp/cpu-active.json", "w").write(json.dumps(samples))
PY
SAMPLER=$!
sleep 2
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-cpu-active.sh" >/dev/null
bash "$E/speak.sh" s2 /tmp/utt-memory.raw cpuflow 1 | grep -E "transcript|speech_started|finished" | head -4
sleep 8
python3 "$E/ask.py" s2 shell --timeout 60 'cat /tmp/cpu-active.json 2>/dev/null | head -c 3000; echo' | tee "$L/cpu-active.json"

echo "############ PHASE6 DONE ############"
