#!/usr/bin/bash
# Record the identity of a release-candidate artifact: the commit it was built
# from, the pinned inputs, and the digest of every artifact produced.
#
#   rc-identity.sh <output-directory> [build-log]
#
# Two rules this script exists to keep, both learned by breaking them (see
# qualification/phase4/artifact/CORRECTION.md):
#
#   1. The tree's cleanliness is a fact about the *build*, not about the moment
#      the record is written. Measuring it afterwards produced "dirty: 1
#      file(s)" against a build whose own log said `dirty: 0`, which reads as
#      an artifact that matches no commit. So the build log's measurement is
#      preferred when one is given, and any measurement taken here is labelled
#      as what it is and *names* the files rather than counting them — a count
#      cannot be argued with, a name can be checked.
#
#   2. An image reference is printed once. Prefixing a literal repository name
#      onto `{{index .RepoTags 0}}`, which is already fully qualified, yields
#      `localhost/bunny-os-beta:localhost/bunny-os-beta:…` — not a reference
#      anything can pull.
set -uo pipefail
cd /root/bunny-os

out="${1:?usage: rc-identity.sh <output-directory> [build-log]}"
build_log="${2:-}"
mkdir -p "${out}"

commit=$(git rev-parse HEAD)
short=$(git rev-parse --short=12 HEAD)
image="localhost/bunny-os-beta:${short}"

{
  echo "# Release-candidate artifact identity"
  echo
  echo "Recorded $(date -u +%Y-%m-%dT%H:%M:%SZ) on the Fedora WSL builder."
  echo
  echo '## Commit'
  echo
  echo "    ${commit}"
  echo
  if [ -n "${build_log}" ] && [ -r "${build_log}" ]; then
    built_at=$(grep -m1 -E '^building at: ' "${build_log}" | sed 's/^building at: //')
    built_dirty=$(grep -m1 -E '^dirty: ' "${build_log}" | sed 's/^dirty: //')
    echo "Working tree at build time, from the build's own measurement taken"
    echo "immediately before the first image was produced (${build_log}):"
    echo
    echo "    building at: ${built_at:-<not recorded>}"
    echo "    dirty:       ${built_dirty:-<not recorded>}"
    if [ -n "${built_at}" ] && [ "${built_at}" != "${commit}" ]; then
      echo
      echo "    WARNING: the build log names ${built_at}, which is not HEAD."
      echo "    This record describes an artifact built from a different tree."
    fi
  else
    echo "No build log was given, so the tree is measured now — *after* the"
    echo "build, which is not the same question. Any file listed here may have"
    echo "been modified by the build rather than present during it."
    echo
    dirty=$(git status --porcelain)
    if [ -z "${dirty}" ]; then
      echo "    clean"
    else
      echo "${dirty}" | sed 's/^/    /'
    fi
  fi
  echo
  echo '## Base image (retained, digest-pinned)'
  echo
  python3 -c 'import json; l=json.load(open("build/inputs/base-image-lock.json")); print("    retainedDigest  ", l["retainedDigest"]); print("    retainedLocation", l["retainedLocation"])'
  echo
  echo '## Builder image'
  echo
  python3 -c 'import json; l=json.load(open("build/inputs/builder-image-lock.json")); print("    builderDigest   ", l.get("builderDigest","")); print("    sourceCommit    ", l.get("sourceCommit",""))'
  echo
  echo '## Package snapshot'
  echo
  python3 -c 'import json; l=json.load(open("build/inputs/package-snapshot-lock.json")); print("    snapshotId      ", l.get("snapshotId","")); print("    manifestDigest  ", l.get("manifestDigest",""))'
  echo
  echo '## Artifacts'
  echo
  echo '### Live installation medium (the ISO an alpha tester writes)'
  echo
  find build/out/live -name '*.iso' -exec sha256sum {} \; | sed 's/^/    /'
  echo
  echo '### Shell-test machine image (voice and desktop qualification)'
  echo
  find build/out/shell-test -name '*.qcow2' -exec sha256sum {} \; | sed 's/^/    /'
  echo
  echo '### Beta payload (the installed system'"'"'s container image)'
  echo
  # RepoTags[0] is already fully qualified. Printing it bare is the whole fix.
  podman inspect --format '    {{index .RepoTags 0}}' "${image}" 2>/dev/null | head -1
  skopeo inspect --no-tags --raw "containers-storage:${image}" 2>/dev/null |
    python3 -c 'import hashlib,sys; print("    manifest sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
  echo
  echo '## Package versions of the parts this phase changed'
  echo
  podman run --rm "${image}" \
    rpm -q gnome-shell mutter gnome-settings-daemon accountsservice gdm systemd 2>/dev/null | sed 's/^/    /'
  echo
  echo '## Test environment'
  echo
  echo "    builder      Fedora Linux 44 under WSL2, $(nproc) cores, $(free -g | awk '/^Mem:/{print $2}') GiB"
  echo "    guest        qemu-system-x86_64 -machine q35,accel=kvm -cpu max -smp 4 -m 6144"
  echo "    firmware     $(ls /usr/share/edk2/ovmf/OVMF_CODE.secboot.fd 2>/dev/null || echo 'OVMF (see vm-lib.sh)')"
  echo "    screen       1920x1080"
} > "${out}/ARTIFACT.md"
cat "${out}/ARTIFACT.md"
echo RC-IDENTITY-DONE
