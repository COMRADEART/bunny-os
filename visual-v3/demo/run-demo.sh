#!/bin/sh
# Bunny Shell Experimental — reviewer demo.
#
# BUNNY WAYLAND SHELL EXPERIMENT
# NOT RELEASE QUALIFIED
# DO NOT USE AS THE DEFAULT SESSION
#
# Runs the shell nested inside your existing desktop, with the Bunny chrome and
# a real GTK 4 application on top of it. Your own session is never replaced.
set -eu

printf '%s\n' 'BUNNY WAYLAND SHELL EXPERIMENT' >&2
printf '%s\n' 'NOT RELEASE QUALIFIED' >&2
printf '%s\n' 'DO NOT USE AS THE DEFAULT SESSION' >&2

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BINARY=${BUNNY_SHELL_BINARY:-$ROOT/compositor/bunny-shell/target/release/bunny-shell}
MODE=${MODE:-regular}
SOCKET=${SOCKET:-bunny-demo}
DURATION=${DURATION:-120}

[ -x "$BINARY" ] || { echo "build it first: make bunny-shell-build" >&2; exit 2; }
[ -n "${WAYLAND_DISPLAY:-}" ] || { echo "needs a Wayland session to nest inside" >&2; exit 2; }

export BUNNY_SHELL_EXPERIMENTAL=1
export PYTHONPATH="$ROOT/apps/common"
RUNTIME=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
rm -f "$RUNTIME/$SOCKET" "$RUNTIME/$SOCKET.lock"

echo "starting the compositor on WAYLAND_DISPLAY=$SOCKET for ${DURATION}s (mode: $MODE)" >&2
BUNNY_SHELL_MODE="$MODE" "$BINARY" --socket "$SOCKET" --run-seconds "$DURATION" &
SHELL_PID=$!

i=0
while [ "$i" -lt 200 ]; do
    [ -S "$RUNTIME/$SOCKET" ] && break
    i=$((i + 1))
    sleep 0.1
done
[ -S "$RUNTIME/$SOCKET" ] || { echo "the compositor did not come up" >&2; exit 1; }

launch() {
    WAYLAND_DISPLAY="$SOCKET" BUNNY_SHELL_MODE="$MODE" GDK_BACKEND=wayland "$@" &
    sleep 3
}

launch python3 "$ROOT/shell-ui/top-bar/bunny-top-bar"
launch python3 "$ROOT/shell-ui/dock/bunny-dock"
launch python3 "$ROOT/shell-ui/assistant-panel/bunny-assistant-panel"
launch python3 "$ROOT/shell-ui/command-palette/bunny-command-palette"
if command -v gtk4-widget-factory >/dev/null 2>&1; then
    launch gtk4-widget-factory
fi

echo "demo running; the shell exits on its own after ${DURATION}s" >&2
wait "$SHELL_PID" || true
echo "demo finished" >&2
