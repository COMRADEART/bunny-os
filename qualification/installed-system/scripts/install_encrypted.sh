#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Encrypted installation of the reproducible root filesystem: LUKS2 under the
# root, prepared explicitly, deployed through `bootc install to-filesystem`.
#
# bootc's to-disk path owns partitioning and carries no LUKS option, so the
# encrypted layout is prepared here — GPT, ESP, /boot, LUKS2 root — and bootc
# deploys into the opened container. The passphrase is a test credential for
# a disposable disk: it arrives through BUNNY_TEST_PASSPHRASE_FILE, reaches
# cryptsetup on stdin, and appears in no log, no record and no error path.
# The record notes the LUKS UUID because two installations must differ in it;
# the UUID identifies a disk, not a secret.
#
# Usage: install_encrypted.sh --target disk.raw --image <ref> --record out.json
#        [--size 64G]

set -euo pipefail

size="64G"
target=""
image=""
record=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --size) size="${2:?}"; shift 2 ;;
    --target) target="${2:?}"; shift 2 ;;
    --image) image="${2:?}"; shift 2 ;;
    --record) record="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${target}" && -n "${image}" && -n "${record}" ]] || {
  echo "BLOCKED: --target, --image and --record are required" >&2; exit 2; }
[[ -n "${BUNNY_TEST_PASSPHRASE_FILE:-}" && -f "${BUNNY_TEST_PASSPHRASE_FILE}" ]] || {
  echo "BLOCKED: BUNNY_TEST_PASSPHRASE_FILE must name a file. The passphrase is" >&2
  echo "never taken from an argument: arguments land in shell history and ps." >&2
  exit 2; }

# The key file must not end with a newline, and this refuses one rather than
# silently creating a volume nobody can unlock by typing.
#
# cryptsetup --key-file uses every byte of the file, newline included; an
# interactive prompt sends the line without it. Measured: an installation
# whose key file ended in \n presented its passphrase prompt, rejected the
# correct passphrase typed at that prompt, and prompted again — with the
# file form accepted and the typed form refused on the same keyslot.
if [[ "$(tail -c 1 "${BUNNY_TEST_PASSPHRASE_FILE}" | od -An -tu1 | tr -d ' ')" == "10" ]]; then
  echo "BLOCKED: ${BUNNY_TEST_PASSPHRASE_FILE} ends with a newline." >&2
  echo "cryptsetup would make that byte part of the key, and nobody typing the" >&2
  echo "passphrase at the boot prompt can send it. Write the file with printf." >&2
  exit 2
fi

for command in podman cryptsetup sgdisk mkfs.fat mkfs.ext4 losetup blkid; do
  command -v "${command}" >/dev/null || { echo "BLOCKED: ${command} missing" >&2; exit 3; }
done

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
rm -f "${target}"
truncate -s "${size}" "${target}"

loop="$(losetup --find --show --partscan "${target}")"
# One teardown, used by both paths. The EXIT trap covers every failure
# between luksOpen and the end; the success path calls it directly rather
# than repeating the same three commands, which is also why shellcheck can
# see that it is invoked.
cleanup() {
  set +e
  umount -R /mnt/bunny-encrypted-install 2>/dev/null
  cryptsetup close bunny-install-root 2>/dev/null
  losetup -d "${loop}" 2>/dev/null
}
trap cleanup EXIT

# GPT: BIOS boot (1M — bootupd installs the BIOS half unconditionally and
# grub2-install refuses a GPT disk without an embedding target; measured) +
# ESP (512M) + /boot (1G, clear-text — the bootloader must read the kernel
# before the passphrase exists) + LUKS2 root (rest). Matches the layout the
# generated disk images carry.
sgdisk --zap-all "${loop}" >/dev/null
sgdisk --new=1:0:+1M   --typecode=1:ef02 --change-name=1:BIOS-BOOT \
       --new=2:0:+512M --typecode=2:ef00 --change-name=2:EFI-SYSTEM \
       --new=3:0:+1G   --typecode=3:8300 --change-name=3:boot \
       --new=4:0:0     --typecode=4:8309 --change-name=4:root "${loop}" >/dev/null
partprobe "${loop}"
sleep 1

mkfs.fat -F32 -n EFI-SYSTEM "${loop}p2" >/dev/null
mkfs.ext4 -q -L boot "${loop}p3"

cryptsetup luksFormat --type luks2 --batch-mode \
  --key-file "${BUNNY_TEST_PASSPHRASE_FILE}" "${loop}p4"
cryptsetup open --key-file "${BUNNY_TEST_PASSPHRASE_FILE}" "${loop}p4" bunny-install-root
mkfs.ext4 -q -L root /dev/mapper/bunny-install-root

mkdir -p /mnt/bunny-encrypted-install
mount /dev/mapper/bunny-install-root /mnt/bunny-encrypted-install
mkdir -p /mnt/bunny-encrypted-install/boot
mount "${loop}p3" /mnt/bunny-encrypted-install/boot
mkdir -p /mnt/bunny-encrypted-install/boot/efi
mount "${loop}p2" /mnt/bunny-encrypted-install/boot/efi

luks_uuid="$(blkid -s UUID -o value "${loop}p4")"

podman run --rm --privileged --pid=host \
  --security-opt label=type:unconfined_t \
  -v /var/lib/containers:/var/lib/containers \
  -v /dev:/dev \
  -v /mnt/bunny-encrypted-install:/target \
  "${image}" \
  bootc install to-filesystem --skip-fetch-check --generic-image \
  --karg "rd.luks.uuid=${luks_uuid}" \
  --karg console=tty0 --karg "console=ttyS0,115200" \
  /target
status=$?

cleanup
trap - EXIT

completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
image_digest="$(podman image inspect --format '{{.Digest}}' "${image}" 2>/dev/null || echo unknown)"

python3 - "${record}" <<PY
import json, sys
json.dump({
    "schemaVersion": 1,
    "mode": "encrypted",
    "image": "${image}",
    "imageDigest": "${image_digest}",
    "target": "${target}",
    "luksVersion": "luks2",
    "luksUuid": "${luks_uuid}",
    "layout": ["EFI-SYSTEM 512M vfat", "boot 1G ext4", "root LUKS2+ext4"],
    "kargAdded": "rd.luks.uuid=${luks_uuid}",
    "startedAt": "${started}",
    "completedAt": "${completed}",
    "outcome": "INSTALLED" if ${status} == 0 else "FAILED",
    "exitStatus": ${status},
    "note": (
        "Passphrase supplied via file to cryptsetup only; it appears in no "
        "argument, log or record. The LUKS UUID is recorded because two "
        "installations must differ in it — it identifies a disk, not a secret."
    ),
}, open(sys.argv[1], "w", encoding="utf-8"), indent=2, sort_keys=True)
open(sys.argv[1], "a", encoding="utf-8").write("\n")
PY

echo "encrypted install: $([[ ${status} -eq 0 ]] && echo INSTALLED || echo FAILED)"
exit "${status}"
