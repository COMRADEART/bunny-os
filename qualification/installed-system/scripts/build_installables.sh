#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Wrap the qualified archive — the exact bytes — in installable disk images.
#
# Earlier versions rebuilt the archive and checked the digest afterwards, and
# the check kept refusing for environmental reasons worth recording: a
# rebuild in Fedora's default container store came out naive-diff (mountopt
# metacopy=on), and an isolated store handed down through
# CONTAINERS_STORAGE_CONF never reached podman because the build script's
# sudo wrapper strips the environment. Both failures were the guard working;
# neither was necessary. The qualified archive already exists as a file with
# a measured digest, `podman load` preserves its layers and config
# byte-for-byte, and image-builder deploys from the loaded image — so the
# root filesystem inside the disk images is the qualified one by
# construction, and the verification is of file digest and loaded image
# identity, not of a rebuild's luck.
#
# Usage: build_installables.sh --archive <qualified bunny-os.oci.tar>
#                              --expected-archive <sha256>
#                              --commit <target sha> --output <dir>

set -euo pipefail

archive=""
expected=""
commit=""
output=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) archive="${2:?}"; shift 2 ;;
    --expected-archive) expected="${2:?}"; shift 2 ;;
    --commit) commit="${2:?}"; shift 2 ;;
    --output) output="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${archive}" && -n "${expected}" && -n "${commit}" && -n "${output}" ]] || {
  echo "BLOCKED: --archive, --expected-archive, --commit and --output are required." >&2
  echo "The expected digest comes from the qualification target's evidence, not" >&2
  echo "from this script's input describing itself." >&2
  exit 2; }

for required in podman image-builder qemu-img sha256sum python3; do
  command -v "${required}" >/dev/null || { echo "BLOCKED: ${required} missing" >&2; exit 3; }
done

actual="$(sha256sum "${archive}" | awk '{print $1}')"
if [[ "${actual}" != "${expected}" ]]; then
  echo "BLOCKED: ${archive} digests to ${actual:0:12}, expected ${expected:0:12}." >&2
  echo "Disk images may only wrap the qualified archive." >&2
  exit 4
fi
echo "qualified archive verified: ${actual:0:16}"

tag="localhost/bunny-os-beta:${commit:0:12}"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

loaded="$(podman load --quiet -i "${archive}" | awk '{print $NF}')"
podman tag "${loaded}" "${tag}"
image_id="$(podman image inspect --format '{{.Id}}' "${tag}")"
echo "loaded ${loaded} as ${tag} (id ${image_id:0:16})"

workdir="$(mktemp -d /var/tmp/bunny-installables.XXXXXX)"
mkdir -p "${output}"

for image_type in qcow2 raw; do
  echo "==> image-builder ${image_type}"
  ( cd "${workdir}" && image-builder build \
      --bootc-ref "${tag}" \
      --bootc-default-fs ext4 \
      "${image_type}" ) 2>&1 | tee -a "${output}/image-builder.log" | tail -2
done

shopt -s globstar nullglob
artifacts=()
for artifact in "${workdir}"/**/*.qcow2 "${workdir}"/**/*.raw; do
  name="bunny-os-${commit:0:12}.${artifact##*.}"
  cp --sparse=always "${artifact}" "${output}/${name}"
  artifacts+=("${output}/${name}")
done
[[ ${#artifacts[@]} -ge 2 ]] || {
  echo "BLOCKED: expected qcow2 and raw, found ${#artifacts[@]} artifact(s)" >&2
  exit 4; }

completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - "${output}/installables.json" "${commit}" "${expected}" "${image_id}" \
  "${started}" "${completed}" "${artifacts[@]}" <<'PY'
import hashlib, json, subprocess, sys
output, commit, archive_digest, image_id, started, completed, *artifacts = sys.argv[1:]

def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()

records = []
for artifact in artifacts:
    info = json.loads(subprocess.run(
        ["qemu-img", "info", "--output=json", artifact],
        capture_output=True, text=True, check=True).stdout)
    records.append({
        "artifact": artifact.rsplit("/", 1)[-1],
        "format": info.get("format"),
        "virtualSizeBytes": info.get("virtual-size"),
        "sha256": digest(artifact),
    })

json.dump({
    "schemaVersion": 1,
    "sourceCommit": commit,
    "sourceArchiveDigest": archive_digest,
    "sourceArchiveVerified": True,
    "deployedImageId": image_id,
    "mechanism": (
        "podman load of the qualified archive (layers and config preserved "
        "byte-for-byte), deployed by image-builder --bootc-ref; the root "
        "filesystem is the qualified archive's by construction"
    ),
    "firmwareMode": "uefi",
    "partitioning": "GPT: ESP + boot + root (image-builder bootc default, ext4)",
    "bootloader": "bootupd-managed GRUB2, BLS entries",
    "encryption": "none in generated images; encrypted installation is a separate, prepared path",
    "creationCommand": "image-builder build --bootc-ref localhost/bunny-os-beta:<sha12> --bootc-default-fs ext4 {qcow2,raw}",
    "startedAt": started,
    "completedAt": completed,
    "artifacts": records,
    "uniquePerGeneration": ["partition GUIDs", "filesystem UUIDs", "ESP volume id"],
    "note": (
        "Root-filesystem reproducibility is established evidence; disk-image "
        "byte reproducibility is a separate claim this record does not make. "
        "The identifiers listed as unique-per-generation are the measured "
        "reason the two claims differ."
    ),
}, open(output, "w", encoding="utf-8"), indent=2, sort_keys=True)
open(output, "a", encoding="utf-8").write("\n")
print(f"wrote {output}")
for record in records:
    print(f"  {record['artifact']}: {record['sha256'][:16]} ({record['format']})")
PY

rm -rf "${workdir}"
echo "installable artifacts in ${output}"
