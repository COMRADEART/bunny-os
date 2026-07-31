#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One clean hermetic build of the qualification target, packaged as the local
# builder's evidence bundle.
#
# release/hosted.py imports a hosted builder's bundle and, beside it, the local
# builder's pair — and it holds both to the same shape: builder-record.json,
# ci-provenance.json, artifact-manifest.sha256, normalisation.json,
# sbom.spdx.json, package-inventory.txt, runner-environment.txt and build.log,
# every claim cross-checked against another file in the same bundle. Until now
# the local bundle was assembled by hand, which is exactly the shape of
# operator-dependent step this repository keeps finding in its own evidence.
#
# The build is of the *target commit*, not of whatever tree this script runs
# from. The qualification target is a child of the commit the local gate
# measured, and the target file itself sits in a COPY layer, so a local archive
# built at the parent is a different artifact from a hosted archive built at
# the target. Three builders compare only if all three built the same commit.
#
# Usage: collect-local-bundle.sh --commit SHA [--output DIR]
#                                [--workspace-root DIR] [--profile NAME]
#                                [--builder-id ID] [--keep]

set -euo pipefail

commit=""
output=""
workspace_root="/var/tmp"
profile="${BUNNY_PROFILE:-beta}"
builder_id="${BUNNY_BUILDER_ID:-local-fedora-wsl}"
keep=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit) commit="${2:?}"; shift 2 ;;
    --output) output="${2:?}"; shift 2 ;;
    --workspace-root) workspace_root="${2:?}"; shift 2 ;;
    --profile) profile="${2:?}"; shift 2 ;;
    --builder-id) builder_id="${2:?}"; shift 2 ;;
    --keep) keep=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for required in git podman skopeo python3 syft sha256sum; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "BLOCKED: ${required} is required and is not available." >&2
    exit 3
  fi
done

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"

if [[ -z "${commit}" ]]; then
  echo "BLOCKED: --commit is required and must be the qualification target." >&2
  echo "This bundle exists to be compared against hosted builds of one exact" >&2
  echo "commit; defaulting to HEAD would let the local leg drift to a commit" >&2
  echo "nobody dispatched." >&2
  exit 2
fi
commit="$(git rev-parse --verify "${commit}^{commit}")"

# The commit must be the target its own file describes, checked the same way
# the hosted guard checks it. A local bundle of a non-target commit would
# import cleanly and compare against nothing.
python3 scripts/supply-chain/assert-target-commit.py --commit "${commit}"

[[ -n "${output}" ]] || output="${repository_root}/build/out/qualification/local-bundle"
rm -rf "${output}"
mkdir -p "${output}"

workspace="${workspace_root}/bunny-local-bundle"
storage="${workspace_root}/storage-local-bundle"

echo "==> local bundle build: ${workspace}"
rm -rf "${workspace}" "${storage}"
mkdir -p "${storage}"
git clone --quiet --no-hardlinks "${repository_root}" "${workspace}"
git -C "${workspace}" checkout --quiet "${commit}"

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

(
  cd "${workspace}"
  BUNNY_PODMAN_ROOT="${storage}/graph" \
  BUNNY_PODMAN_RUNROOT="${storage}/run" \
  BUNNY_HERMETIC_BUILD=1 \
  BUNNY_ARCHIVE_ONLY=1 \
  bash build/scripts/build-image.sh "${profile}"
) 2>&1 | tee "${output}/build.log" | tail -3

completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

archive="${workspace}/build/out/${profile}/bunny-os.oci.tar"
[[ -f "${archive}" ]] || { echo "BLOCKED: the build produced no archive" >&2; exit 4; }

echo "==> collecting the bundle"

# The base pin both builders must record, read from the commit that was built
# rather than from this tree.
base_reference="$(cd "${workspace}" && python3 -c '
import json
lock = json.load(open("build/inputs/input-publication-lock.json"))
print(lock["inputs"]["base"]["digestReference"])
')"

