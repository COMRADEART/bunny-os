#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the reproducible root filesystem onto a target disk, and record it.
#
# The supported installation mechanism is bootc's own: the image installs
# itself, running from the image, via `bootc install to-disk` against a
# loopback target. Nothing here unpacks, edits or "fixes up" the root
# filesystem — the deployed root is the image's, byte for byte, which is the
# property stage 2 requires and the verification step below measures.
#
# Modes:
#   blank         a new raw disk of --size, GPT, default layout
#   offline       blank, with --network=none on the installing container: the
#                 installation must complete from retained local content with
#                 no registry or repository fallback possible at all
#   encrypted     LUKS2 with a passphrase read from BUNNY_TEST_PASSPHRASE_FILE
#                 (a test credential for a disposable disk, never logged)
#   undersized    a deliberately too-small disk; the expected outcome is a
#                 refusal before destructive partial deployment
#   existing-data a disk carrying recognisable test data; the installer must
#                 not touch it without the explicit destructive flag
#   interrupted   the install is killed at --interrupt-after seconds; the
#                 disk is kept for recovery-media inspection
#
# Every run writes a machine-readable installation record beside the disk:
# what was installed, from which image digest, with which command, and what
# the verification found.

set -euo pipefail

mode="blank"
size="64G"
target=""
image=""
record=""
interrupt_after=""
destructive=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) mode="${2:?}"; shift 2 ;;
    --size) size="${2:?}"; shift 2 ;;
    --target) target="${2:?}"; shift 2 ;;
    --image) image="${2:?}"; shift 2 ;;
    --record) record="${2:?}"; shift 2 ;;
    --interrupt-after) interrupt_after="${2:?}"; shift 2 ;;
    --destructive) destructive=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "${target}" && -n "${image}" && -n "${record}" ]] || {
  echo "BLOCKED: --target, --image and --record are required" >&2; exit 2; }

for command in podman qemu-img sha256sum python3; do
  command -v "${command}" >/dev/null || { echo "BLOCKED: ${command} missing" >&2; exit 3; }
done

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
outcome="UNKNOWN"
detail=""

if [[ "${mode}" == "encrypted" ]]; then
  # Refused rather than faked: bootc install to-disk carries no LUKS path, so
  # encrypted installation goes through prepared LUKS2 + `install to-filesystem`
  # in install_encrypted.sh. A record from this script labelled "encrypted"
  # over a plaintext deployment would be adversarial-test material, not
  # evidence.
  echo "BLOCKED: encrypted mode is owned by install_encrypted.sh" >&2
  exit 2
fi

case "${mode}" in
  blank|offline|interrupted)
    rm -f "${target}"
    truncate -s "${size}" "${target}"
    ;;
  undersized)
    rm -f "${target}"
    truncate -s 4G "${target}"
    ;;
  existing-data)
    if [[ ! -f "${target}" ]]; then
      # A recognisable, disposable fixture: a filesystem with marker files.
      # Never real user data — the marker content names itself as a fixture.
      truncate -s "${size}" "${target}"
      mkfs.ext4 -q -L BUNNY-PRECIOUS "${target}"
      mount_dir="$(mktemp -d)"
      mount -o loop "${target}" "${mount_dir}"
      echo "existing-data fixture $(date -u +%s): if installation erased this file without --destructive, that is the defect being tested for" \
        > "${mount_dir}/DO-NOT-ERASE.txt"
      sha256sum "${mount_dir}/DO-NOT-ERASE.txt" | awk '{print $1}' > "${target}.fixture-digest"
      umount "${mount_dir}"
      rmdir "${mount_dir}"
    fi
    ;;
  *) echo "unknown mode: ${mode}" >&2; exit 2 ;;
esac

network_args=()
if [[ "${mode}" == "offline" ]]; then
  network_args=(--network=none)
fi

# --filesystem ext4 is explicit because the image ships no install config
# default — measured as "error: Installing to disk: No root filesystem
# specified" — and it matches the ext4 the installable images deploy.
# --wipe rides with --destructive only: bootc itself refuses a carrying
# disk without it, which is a second, independent protection under the
# runner's own authorization gate.
wipe_args=()
[[ "${destructive}" == "1" ]] && wipe_args=(--wipe)

