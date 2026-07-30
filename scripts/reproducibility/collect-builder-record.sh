#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Emit this builder's identity record as JSON on stdout.
#
# The fields exist to answer one question: in what way is this builder
# *different* from the other one? A record that cannot answer that is a record
# of a build, not of an independent build, and release/reproducibility.py will
# refuse the independent-builder claim on that basis.
#
# machineId is deliberately a salted hash rather than the raw /etc/machine-id.
# The raw value is a stable host identifier and does not belong in a committed
# evidence file; the hash still compares equal or unequal, which is all the
# comparison needs.

set -euo pipefail

BUILDER_ID="${1:-${BUNNY_BUILDER_ID:-unnamed}}"
WORKTREE="${BUNNY_WORKTREE:-$(pwd)}"
SALT="${BUNNY_MACHINE_ID_SALT:-bunny-os-reproducibility}"

hash_of() { printf '%s' "$1" | sha256sum | cut -c1-32; }

raw_machine_id="$(cat /etc/machine-id 2>/dev/null || hostname 2>/dev/null || echo unknown)"
machine_id="$(hash_of "${SALT}:${raw_machine_id}")"

# A WSL/container instance is not the same environment as its host even though
# it shares a machine-id, so the virtualisation instance is recorded separately.
if [ -n "${WSL_DISTRO_NAME:-}" ]; then
    virtualisation="wsl:${WSL_DISTRO_NAME}"
elif [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
    virtualisation="container:$(hostname)"
elif command -v systemd-detect-virt >/dev/null 2>&1; then
    virtualisation="$(systemd-detect-virt || echo none)"
else
    virtualisation="unknown"
fi

cloud_runner="${GITHUB_RUN_ID:-${CI_JOB_ID:-null}}"
administrator="$(hash_of "${SALT}:$(id -un)@${virtualisation}")"
environment_id="$(hash_of "${SALT}:${WORKTREE}:${CONTAINERS_STORAGE_ROOT:-default}")"

tool_version() {
    local tool="$1"
    if command -v "$tool" >/dev/null 2>&1; then
        "$tool" --version 2>/dev/null | head -1 | tr -d '"' || echo "present"
    else
        echo "absent"
    fi
}

commit="$(git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || echo unknown)"
base_image="${BUNNY_BASE_IMAGE:-unset}"

cat <<JSON
{
  "builderId": "${BUILDER_ID}",
  "machineId": "${machine_id}",
  "virtualisationInstance": "${virtualisation}",
  "cloudRunner": $( [ "$cloud_runner" = "null" ] && echo null || echo "\"${cloud_runner}\"" ),
  "administrator": "${administrator}",
  "environmentId": "${environment_id}",
  "operatingSystem": "$(. /etc/os-release 2>/dev/null && echo "${ID}-${VERSION_ID}" || echo unknown) $(uname -r)",
  "toolchain": {
    "podman": "$(tool_version podman)",
    "image-builder": "$(tool_version image-builder)",
    "syft": "$(syft version 2>/dev/null | awk '/^Version:/{print $2}' || echo absent)",
    "grype": "$(grype version 2>/dev/null | awk '/^Version:/{print $2}' || echo absent)",
    "python3": "$(tool_version python3)"
  },
  "workspace": "${WORKTREE}",
  "sourceCommit": "${commit}",
  "baseImageDigest": "${base_image}"
}
JSON
