#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Return the qualification host to a known state between matrices.
#
# This script runs as root on a machine that also holds the operator's real work,
# so it is written to be timid. It removes only things it created, identified by
# a naming prefix it controls, and it refuses to guess. Anything it does not
# recognise is reported and left alone.
#
# The rule it exists to enforce is that a matrix must not inherit state from the
# previous one. A passing run that only passed because a portal permission was
# still granted from an hour ago is not evidence of anything.
#
#   reset-test-state.sh --scope visual-v4 --dry-run
#   sudo reset-test-state.sh --scope encryption
#
# --dry-run prints what would happen and changes nothing. Use it first; the
# default is to require it for any scope touching block devices.

set -uo pipefail

PREFIX="${BUNNY_QUAL_PREFIX:-bunnyqual}"
ROOT="${BUNNY_EVIDENCE_ROOT:-/var/lib/bunny-qualification}"
DRY_RUN=0
SCOPE=""

SCOPES=(visual-v4 encryption selinux update accessibility hardware-rehearsal all)

usage() {
    cat <<USAGE
usage: reset-test-state.sh --scope <scope> [--dry-run]

scopes: ${SCOPES[*]}

Only resources named with the prefix '${PREFIX}' are touched. Everything else is
reported and left alone, including unrelated VMs, unknown disks and user files.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --scope) SCOPE="${2:-}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
    shift
done

if [ -z "$SCOPE" ]; then
    echo "BLOCKED: --scope is required" >&2
    usage
    exit 2
fi

SCOPE_KNOWN=0
for known in "${SCOPES[@]}"; do
    if [ "$known" = "$SCOPE" ]; then
        SCOPE_KNOWN=1
        break
    fi
done

if [ "$SCOPE_KNOWN" -eq 0 ]; then
    echo "BLOCKED: unknown scope '${SCOPE}'" >&2
    exit 2
fi

say()  { echo "  $*"; }
act()  {
    if [ "$DRY_RUN" -eq 1 ]; then
        say "would run: $*"
    else
        say "running: $*"
        "$@" || say "  (non-fatal: exit $?)"
    fi
}

require_root() {
    if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
        echo "BLOCKED: this scope changes system state and needs root. Re-run with sudo, or use --dry-run." >&2
        exit 2
    fi
}

# --- scopes ----------------------------------------------------------------

reset_compositor() {
    echo "compositor and session state"
    # Only processes started from the qualification tree. Killing by binary name
    # alone would reach the operator's own GNOME session.
    local pids
    pids="$(pgrep -f "${ROOT}/.*bunny-(shell|smithay|mutter)" 2>/dev/null || true)"
    if [ -n "$pids" ]; then
        for pid in $pids; do act kill -TERM "$pid"; done
    else
        say "no qualification compositor processes found"
    fi
    say "leaving the operator GNOME session untouched"
}

reset_portal_permissions() {
    echo "portal permissions and screen-sharing grants"
    local db="${HOME}/.local/share/flatpak/db/screencast"
    if [ -f "$db" ]; then
        act rm -f "$db"
    else
        say "no screencast permission store at ${db}"
    fi
    act flatpak permission-reset --all "${PREFIX}.test" 2>/dev/null
}

reset_accessibility() {
    echo "accessibility preferences"
    for key in screen-reader-enabled magnifier-enabled high-contrast large-text; do
        act gsettings reset "org.gnome.desktop.a11y.applications" "$key" 2>/dev/null
    done
    say "note: resets the test account only; run as the qualification operator"
}

reset_input_method() {
    echo "input method state"
    act pkill -f "ibus-daemon.*${PREFIX}" 2>/dev/null
    say "IBus/Fcitx user configuration left in place; matrices set it explicitly"
}

reset_guests() {
    require_root
    echo "libvirt guests, overlays and firmware variable stores"
    local domains
    domains="$(virsh list --all --name 2>/dev/null | grep "^${PREFIX}-" || true)"
    if [ -z "$domains" ]; then
        say "no guests named ${PREFIX}-*"
    else
        for domain in $domains; do
            act virsh destroy "$domain"
            act virsh undefine "$domain" --nvram
        done
    fi

    local others
    others="$(virsh list --all --name 2>/dev/null | grep -v "^${PREFIX}-" | grep -v '^$' || true)"
    if [ -n "$others" ]; then
        say "leaving unrelated guests alone:"
        for domain in $others; do say "  - ${domain}"; done
    fi

    if [ -d "${ROOT}/overlays" ]; then
        act find "${ROOT}/overlays" -maxdepth 1 -name "${PREFIX}-*" -delete
    fi
    if [ -d "${ROOT}/temporary" ]; then
        act find "${ROOT}/temporary" -mindepth 1 -maxdepth 1 -delete
    fi
}