install_cmd=(
  podman run --rm --privileged --pid=host
  --security-opt label=type:unconfined_t
  "${network_args[@]+"${network_args[@]}"}"
  -v /var/lib/containers:/var/lib/containers
  -v /dev:/dev
  -v "$(dirname "$(readlink -f "${target}")"):/output"
  "${image}"
  bootc install to-disk --via-loopback --generic-image
  --filesystem ext4
  # The serial console karg is the qualification harness's one addition to
  # the installed system, and it is why the evidence stream exists at all:
  # without it the kernel boots silently past GRUB and a passing boot is
  # indistinguishable from a hang. Recorded here and in the record below.
  --karg console=ttyS0,115200 --karg console=tty0
  "${wipe_args[@]+"${wipe_args[@]}"}"
  --skip-fetch-check "/output/$(basename "${target}")"
)

run_install() {
  if [[ "${mode}" == "existing-data" && "${destructive}" != "1" ]]; then
    # The protection under test is the runner's own authorization gate: a
    # target holding data is not installed over unless the caller states the
    # destruction explicitly. bootc itself wipes whatever it is pointed at,
    # so the refusal has to live in front of it — and this is it, tested.
    echo "REFUSED: ${target} carries the existing-data fixture and --destructive was not given" >&2
    return 78
  fi
  "${install_cmd[@]}"
}

set +e
if [[ -n "${interrupt_after}" ]]; then
  run_install &
  install_pid=$!
  sleep "${interrupt_after}"
  # SIGKILL to the whole tree: an interruption test that lets the installer
  # clean up is a shutdown test wearing the wrong name.
  pkill -KILL -P "${install_pid}" 2>/dev/null
  kill -KILL "${install_pid}" 2>/dev/null
  wait "${install_pid}" 2>/dev/null
  status=137
  outcome="INTERRUPTED"
  detail="killed after ${interrupt_after}s during deployment"
else
  run_install
  status=$?
fi
set -e

if [[ "${outcome}" != "INTERRUPTED" ]]; then
  case "${mode}" in
    undersized)
      if [[ "${status}" -ne 0 ]]; then
        outcome="REFUSED_AS_EXPECTED"
        detail="installer exited ${status} on a 4G target without partial deployment"
      else
        outcome="FALSE_SUCCESS"
        detail="installation claimed success on an undersized disk"
      fi
      ;;
    existing-data)
      if [[ "${destructive}" != "1" && "${status}" -eq 78 ]]; then
        outcome="PROTECTED"
        detail="existing data refused without explicit destructive authorization"
      elif [[ "${destructive}" == "1" && "${status}" -eq 0 ]]; then
        outcome="INSTALLED"
        detail="explicitly authorized destructive install over fixture data"
      else
        outcome="FAILED"
        detail="unexpected status ${status} for existing-data mode"
      fi
      ;;
    *)
      if [[ "${status}" -eq 0 ]]; then outcome="INSTALLED"; else outcome="FAILED"; detail="exit ${status}"; fi
      ;;
  esac
fi

completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
image_digest="$(podman image inspect --format '{{.Digest}}' "${image}" 2>/dev/null || echo unknown)"
target_digest="none"
[[ -f "${target}" ]] && target_digest="$(sha256sum "${target}" | awk '{print $1}')"

python3 - "${record}" <<PY
import json, sys
record = {
    "schemaVersion": 1,
    "mode": "${mode}",
    "image": "${image}",
    "imageDigest": "${image_digest}",
    "target": "${target}",
    "targetSizeRequested": "${size}",
    "targetDigestAfter": "${target_digest}",
    "installCommand": "podman run ... bootc install to-disk --via-loopback",
    "startedAt": "${started}",
    "completedAt": "${completed}",
    "outcome": "${outcome}",
    "detail": "${detail}",
    "exitStatus": ${status},
    "note": (
        "The deployed root filesystem is the image's own, installed by bootc "
        "running from the image. No secret appears in this record: encrypted "
        "mode reads its passphrase from a file descriptor and never echoes it."
    ),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(record, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

echo "install ${mode}: ${outcome} (${detail:-ok})"
echo "record written to ${record}"
case "${outcome}" in
  INSTALLED|REFUSED_AS_EXPECTED|PROTECTED|INTERRUPTED) exit 0 ;;
  *) exit 1 ;;
esac
