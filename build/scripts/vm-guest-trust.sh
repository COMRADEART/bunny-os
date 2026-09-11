#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Cold-boot the Bunny desktop twice and drive the Trust journeys through
# AT-SPI: granted, then denied. Each boot is a first request. The driver
# locates Allow/Deny by accessible name and presses them with the tablet;
# it never calls resolve_approval.
#
# Requires a composed shell-test (or shell) QCOW2. This script does not
# invent a guest. Missing image → exit 2.
set -uo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}" || exit 1

evidence="${1:-demos/09-guest-trust/out/latest/guest}"
mkdir -p "${evidence}"

profile="${BUNNY_DESKTOP_PROFILE:-shell-test}"
source_image="${BUNNY_DESKTOP_IMAGE:-}"
if [[ -z "${source_image}" ]]; then
  source_image="$(find "build/out/${profile}" -type f -name '*.qcow2' \
    -not -path '*/desktop-story/*' -not -path '*/guest-trust/*' -print -quit 2>/dev/null || true)"
fi
if [[ -z "${source_image}" || ! -f "${source_image}" ]]; then
  echo "no qcow2 under build/out/${profile}; run make build-shell-test-image on a Fedora 44 image-builder host" >&2
  exit 2
fi

status=0
for journey in granted denied; do
  label="guest-trust-${journey}"
  work="${evidence}/${journey}"
  rm -rf "${work}"
  echo "=== cold boot Trust journey: ${journey} ==="
  if BUNNY_DESKTOP_IMAGE="${source_image}" \
     BUNNY_DESKTOP_WORK="${work}" \
     BUNNY_DESKTOP_PROFILE="${profile}" \
     bash build/scripts/vm-desktop-story.sh --journey "${journey}" "${label}"; then
    echo "=== ${journey}: complete ==="
  else
    echo "=== ${journey}: FAILED (exit $?) ===" >&2
    status=1
  fi
done

exit "${status}"
