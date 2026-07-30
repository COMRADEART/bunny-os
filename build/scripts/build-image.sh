#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

profile="${1:-}"
case "${profile}" in
  developer|recovery|shell|shell-test|beta) ;;
  *) echo "usage: $0 developer|recovery|shell|shell-test|beta" >&2; exit 2 ;;
esac

# BUNNY_ARCHIVE_ONLY=1 stops after the normalised OCI archive and skips the
# disk-image stage.
#
# This exists so a hosted CI runner can be a real second builder. The
# reproducibility comparison compares the OCI archive, its members, the SBOM and
# the package inventory; none of those come from image-builder, which is
# Fedora-only and unavailable on a hosted Ubuntu worker. Rather than pretend a
# hosted build is impossible, or ship a hosted build that silently produces
# fewer artifacts than it claims, the mode is named and the omission is
# explicit: an archive-only build produces no qcow2 or raw image and must never
# be recorded as a candidate build.
archive_only="${BUNNY_ARCHIVE_ONLY:-0}"

required_commands=(git podman python3)
if [[ "${archive_only}" != "1" ]]; then
  required_commands+=(image-builder)
fi
for command in "${required_commands[@]}"; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "missing required build command: ${command}" >&2
    exit 3
  fi
done

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
source_commit="$(git rev-parse HEAD)"
source_epoch="$(git show -s --format=%ct HEAD)"
base_image="${BUNNY_BASE_IMAGE:-quay.io/fedora/fedora-bootc:44}"
if [[ "${BUNNY_RELEASE_BUILD:-0}" == "1" && ! "${base_image}" =~ @sha256:[a-f0-9]{64}$ ]]; then
  echo "release builds require BUNNY_BASE_IMAGE pinned with @sha256:<digest>" >&2
  exit 4
fi
if [[ "${BUNNY_RELEASE_BUILD:-0}" == "1" ]]; then
  [[ -n "${BUNNY_IMAGE_BUILDER_VERSION:-}" && -n "${BUNNY_PODMAN_VERSION:-}" ]] || {
    echo "release builds require exact BUNNY_IMAGE_BUILDER_VERSION and BUNNY_PODMAN_VERSION" >&2
    exit 4
  }
  python3 build/scripts/verify-toolchain.py \
    --image-builder "${BUNNY_IMAGE_BUILDER_VERSION}" \
    --podman "${BUNNY_PODMAN_VERSION}"
  [[ -f build/repositories/fedora-44-snapshot.repo ]] || {
    echo "release builds require reviewed build/repositories/fedora-44-snapshot.repo" >&2
    exit 4
  }
fi

tag="localhost/bunny-os-${profile}:${source_commit:0:12}"
output="${repository_root}/build/out/${profile}"
if [[ -d "${output}" && -n "$(find "${output}" -mindepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: ${output}; archive it before a new evidence run" >&2
  exit 5
fi
mkdir -p "${output}"

sudo podman build \
  --file build/Containerfile \
  --tag "${tag}" \
  --build-arg "BASE_IMAGE=${base_image}" \
  --build-arg "BUNNY_PROFILE=${profile}" \
  --build-arg "BUNNY_OS_VERSION=0.1.0" \
  --build-arg "BUNNY_IMAGE_VERSION=0.1.0-${profile}.${source_commit:0:12}" \
  --build-arg "BUNNY_SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_epoch}" \
  --build-arg "BUNNY_RELEASE_BUILD=${BUNNY_RELEASE_BUILD:-0}" \
  . 2>&1 | tee "${output}/oci-build.log"

sudo podman image inspect "${tag}" | tee "${output}/oci-inspect.json" >/dev/null
sudo podman save --format oci-archive --output "${output}/bunny-os.oci.tar" "${tag}"
sudo chown "$(id -u):$(id -g)" "${output}/bunny-os.oci.tar"

# Normalise the archive wrapper so the artifact digest is reproducible.
#
# Measured: two builds of one commit produced identical blobs, an identical
# index.json and identical file contents, but different archive digests,
# because podman save stamps tar entry mtimes with the wall-clock time of
# archive creation rather than honouring SOURCE_DATE_EPOCH. The image was
# already deterministic; only the wrapper was not. See
# REPRODUCIBLE_BUILD_REPORT.md.
bash "${repository_root}/build/scripts/normalise-oci-archive.sh" \
  "${output}/bunny-os.oci.tar" "${source_epoch}"
if [[ "${archive_only}" == "1" ]]; then
  printf 'BUNNY_ARCHIVE_ONLY=1: skipped image-builder; no qcow2 or raw image produced\n' \
    | tee "${output}/image-builder.log"
else
  image_types=(qcow2)
  if [[ "${profile}" == "beta" ]]; then
    image_types=(qcow2 raw)
  fi
  (
    cd "${output}"
    for image_type in "${image_types[@]}"; do
      sudo image-builder build --bootc-ref "${tag}" --bootc-default-fs ext4 "${image_type}"
    done
  ) 2>&1 | tee "${output}/image-builder.log"
fi
sudo chown -R "$(id -u):$(id -g)" "${output}"

provenance_arguments=(
  --profile "${profile}"
  --output "${output}"
  --source-commit "${source_commit}"
  --source-date-epoch "${source_epoch}"
  --base-image "${base_image}"
  --image-reference "${tag}"
)
if [[ "${archive_only}" == "1" ]]; then
  provenance_arguments+=(--archive-only)
fi
python3 build/scripts/write-build-provenance.py "${provenance_arguments[@]}"
