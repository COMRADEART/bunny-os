#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The booted vertical slice: start, limit, health-check and stop one harmless
# real service through the applicator, against real systemd and a real cgroup v2
# hierarchy, and record what the kernel actually reports at each step.
#
# Every number this prints is read back from the kernel or from systemd. Nothing
# is asserted from what the applicator believes it did, because the entire point
# of the exercise is to find out whether those two agree.
#
# It refuses to run anywhere it could damage something: systemd must be PID 1,
# the cgroup hierarchy must be v2, and the target unit must be the probe.

set -uo pipefail

SLICE_ROOT="${SLICE_ROOT:-/root/capability-validation}"
EVIDENCE="${EVIDENCE:-/root/capability-evidence}"
UNIT="bunny-bunny-capability-probe.service"
STATE="${STATE:-/tmp/cap-slice-state}"
RUNDIR="${RUNDIR:-/tmp/cap-slice-run}"

fail() { echo "BLOCKED: $*" >&2; exit 2; }
step() { printf '\n=== %s ===\n' "$*"; }

# ---------------------------------------------------------------- preflight --
step "preflight"
[ "$(ps -p 1 -o comm=)" = "systemd" ] || fail "systemd is not PID 1; this measures nothing"
[ "$(stat -fc %T /sys/fs/cgroup)" = "cgroup2fs" ] || fail "/sys/fs/cgroup is not cgroup v2"
grep -qw memory /sys/fs/cgroup/cgroup.controllers || fail "no memory controller"
command -v systemctl >/dev/null || fail "systemctl absent"

mkdir -p "$EVIDENCE"
{
  echo "kernel=$(uname -r)"
  echo "arch=$(uname -m)"
  echo "systemd=$(systemctl --version | head -1)"
  echo "cgroup=$(stat -fc %T /sys/fs/cgroup)"
  echo "controllers=$(cat /sys/fs/cgroup/cgroup.controllers)"
  echo "python=$(python3 --version)"
  echo "virtualisation=$(systemd-detect-virt || echo none)"
} | tee "$EVIDENCE/environment.txt"

# ------------------------------------------------------------------ install --
step "install the probe and its unit"
install -m 0555 "$SLICE_ROOT/capability/testing/bunny-capability-probe" /usr/libexec/bunny-capability-probe \
  || fail "could not install the probe"
install -m 0644 "$SLICE_ROOT/capability/testing/bunny-capability-probe.service" "/usr/lib/systemd/system/$UNIT" \
  || fail "could not install the unit"
systemctl daemon-reload || fail "daemon-reload failed"
echo "installed /usr/libexec/bunny-capability-probe and $UNIT"

# The applicator derives the unit name from the service id. Confirm the name it
# will use is the name we installed, rather than assuming the mapping.
DERIVED=$(cd "$SLICE_ROOT" && python3 -c "
from capability.apply.systemd import unit_name_for
print(unit_name_for('bunny.capability.probe'))")
[ "$DERIVED" = "$UNIT" ] || fail "the applicator derives '$DERIVED' but '$UNIT' was installed"
echo "unit-name mapping confirmed: bunny.capability.probe -> $DERIVED"

# --------------------------------------------------------------------- slice --
step "run the vertical slice through the applicator"
rm -rf "$STATE" "$RUNDIR"
cd "$SLICE_ROOT" || fail "no $SLICE_ROOT"

STATE="$STATE" RUNDIR="$RUNDIR" UNIT="$UNIT" EVIDENCE="$EVIDENCE" \
python3 scripts/capability_slice.py
RESULT=$?

# ------------------------------------------------------------------ cleanup --
step "cleanup"
systemctl stop "$UNIT" 2>/dev/null
systemctl disable "$UNIT" 2>/dev/null
rm -f "/usr/lib/systemd/system/$UNIT" /usr/libexec/bunny-capability-probe
systemctl daemon-reload
echo "removed the probe unit and binary"

exit $RESULT
