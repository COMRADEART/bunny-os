#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

version="${BUNNY_RC_VERSION:-}"
source_commit="${BUNNY_SOURCE_COMMIT:-}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-stable-rc[1-9][0-9]*$ ]]; then
  echo "BUNNY_RC_VERSION must identify a new stable release candidate" >&2
  exit 1
fi
if [[ ! "$source_commit" =~ ^[a-f0-9]{40}$ ]] || [[ "$(git rev-parse HEAD)" != "$source_commit" ]]; then
  echo "BUNNY_SOURCE_COMMIT must exactly match the immutable checkout" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "stable candidate builds require a clean immutable source checkout" >&2
  exit 1
fi
for command in podman image-builder syft openssl; do
  command -v "$command" >/dev/null || { echo "missing stable candidate tool: $command" >&2; exit 1; }
done

"$root/build/scripts/build-live-image.sh"
"$root/build/scripts/build-beta-image.sh"
"$root/build/scripts/build-image.sh" recovery

required=(
  "build/out/live"
  "build/out/beta"
  "build/out/recovery"
)
for path in "${required[@]}"; do
  [[ -d "$path" ]] || { echo "missing candidate artifact directory: $path" >&2; exit 1; }
done

find build/out/live -type f -name '*.iso' -print -quit | grep -q . || { echo "missing stable ISO input" >&2; exit 1; }
find build/out/beta -type f -name '*.raw' -print -quit | grep -q . || { echo "missing stable raw input" >&2; exit 1; }
find build/out/beta -type f -name '*.qcow2' -print -quit | grep -q . || { echo "missing stable QCOW2 input" >&2; exit 1; }
find build/out/recovery -type f -name '*.iso' -print -quit | grep -q . || { echo "missing independently bootable recovery ISO" >&2; exit 1; }

echo "candidate build inputs exist; signing, independent recovery ISO, verification, and qualification are still required"
