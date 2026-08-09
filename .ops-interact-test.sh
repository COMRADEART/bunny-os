#!/usr/bin/bash
# Exercise the new pointer path against the image that is already built.
#
# The point of running it here first is that this image predates every product
# change in this branch, so anything that goes wrong is the harness's fault and
# not the desktop's — which is the distinction the first graphical run of the
# previous phase got wrong and spent a cycle on.
set -uo pipefail
cd /root/bunny-os || exit 9
label="${1:-p1}"
export BUNNY_DESKTOP_SHOTS="${BUNNY_DESKTOP_SHOTS:-140 220}"
export BUNNY_DESKTOP_TIMEOUT="${BUNNY_DESKTOP_TIMEOUT:-1200}"
export BUNNY_DESKTOP_IMAGE="${BUNNY_DESKTOP_IMAGE:-/root/bunny-os/build/out/shell-test/bootc-fedora-44-qcow2-x86_64/bootc-fedora-44-qcow2-x86_64.qcow2}"
export BUNNY_DESKTOP_WORK="/root/interact/${label}"
mkdir -p "${BUNNY_DESKTOP_WORK}"
echo "image: ${BUNNY_DESKTOP_IMAGE}"
echo "work:  ${BUNNY_DESKTOP_WORK}"
bash build/scripts/vm-desktop-story.sh "${label}"
echo "STORY_EXIT=$?"
