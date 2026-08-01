#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Accessibility evidence collector. Runs ON the target device.
#
# Backs the keyboard-only-operation and orca-operation tests: those are
# operator-driven, but the operator's claim needs the stack to exist first —
# which packages are installed, at which versions, and whether the session's
# a11y switches are reachable. Two guards matter here: gsettings needs a
# session bus (a console or ssh shell has none, and that absence is recorded,
# not fatal), and /etc/brlapi.key is a SECRET — it is the authentication key
# for the braille daemon, so it is stat'd for existence, mode and owner and
# its content is never read. Evidence that leaks a key disqualifies itself.
#
# Usage: collect-accessibility.sh <output-dir>
set -euo pipefail

if [[ $# -ne 1 || -z "${1:-}" ]]; then
    echo "usage: $0 <output-dir>" >&2
    exit 2
fi

# Refuse to run as a demo (see collect-hardware.sh: a VM also has DMI, so
# this check refuses obviously-wrong environments; the hardware RECORD
# binding is what establishes physicality).
if [[ ! -d /sys/class/dmi/id ]]; then
    echo "REFUSED: /sys/class/dmi/id is absent; this is not an installed" >&2
    echo "physical-style system. This collector produces qualification" >&2
    echo "evidence and must not be run as a demo. Exit 2, fail closed." >&2
    exit 2
fi

outdir="$1"
mkdir -p "$outdir"

# Package presence and versions. rpm -q exits non-zero for a missing package
# while printing "package X is not installed" — exactly the record we want,
# so the non-zero exit is expected, not an error.
{
    if command -v rpm > /dev/null 2>&1; then
        for pkg in orca brltty speech-dispatcher; do
            rpm -q "$pkg" 2>&1 || true
        done
    else
        printf 'ABSENT: rpm is not installed on this system\n'
    fi
} > "$outdir/a11y-packages.txt"

# Session a11y settings, only where a session bus exists. gsettings without
# a bus returns defaults or errors misleadingly, so the guard records the
# absence instead of writing values that were never in effect.
{
    if ! command -v gsettings > /dev/null 2>&1; then
        printf 'ABSENT: gsettings is not installed on this system\n'
    elif [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
        printf 'NO-SESSION-BUS: DBUS_SESSION_BUS_ADDRESS is unset; run this from a\n'
        printf 'logged-in session to capture the a11y keys actually in effect\n'
    else
        for schema in \
            org.gnome.desktop.a11y \
            org.gnome.desktop.a11y.applications \
            org.gnome.desktop.a11y.interface \
            org.gnome.desktop.a11y.keyboard \
            org.gnome.desktop.a11y.magnifier \
            org.gnome.desktop.a11y.mouse; do
            printf '== schema: %s ==\n' "$schema"
            gsettings list-recursively "$schema" 2>&1 || printf 'schema not present\n'
            printf '\n'
        done
    fi
} > "$outdir/a11y-settings.txt"

# /etc/brlapi.key: stat ONLY. The key content is a secret and reading it
# into an evidence file would make the evidence itself a leak; existence,
# mode and owner are all the brltty qualification needs.
{
    if [[ -e /etc/brlapi.key ]]; then
        stat -c 'exists: yes  mode: %a  owner: %U:%G' /etc/brlapi.key 2>&1 \
            || printf 'exists: yes  (stat failed)\n'
    else
        printf 'exists: no\n'
    fi
} > "$outdir/brlapi-key-stat.txt"

# Manifest last, sorted, so post-collection edits are detectable.
#
# Built outside the directory it describes and moved in afterwards. A
# manifest written into the tree being walked is a file that would have to
# either digest itself or be excluded by name, and shellcheck refuses the
# shape (SC2094) for the same reason it is worth avoiding: the output of the
# walk depends on when the walk reached its own output.
manifest="$(mktemp)"
(
    cd "$outdir"
    find . -type f -print0 | sort -z | xargs -0 sha256sum
) > "$manifest"
mv "$manifest" "$outdir/manifest.sha256"

echo "collect-accessibility.sh: wrote $(wc -l < "$outdir/manifest.sha256") files into $outdir (see manifest.sha256)"
