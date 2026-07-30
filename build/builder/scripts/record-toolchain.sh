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
    # `crun --version` prints "crun version 1.28", so field 2 is the word
    # "version". Recorded as `version` in the first lock this produced, which is
    # a string that compares equal between two builders and says nothing about
    # either. write-builder-lock.py now refuses a version that is not
    # version-shaped, so the next such slip fails instead of being written down.
    crun)            crun --version 2>/dev/null | awk '/^crun version/ {print $3; exit}' ;;
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
    # "Version: 1.2.1 (Features: DeltaRPM LegacyWeakdeps )" — the last field is
    # a closing parenthesis.
    createrepo_c)    createrepo_c --version 2>/dev/null | sed -n 's/^Version: \([0-9][0-9.]*\).*/\1/p' | head -1 ;;
    policycoreutils) rpm -q --qf '%{VERSION}-%{RELEASE}' policycoreutils 2>/dev/null ;;
    libselinux-utils) rpm -q --qf '%{VERSION}-%{RELEASE}' libselinux-utils 2>/dev/null ;;
    # "3.51.2 2026-01-09 17:27:48 b270f833..." — the first field is the version
    # and the rest is the source-tree identifier of the exact amalgamation.
    sqlite3)         sqlite3 --version 2>/dev/null | awk '{print $1}' ;;
    # libfaketime has no --version and no binary of its own here; the library is
    # what matters, so the package's version is the recorded identity.
    libfaketime)     rpm -q --qf '%{VERSION}-%{RELEASE}' libfaketime 2>/dev/null ;;
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
    libfaketime)      echo libfaketime ;;
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
  sqlite3 libfaketime
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
    nevra="$(rpm -q --qf '%{NAME}-%|EPOCH?{%{EPOCH}}:{0}|:%{VERSION}-%{RELEASE}.%{ARCH}' "${package}" 2>/dev/null || true)"
  fi
  [[ "${first}" == "1" ]] || printf ',\n'
  first=0
  printf '    {"name": "%s", "version": "%s", "package": "%s", "nevra": "%s", "packageChecksum": "%s"}' \
    "${tool}" "${version}" "${package}" "${nevra}" "${checksum}"
done

printf '\n  ],\n'

# The SQLite implementation gets its own section rather than one version string.
# Two SQLite builds at the same upstream version can differ in page size,
# threading mode and which extensions are compiled in, and every one of those
# changes the on-disk file a package transaction leaves behind. The finaliser
# refuses to run against a SQLite that does not match what is recorded here, so
# what is recorded has to be enough to tell two of them apart.
printf '  "sqlite": '
if command -v sqlite3 >/dev/null 2>&1; then
  python3 - <<'PYTHON'
import json
import sqlite3
import subprocess

connection = sqlite3.connect(":memory:")
options = sorted(row[0] for row in connection.execute("PRAGMA compile_options"))
record = {
    "libraryVersion": sqlite3.sqlite_version,
    "cliVersion": subprocess.run(
        ["sqlite3", "--version"], capture_output=True, text=True, check=False
    ).stdout.split()[0],
    "sourceId": subprocess.run(
        ["sqlite3", ":memory:", "select sqlite_source_id();"],
        capture_output=True, text=True, check=False,
    ).stdout.strip(),
    "defaultPageSize": connection.execute("PRAGMA page_size").fetchone()[0],
    "threadSafe": next(
        (option.split("=")[1] for option in options if option.startswith("THREADSAFE=")),
        "unrecorded",
    ),
    "extensionsCompiledIn": [option for option in options if option.startswith("ENABLE_")],
    "compileOptions": options,
    "compileOptionsSha256": __import__("hashlib").sha256(
        "\n".join(options).encode("utf-8")
    ).hexdigest(),
}
connection.close()
print(json.dumps(record, indent=4, sort_keys=True))
PYTHON
else
  printf 'null'
fi

printf ',\n  "faketimeLibrary": '
if [[ -f /usr/local/lib/bunny-faketime/libfaketime.so.1 ]]; then
  printf '{"path": "/usr/local/lib/bunny-faketime/libfaketime.so.1", "sha256": "%s"}' \
    "$(sha256sum /usr/local/lib/bunny-faketime/libfaketime.so.1 | awk '{print $1}')"
else
  printf 'null'
fi

printf '\n}\n'
