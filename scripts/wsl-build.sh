#!/usr/bin/env bash
# Run Bunny OS build and evidence steps inside the Fedora WSL builder.
#
# Two hard-won constraints are encoded here rather than left to memory:
#
#  1. Never run from /mnt/c. Linux git reports ~910 spurious modified files on
#     the Windows mount because of line-ending normalisation, so
#     build-stable-rc.sh (which requires a clean tree) can never pass there.
#     9p I/O is also 10-20x slower and loopback operations on it are unreliable.
#
#  2. Invoke this file directly. The agent harness that drives WSL strips $VAR
#     references and mangles $(...) inside `wsl -- bash -lc '...'`, and a `cd`
#     in a compound command does not stick. Running a script file avoids all of
#     that because the shell that expands the variables is the one inside WSL.
#
# Usage, from Windows:
#   wsl -d FedoraLinux-44 -- /root/bunny-os/scripts/wsl-build.sh <command> [args]

set -euo pipefail

WORKTREE=/root/bunny-os
EVIDENCE=/root/bunny-evidence
KEYS=/root/.bunny-dev-keys

log() { printf '\n=== %s ===\n' "$1"; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

require_ext4() {
    case "$PWD" in
        /mnt/*) die "refusing to run from the Windows mount; use $WORKTREE" ;;
    esac
}

cmd_sync() {
    local target="${1:-}"
    [ -n "$target" ] || die "sync requires a commit sha"
    git -C "$WORKTREE" fetch origin --prune
    git -C "$WORKTREE" checkout --force "$target"
    git -C "$WORKTREE" clean -fdx build/out
    log "worktree state"
    git -C "$WORKTREE" log --oneline -1
    git -C "$WORKTREE" status --porcelain=v1 --untracked-files=all | head -20
    local dirty
    dirty=$(git -C "$WORKTREE" status --porcelain=v1 --untracked-files=all | wc -l)
    printf 'dirty entries: %s\n' "$dirty"
}

cmd_doctor() {
    log "toolchain"
    for tool in podman image-builder syft grype openssl qemu-system-x86_64 qemu-img \
                skopeo shellcheck systemd-analyze make python3 bootc jq xorriso virt-filesystems; do
        printf '%-22s %s\n' "$tool" "$(command -v "$tool" || echo MISSING)"
    done
    log "kvm"
    ls -l /dev/kvm 2>&1 || true
    log "resources"
    nproc
    free -g | head -2
    df -h /var/tmp | tail -1
    log "firmware"
    ls /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd 2>&1 || true
    log "python"
    python3 -c 'import cryptography; print("cryptography", cryptography.__version__)'
}

# Build one image profile. build-image.sh refuses a non-empty output directory
# (exit 5), so the caller archives or clears it first.
cmd_build() {
    local profile="${1:-}"
    [ -n "$profile" ] || die "build requires a profile"
    cd "$WORKTREE"
    require_ext4
    rm -rf "build/out/$profile"
    SOURCE_DATE_EPOCH="$(git -C "$WORKTREE" show -s --format=%ct HEAD)" \
        bash build/scripts/build-image.sh "$profile"
}

cmd_evidence() {
    local profile="${1:-}"
    [ -n "$profile" ] || die "evidence requires a profile"
    cd "$WORKTREE"
    require_ext4
    mkdir -p "$EVIDENCE/$profile"
    log "inspect"
    bash build/scripts/inspect-image.sh "$profile" 2>&1 | tee "$EVIDENCE/$profile/inspect.log"
    log "sbom"
    bash build/scripts/sbom.sh "$profile" 2>&1 | tee "$EVIDENCE/$profile/sbom.log"
    log "license scan"
    python3 build/scripts/license-scan.py "build/out/$profile/sbom/bunny-os.spdx.json" \
        2>&1 | tee "$EVIDENCE/$profile/license.log"
    log "vulnerability scan (non-fatal here; the gate records the result)"
    bash build/scripts/security-scan.sh "$profile" 2>&1 | tee "$EVIDENCE/$profile/grype.log" || true
    log "vm smoke"
    bash build/scripts/vm-smoke.sh "$profile" 2>&1 | tee "$EVIDENCE/$profile/vm-smoke.log"
}

# Two builds of the same commit, compared by OCI archive digest. This is
# same-host determinism, NOT the two-independent-builder evidence the
# production gate requires. Reported as such.
cmd_reproducibility() {
    local profile="${1:-developer}"
    cd "$WORKTREE"
    require_ext4
    mkdir -p "$EVIDENCE/reproducibility"
    local first="$EVIDENCE/reproducibility/${profile}-run1.oci.tar"
    local second="$EVIDENCE/reproducibility/${profile}-run2.oci.tar"
    cmd_build "$profile"
    cp "build/out/$profile/bunny-os.oci.tar" "$first"
    cmd_build "$profile"
    cp "build/out/$profile/bunny-os.oci.tar" "$second"
    sha256sum "$first" "$second" | tee "$EVIDENCE/reproducibility/${profile}-digests.txt"
}

# Development signing keys. Generated outside the worktree because
# sign-stable-rc.py refuses a key path inside the repository, and because these
# must never be mistaken for production release keys.
cmd_devkeys() {
    mkdir -p "$KEYS"
    chmod 700 "$KEYS"
    if [ -f "$KEYS/stable-dev.pem" ]; then
        printf 'development keypair already present at %s\n' "$KEYS"
    else
        openssl genpkey -algorithm ed25519 -out "$KEYS/stable-dev.pem"
        chmod 600 "$KEYS/stable-dev.pem"
        openssl pkey -in "$KEYS/stable-dev.pem" -pubout -out "$KEYS/stable-dev.pub.pem"
    fi
    ls -l "$KEYS"
    printf '\nThese are DEVELOPMENT keys. They are not a production release root.\n'
}

cmd_selfcheck() {
    cd "$WORKTREE"
    require_ext4
    log "validate"
    python3 scripts/task.py validate
    log "test"
    python3 scripts/task.py test
    log "phase7"
    python3 scripts/task.py phase7-audit
    python3 scripts/phase7.py source-gate
    log "shellcheck"
    shellcheck build/scripts/*.sh scripts/*.sh || true
    log "systemd units"
    systemd-analyze verify systemd/*.service systemd/*.socket systemd/*.timer systemd/*.target 2>&1 | head -40 || true
}

main() {
    local command="${1:-}"
    shift || true
    case "$command" in
        sync)            cmd_sync "$@" ;;
        doctor)          cmd_doctor ;;
        build)           cmd_build "$@" ;;
        evidence)        cmd_evidence "$@" ;;
        reproducibility) cmd_reproducibility "$@" ;;
        devkeys)         cmd_devkeys ;;
        selfcheck)       cmd_selfcheck ;;
        *) die "usage: wsl-build.sh {sync <sha>|doctor|build <profile>|evidence <profile>|reproducibility [profile]|devkeys|selfcheck}" ;;
    esac
}

main "$@"
