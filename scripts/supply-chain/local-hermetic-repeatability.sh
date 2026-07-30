#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Two clean hermetic builds of one commit, compared across every archive-stage
# dimension.
#
# This measures *determinism*, not reproducibility. Both builds run on one host,
# under one kernel, one container store, one clock and one operator; a defect in
# any of those reproduces in both and this comparison cannot see it. It is the
# gate that must pass before a hosted build is dispatched, because dispatching
# one before it passes measures nothing the local builder has not already
# settled — and it is only that gate.
#
# Every stage is driven from a fresh clone into an empty workspace with its own
# container storage. Sharing a store between the two builds would let a layer
# cached from the first satisfy the second, and two builds where one was partly
# copied from the other are one build.
#
# Modes:
#   qualification   every archive-stage dimension must be collected; a missing
#                   one is a refusal. Only this mode produces gate evidence.
#   diagnostic      missing dimensions are recorded as NOT_COLLECTED.
#
# Usage: local-hermetic-repeatability.sh [--mode qualification|diagnostic]
#                                        [--workspace-root DIR] [--keep]
#                                        [--profile NAME] [--output DIR]

set -euo pipefail

mode="qualification"
workspace_root="/var/tmp"
profile="${BUNNY_PROFILE:-beta}"
keep=0
output=""
labels=("a2" "b2")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) mode="${2:?}"; shift 2 ;;
    --workspace-root) workspace_root="${2:?}"; shift 2 ;;
    --profile) profile="${2:?}"; shift 2 ;;
    --labels) IFS=',' read -r -a labels <<< "${2:?}"; shift 2 ;;
    --output) output="${2:?}"; shift 2 ;;
    --keep) keep=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "${mode}" in
  qualification|diagnostic) ;;
  *) echo "--mode must be qualification or diagnostic" >&2; exit 2 ;;
esac

for command in git podman skopeo python3 syft matchpathcon; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "BLOCKED: ${command} is required and is not available." >&2
    if [[ "${mode}" == "qualification" ]]; then
      echo "In qualification mode a missing tool is a refusal, not a dimension to omit:" >&2
      echo "reporting a dimension as NOT_COLLECTED because a tool was absent records an" >&2
      echo "environment defect as an evidence gap." >&2
    fi
    exit 3
  fi
done

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
source_commit="$(git rev-parse HEAD)"
[[ -n "${output}" ]] || output="${repository_root}/build/out/qualification/repeatability"
mkdir -p "${output}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "BLOCKED: the working tree is not clean." >&2
  echo "Both builds clone this commit; uncommitted work would be in neither, and the" >&2
  echo "evidence would name a commit that does not describe what was built." >&2
  exit 2
fi

epoch="$(python3 -c '
import json
print(json.load(open("build/inputs/reproducibility-lock.json"))["sourceDateEpoch"])
')"
base_digest="$(python3 -c '
import json
print(json.load(open("build/inputs/base-image-lock.json"))["retainedDigest"])
')"

echo "local hermetic repeatability"
echo "  commit   ${source_commit}"
echo "  profile  ${profile}"
echo "  epoch    ${epoch}"
echo "  base     ${base_digest}"
echo "  mode     ${mode}"
echo

