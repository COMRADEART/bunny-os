#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hardware inventory collector. Runs ON the target device (a Fedora-family
# installed system), never on a developer workstation, and never as a demo.
#
# dmidecode-free by design: /sys/class/dmi/id exposes the same identity-class
# fields without needing root for most of them, and reading files is easier to
# audit than parsing a binary table. What this script collects are *classes*
# (vendor, model, chipset, driver version); what it must never emit are
# *identities* (serials, MACs, UUIDs, asset tags). The redaction pass at the
# end is therefore not optional post-processing — it runs unconditionally and
# names every redaction it performed in redaction-notes.txt, so a reviewer can
# see that the pass ran and what it removed, without seeing the removed values
# (writing the redacted value into the notes would re-leak it).
#
# Usage: collect-hardware.sh <output-dir>
set -euo pipefail

if [[ $# -ne 1 || -z "${1:-}" ]]; then
    echo "usage: $0 <output-dir>" >&2
    exit 2
fi

# Refuse to run as a demo. No DMI directory means this is not an installed
# physical-style system — a container, WSL without DMI, or a developer shell —
# and evidence produced there would be fabrication with extra steps. NOTE: a
# VM also has DMI, so passing this check does not prove physical hardware;
# what proves it is the hardware RECORD binding (installedArtifactDigest plus
# an operator attesting to a real machine), which no collector can fake.
if [[ ! -d /sys/class/dmi/id ]]; then
    echo "REFUSED: /sys/class/dmi/id is absent; this is not an installed" >&2
    echo "physical-style system. This collector produces qualification" >&2
    echo "evidence and must not be run as a demo. Exit 2, fail closed." >&2
    exit 2
fi

outdir="$1"
mkdir -p "$outdir"
notes="$outdir/redaction-notes.txt"
printf 'redactions performed by collect-hardware.sh:\n' > "$notes"

# --------------------------------------------------------------------------
# DMI identity-class fields. The serial and UUID fields are replaced with the
# literal REDACTED at read time — the unredacted value never touches the
# output directory, not even transiently, because a crash between "write" and
# "redact" must not leave an identifier on disk. product_uuid and the asset
# tags are redacted beyond the brief's three serials: they identify one unit
# exactly as a serial does, and the rule is the category, not the field list.
# --------------------------------------------------------------------------
{
    for f in /sys/class/dmi/id/*; do
        [[ -f "$f" && -r "$f" ]] || continue
        key="$(basename "$f")"
        case "$key" in
            product_serial|board_serial|chassis_serial|product_uuid|chassis_asset_tag|board_asset_tag)
                printf '%s: REDACTED\n' "$key"
                printf 'dmi.txt: %s replaced with REDACTED (device identifier)\n' "$key" >> "$notes"
                ;;
            *)
                printf '%s: %s\n' "$key" "$(tr -d '\0' < "$f" | tr '\n' ' ')"
                ;;
        esac
    done
} > "$outdir/dmi.txt"

# --------------------------------------------------------------------------
# Inventory commands. Each is guarded: an absent tool is RECORDED as absent
# rather than failing the run, because "this system has no lsusb" is itself a
# fact about the system under test, and a collector that dies half-way leaves
# a partial directory that looks like a complete one.
# --------------------------------------------------------------------------
collect() {
    # $1 = output file name, $2... = command
    local out="$outdir/$1"
    shift
    if command -v "$1" > /dev/null 2>&1; then
        # A non-zero exit is recorded, not hidden: a command that failed on
        # this device is evidence too.
        "$@" > "$out" 2>&1 || printf '\nEXIT-STATUS: %s exited non-zero\n' "$1" >> "$out"
    else
        printf 'ABSENT: %s is not installed on this system\n' "$1" > "$out"
    fi
}

collect cpu.txt lscpu
collect pci.txt lspci -nn
collect usb.txt lsusb
cat /proc/version > "$outdir/kernel-version.txt"

# --------------------------------------------------------------------------
# Driver versions for the modules that are actually loaded for GPU and
# network devices. Walked from /sys/class/{drm,net} rather than from lsmod,
# because "loaded" is not "driving a device" — the qualification cares about
# the module bound to the hardware under test.
# --------------------------------------------------------------------------
{
    declare -A seen=()
    for link in /sys/class/drm/card*/device/driver/module /sys/class/net/*/device/driver/module; do
        [[ -e "$link" ]] || continue
        mod="$(basename "$(readlink -f "$link")")"
        [[ -n "${seen[$mod]:-}" ]] && continue
        seen[$mod]=1
        printf '== module: %s ==\n' "$mod"
        if command -v modinfo > /dev/null 2>&1; then
            modinfo "$mod" 2>&1 | grep -E '^(filename|version|vermagic|license|description):' \
                || printf 'modinfo returned nothing for %s\n' "$mod"
        else
            printf 'ABSENT: modinfo is not installed on this system\n'
        fi
    done
    [[ "${#seen[@]}" -gt 0 ]] || printf 'no GPU or network driver modules found via /sys/class\n'
} > "$outdir/driver-versions.txt"

# --------------------------------------------------------------------------
# Redaction pass, unconditional. Lines matching a MAC address are STRIPPED
# (not masked — lspci/lsusb context around a MAC can itself narrow a device,
# so the whole line goes) and each strip is counted per file in
# redaction-notes.txt. The count, not the content: naming the value would
# undo the redaction.
# --------------------------------------------------------------------------
mac_re='([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}'
for f in "$outdir"/*.txt; do
    [[ "$f" == "$notes" ]] && continue
    n="$(grep -cE "$mac_re" "$f" || true)"
    if [[ "${n:-0}" -gt 0 ]]; then
        grep -vE "$mac_re" "$f" > "$f.tmp"
        mv "$f.tmp" "$f"
        printf '%s: stripped %s line(s) matching a MAC address pattern\n' \
            "$(basename "$f")" "$n" >> "$notes"
    fi
done
# A notes file with only its header still proves the pass ran, which is the
# difference between "nothing found" and "nobody looked".
if [[ "$(wc -l < "$notes")" -le 1 ]]; then
    printf 'no further redactions required; the pass ran and found nothing\n' >> "$notes"
fi

# --------------------------------------------------------------------------
# Manifest last: every produced file bound to its sha256, so an edit after
# collection is detectable. sorted for a stable, diffable manifest.
# --------------------------------------------------------------------------
(
    cd "$outdir"
    find . -type f ! -name manifest.sha256 -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
)

echo "collect-hardware.sh: wrote $(wc -l < "$outdir/manifest.sha256") files into $outdir (see manifest.sha256)"
