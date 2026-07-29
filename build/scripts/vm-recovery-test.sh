#!/usr/bin/env bash
set -euo pipefail

recovery="${BUNNY_RECOVERY_ISO:-}"
installed="${BUNNY_RECOVERY_TEST_DISK:-}"
public_key="${BUNNY_STABLE_PUBLIC_KEY:-}"
for command in qemu-system-x86_64 openssl; do
  command -v "$command" >/dev/null || { echo "missing recovery VM command: $command" >&2; exit 3; }
done
[[ -f "$recovery" && "$recovery" == *.iso ]] || { echo "a signed independent BUNNY_RECOVERY_ISO is required" >&2; exit 3; }
[[ -f "$installed" && "$installed" == *.qcow2 ]] || { echo "a disposable installed BUNNY_RECOVERY_TEST_DISK is required" >&2; exit 3; }
[[ -f "$public_key" ]] || { echo "an authenticated BUNNY_STABLE_PUBLIC_KEY is required" >&2; exit 3; }
[[ -f "$recovery.sig" ]] || { echo "recovery ISO detached signature is required" >&2; exit 3; }
openssl pkeyutl -verify -pubin -inkey "$public_key" -rawin -in "$recovery" -sigfile "$recovery.sig" >/dev/null

echo "Recovery media signature verified. Interactive credential, boot repair, safe mode, and preservation steps require the reviewed KVM harness." >&2
exit 78
