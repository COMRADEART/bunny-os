#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The Public Alpha image target: one bootable disk image, labelled Alpha.
#
# It builds the `beta` profile, and that is deliberate rather than an oversight.
# A profile names a package set and an install-route subset; a channel names a
# promise about the build. The installed desktop payload has been the `beta`
# profile since the installer branch, it is what the live ISO deploys onto a
# disk, and renaming it would change the profile enumeration in the installer,
# the closure analyser, the preset table and every per-profile evidence record —
# a large change to the build in order to change a string that is already
# carried correctly by BUNNY_RELEASE_CHANNEL.
#
# So: profile `beta`, channel `alpha`. release.json and /usr/lib/os-release both
# say Alpha, the OCI configuration carries the channel as a label, and the
# artifacts are named from the same identity the running system reports.
set -euo pipefail

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
source_commit="$(git rev-parse HEAD)"
source_epoch="$(git show -s --format=%ct HEAD)"
build_id="${source_commit:0:12}.${source_epoch}"
architecture="$(uname -m)"
version="${BUNNY_ALPHA_VERSION:-0.1.0}"

echo "Bunny OS Alpha ${version%.*}"
echo "  build id     ${build_id}"
echo "  commit       ${source_commit}"
echo "  architecture ${architecture}"
echo "  channel      alpha"
echo "  profile      beta (the installed desktop payload; see the comment in this script)"

BUNNY_RELEASE_CHANNEL=alpha "${BASH:-/usr/bin/bash}" build/scripts/build-image.sh beta

output="${repository_root}/build/out/beta"
python3 build/scripts/write-media-manifest.py \
  --root "${output}" \
  --source-commit "${source_commit}" \
  --image-version "${version}-alpha.${source_commit:0:12}"

# §39: the image filename carries the identity. Derived from the same fields the
# running system reports through `bunny-os companion identity`, so a downloaded
# file and the machine it becomes cannot disagree about what they are.
name="bunny-os-${version}-alpha-${build_id}-${architecture}"
shopt -s nullglob
for artifact in "${output}"/*.qcow2 "${output}"/*.raw "${output}"/*.iso; do
  extension="${artifact##*.}"
  target="${output}/${name}.${extension}"
  [[ "${artifact}" == "${target}" ]] && continue
  mv -- "${artifact}" "${target}"
  echo "  artifact     ${target}"
done
shopt -u nullglob

echo
echo "This is an Alpha build. It is not a release candidate and this branch makes"
echo "no reproducibility claim; see docs/PUBLIC_ALPHA_SCOPE.md §7."
