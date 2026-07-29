#!/usr/bin/bash
set -euo pipefail

root="${1:-build/out/live}"
manifest="${2:-${root}/BUNNY-MANIFEST.json}"
signature="${3:-${root}/BUNNY-MANIFEST.json.sig}"
public_key="${4:-build/keys/media-release.pem}"

for path in "${root}" "${manifest}" "${signature}" "${public_key}"; do
  [[ -e "${path}" ]] || { echo "missing media verification input: ${path}" >&2; exit 3; }
done
python3 tools/bunny-os/bin/bunny-os --json media verify --root "${root}" --manifest "${manifest}" --signature "${signature}" --public-key "${public_key}"
