#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copy an approved upstream base image into storage this project controls.
#
# The reason this exists, stated once so it is not re-derived later: the digest
# this project pinned in Phase 6 was garbage collected from quay.io within days.
# `fedora-bootc:44` is rebuilt daily and old digests do not survive. The hosted
# builder could not pull it and failed; the local builder built against it
# anyway, because podman had the layers in its store, and nothing reported the
# difference. A pinned digest records *which* base was used. It does not make
# that base obtainable, and the machine holding the cache is the one machine
# that cannot notice.
#
# So this copies manifests and blobs — not a tag, not a cache reference — and
# verifies every copied blob against its own digest afterwards. A local podman
# cache is explicitly not retention: it is unreachable from the second builder,
# which is the entire point of having one.
#
# Usage:
#   mirror-base-image.sh --upstream <name@sha256:...> [options]
#
#   --upstream REF          digest-pinned upstream reference (required)
#   --architecture ARCH     architecture to retain (default: amd64)
#   --retention-root DIR    controlled content-addressed store
#                           (default: /var/lib/bunny-retention/base-images)
#   --push-to REF_PREFIX    also push to a controlled registry, by digest
#   --all-architectures     retain every architecture in the index
#   --lock PATH             where to write the lock
#                           (default: build/inputs/base-image-lock.json)

set -euo pipefail

upstream=""
architecture="amd64"
retention_root="${BUNNY_RETENTION_ROOT:-/var/lib/bunny-retention}/base-images"
push_to=""
all_architectures=0
lock_path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upstream) upstream="${2:?}"; shift 2 ;;
    --architecture) architecture="${2:?}"; shift 2 ;;
    --retention-root) retention_root="${2:?}"; shift 2 ;;
    --push-to) push_to="${2:?}"; shift 2 ;;
    --all-architectures) all_architectures=1; shift ;;
    --lock) lock_path="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "${upstream}" ]] || { echo "--upstream is required" >&2; exit 2; }

# A mutable tag is refused before anything is copied. Mirroring a tag would
# produce a controlled copy of an uncontrolled thing, which is worse than not
# mirroring at all: it looks pinned.
if [[ ! "${upstream}" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "refusing to mirror ${upstream}: not digest-pinned." >&2
  echo "A mutable tag does not identify content. Resolve it to a digest first:" >&2
  echo "  skopeo inspect --no-tags docker://<name>:<tag> | jq -r .Digest" >&2
  exit 2
fi

repository_root="$(git rev-parse --show-toplevel)"
[[ -n "${lock_path}" ]] || lock_path="${repository_root}/build/inputs/base-image-lock.json"

for command in skopeo python3 git; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing required command: ${command}" >&2; exit 3; }
done

upstream_digest="${upstream##*@}"
upstream_name="${upstream%@*}"
layout="${retention_root}/${upstream_digest//:/-}"

echo "==> verifying the source manifest before copying anything"
raw="$(mktemp)"; trap 'rm -f "${raw}"' EXIT
skopeo inspect --raw "docker://${upstream}" >"${raw}"

# Recompute the digest of the manifest we were served and compare it with the
# digest we asked for. A registry that serves different bytes under a digest is
# the failure a content-addressed reference is supposed to make impossible, and
# checking costs one hash.
served="sha256:$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${raw}")"
if [[ "${served}" != "${upstream_digest}" ]]; then
  echo "source manifest digest mismatch:" >&2
  echo "  requested ${upstream_digest}" >&2
  echo "  served    ${served}" >&2
  exit 4
fi
echo "    source manifest digest verified: ${served}"

mkdir -p "${layout}"

copy_arguments=(--preserve-digests)
if [[ "${all_architectures}" == "1" ]]; then
  copy_arguments+=(--all)
  echo "==> copying every architecture in the index into ${layout}"
else
  copy_arguments+=(--override-arch "${architecture}" --override-os linux)
  echo "==> copying ${architecture} into ${layout}"
fi

skopeo copy "${copy_arguments[@]}" \
  "docker://${upstream}" \
  "oci:${layout}:retained"

echo "==> verifying every copied blob against its own digest"
python3 "${repository_root}/scripts/supply-chain/verify-retained-base.py" \
  --emit-lock \
  --layout "${layout}" \
  --upstream "${upstream}" \
  --upstream-manifest "${raw}" \
  --architecture "${architecture}" \
  --retained-location "${layout}" \
  --lock "${lock_path}"

if [[ -n "${push_to}" ]]; then
  # Push by digest into the controlled registry. The destination is written
  # with a tag because a registry needs one to accept an upload; the *reference*
  # recorded in the lock is by digest, and nothing in the build ever resolves
  # the tag.
  retained_digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["retainedDigest"])' "${lock_path}")"
  destination_tag="${push_to}:retained-${retained_digest#sha256:}"
  echo "==> pushing to the controlled registry: ${destination_tag}"
  skopeo copy --preserve-digests "oci:${layout}:retained" "docker://${destination_tag}"

  echo "==> confirming the pushed manifest digest is unchanged"
  pushed="$(skopeo inspect --no-tags --raw "docker://${destination_tag}" |
    python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if [[ "${pushed}" != "${retained_digest}" ]]; then
    echo "the controlled registry returned a different manifest digest:" >&2
    echo "  retained ${retained_digest}" >&2
    echo "  pushed   ${pushed}" >&2
    echo "A re-encoded image is a different image, however similar it looks." >&2
    exit 5
  fi

  python3 - "${lock_path}" "${push_to}@${retained_digest}" <<'PYTHON'
import json
import sys

path, reference = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    lock = json.load(handle)
lock["retainedReference"] = reference
lock["retainedLocation"] = reference.split("@", 1)[0]
with open(path, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(lock, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(f"    lock now records the registry reference {reference}")
PYTHON
fi

echo
echo "mirrored ${upstream_name}"
echo "  upstream digest  ${upstream_digest}"
echo "  retained at      ${layout}"
[[ -n "${push_to}" ]] && echo "  pushed to        ${push_to}"
echo "  lock             ${lock_path}"
echo
echo "A mirror is not a verification. Run verify-retained-base.py, and run the"
echo "cold-pull test, before any qualification build consumes this base."
