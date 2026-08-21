set -u
cp -f /mnt/bunnyshare/tools/py-spy /tmp/py-spy
chmod 0755 /tmp/py-spy
/tmp/py-spy --version || { echo "py-spy unavailable"; exit 3; }
COMPANION_PID=$(pgrep -f "bunny-companion" | head -1)
echo "companion pid: $COMPANION_PID"
ps -o pid,cmd -p "$COMPANION_PID" | tail -1 | cut -c1-140
echo "=================== STACKS (mid-stall) ==================="
/tmp/py-spy dump --pid "$COMPANION_PID" 2>&1
echo "=================== STACKS again (+8s) ==================="
sleep 8
/tmp/py-spy dump --pid "$COMPANION_PID" 2>&1
