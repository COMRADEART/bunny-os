#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build the qualification builder image and emit the lock that pins it.
#
# The image is the environment both builders run. Everything about it that could
# vary is recorded: the base it was built from, the commit and Containerfile
# that describe it, every pinned tool's version and the checksum of the package
# providing it, and the image's own manifest digest.
#
# It is retained the same way the base is — as a content-addressed OCI layout,
# and pushed to a controlled registry when one is reachable. A builder image
# that exists only in one machine's podman store has the defect this whole
# remediation is about.
#
# Usage: build-builder-image.sh [--push-to REF_PREFIX] [--retention-root DIR]

set -euo pipefail

push_to=""
retention_root="${BUNNY_RETENTION_ROOT:-/var/lib/bunny-retention}"
lock_path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --push-to) push_to="${2:?}"; shift 2 ;;
    --retention-root) retention_root="${2:?}"; shift 2 ;;
    --lock) lock_path="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for command in podman skopeo python3 git; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing required command: ${command}" >&2; exit 3; }
done

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
[[ -n "${lock_path}" ]] || lock_path="${repository_root}/build/inputs/builder-image-lock.json"

source_commit="$(git rev-parse HEAD)"
source_epoch="$(git show -s --format=%ct HEAD)"
containerfile="build/builder/Containerfile"
containerfile_digest="$(python3 -c '
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())
' "${containerfile}")"

builder_base="$(python3 -c '
import json
print(json.load(open("build/builder/toolchain.lock.json"))["builderBase"])
')"

if [[ ! "${builder_base}" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "refusing to build: builderBase ${builder_base} is not digest-pinned." >&2
  echo "A builder image built from a mutable tag is not a pinned environment." >&2
  exit 2
fi

tag="localhost/bunny-os-builder:${source_commit:0:12}"

echo "==> building ${tag}"
echo "    base   ${builder_base}"
echo "    commit ${source_commit}"
podman build \
  --file "${containerfile}" \
  --tag "${tag}" \
  --build-arg "BUILDER_BASE=${builder_base}" \
  --build-arg "BUNNY_SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_epoch}" \
  --timestamp "${source_epoch}" \
  .

echo "==> recording the toolchain from inside the image"
toolchain_json="$(mktemp)"
trap 'rm -f "${toolchain_json}"' EXIT
podman run --rm --network=none "${tag}" toolchain >"${toolchain_json}"

layout="${retention_root}/builder-images/${source_commit:0:12}"
mkdir -p "$(dirname "${layout}")"
rm -rf "${layout}"
echo "==> retaining the builder image at ${layout}"
skopeo copy "containers-storage:${tag}" "oci:${layout}:builder"

builder_digest="$(skopeo inspect --raw "oci:${layout}:builder" |
  python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"

retained_reference="${layout}@${builder_digest}"

if [[ -n "${push_to}" ]]; then
  destination_tag="${push_to}:builder-${source_commit:0:12}"
  echo "==> pushing to the controlled registry: ${destination_tag}"
  skopeo copy --preserve-digests "oci:${layout}:builder" "docker://${destination_tag}"
  pushed="$(skopeo inspect --no-tags --raw "docker://${destination_tag}" |
    python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if [[ "${pushed}" != "${builder_digest}" ]]; then
    echo "the controlled registry returned a different manifest digest:" >&2
    echo "  retained ${builder_digest}" >&2
    echo "  pushed   ${pushed}" >&2
    exit 5
  fi
  retained_reference="${push_to}@${builder_digest}"
fi

echo "==> writing ${lock_path}"
python3 scripts/supply-chain/write-builder-lock.py \
  --toolchain "${toolchain_json}" \
  --declared build/builder/toolchain.lock.json \
  --builder-reference "${retained_reference}" \
  --builder-digest "${builder_digest}" \
  --base-reference "${builder_base}" \
  --source-commit "${source_commit}" \
  --containerfile-digest "${containerfile_digest}" \
  --lock "${lock_path}"

echo
echo "builder image built and retained"
echo "  reference ${retained_reference}"
echo "  digest    ${builder_digest}"
echo "  layout    ${layout}"
echo
echo "The digest is the pin. A mutable builder tag is refused by"
echo "verify-builder-image.py, and both builders must present this digest."
