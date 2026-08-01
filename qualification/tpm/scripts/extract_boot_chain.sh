#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Extract the boot chain from the qualified disk, read-only, and record who
# owns which behaviour: every EFI executable hashed, the BLS entries and
# GRUB configuration digested, and the ownership of the restoration-dialog
# strings established by encoding-aware string extraction (shim stores its
# messages as UTF-16LE; a single-byte pass finds nothing and an earlier
# investigator would have concluded, wrongly, that no binary prints them).
#
# The disk is asserted against the pinned artifact digest before anything
# is read. Requires guestfish (libguestfs) on the machine holding the disk.
set -eu

DISK="${1:?usage: extract_boot_chain.sh <qcow2> <expected-sha256> <output-dir>}"
EXPECTED="${2:?expected sha256 required}"
OUT="${3:?output dir required}"

actual=$(sha256sum "$DISK" | cut -d' ' -f1)
if [ "$actual" != "$EXPECTED" ]; then
  echo "BLOCKED: $DISK digests to ${actual:0:12}, expected ${EXPECTED:0:12}" >&2
  exit 2
fi

rm -rf "$OUT"; mkdir -p "$OUT/esp" "$OUT/boot"
FSLIST=$(guestfish --ro -a "$DISK" launch : list-filesystems)
ESP=$(echo "$FSLIST" | awk -F: '/vfat/ {print $1; exit}' | tr -d ' ')
BOOT=$(echo "$FSLIST" | awk -F: '/ext4/ {print $1; exit}' | tr -d ' ')

guestfish --ro -a "$DISK" <<GF
run
mount-ro $ESP /
tar-out / $OUT/esp.tar
umount /
mount-ro $BOOT /
tar-out / $OUT/bootpart.tar
GF
tar -xf "$OUT/esp.tar" -C "$OUT/esp" && rm "$OUT/esp.tar"
tar -xf "$OUT/bootpart.tar" -C "$OUT/boot" && rm "$OUT/bootpart.tar"

MANIFEST="$OUT/boot-chain-manifest.txt"
{
  echo "# Boot chain of $DISK ($actual)"
  echo "## ESP inventory"
  (cd "$OUT/esp" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
  echo "## boot partition GRUB configuration"
  for f in $(find "$OUT/boot" -maxdepth 3 \( -name grub.cfg -o -name grubenv \) -type f | sort); do
    sha256sum "$f"
  done
  echo "## BLS entries"
  for f in $(find "$OUT/boot" -path '*loader/entries*' -name '*.conf' | sort); do
    sha256sum "$f"; sed 's/^/    /' "$f"
  done
  echo "## dialog-string ownership (UTF-16LE pass)"
  for b in $(find "$OUT/esp" -type f \( -name '*.efi' -o -name '*.EFI' \) | sort); do
    hits=$(strings -e l "$b" | grep -cE 'Boot Option Restoration|Reset System|stop system reset' || true)
    echo "$b: $hits"
    [ "$hits" -gt 0 ] && strings -e l "$b" | grep -E 'Boot Option Restoration|Reset System|stop system reset' | sort -u | sed 's/^/    /'
  done
  echo "## fallback control strings"
  for b in $(find "$OUT/esp" -type f \( -name '*.efi' -o -name '*.EFI' \) | sort); do
    strings -e l "$b" | grep -E '^FB_NO_REBOOT$|fbx64\.efi' | sort -u | sed "s|^|$b: |"
  done
  echo "## BOOT.CSV"
  for c in $(find "$OUT/esp" -iname '*.csv' | sort); do
    sha256sum "$c"; iconv -f UTF-16 -t UTF-8 "$c" 2>/dev/null | sed 's/^/    /'
  done
  echo "## TPM-related symbols in grubx64.efi"
  strings "$OUT/esp/EFI/fedora/grubx64.efi" | grep -E 'grub_tpm|tpm_fail_fatal|commands/(efi/)?tpm\.c' | sort -u
} > "$MANIFEST"
echo "manifest written to $MANIFEST"