reset_block_devices() {
    require_root
    echo "LUKS mappings, loop devices and mounts"
    # Named mappings only. A blanket cryptsetup close would reach the operator's
    # own encrypted disks, which is exactly the accident this script must not have.
    local -a mappings=()
    local path
    for path in "/dev/mapper/${PREFIX}"-*; do
        [ -e "$path" ] || continue
        mappings+=("${path##*/}")
    done

    if [ "${#mappings[@]}" -eq 0 ]; then
        say "no device-mapper entries named ${PREFIX}-*"
    else
        local mapping mount
        for mapping in "${mappings[@]}"; do
            mount="$(findmnt -n -o TARGET "/dev/mapper/${mapping}" 2>/dev/null || true)"
            [ -n "$mount" ] && act umount "$mount"
            act cryptsetup close "$mapping"
        done
    fi

    local loops
    loops="$(losetup -l -n -O NAME,BACK-FILE 2>/dev/null | awk -v r="$ROOT" '$2 ~ r {print $1}' || true)"
    if [ -z "$loops" ]; then
        say "no loop devices backed by ${ROOT}"
    else
        for loop in $loops; do act losetup -d "$loop"; done
    fi

    say "unknown disks and unrelated mounts are never touched"
}

reset_swtpm() {
    require_root
    echo "software TPM state"
    act pkill -f "swtpm.*${ROOT}" 2>/dev/null
    if [ -d "${ROOT}/vm-images" ]; then
        act find "${ROOT}/vm-images" -maxdepth 2 -type d -name "${PREFIX}-*-tpm" -exec rm -rf {} +
    fi
    say "reminder: swtpm state is never physical TPM evidence"
}

reset_pam() {
    require_root
    echo "temporary PAM configuration"
    local stack="/etc/pam.d/${PREFIX}-test"
    if [ -f "$stack" ]; then
        act rm -f "$stack"
    else
        say "no temporary PAM stack at ${stack}"
    fi
    say "system PAM configuration is never modified by this script"
}

check_no_secrets() {
    echo "secret check"
    local hits=0
    if [ -d "${ROOT}/evidence" ]; then
        hits="$(grep -rIl -E 'passphrase|password|BEGIN [A-Z ]*PRIVATE KEY' "${ROOT}/evidence" 2>/dev/null | wc -l)"
    fi
    if [ "$hits" -gt 0 ]; then
        echo "  WARNING: ${hits} evidence file(s) match a secret pattern. Review before committing."
        echo "  Plaintext passphrases must never be retained."
    else
        say "no evidence file matched a secret pattern"
    fi
}

# --- dispatch ---------------------------------------------------------------

echo "reset-test-state: scope=${SCOPE} dry-run=${DRY_RUN} prefix=${PREFIX} root=${ROOT}"
echo

case "$SCOPE" in
    visual-v4)
        reset_compositor; reset_portal_permissions; reset_accessibility; reset_input_method ;;
    encryption)
        reset_guests; reset_block_devices; reset_swtpm ;;
    selinux)
        reset_guests; reset_block_devices ;;
    update)
        reset_guests; reset_block_devices; reset_swtpm ;;
    accessibility)
        reset_accessibility; reset_compositor; reset_portal_permissions ;;
    hardware-rehearsal)
        reset_compositor; reset_portal_permissions; reset_accessibility; reset_pam ;;
    all)
        reset_compositor; reset_portal_permissions; reset_accessibility; reset_input_method
        reset_guests; reset_block_devices; reset_swtpm; reset_pam ;;
esac

echo
check_no_secrets
echo
if [ "$DRY_RUN" -eq 1 ]; then
    echo "dry run: nothing was changed."
else
    echo "reset complete for scope ${SCOPE}."
fi
echo "This resets test state. It qualifies nothing."
