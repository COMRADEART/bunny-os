#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Deterministic finalisation of the rpm and libdnf5 SQLite databases.
#
# Runs inside the build container, after packages are installed and before the
# archive is written. Split out of finalise-image.sh because it has a contract
# the rest of finalisation does not: it must be idempotent, it must fail closed
# on a long list of conditions, and it must be able to prove it changed no
# content.
#
# What it does NOT do is as important as what it does. It does not reconcile two
# databases, does not rewrite rows, and does not normalise a difference away.
# Measured on this project's two hermetic builds: the databases had identical
# page sizes, identical page counts, an empty freelist on both sides, identical
# b-tree depths and identical cell offsets — and differed in fifty rows of
# Packages, in one header tag, INSTALLTIME. A canonicaliser would have made those
# bytes match while destroying the evidence that the build clock was wrong. So
# the only transformation here is VACUUM, which SQLite defines as content-
# preserving, and the script *verifies* that it was by digesting the logical
# content before and after and refusing to continue if it moved.
#
# Usage:
#   finalise-package-databases.sh --report PATH [--expect-sqlite VERSION]
#                                 [--root DIR] [--skip-functional-checks]

set -euo pipefail

report=""
expect_sqlite=""
root=""
functional=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --report) report="${2:?}"; shift 2 ;;
    --expect-sqlite) expect_sqlite="${2:?}"; shift 2 ;;
    --root) root="${2:?}"; shift 2 ;;
    --skip-functional-checks) functional=0; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

rpmdb="${root}/usr/share/rpm/rpmdb.sqlite"
history="${root}/usr/lib/sysimage/libdnf5/transaction_history.sqlite"

if [[ ! -f "${rpmdb}" ]]; then
  echo "BLOCKED: ${rpmdb} is not present. This script finalises the databases a" >&2
  echo "package transaction produced; running it where there are none means the" >&2
  echo "transaction did not happen, and continuing would report success for work" >&2
  echo "nothing did." >&2
  exit 2
fi

# The logic lives in an importable module so the regression fixtures exercise
# the code that ships rather than a re-implementation of it. The path is
# relative to this script, which holds both in the repository and at
# /tmp/bunny-os inside the build container.
exec python3 "$(dirname "${BASH_SOURCE[0]}")/../../scripts/reproducibility/finalise_package_databases.py"   "${rpmdb}" "${history}" "${report}" "${expect_sqlite}" "${functional}" "${root}"
