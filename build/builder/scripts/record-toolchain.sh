#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Record every pinned tool's version and the checksum of the package that
# provides it, from inside the builder image.
#
# The version string alone is not enough. Two Fedora builds of one upstream
# version differ in their release field and can differ in their bytes, so the
# lock records the package's SHA-256 as well — which is what makes "the same
# builder image" a checkable claim rather than a version-string comparison.
#
# Written as a normalised JSON object on stdout. Nothing is inferred: a tool
# that is not installed is reported as absent, and the caller decides whether
# that is acceptable.

set -euo pipefail

emit_version() {
  local tool="$1"
  case "${tool}" in
    podman)          podman --version 2>/dev/null | awk '{print $3}' ;;
    buildah)         buildah --version 2>/dev/null | awk '{print $3}' ;;
    skopeo)          skopeo --version 2>/dev/null | awk '{print $3}' ;;
    conmon)          conmon --version 2>/dev/null | awk '/conmon version/ {print $3}' ;;
    crun)            crun --version 2>/dev/null | awk '/crun /{print $2; exit}' ;;
    runc)            runc --version 2>/dev/null | awk '/runc version/ {print $3}' ;;
    python3)         python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null ;;
    rpm)             rpm --version 2>/dev/null | awk '{print $NF}' ;;
    dnf5)            dnf5 --version 2>/dev/null | head -1 | awk '{print $NF}' ;;
    libdnf5)         rpm -q --qf '%{VERSION}-%{RELEASE}' libdnf5 2>/dev/null ;;
    tar)             tar --version 2>/dev/null | head -1 | awk '{print $NF}' ;;
    gzip)            gzip --version 2>/dev/null | head -1 | awk '{print $NF}' ;;
    zstd)            zstd --version 2>/dev/null | sed -n 's/.*v\([0-9.]*\).*/\1/p' ;;
    syft)            syft version -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' ;;
    grype)           grype version -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' ;;
    createrepo_c)    createrepo_c --version 2>/dev/null | awk '{print $NF}' ;;
    policycoreutils) rpm -q --qf '%{VERSION}-%{RELEASE}' policycoreutils 2>/dev/null ;;
    libselinux-utils) rpm -q --qf '%{VERSION}-%{RELEASE}' libselinux-utils 2>/dev/null ;;
    *) return 1 ;;
  esac
}

# Which RPM provides each tool. `rpm -qf` on the binary is the honest answer for
# packaged tools; syft and grype are release tarballs and are checksummed as
# files, because there is no package to ask.
providing_package() {
  local tool="$1"
  case "${tool}" in
    python3)          echo python3 ;;
    libdnf5)          echo libdnf5 ;;
    policycoreutils)  echo policycoreutils ;;
    libselinux-utils) echo libselinux-utils ;;
    syft|grype)       echo "" ;;
    *)
      local path
      path="$(command -v "${tool}" 2>/dev/null || true)"
      [[ -n "${path}" ]] || { echo ""; return 0; }
      rpm -qf --qf '%{NAME}' "${path}" 2>/dev/null || echo ""
      ;;
  esac
}

package_checksum() {
  local tool="$1" package
  case "${tool}" in
    syft|grype)
      sha256sum "$(command -v "${tool}")" 2>/dev/null | awk '{print $1}'
      return 0
      ;;
  esac
  package="$(providing_package "${tool}")"
  [[ -n "${package}" ]] || { echo ""; return 0; }
  # SIGPGP is the package's own signature; the NEVRA plus the header's
  # SHA1HEADER identify the exact build Fedora shipped.
  rpm -q --qf '%{SHA256HEADER}' "${package}" 2>/dev/null || echo ""
}

tools=(
  podman buildah skopeo conmon crun runc python3 rpm dnf5 libdnf5
  tar gzip zstd syft grype createrepo_c policycoreutils libselinux-utils
)

printf '{\n  "recordedAt": "%s",\n  "tools": [\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

first=1
for tool in "${tools[@]}"; do
  version="$(emit_version "${tool}" 2>/dev/null || true)"
  [[ -n "${version}" ]] || version="absent"
  checksum="$(package_checksum "${tool}" 2>/dev/null || true)"
  package="$(providing_package "${tool}" 2>/dev/null || true)"
  nevra=""
  if [[ -n "${package}" ]]; then
    nevra="$(rpm -q --qf '%{NAME}-%{EPOCH}:%{VERSION}-%{RELEASE}.%{ARCH}' "${package}" 2>/dev/null || true)"
  fi
  [[ "${first}" == "1" ]] || printf ',\n'
  first=0
  printf '    {"name": "%s", "version": "%s", "package": "%s", "nevra": "%s", "packageChecksum": "%s"}' \
    "${tool}" "${version}" "${package}" "${nevra}" "${checksum}"
done

printf '\n  ]\n}\n'
