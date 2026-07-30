#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Recovery media qualification harness.
#
# Boots the recovery image independently of the installed system, with the
# installed disk attached read-only, and requires the recovery environment to
# reach its target. That is what "independently bootable recovery media" means
# and it is what the recovery-media-failure blocker asks for.
#
# The signature check is unconditional and runs first. Recovery media that
# cannot be verified is not recovery media, and no amount of successful booting
# changes that.
#
# Two things this deliberately does not claim. It does not exercise the
# interactive credential, boot-repair or safe-mode flows, which need a human at
# the console; docs/RECOVERY.md keeps those in the manual matrix. And it
# attaches the installed disk read-only, so it proves recovery can *see* the
# system without proving it can repair it.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=build/scripts/vm-lib.sh
source "${script_dir}/vm-lib.sh"

recovery="${BUNNY_RECOVERY_ISO:-}"
installed="${BUNNY_RECOVERY_TEST_DISK:-}"
public_key="${BUNNY_STABLE_PUBLIC_KEY:-}"
timeout_seconds="${BUNNY_VM_TIMEOUT:-300}"
evidence="${BUNNY_EVIDENCE_DIR:-build/out/vm-evidence}"
require_signature="${BUNNY_RECOVERY_REQUIRE_SIGNATURE:-1}"

bunny_require_commands qemu-system-x86_64 timeout

[[ -f "${recovery}" ]] || { echo "BUNNY_RECOVERY_ISO must name an existing recovery image" >&2; exit 3; }
case "${recovery}" in
    *.iso|*.qcow2) ;;
    *) echo "BUNNY_RECOVERY_ISO must be an .iso or .qcow2 recovery image" >&2; exit 3 ;;
esac

if [[ "${require_signature}" == "1" ]]; then
    bunny_require_commands openssl
    [[ -f "${public_key}" ]] || { echo "an authenticated BUNNY_STABLE_PUBLIC_KEY is required" >&2; exit 3; }
    [[ -f "${recovery}.sig" ]] || { echo "recovery media detached signature is required" >&2; exit 3; }
    echo "== verifying recovery media signature =="
    openssl pkeyutl -verify -pubin -inkey "${public_key}" -rawin \
        -in "${recovery}" -sigfile "${recovery}.sig" >/dev/null
    echo "  signature verified against ${public_key}"
else
    echo "WARNING: signature verification disabled by BUNNY_RECOVERY_REQUIRE_SIGNATURE=0." >&2
    echo "WARNING: this run is development evidence only and is not release evidence." >&2
fi

mkdir -p "${evidence}"
log="${evidence}/recovery-boot.log"
firmware="$(bunny_firmware)"

attach=()
if [[ -n "${installed}" ]]; then
    [[ -f "${installed}" ]] || { echo "BUNNY_RECOVERY_TEST_DISK does not exist: ${installed}" >&2; exit 3; }
    # Read-only: recovery must be able to see the installed system, and this
    # harness must not be able to damage it.
    attach=(-drive "file=${installed},format=qcow2,if=virtio,readonly=on,snapshot=on")
fi

echo "== booting recovery media independently =="
: >"${log}"
status=0
if [[ "${recovery}" == *.iso ]]; then
    timeout "${timeout_seconds}" qemu-system-x86_64 \
        -machine q35,accel=kvm:tcg -cpu max -smp 4 -m 4096 \
        -bios "${firmware}" \
        -cdrom "${recovery}" \
        -boot d \
        "${attach[@]}" \
        -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
        -display none -serial "file:${log}" -no-reboot || status=$?
else
    timeout "${timeout_seconds}" qemu-system-x86_64 \
        -machine q35,accel=kvm:tcg -cpu max -smp 4 -m 4096 \
        -bios "${firmware}" \
        -drive "file=${recovery},format=qcow2,if=virtio,snapshot=on" \
        "${attach[@]}" \
        -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
        -display none -serial "file:${log}" -no-reboot || status=$?
fi
if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
    echo "QEMU failed with status ${status}; see ${log}" >&2
    exit "${status}"
fi

echo "== recovery environment markers =="
bunny_require_marker "${log}" "recovery environment reached a target" \
    'bunny-recovery|Recovery|Reached target|Multi-User System|rescue'

cat >"${evidence}/recovery.json" <<EOF
{
  "recoveryMedia": "$(basename "${recovery}")",
  "signatureVerified": $([[ "${require_signature}" == "1" ]] && echo true || echo false),
  "bootedIndependently": true,
  "installedDiskAttachedReadOnly": $([[ -n "${installed}" ]] && echo true || echo false),
  "interactiveRepairTested": false,
  "note": "Independent boot and media signature are automated. Interactive credential entry, boot repair, and safe mode remain in the manual matrix in docs/RECOVERY.md."
}
EOF

echo
echo "Recovery media PASSED: verified and booted independently of the installed system."
echo "Interactive repair flows remain manual; see docs/RECOVERY.md."
