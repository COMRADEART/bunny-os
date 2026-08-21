#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Shared QEMU harness helpers.
#
# Extracted from vm-smoke.sh, which is the only VM script that was ever proven
# to work. Every harness that boots a disk uses the same firmware discovery,
# the same accel fallback, the same serial-log capture, and the same
# exit-0-or-124 tolerance, so a failure means the guest failed rather than the
# harness differing between scripts.

# shellcheck shell=bash

bunny_firmware() {
    local candidate
    for candidate in "${BUNNY_OVMF_CODE:-}" "${OVMF_CODE:-}" \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/edk2/ovmf/OVMF_CODE.fd; do
        if [[ -n "${candidate}" && -r "${candidate}" ]]; then
            printf '%s' "${candidate}"
            return 0
        fi
    done
    echo "OVMF firmware not found; set BUNNY_OVMF_CODE" >&2
    return 3
}

bunny_require_commands() {
    local command
    for command in "$@"; do
        command -v "${command}" >/dev/null 2>&1 || {
            echo "missing required command: ${command}" >&2
            return 3
        }
    done
}

# bunny_boot <disk> <log> <timeout> [extra qemu args...]
#
# Boots a disk with a snapshot overlay so the source image is never mutated,
# and captures the guest serial console. QEMU exiting 124 is the timeout path
# and is expected: a guest that reaches its target and idles is a success, and
# the markers in the log are what decide the outcome.
bunny_boot() {
    local disk="$1" log="$2" seconds="$3"
    shift 3
    local firmware
    firmware="$(bunny_firmware)" || return 3
    mkdir -p "$(dirname "${log}")"
    : >"${log}"
    local status=0
    timeout "${seconds}" qemu-system-x86_64 \
        -machine q35,accel=kvm:tcg \
        -cpu max \
        -smp 4 \
        -m 6144 \
        -bios "${firmware}" \
        -drive "file=${disk},format=qcow2,if=virtio,snapshot=on" \
        -device virtio-net-pci,netdev=net0 \
        -netdev user,id=net0 \
        -device virtio-vga \
        -display none \
        -serial "file:${log}" \
        -no-reboot \
        "$@" || status=$?
    if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
        echo "QEMU failed with status ${status}; see ${log}" >&2
        return "${status}"
    fi
    return 0
}

# bunny_require_marker <log> <label> <extended-regex>
bunny_require_marker() {
    local log="$1" label="$2" pattern="$3"
    if grep -aEiq "${pattern}" "${log}"; then
        echo "  observed: ${label}"
        return 0
    fi
    echo "  MISSING: ${label} (pattern: ${pattern}); see ${log}" >&2
    return 4
}

# bunny_boot_health <log> — the two markers vm-smoke.sh has always required.
bunny_boot_health() {
    local log="$1"
    bunny_require_marker "${log}" "system reached a boot target" \
        'Graphical Interface|Multi-User System|GNOME Display Manager|Reached target' || return 4
    bunny_require_marker "${log}" "Bunny OS boot health check finished" \
        'Finished .*Bunny OS boot health check' || return 4
}

# bunny_count_deployments <disk> — number of BLS entries on the boot filesystem.
# A freshly built image has exactly one; a rollback target only exists once an
# update has been staged.
bunny_count_deployments() {
    local disk="$1"
    local partition="${BUNNY_BOOT_PARTITION:-/dev/sda3}"
    virt-ls -a "${disk}" -m "${partition}" /loader/entries 2>/dev/null \
        | grep -c '\.conf$' || true
}

bunny_list_deployments() {
    local disk="$1"
    local partition="${BUNNY_BOOT_PARTITION:-/dev/sda3}"
    virt-ls -a "${disk}" -m "${partition}" /loader/entries 2>/dev/null || true
}

# bunny_deployment_checksums <disk>
#
# The ostree checksum of each deployment, read from the BLS entries.
#
# The *checksum* and not the whole `ostree=` argument, because the argument
# carries a `boot.N` component that bootc rewrites when the deployment order
# changes: the same deployment appears as `boot.0/<checksum>/0` in the BLS
# entry and boots as `boot.1/<checksum>/0` after a rollback. Comparing the
# whole string would report a correct rollback as a failure.
bunny_deployment_checksums() {
    local disk="$1"
    local partition="${BUNNY_BOOT_PARTITION:-/dev/sda3}"
    local entry
    while IFS= read -r entry; do
        [[ "${entry}" == *.conf ]] || continue
        virt-cat -a "${disk}" -m "${partition}" "/loader/entries/${entry}" 2>/dev/null \
            | grep -oE 'ostree=/ostree/boot\.[0-9]+/[^/]+/[a-f0-9]{64}/[0-9]+' \
            | grep -oE '[a-f0-9]{64}' \
            | head -1
    done < <(virt-ls -a "${disk}" -m "${partition}" /loader/entries 2>/dev/null | sort)
}

# bunny_booted_checksum <log>
#
# The deployment checksum the kernel was actually told to boot. The kernel
# prints its own command line, so this needs nothing injected into the guest.
bunny_booted_checksum() {
    grep -aoE 'ostree=/ostree/boot\.[0-9]+/[^/ ]+/[a-f0-9]{64}/[0-9]+' "$1" \
        | head -1 | grep -oE '[a-f0-9]{64}'
}

# bunny_require_booted_deployment <log> <ostree-argument>
#
# Assert that the boot used a particular deployment.
#
# This exists because `vm-rollback-test.sh` reported
#   "Rollback PASSED: the previous deployment was selected"
# for three consecutive runs in which the machine booted the *default*
# deployment every time. Its only check was that a healthy target was reached,
# and a machine that never rolled back reaches one perfectly well. §5 of the
# Phase 5 brief names this exact failure: the grader must never interpret "the
# machine survived" as "the journey succeeded".
#
# The kernel prints its own command line, so the evidence is already in the
# serial log and nothing needs to be injected into the guest to read it.
bunny_require_booted_deployment() {
    local log="$1" expected="$2"
    local observed
    observed="$(bunny_booted_checksum "${log}")"
    if [[ -z "${observed}" ]]; then
        echo "  no ostree= argument in the kernel command line; cannot say which deployment booted" >&2
        return 1
    fi
    if [[ "${observed}" != "${expected}" ]]; then
        echo "  booted the wrong deployment" >&2
        echo "    expected: ${expected}" >&2
        echo "    observed: ${observed}" >&2
        return 1
    fi
    echo "  booted deployment: ${observed}"
    return 0
}
