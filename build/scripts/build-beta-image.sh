#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
source_commit="$(git rev-parse HEAD)"
"${BASH:-/usr/bin/bash}" build/scripts/build-image.sh beta
output="${repository_root}/build/out/beta"
python3 build/scripts/write-media-manifest.py --root "${output}" --source-commit "${source_commit}" --image-version "0.3.0-beta.${source_commit:0:12}"
if [[ -n "${BUNNY_MEDIA_SIGNING_KEY:-}" ]]; then
  openssl pkeyutl -sign -rawin -inkey "${BUNNY_MEDIA_SIGNING_KEY}" -in "${output}/BUNNY-MANIFEST.json" -out "${output}/BUNNY-MANIFEST.json.sig"
else
  echo "beta manifest generated but not signed; beta publication is blocked" >&2
fi
