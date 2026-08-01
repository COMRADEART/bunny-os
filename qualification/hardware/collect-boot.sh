#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Boot evidence collector. Runs ON the target device after a boot whose
# outcome is being recorded (first-boot, reboot, update, rollback...).
#
# The journal is the risky artifact here: every line carries the hostname,
# and NetworkManager logs MAC addresses. Hostname and MAC are both excluded
# categories in release/hardware.py, and the intake would reject the report —
# so they are removed at collection time (--no-hostname, plus a MAC strip on
# the way to disk) rather than trusted to a later manual pass.
#
# Usage: collect-boot.sh <output-dir>
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

collect() {
    local out="$outdir/$1"
    shift
    if command -v "$1" > /dev/null 2>&1; then
        "$@" > "$out" 2>&1 || printf '\nEXIT-STATUS: %s exited non-zero\n' "$1" >> "$out"
    else
        printf 'ABSENT: %s is not installed on this system\n' "$1" > "$out"
    fi
}

# Journal of the current boot. --no-hostname drops the hostname column, and
# the sed strips any MAC before the line reaches disk — the unredacted form
# never exists in the output directory, not even transiently.
if command -v journalctl > /dev/null 2>&1; then
    journalctl -b --no-hostname -o short-iso 2>&1 \
        | sed -E "s/$mac_re/REDACTED-MAC/g" > "$outdir/journal-current-boot.txt" \
        || printf '\nEXIT-STATUS: journalctl exited non-zero\n' >> "$outdir/journal-current-boot.txt"
else
    printf 'ABSENT: journalctl is not installed on this system\n' > "$outdir/journal-current-boot.txt"
fi

collect systemd-analyze.txt systemd-analyze
collect critical-chain.txt systemd-analyze critical-chain
collect bootctl-status.txt bootctl status
# bootc status names the deployed image and digest — this is the file that
# ties the boot evidence to installedArtifactDigest in the hardware record.
collect bootc-status.txt bootc status
collect lsblk.txt lsblk
collect findmnt.txt findmnt
cat /proc/cmdline > "$outdir/cmdline.txt"

# Manifest last, sorted, so post-collection edits are detectable.
(
    cd "$outdir"
    find . -type f ! -name manifest.sha256 -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
)

echo "collect-boot.sh: wrote $(wc -l < "$outdir/manifest.sha256") files into $outdir (see manifest.sha256)"
