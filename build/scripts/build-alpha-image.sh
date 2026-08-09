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

# §39: the image filename carries the identity. Derived from the same fields the
# running system reports through `bunny-os companion identity`, so a downloaded
# file and the machine it becomes cannot disagree about what they are.
#
# image-builder writes into a per-type subdirectory
# (bootc-fedora-44-qcow2-x86_64/…), so this walks rather than globs the top
# level. A glob was the first version and it renamed nothing at all, silently:
# the loop simply had no iterations and the artifacts kept image-builder's
# generic names.
name="bunny-os-${version}-alpha-${build_id}-${architecture}"
while IFS= read -r artifact; do
  extension="${artifact##*.}"
  target="$(dirname "${artifact}")/${name}.${extension}"
  [[ "${artifact}" == "${target}" ]] && continue
  mv -- "${artifact}" "${target}"
  echo "  artifact     ${target}"
done < <(find "${output}" -type f \( -name '*.qcow2' -o -name '*.raw' -o -name '*.iso' \) \
           -not -path '*/alpha-story/*' | sort)

# build-image writes provenance for image-builder's generic filenames. The
# Alpha wrapper gives the media its public identity above, so regenerate both
# records only after those final paths exist. This keeps provenance.json,
# SHA256SUMS and BUNNY-MANIFEST.json bound to the files a user actually gets.
base_image="${BUNNY_BASE_IMAGE:-quay.io/fedora/fedora-bootc:44}"
provenance_arguments=(
  --profile beta
  --output "${output}"
  --source-commit "${source_commit}"
  --source-date-epoch "${source_epoch}"
  --base-image "${base_image}"
  --image-reference "localhost/bunny-os-beta:${source_commit:0:12}"
)
if [[ "${BUNNY_ARCHIVE_ONLY:-0}" == "1" ]]; then
  provenance_arguments+=(--archive-only)
fi
python3 build/scripts/write-build-provenance.py "${provenance_arguments[@]}"
python3 build/scripts/write-media-manifest.py \
  --root "${output}" \
  --source-commit "${source_commit}" \
  --image-version "${version}-alpha.${source_commit:0:12}"

echo
echo "This is an Alpha build. It is not a release candidate and this branch makes"
echo "no reproducibility claim; see docs/PUBLIC_ALPHA_SCOPE.md §7."
