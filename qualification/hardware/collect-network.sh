#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Network evidence collector. Runs ON the target device.
#
# This is the collector most likely to leak: link output carries MAC
# addresses, and NetworkManager's connection column is usually the Wi-Fi
# SSID — both excluded categories in release/hardware.py. The rule applied
# throughout is redact-before-write: identifiers are removed in the pipe, so
# the unredacted form never exists in the output directory, not even between
# two lines of this script.
#
# Usage: collect-network.sh <output-dir>
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
mac_re='([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}'

# Link state with MAC redaction applied IN THE PIPE, before anything is
# written. The replacement keeps the JSON a valid document (it lands inside
# the string values), and "REDACTED-MAC" is greppable proof the pass ran.
if command -v ip > /dev/null 2>&1; then
    ip -j link 2>&1 | sed -E "s/$mac_re/REDACTED-MAC/g" > "$outdir/ip-link.json" \
        || printf '\nEXIT-STATUS: ip exited non-zero\n' >> "$outdir/ip-link.json"
else
    printf 'ABSENT: ip is not installed on this system\n' > "$outdir/ip-link.json"
fi

# Device status WITHOUT the CONNECTION column: an active connection's name
# is almost always the Wi-Fi network name, an excluded category, and a value
# that was never printed needs no redaction.
if command -v nmcli > /dev/null 2>&1; then
    nmcli --fields DEVICE,TYPE,STATE device status > "$outdir/nmcli-devices.txt" 2>&1 \
        || printf '\nEXIT-STATUS: nmcli exited non-zero\n' >> "$outdir/nmcli-devices.txt"
else
    printf 'ABSENT: nmcli is not installed on this system\n' > "$outdir/nmcli-devices.txt"
fi

collect() {
    local out="$outdir/$1"
    shift
    if command -v "$1" > /dev/null 2>&1; then
        "$@" > "$out" 2>&1 || printf '\nEXIT-STATUS: %s exited non-zero\n' "$1" >> "$out"
    else
        printf 'ABSENT: %s is not installed on this system\n' "$1" > "$out"
    fi
}

collect rfkill.txt rfkill list
# Listening sockets only (-l): what the installed system exposes is a
# qualification fact; who it is talking to is not, and -l never shows peers.
collect listening-sockets.txt ss -lntup

# Manifest last, sorted, so post-collection edits are detectable.
(
    cd "$outdir"
    find . -type f ! -name manifest.sha256 -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
)

echo "collect-network.sh: wrote $(wc -l < "$outdir/manifest.sha256") files into $outdir (see manifest.sha256)"
