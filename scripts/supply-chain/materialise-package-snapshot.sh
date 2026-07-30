#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Turn a resolved package lock into an immutable, signed, offline repository.
#
# This is the **materialisation** stage. Resolution decided the set once, against
# live Fedora repositories; nothing after this point resolves anything. A
# qualification build enables this repository and no other, and fails rather than
# reaching a mirror.
#
# Fedora's own signatures are preserved byte for byte. The snapshot signature is
# additional, not a replacement: re-signing the RPMs would discard the trust that
# matters most and substitute a development key for it.
#
# Usage:
#   materialise-package-snapshot.sh --snapshot-id <id> [options]
#
#   --lock PATH          resolved package lock (default: build/inputs/package-lock.json)
#   --packages DIR       where the resolved RPMs already are
#   --retention-root DIR controlled store (default: /var/lib/bunny-retention)
#   --signing-key PATH   development snapshot signing key
#                        (default: ~/.bunny-dev-keys/snapshot/dev-snapshot-signing1.pem)

set -euo pipefail

snapshot_id=""
lock="build/inputs/package-lock.json"
packages=""
retention_root="${BUNNY_RETENTION_ROOT:-/var/lib/bunny-retention}"
signing_key="${HOME}/.bunny-dev-keys/snapshot/dev-snapshot-signing1.pem"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --snapshot-id) snapshot_id="${2:?}"; shift 2 ;;
    --lock) lock="${2:?}"; shift 2 ;;
    --packages) packages="${2:?}"; shift 2 ;;
    --retention-root) retention_root="${2:?}"; shift 2 ;;
    --signing-key) signing_key="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "${snapshot_id}" ]] || { echo "--snapshot-id is required" >&2; exit 2; }
[[ -n "${packages}" ]] || { echo "--packages is required" >&2; exit 2; }

for command in createrepo_c rpmkeys openssl python3 git; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing required command: ${command}" >&2; exit 3; }
done

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
[[ -f "${lock}" ]] || { echo "no package lock at ${lock}" >&2; exit 2; }

snapshot="${retention_root}/package-snapshots/${snapshot_id}"
echo "==> materialising snapshot ${snapshot_id} at ${snapshot}"
rm -rf "${snapshot}"
mkdir -p "${snapshot}/packages" "${snapshot}/repodata"

echo "==> copying and verifying every locked package"
python3 scripts/supply-chain/collect-snapshot-packages.py \
  --lock "${lock}" \
  --source "${packages}" \
  --destination "${snapshot}/packages"

echo "==> re-verifying every signature in the materialised snapshot"
# Verified again here rather than trusted from resolution. Copying is where a
# file can change, and a snapshot that verified its inputs but not its contents
# would be checking the wrong thing.
failed=0
while IFS= read -r rpm; do
  if ! rpmkeys --checksig "${rpm}" | grep -q 'signatures OK'; then
    echo "  FAIL $(basename "${rpm}")" >&2
    failed=1
  fi
done < <(find "${snapshot}/packages" -name '*.rpm')
if [[ "${failed}" != "0" ]]; then
  echo "BLOCKED: at least one package in the snapshot does not verify." >&2
  exit 2
fi
echo "    all signatures verified"

echo "==> generating repository metadata"
createrepo_c --quiet --general-compress-type=gz "${snapshot}"

# The metadata digest is over repomd.xml, which is itself a manifest of every
# other metadata file with their checksums. Signing repomd.xml therefore covers
# the whole of repodata, which is why `repo_gpgcheck=1` is meaningful.
metadata_digest="$(sha256sum "${snapshot}/repodata/repomd.xml" | awk '{print $1}')"
echo "    repomd.xml ${metadata_digest}"

echo "==> writing the snapshot manifest"
python3 scripts/supply-chain/write-snapshot-lock.py \
  --lock "${lock}" \
  --snapshot-id "${snapshot_id}" \
  --snapshot-root "${snapshot}" \
  --metadata-digest "${metadata_digest}" \
  --signing-key "${signing_key}"

echo
echo "snapshot ${snapshot_id} materialised"
echo "  packages  $(find "${snapshot}/packages" -name '*.rpm' | wc -l)"
echo "  location  ${snapshot}"
echo
echo "The development snapshot-signing key is not production trust. It proves the"
echo "signing path works and nothing about release authorisation; see"
echo "docs/PACKAGE_SNAPSHOTS.md for the production signing role, which does not exist."
