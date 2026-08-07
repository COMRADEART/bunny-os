#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

for command in git podman image-builder python3; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing required build command: ${command}" >&2; exit 3; }
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

# The channel labels the medium as well as the payload. An installer ISO that
# called itself beta while writing an alpha system to the disk would be the one
# artifact a user reads the name of before anything else is true about it.
release_channel="${BUNNY_RELEASE_CHANNEL:-development}"
case "${release_channel}" in
  development|alpha) ;;
  *) echo "BUNNY_RELEASE_CHANNEL must be 'development' or 'alpha', not '${release_channel}'" >&2; exit 2 ;;
esac
if [[ "${release_channel}" == "alpha" ]]; then
  live_os_version="${BUNNY_ALPHA_VERSION:-0.1.0}"
  live_image_version="${live_os_version}-alpha-live.${source_commit:0:12}"
else
  live_os_version="0.3.0-beta"
  live_image_version="0.3.0-live.${source_commit:0:12}"
fi

payload_tag="localhost/bunny-os-beta:${source_commit:0:12}"
installer_tag="localhost/bunny-os-live:${source_commit:0:12}"
output="${repository_root}/build/out/live"
if [[ -d "${output}" && -n "$(find "${output}" -mindepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: ${output}; archive it before a new evidence run" >&2
  exit 5
fi
mkdir -p "${output}"

if ! sudo podman image exists "${payload_tag}"; then
  echo "missing local beta payload ${payload_tag}; run make build-beta-image first" >&2
  exit 6
fi

sudo podman build \
  --file build/Containerfile \
  --tag "${installer_tag}" \
  --build-arg "BASE_IMAGE=${base_image}" \
  --build-arg "BUNNY_PROFILE=live" \
  --build-arg "BUNNY_OS_VERSION=${live_os_version}" \
  --build-arg "BUNNY_IMAGE_VERSION=${live_image_version}" \
  --build-arg "BUNNY_SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_epoch}" \
  --build-arg "BUNNY_RELEASE_BUILD=${BUNNY_RELEASE_BUILD:-0}" \
  --build-arg "BUNNY_RELEASE_CHANNEL=${release_channel}" \
  . 2>&1 | tee "${output}/oci-build.log"

(
  cd "${output}"
  sudo image-builder build \
    --bootc-ref "${installer_tag}" \
    --bootc-installer-payload-ref "${payload_tag}" \
    --bootc-default-fs ext4 \
    bootc-generic-iso
) 2>&1 | tee "${output}/image-builder.log"
sudo chown -R "$(id -u):$(id -g)" "${output}"

python3 build/scripts/write-build-provenance.py \
  --profile live \
  --output "${output}" \
  --source-commit "${source_commit}" \
  --source-date-epoch "${source_epoch}" \
  --base-image "${base_image}" \
  --image-reference "${installer_tag}"

python3 build/scripts/write-media-manifest.py --root "${output}" --source-commit "${source_commit}" --image-version "0.3.0-live.${source_commit:0:12}"
if [[ -n "${BUNNY_MEDIA_SIGNING_KEY:-}" ]]; then
  openssl pkeyutl -sign -rawin -inkey "${BUNNY_MEDIA_SIGNING_KEY}" -in "${output}/BUNNY-MANIFEST.json" -out "${output}/BUNNY-MANIFEST.json.sig"
else
  echo "media manifest generated but not signed; beta publication is blocked" >&2
fi
