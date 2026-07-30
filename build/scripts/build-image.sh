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

# Hermetic mode: the base, the packages and the clock all come from recorded,
# verified inputs rather than from whatever the machine can reach.
#
# The epoch is taken from the lock rather than from `git show HEAD`. Two
# builders checking out the same commit derive the same value either way, but a
# builder that checked out something else would silently get a different epoch,
# and the mismatch would surface as an unexplained archive difference instead of
# as a wrong input.
hermetic="${BUNNY_HERMETIC_BUILD:-0}"
build_mounts=()
if [[ "${hermetic}" == "1" ]]; then
  for lock in base-image-lock builder-image-lock package-snapshot-lock reproducibility-lock; do
    [[ -f "build/inputs/${lock}.json" ]] || {
      echo "hermetic build requires build/inputs/${lock}.json" >&2
      exit 4
    }
  done
  python3 scripts/supplychain.py verify-input-locks || exit 4

  source_epoch="$(python3 -c '
import json
print(json.load(open("build/inputs/reproducibility-lock.json"))["sourceDateEpoch"])
')"
  # podman cannot use an OCI-layout path as a FROM reference, so the retained
  # base is pulled into local storage first and the pulled image's own manifest
  # digest is checked against the lock. The lock is what pins the base; the tag
  # below is only a handle, and a mismatch stops the build before it starts.
  retained_layout="$(python3 -c '
import json
lock = json.load(open("build/inputs/base-image-lock.json"))
print(lock["retainedLocation"])
')"
  retained_digest="$(python3 -c '
import json
print(json.load(open("build/inputs/base-image-lock.json"))["retainedDigest"])
')"
  base_tag="localhost/bunny-os-retained-base:${retained_digest#sha256:}"
  sudo podman pull "oci:${retained_layout}:retained" >/dev/null
  pulled_id="$(sudo podman pull "oci:${retained_layout}:retained" 2>/dev/null | tail -1)"
  sudo podman tag "${pulled_id}" "${base_tag}"
  observed="$(sudo skopeo inspect --raw "containers-storage:${base_tag}" |
    python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if [[ "${observed}" != "${retained_digest}" ]]; then
    echo "the base pulled from retention does not carry the locked digest:" >&2
    echo "  locked   ${retained_digest}" >&2
    echo "  observed ${observed}" >&2
    exit 4
  fi
  base_image="${base_tag}"
  snapshot_root="$(python3 -c '
import json
print(json.load(open("build/inputs/package-snapshot-lock.json"))["retainedLocation"])
')"

  python3 scripts/supply-chain/verify-package-snapshot.py || exit 4

  faketime_library="${BUNNY_FAKETIME_LIBRARY:-}"
  if [[ -z "${faketime_library}" ]]; then
    faketime_library="$(find /usr/lib64 /usr/lib -name 'libfaketime.so.1' 2>/dev/null | head -1 || true)"
  fi
  if [[ -z "${faketime_library}" ]]; then
    echo "hermetic build requires libfaketime; without it the rpm database records" >&2
    echo "wall-clock install times and the build cannot reproduce. Install libfaketime" >&2
    echo "or set BUNNY_FAKETIME_LIBRARY." >&2
    exit 4
  fi

  build_mounts=(
    --volume "${snapshot_root}:/snapshot:ro"
    --volume "${faketime_library}:/run/bunny-faketime.so:ro"
  )
  echo "hermetic build"
  echo "  base     ${base_image}"
  echo "  snapshot ${snapshot_root}"
  echo "  epoch    ${source_epoch}"
fi
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

hermetic_args=()
if [[ "${hermetic}" == "1" ]]; then
  hermetic_args=(
    --build-arg "BUNNY_SNAPSHOT_ROOT=/snapshot"
    --build-arg "BUNNY_FAKETIME_LIBRARY=/run/bunny-faketime.so"
  )
fi

sudo podman build \
  --file build/Containerfile \
  --tag "${tag}" \
  "${build_mounts[@]+"${build_mounts[@]}"}" \
  --build-arg "BASE_IMAGE=${base_image}" \
  --build-arg "BUNNY_PROFILE=${profile}" \
  --build-arg "BUNNY_OS_VERSION=0.1.0" \
  --build-arg "BUNNY_IMAGE_VERSION=0.1.0-${profile}.${source_commit:0:12}" \
  --build-arg "BUNNY_SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_epoch}" \
  --build-arg "BUNNY_RELEASE_BUILD=${BUNNY_RELEASE_BUILD:-0}" \
  "${hermetic_args[@]+"${hermetic_args[@]}"}" \
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
