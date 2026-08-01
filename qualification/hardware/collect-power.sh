#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Power and suspend/resume evidence collector. Runs ON the target device.
#
# Every source here is optional hardware or optional tooling: a desktop has
# no battery, a minimal install has no upower. Absence is therefore RECORDED
# rather than fatal — "this system has no upower" is a fact about the system,
# and a collector that exits half-way leaves a directory that looks complete
# but is not. Batteries carry serial numbers (upower prints one, the kernel
# uevent carries POWER_SUPPLY_SERIAL_NUMBER); both are redacted on the way to
# disk because a battery serial identifies a unit as surely as a chassis
# serial does.
#
# Usage: collect-power.sh <output-dir>
set -euo pipefail

if [[ $# -ne 1 || -z "${1:-}" ]]; then
    echo "usage: $0 <output-dir>" >&2
    exit 2
fi

# Refuse to run as a demo (see collect-hardware.sh: a VM also has DMI, so
# this check refuses obviously-wrong environments; the hardware RECORD
# binding is what establishes physicality).
if [[ ! -d /sys/class/dmi/id ]]; then
    echo "REFUSED: /sys/class/dmi/id is absent; this is not an installed" >&2
    echo "physical-style system. This collector produces qualification" >&2
    echo "evidence and must not be run as a demo. Exit 2, fail closed." >&2
    exit 2
fi

outdir="$1"
mkdir -p "$outdir"

# upower -d, with the serial line redacted before it reaches disk.
if command -v upower > /dev/null 2>&1; then
    upower -d 2>&1 \
        | sed -E 's/(serial:[[:space:]]*).*/\1REDACTED/' > "$outdir/upower.txt" \
        || printf '\nEXIT-STATUS: upower exited non-zero\n' >> "$outdir/upower.txt"
else
    printf 'ABSENT: upower is not installed on this system\n' > "$outdir/upower.txt"
fi

# Kernel view of the supplies, independent of upower. The uevent file is the
# stable, parseable form; its SERIAL_NUMBER line is redacted at read time.
{
    found=0
    for supply in /sys/class/power_supply/*; do
        [[ -d "$supply" ]] || continue
        found=1
        printf '== %s ==\n' "$(basename "$supply")"
        if [[ -r "$supply/uevent" ]]; then
            sed -E 's/^(POWER_SUPPLY_SERIAL_NUMBER=).*/\1REDACTED/' "$supply/uevent"
        else
            printf 'uevent not readable\n'
        fi
        printf '\n'
    done
    # No supplies at all is a real state (some desktops), and it must be
    # distinguishable from "the collector did not look".
    [[ "$found" -eq 1 ]] || printf 'NONE: /sys/class/power_supply contains no supplies\n'
} > "$outdir/power-supplies.txt"

# Suspend/resume markers from the journal. --no-hostname because every
# journal line otherwise carries the hostname, an excluded category. A grep
# with no matches exits 1, which here means "this boot never suspended" —
# recorded, not fatal.
if command -v journalctl > /dev/null 2>&1; then
    {
        journalctl -b --no-hostname -o short-iso 2> /dev/null \
            | grep -iE 'suspend entry|suspend exit|PM: suspend|Reached target Sleep|Starting.*[Ss]uspend|resumed from suspend|systemd-sleep' \
            || printf 'NONE: no suspend/resume markers in the current boot journal\n'
    } > "$outdir/suspend-markers.txt"
else
    printf 'ABSENT: journalctl is not installed on this system\n' > "$outdir/suspend-markers.txt"
fi

# Manifest last, sorted, so post-collection edits are detectable.
(
    cd "$outdir"
    find . -type f ! -name manifest.sha256 -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
)

echo "collect-power.sh: wrote $(wc -l < "$outdir/manifest.sha256") files into $outdir (see manifest.sha256)"