epoch="$(cd "${workspace}" && python3 -c '
import json
print(json.load(open("build/inputs/reproducibility-lock.json"))["sourceDateEpoch"])
')"

syft "oci-archive:${archive}" \
  -o "spdx-json=${output}/sbom.spdx.json" \
  >/dev/null 2>"${output}/syft.log"

python3 - "${output}" <<'PY'
import json, pathlib, sys
bundle = pathlib.Path(sys.argv[1])
document = json.loads((bundle / "sbom.spdx.json").read_text(encoding="utf-8"))
entries = sorted(
    f"{item.get('name')}@{item.get('versionInfo', 'UNKNOWN')}"
    for item in document.get("packages", [])
)
(bundle / "package-inventory.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
print(f"{len(entries)} package entries")
PY

# The bundle's normalisation.json is the operator-side pass over the shipped
# archive, so its rawDigest is the digest the artifact manifest records for
# bunny-os.oci.tar. The build's own normalisation.json describes the
# pre-shipping normalisation and travels separately for the dimension collector.
python3 scripts/release.py normalise-artifact \
  --source "${archive}" \
  --destination "${output}/bunny-os.normalised.tar" \
  --output "${output}/normalisation.json"
rm -f "${output}/bunny-os.normalised.tar"

(
  cd "${workspace}"
  BUNNY_BASE_IMAGE="${base_reference}" \
  python3 scripts/reproducibility/collect_builder_record.py builder-record \
    --builder-id "${builder_id}" \
    --started-at "${started_at}" \
    --completed-at "${completed_at}" \
    --output "${output}/builder-record.json"
  BUNNY_BASE_IMAGE="${base_reference}" \
  python3 scripts/reproducibility/collect_builder_record.py provenance \
    --profile "${profile}" \
    --artifact-dir "build/out/${profile}" \
    --output "${output}/ci-provenance.json"
)

( cd "${workspace}/build/out/${profile}" && sha256sum -- * ) \
  > "${output}/artifact-manifest.sha256"

# The local machine's own report, written the way a runner writes its own.
# There is no workflow run and no hosted environment to claim; the import
# knows a local record legitimately lacks both.
{
  echo "kernel=$(uname -r)"
  echo "containerRuntime=$(podman --version)"
} > "${output}/runner-environment.txt"

cp "${workspace}/build/out/${profile}/provenance.json" "${output}/provenance.json"
cp "${workspace}/build/out/${profile}/normalisation.json" "${output}/build-normalisation.json"

# The comparison inputs, collected the same way the gate and the hosted
# workflow collect theirs.
python3 scripts/reproducibility/collect_intended_selinux.py \
  --archive "${archive}" \
  --output "${output}/intended-selinux.json"

python3 scripts/reproducibility/collect_comparison_dimensions.py \
  --archive "${archive}" \
  --sbom "${output}/sbom.spdx.json" \
  --normalisation "${workspace}/build/out/${profile}/normalisation.json" \
  --epoch "${epoch}" \
  --mode qualification \
  --output "${output}/dimensions.json"

python3 scripts/reproducibility/extract_archive_paths.py \
  --archive "${archive}" \
  --path usr/share/bunny-os/package-databases.json \
  --path usr/share/rpm/rpmdb.sqlite \
  --path usr/lib/sysimage/libdnf5/transaction_history.sqlite \
  --destination "${output}/databases" \
  --manifest "${output}/databases/extraction.json" \
  --require-all >/dev/null

if [[ "${keep}" == "0" ]]; then
  sudo rm -rf "${storage}" 2>/dev/null || rm -rf "${storage}"
fi

echo
echo "local bundle for ${commit:0:12} in ${output}"
echo "  raw         $(python3 -c "import json;print(json.load(open('${output}/normalisation.json'))['rawDigest'])")"
echo "  normalised  $(python3 -c "import json;print(json.load(open('${output}/normalisation.json'))['normalisedDigest'])")"
echo "  builder     ${builder_id}"
