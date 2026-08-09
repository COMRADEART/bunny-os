#!/usr/bin/bash
# Boot the exact Alpha artifact and press the Bunny desktop's controls.
#
# The image is named explicitly rather than discovered, so this cannot silently
# run against an older build that happens to be lying around — the failure the
# evidence rules in this repository exist to prevent.
set -uo pipefail
cd /root/bunny-os || exit 9
label="${1:-a1}"
width="${2:-1920}"
height="${3:-1080}"

image="$(find /root/bunny-os/build/out/beta -maxdepth 2 -type f -name '*.qcow2' \
  -not -path '*/desktop-story/*' -not -path '*/alpha-story/*' -print -quit)"
if [[ -z "${image}" ]]; then
  echo "no Alpha qcow2 under build/out/beta" >&2
  exit 2
fi

export BUNNY_DESKTOP_IMAGE="${image}"
export BUNNY_DESKTOP_PROFILE=beta
export BUNNY_DESKTOP_WIDTH="${width}"
export BUNNY_DESKTOP_HEIGHT="${height}"
export BUNNY_DESKTOP_SHOTS="${BUNNY_DESKTOP_SHOTS:-150 240}"
export BUNNY_DESKTOP_TIMEOUT=1500
export BUNNY_DESKTOP_WORK="/root/alpha-desktop/${label}"
mkdir -p "${BUNNY_DESKTOP_WORK}"

echo "=== Alpha desktop run ${label} at ${width}x${height} ==="
echo "artifact: ${image}"
echo "sha256:   $(sha256sum "${image}" | cut -d' ' -f1)"
echo "bytes:    $(stat -c%s "${image}")"
echo "commit:   $(git rev-parse HEAD)"
bash build/scripts/vm-desktop-story.sh "${label}"
echo "STORY_EXIT=$?"