build_one() {
  local label="$1"
  local workspace="${workspace_root}/bunny-hermetic-${label}"
  local storage="${workspace_root}/storage-${label}"

  echo "==> build ${label}: ${workspace}"
  rm -rf "${workspace}" "${storage}"
  mkdir -p "${storage}"
  git clone --quiet --no-hardlinks "${repository_root}" "${workspace}"
  git -C "${workspace}" checkout --quiet "${source_commit}"

  # Its own container storage. A store shared with the other build could serve
  # a cached layer to the second one, and a build partly copied from another is
  # not an independent measurement of anything.
  (
    cd "${workspace}"
    CONTAINERS_STORAGE_CONF="" \
    BUNNY_HERMETIC_BUILD=1 \
    BUNNY_ARCHIVE_ONLY=1 \
    bash build/scripts/build-image.sh "${profile}"
  ) 2>&1 | tee "${output}/build-${label}.log" | tail -3

  local archive="${workspace}/build/out/${profile}/bunny-os.oci.tar"
  [[ -f "${archive}" ]] || { echo "BLOCKED: build ${label} produced no archive" >&2; exit 4; }

  echo "==> collecting evidence for ${label}"

  # The SBOM is generated here rather than left to whoever remembers, because
  # the previous run reported four dimensions NOT_COLLECTED for exactly that
  # reason. In qualification mode the collector refuses an incomplete result, so
  # a forgotten step now stops the run instead of producing evidence that looks
  # complete in a summary line.
  mkdir -p "${workspace}/build/out/${profile}/sbom"
  syft "oci-archive:${archive}" \
    -o "spdx-json=${workspace}/build/out/${profile}/sbom/bunny-os.spdx.json" \
    >/dev/null 2>"${output}/syft-${label}.log"

  python3 scripts/reproducibility/collect_intended_selinux.py \
    --archive "${archive}" \
    --output "${output}/intended-selinux-${label}.json"

  python3 scripts/reproducibility/collect_comparison_dimensions.py \
    --archive "${archive}" \
    --sbom "${workspace}/build/out/${profile}/sbom/bunny-os.spdx.json" \
    --normalisation "${workspace}/build/out/${profile}/normalisation.json" \
    --epoch "${epoch}" \
    --mode "${mode}" \
    --output "${output}/dimensions-${label}.json"

  cp "${workspace}/build/out/${profile}/normalisation.json" \
     "${output}/normalisation-${label}.json"

  # The finalisation manifest the databases produced, kept beside the evidence.
  # It is what says the canonicalisation preserved content, and it belongs with
  # the comparison rather than only inside the image.
  python3 scripts/reproducibility/extract_archive_paths.py \
    --archive "${archive}" \
    --path usr/share/bunny-os/package-databases.json \
    --path usr/share/rpm/rpmdb.sqlite \
    --path usr/lib/sysimage/libdnf5/transaction_history.sqlite \
    --destination "${output}/databases-${label}" \
    --manifest "${output}/databases-${label}/extraction.json" \
    --require-all >/dev/null

  if [[ "${keep}" == "0" ]]; then
    rm -rf "${storage}"
  fi
  echo
}

for label in "${labels[@]}"; do
  build_one "${label}"
done

first="${labels[0]}"
second="${labels[1]}"

echo "==> comparing ${first} and ${second}"
python3 scripts/reproducibility/build_comparison_document.py \
  --first-dimensions "${output}/dimensions-${first}.json" \
  --second-dimensions "${output}/dimensions-${second}.json" \
  --first-selinux "${output}/intended-selinux-${first}.json" \
  --second-selinux "${output}/intended-selinux-${second}.json" \
  --first-builder "local-fedora-wsl-${first}" \
  --second-builder "local-fedora-wsl-${second}" \
  --source-commit "${source_commit}" \
  --base-image-digest "${base_digest}" \
  --claim "same-host-repeatability" \
  --mode "${mode}" \
  --output "${output}/comparison.json"

echo
echo "==> comparing the package databases directly"
python3 scripts/reproducibility/compare_sqlite_logical.py \
  --first "${output}/databases-${first}/usr__share__rpm__rpmdb.sqlite" \
  --second "${output}/databases-${second}/usr__share__rpm__rpmdb.sqlite" \
  --output "${output}/sqlite-logical-rpmdb.json" || true
python3 scripts/reproducibility/compare_sqlite_pages.py \
  --first "${output}/databases-${first}/usr__share__rpm__rpmdb.sqlite" \
  --second "${output}/databases-${second}/usr__share__rpm__rpmdb.sqlite" \
  --output "${output}/sqlite-pages-rpmdb.json" || true
python3 scripts/reproducibility/compare_sqlite_logical.py \
  --first "${output}/databases-${first}/usr__lib__sysimage__libdnf5__transaction_history.sqlite" \
  --second "${output}/databases-${second}/usr__lib__sysimage__libdnf5__transaction_history.sqlite" \
  --output "${output}/sqlite-logical-history.json" || true

echo
outcome="$(python3 -c '
import json, sys
print(json.load(open(sys.argv[1]))["evaluation"]["outcome"])
' "${output}/comparison.json")"

echo "evidence in ${output}"
echo "outcome: ${outcome}"

# Same-host repeatability passes only on REPRODUCIBLE, and even then it is not
# reproducibility. The exit code is what the Makefile and CI read, so it says
# exactly one thing: may a hosted build be dispatched against this tree.
if [[ "${outcome}" != "REPRODUCIBLE" ]]; then
  echo >&2
  echo "BLOCKED: the local repeatability gate does not pass (${outcome})." >&2
  echo "No hosted build may be dispatched and no qualification target may be created" >&2
  echo "from this tree." >&2
  exit 2
fi

echo
echo "The local gate passes. This is same-host determinism: two builds on one host"
echo "share a kernel, a container store, a clock and an operator, and a defect in any"
echo "of them reproduces in both. Reproducibility requires independent builders."
