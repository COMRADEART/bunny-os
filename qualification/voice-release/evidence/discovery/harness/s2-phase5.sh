#!/bin/bash
# Stage 2 phase 5: deny path, session parity, continuity honesty, offline E2E.
set -uo pipefail
exec 2>&1
E=/root/bunny-ops/e2e
L=$E/s2-logs
mkdir -p "$L"
cd /root/bunny-os

echo "############ AG-5 deny: spoken Open Terminal, denied on purpose ############"
sed 's/"$REQID" allow/"$REQID" deny/' "$E/speak-template.sh" > "$E/s2-deny-template.sh"
grep -n "deny" "$E/s2-deny-template.sh" | head -3
OUT="$E/speak-deny.sh"
sed -e "s#__UTTERANCE__#/tmp/utt-terminal.raw#" -e "s#__TAG__#deny#" -e "s#__APPROVE__#1#" \
  "$E/s2-deny-template.sh" > "$OUT"
python3 "$E/ask.py" s2 shell --timeout 500 "@$OUT" | tee "$L/deny.log" | grep -E "transcript|approval|allowing|reply|finished|error|phase" | head -14
cat > "$E/s2-no-terminal.sh" <<'EOS'
set -u
echo "--- terminal processes after the deny ---"
pgrep -a -u bunny -f "ptyxis|gnome-terminal|kgx" || echo "no terminal process"
echo "--- terminal windows on the accessibility bus ---"
python3 - <<'PY'
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
Atspi.init()
desktop = Atspi.get_desktop(0)
hits = []
for i in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(i)
    if app is None: continue
    name = (app.get_name() or "").lower()
    if "terminal" in name or "ptyxis" in name or "console" in name:
        hits.append(name)
print("terminal applications:", hits or "none")
PY
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-no-terminal.sh" | tail -6

echo "############ AG-2 session parity: a typed question joins the same session ############"
cat > "$E/s2-typed.sh" <<'EOS'
set -u
bunny-shell-assistant ask "What time is it?" 2>/tmp/ask.err | head -12
EOS
python3 "$E/ask.py" s2 shell --timeout 300 "@$E/s2-typed.sh" | tee "$L/typed.log" | head -12
cat > "$E/s2-sessions.sh" <<'EOS'
set -u
python3 - <<'PY'
import json, sys
sys.path.insert(0, "/usr/lib/bunny-os/python")
from companion.protocol import CompanionClient, default_endpoint_path
client = CompanionClient(default_endpoint_path(), timeout=20.0)
listing = dict(client.call("list_sessions", {}))
for session in listing.get("sessions", []):
    print("session:", session.get("sessionId"), repr(session.get("title")),
          "active:", session.get("activeTaskIds", session.get("activeTasks")),
          "completed:", session.get("completedTaskIds", session.get("completedTasks")))
PY
echo "--- the store on disk ---"
for root in ~/.local/state ~/.local/share; do
  find "$root" -name "session.json" 2>/dev/null | while read -r f; do
    d=$(dirname "$f")
    tasks=$(ls "$d"/tasks/*.json 2>/dev/null | wc -l)
    echo "$f tasks=$tasks"
    python3 -c "import json;d=json.load(open('$f'));print('  title:',d.get('title'),'id:',d.get('sessionId'))" 2>/dev/null
  done
done
EOS
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-sessions.sh" | tee "$L/sessions.log" | head -20

echo "############ EE-4 offline: links down, spoken Open Terminal ############"
python3 "$E/ask.py" s2 shell --root --timeout 120 "@$E/go-offline.sh" | tee "$L/offline-links.log" | tail -6
bash "$E/speak.sh" s2 /tmp/utt-terminal.raw offline 1 | tee "$L/offline.log" | grep -E "transcript|approval|allowing|reply|speech_started|finished|error" | head -12
python3 "$E/ask.py" s2 shell --timeout 120 "@$E/s2-no-terminal.sh" | tail -6
python3 "$E/ask.py" s2 shell --root --timeout 120 "@$E/go-online.sh" | tail -3

echo "############ AG-3 continuity honesty: a follow-up by reference ############"
python3 "$E/ask.py" s2 shell --timeout 240 'python3 /tmp/make-utterance.py "Now close it." /tmp/utt-closeit.raw kitten 2>&1 | tail -1'
bash "$E/speak.sh" s2 /tmp/utt-closeit.raw closeit 1 | tee "$L/closeit.log" | grep -E "transcript|reply|finished|error|warning" | head -8

echo "############ PHASE5 DONE ############"
