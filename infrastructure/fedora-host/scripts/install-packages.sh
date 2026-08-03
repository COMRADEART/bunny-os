#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the qualification toolchain and record what actually happened.
#
# The rule this script exists to enforce is that an unavailable package is
# recorded, not skipped. A toolchain report that silently omits what could not be
# installed is how a matrix later reports NOT_RUN for a reason nobody can trace.
#
#   sudo install-packages.sh --manifest ../packages/fedora-packages.txt \
#        --report /var/lib/bunny-qualification/environments/FQH-.../packages.json
#
# --dry-run resolves availability without installing anything.

set -uo pipefail

MANIFEST="$(dirname "$0")/../packages/fedora-packages.txt"
REPORT=""
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --manifest) MANIFEST="${2:-}"; shift ;;
        --report)   REPORT="${2:-}"; shift ;;
        --dry-run)  DRY_RUN=1 ;;
        -h|--help)  echo "usage: install-packages.sh [--manifest F] [--report F] [--dry-run]"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ ! -f "$MANIFEST" ]; then
    echo "BLOCKED: manifest ${MANIFEST} does not exist" >&2
    exit 2
fi

if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    echo "BLOCKED: installation needs root. Re-run with sudo, or use --dry-run." >&2
    exit 2
fi

declare -a INSTALL_QUEUE=()
declare -a ROWS=()

classify() {
    local group="$1" package="$2" state="$3" version="$4"
    ROWS+=("{\"group\":\"${group}\",\"package\":\"${package}\",\"state\":\"${state}\",\"version\":${version}}")
    printf '  %-14s %-28s %s\n' "$group" "$package" "$state"
}

installed_version() {
    rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}' "$1" 2>/dev/null
}

echo "resolving ${MANIFEST}"
echo

while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac

    group="${line%%:*}"
    package="${line#*:}"

    if version="$(installed_version "$package")" && [ -n "$version" ]; then
        classify "$group" "$package" "ALREADY_PRESENT" "\"${version}\""
        continue
    fi

    if dnf --quiet list --available "$package" >/dev/null 2>&1 \
       || dnf --quiet list --installed "$package" >/dev/null 2>&1; then
        INSTALL_QUEUE+=("$package")
        classify "$group" "$package" "AVAILABLE" "null"
    else
        # Not silently dropped. An unavailable package is a recorded fact, and
        # the operator decides whether it was renamed or genuinely absent.
        classify "$group" "$package" "UNAVAILABLE" "null"
    fi
done < "$MANIFEST"

echo
echo "queued for installation: ${#INSTALL_QUEUE[@]}"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "dry run: nothing installed."
elif [ "${#INSTALL_QUEUE[@]}" -gt 0 ]; then
    dnf install -y "${INSTALL_QUEUE[@]}"
    echo
    echo "re-checking installed state"
    NEW_ROWS=()
    for row in "${ROWS[@]}"; do
        package="$(echo "$row" | sed -n 's/.*"package":"\([^"]*\)".*/\1/p')"
        state="$(echo "$row" | sed -n 's/.*"state":"\([^"]*\)".*/\1/p')"
        if [ "$state" = "AVAILABLE" ]; then
            if version="$(installed_version "$package")" && [ -n "$version" ]; then
                row="${row/\"state\":\"AVAILABLE\"/\"state\":\"INSTALLED\"}"
                row="${row/\"version\":null/\"version\":\"${version}\"}"
            else
                row="${row/\"state\":\"AVAILABLE\"/\"state\":\"UNAVAILABLE\"}"
            fi
        fi
        NEW_ROWS+=("$row")
    done
    ROWS=("${NEW_ROWS[@]}")
fi

if [ -n "$REPORT" ]; then
    mkdir -p "$(dirname "$REPORT")"
    {
        printf '{\n  "schemaVersion": 1,\n'
        printf '  "manifest": "%s",\n' "$MANIFEST"
        printf '  "collectedAt": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '  "dryRun": %s,\n' "$([ "$DRY_RUN" -eq 1 ] && echo true || echo false)"
        printf '  "packages": [\n'
        for i in "${!ROWS[@]}"; do
            printf '    %s%s\n' "${ROWS[$i]}" "$([ "$i" -lt $((${#ROWS[@]} - 1)) ] && echo ,)"
        done
        printf '  ]\n}\n'
    } > "$REPORT"
    echo "wrote ${REPORT}"
fi

echo
echo "This is host tooling inventory. It is host evidence, never release evidence."
