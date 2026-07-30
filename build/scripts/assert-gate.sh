#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Assert that a protected gate returned exactly the status it was expected to.
#
#     assert-gate.sh <expected> <label> -- <command> [args...]
#
# The exit-code contract, used by scripts/release.py, scripts/phase5.py and
# scripts/phase7.py:
#
#     0   evaluated, and approved
#     2   evaluated, and refused — GO withheld, NO-GO, or BLOCKED
#     *   failed to evaluate — a traceback, a missing file, an import error,
#         a syntax error, or the interpreter itself failing to start
#
# CI asserted "the gate did not return 0" in several places, which accepts every
# one of those failure modes as proof that a protected gate is holding. A
# traceback exits 1. So does a missing evidence file. A job written that way goes
# green when release.py stops parsing, and reports that the stable gate correctly
# refused — the single most misleading thing this pipeline could say.
#
# Three outcomes are therefore reported distinctly:
#
#     the gate refused as expected           -> success
#     the gate approved unexpectedly         -> failure, and say so loudly
#     the gate did not evaluate at all       -> failure, and do not call it a refusal

set -uo pipefail

if [ "$#" -lt 4 ]; then
    echo "usage: assert-gate.sh <expected-status> <label> -- <command> [args...]" >&2
    exit 64
fi

expected="$1"
label="$2"
shift 2
if [ "$1" != "--" ]; then
    echo "assert-gate.sh: expected -- before the command, got '$1'" >&2
    exit 64
fi
shift

# `evaluated` is for reporting commands whose verdict legitimately depends on the
# evidence present: either outcome is correct, a crash is not.
case "$expected" in
    0|2|evaluated) ;;
    *)
        echo "assert-gate.sh: expected status must be 0, 2 or 'evaluated', got '$expected'" >&2
        exit 64
        ;;
esac

# A missing script is the one crash the exit code cannot distinguish: CPython
# exits 2 for "can't open file", which is also the documented refusal status. So
# the script's existence is checked before it is run, rather than inferred from
# what it returned.
for argument in "$@"; do
    case "$argument" in
        *.py|*.sh)
            if [ ! -f "$argument" ]; then
                echo "::error::${label} cannot run: ${argument} does not exist. A missing script exits 2 on CPython, which is also the refusal status, so this is checked before the command runs and is NOT a protected refusal."
                exit 1
            fi
            ;;
    esac
done

set +e
"$@"
status=$?
set -e

if [ "$expected" = "evaluated" ]; then
    if [ "$status" -eq 0 ] || [ "$status" -eq 2 ]; then
        echo "${label}: evaluated (exit ${status})"
        exit 0
    fi
    echo "::error::${label} failed to evaluate (exit ${status}). Either verdict would have been acceptable; a crash is not."
    exit 1
fi

if [ "$status" -eq "$expected" ]; then
    if [ "$expected" -eq 2 ]; then
        echo "${label}: correctly refused (exit 2)"
    else
        echo "${label}: passed as expected (exit 0)"
    fi
    exit 0
fi

if [ "$status" -eq 0 ] && [ "$expected" -eq 2 ]; then
    echo "::error::${label} unexpectedly returned approval (exit 0); a protected gate must not be opened by CI"
    exit 1
fi

if [ "$status" -eq 2 ] && [ "$expected" -eq 0 ]; then
    echo "::error::${label} refused (exit 2) but was expected to pass"
    exit 1
fi

echo "::error::${label} failed to evaluate (exit ${status}, expected ${expected}). This is a crash, a missing file or a parse failure — it is NOT a protected refusal, and must not be reported as one."
exit 1
