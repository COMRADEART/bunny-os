#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The entry point both builders run. It verifies its inputs before it builds
# anything, because a hermetic build that starts and then discovers a missing
# input has already spent an hour and produced an artifact nobody can trust.
#
# Order matters and is deliberate: verify the base, verify the snapshot, verify
# the epoch, and only then build. Each check exits 2 — *evaluated and refused* —
# so a caller asserting on exit codes can tell a refusal from a crash. A Python
# traceback exits 1, and a job that accepts any non-zero status as "the gate
# correctly refused" would go green on a syntax error.

set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: bunny-builder <command> [options]

  verify-inputs     verify the retained base, snapshot and epoch locks
  toolchain         print this builder's recorded toolchain as JSON
  build             verify inputs, then run a hermetic qualification build
  shell             an interactive shell inside the builder (diagnostics only)

Environment:
  BUNNY_PROFILE            profile to build (default: beta)
  BUNNY_RETENTION_ROOT     controlled retention store (default: /retention)
  BUNNY_ARCHIVE_ONLY       1 to stop after the normalised OCI archive
USAGE
  exit 2
}

command="${1:-}"
[[ -n "${command}" ]] || usage
shift || true

profile="${BUNNY_PROFILE:-beta}"
retention="${BUNNY_RETENTION_ROOT:-/retention}"
workspace="${BUNNY_WORKSPACE:-/workspace}"

cd "${workspace}"

verify_inputs() {
  local failed=0

  echo "==> verifying the retained base image"
  if ! python3 scripts/supply-chain/verify-retained-base.py \
        --lock build/inputs/base-image-lock.json \
        --layout "${retention}/base-images/$(python3 -c '
import json,sys
lock = json.load(open("build/inputs/base-image-lock.json"))
print(lock["upstreamDigest"].replace(":", "-"))
')"; then
    failed=1
  fi

  echo "==> verifying the package snapshot"
  if ! python3 scripts/supply-chain/verify-package-snapshot.py \
        --lock build/inputs/package-snapshot-lock.json \
        --snapshot-root "${retention}/package-snapshots"; then
    failed=1
  fi

  echo "==> verifying the build epoch and the lock set"
  if ! python3 scripts/supplychain.py verify-input-locks; then
    failed=1
  fi

  if [[ "${failed}" != "0" ]]; then
    echo >&2
    echo "BLOCKED: input verification failed. A qualification build must fail before" >&2
    echo "building rather than fall back to an unretained base or a live repository." >&2
    return 2
  fi
  echo "==> all input locks verified"
}

case "${command}" in
  toolchain)
    exec /usr/local/bin/bunny-builder-toolchain
    ;;
  verify-inputs)
    verify_inputs
    ;;
  build)
    verify_inputs
    echo "==> hermetic build: profile=${profile}"
    export BUNNY_HERMETIC_BUILD=1
    export BUNNY_RETENTION_ROOT="${retention}"
    exec bash build/scripts/build-image.sh "${profile}"
    ;;
  shell)
    exec /usr/bin/bash "$@"
    ;;
  *)
    usage
    ;;
esac
