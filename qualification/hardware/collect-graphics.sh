#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Graphics evidence collector. Runs ON the target device.
#
# Reads DRM state straight from /sys/class/drm rather than through a desktop
# tool: connector status and mode lists exist there whether or not a session
# is running, so this works from a console on a machine where gdm-login is
# the very test being investigated. Nothing here identifies a unit — EDID is
# deliberately NOT dumped, because an EDID block carries the display's serial
# number and a display serial is a device identifier like any other.
#
# Usage: collect-graphics.sh <output-dir>
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

# Per-connector state: status (connected/disconnected), enabled, dpms, and
# the mode list. The first mode in "modes" is the preferred one, which is
# what the hidpi-scaling and external-display tests need to interpret.
{
    found=0
    for conn in /sys/class/drm/card*-*; do
        [[ -d "$conn" ]] || continue
        found=1
        printf '== connector: %s ==\n' "$(basename "$conn")"
        for attr in status enabled dpms; do
            [[ -r "$conn/$attr" ]] && printf '%s: %s\n' "$attr" "$(cat "$conn/$attr")"
        done
        if [[ -r "$conn/modes" && -s "$conn/modes" ]]; then
            printf 'modes:\n'
            sed 's/^/  /' "$conn/modes"
        else
            printf 'modes: none\n'
        fi
        printf '\n'
    done
    # Distinguish "no connectors" from "did not look": a machine with no DRM
    # connectors at all is a finding the graphics tests need to know about.
    [[ "$found" -eq 1 ]] || printf 'NONE: /sys/class/drm contains no connectors\n'
} > "$outdir/drm-connectors.txt"

# The GPU module actually bound to each card, with its version. Bound, not
# merely loaded: lsmod shows what is in memory, /sys shows what drives the
# device under test, and only the latter qualifies anything.
{
    found=0
    for link in /sys/class/drm/card*/device/driver/module; do
        [[ -e "$link" ]] || continue
        found=1
        mod="$(basename "$(readlink -f "$link")")"
        printf '== module: %s ==\n' "$mod"
        if command -v modinfo > /dev/null 2>&1; then
            modinfo "$mod" 2>&1 | grep -E '^(filename|version|vermagic|license|description):' \
                || printf 'modinfo returned nothing for %s\n' "$mod"
        else
            printf 'ABSENT: modinfo is not installed on this system\n'
        fi
    done
    [[ "$found" -eq 1 ]] || printf 'NONE: no GPU driver module found via /sys/class/drm\n'
} > "$outdir/gpu-driver.txt"

# Manifest last, sorted, so post-collection edits are detectable.
(
    cd "$outdir"
    find . -type f ! -name manifest.sha256 -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
)

echo "collect-graphics.sh: wrote $(wc -l < "$outdir/manifest.sha256") files into $outdir (see manifest.sha256)"
