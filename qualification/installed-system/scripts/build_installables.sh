#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build the installable disk artifacts — QCOW2 and raw — from the qualified
# archive target, and prove the root filesystem inside them is the qualified
# one.
#
# The full hermetic build reruns the pinned archive build and then hands the
# result to image-builder. The archive step is deterministic — that is what
# the three-builder evidence established — so the shipped archive digest of
# this build must equal the qualified target's digest exactly, and this
# script refuses to emit disk artifacts when it does not: a disk image
# wrapping an unverified root is an installation artifact of nothing.
#
# Disk-image byte reproducibility is NOT inferred from root-filesystem
# reproducibility. image-builder writes filesystems with their own identities
# (partition GUIDs, filesystem UUIDs); the record lists which identifiers are
# legitimately unique per generation, and INSTALLABLE_IMAGE_REPORT.md keeps
# the two claims apart.
#
# Usage: build_installables.sh --commit <sha> --expected-archive <sha256>
#                              --output <dir> [--workspace-root DIR]

set -euo pipefail

commit=""
expected=""
output=""
workspace_root="/var/tmp"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit) commit="${2:?}"; shift 2 ;;
    --expected-archive) expected="${2:?}"; shift 2 ;;
    --output) output="${2:?}"; shift 2 ;;
    --workspace-root) workspace_root="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${commit}" && -n "${expected}" && -n "${output}" ]] || {
  echo "BLOCKED: --commit, --expected-archive and --output are required." >&2
  echo "The expected archive digest comes from the qualification target's" >&2
  echo "evidence, not from this build's own output describing itself." >&2
  exit 2; }

for required in git podman image-builder qemu-img sha256sum python3; do
  command -v "${required}" >/dev/null || { echo "BLOCKED: ${required} missing" >&2; exit 3; }
done

repository_root="$(git rev-parse --show-toplevel)"
workspace="${workspace_root}/bunny-installables"
storage="${workspace_root}/storage-installables"

echo "==> installable build: ${workspace}"
rm -rf "${workspace}" "${storage}"
mkdir -p "${storage}"
git clone --quiet --no-hardlinks "${repository_root}" "${workspace}"
git -C "${workspace}" checkout --quiet "${commit}"

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# One isolated store, shared by podman and image-builder through
# CONTAINERS_STORAGE_CONF — and with no metacopy. Both halves are measured:
# an image built into a store image-builder cannot see dies in a
# localhost-registry fallback, and a build in Fedora's default store produced
# archive f49b8fcf where the qualified target is 0258f92a, because the
# default store's mountopt metacopy=on flips containers/storage onto its
# naive diff — the same mechanism that once separated the Ubuntu runners
# from the local builder (missing opaque marker, unlinked whiteouts, flat
# member order, and an empty mtime-only layer naive diff cannot see).
# The store configuration is part of the toolchain, whether or not anyone
# wrote it down; here it is written down.
mkdir -p "${storage}/graph" "${storage}/run"
cat > "${storage}/storage.conf" <<CONF
[storage]
driver = "overlay"
graphroot = "${storage}/graph"
runroot = "${storage}/run"
CONF
export CONTAINERS_STORAGE_CONF="${storage}/storage.conf"
(
  cd "${workspace}"
  BUNNY_HERMETIC_BUILD=1 \
  bash build/scripts/build-image.sh beta
) 2>&1 | tee "${output}.build.log" | tail -5

archive="${workspace}/build/out/beta/bunny-os.oci.tar"
[[ -f "${archive}" ]] || { echo "BLOCKED: no archive produced" >&2; exit 4; }

actual="$(sha256sum "${archive}" | awk '{print $1}')"
if [[ "${actual}" != "${expected}" ]]; then
  echo "BLOCKED: this build's archive is ${actual:0:12} but the qualified target's" >&2
  echo "archive is ${expected:0:12}. The root filesystem inside these disk images" >&2
  echo "would not be the qualified one, so no disk image is emitted." >&2
  exit 4
fi
echo "root filesystem verified: ${actual:0:16} == qualified target"

mkdir -p "${output}"
shopt -s nullglob
artifacts=()
for artifact in "${workspace}"/build/out/beta/*.qcow2 "${workspace}"/build/out/beta/*.raw \
                "${workspace}"/build/out/beta/*/disk.qcow2 "${workspace}"/build/out/beta/*/disk.raw; do
  name="$(basename "${artifact}")"
  [[ "${name}" == disk.* ]] && name="bunny-os-$(basename "$(dirname "${artifact}")").${name##*.}"
  cp --sparse=always "${artifact}" "${output}/${name}"
  artifacts+=("${output}/${name}")
done
[[ ${#artifacts[@]} -gt 0 ]] || { echo "BLOCKED: image-builder produced no qcow2/raw" >&2; exit 4; }

completed="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - "${output}/installables.json" "${commit}" "${expected}" "${started}" "${completed}" "${artifacts[@]}" <<'PY'
import hashlib, json, subprocess, sys
output, commit, archive_digest, started, completed, *artifacts = sys.argv[1:]

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
    "firmwareMode": "uefi",
    "partitioning": "GPT: ESP + boot + root (image-builder bootc default, ext4)",
    "bootloader": "bootupd-managed GRUB2, BLS entries",
    "encryption": "none in generated images; encrypted installation is a separate, prepared path",
    "creationCommand": "BUNNY_HERMETIC_BUILD=1 build/scripts/build-image.sh beta (image-builder qcow2/raw)",
    "startedAt": started,
    "completedAt": completed,
    "artifacts": records,
    "uniquePerGeneration": [
        "partition GUIDs", "filesystem UUIDs", "ESP volume id",
    ],
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

rm -rf "${storage}"
echo "installable artifacts in ${output}"
