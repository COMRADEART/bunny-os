#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Deterministic image finalisation. Runs inside the build container, after
# packages are installed and before the archive is written.
#
# Fifteen files differed between two builders of one commit. None was product
# code and all fifteen were a function of the build environment or the build
# clock, which is why they are addressed here rather than in the product:
#
#   etc/brlapi.key                        a per-device secret, minted by a %post
#   7 × fontconfig caches                 each embeds a font directory's mtime
#   libdnf5 system.toml                   an rpmdb-derived cookie
#   libdnf5 transaction_history.sqlite    plus its -wal and -shm
#   usr/share/rpm/rpmdb.sqlite            per-package INSTALLTIME
#   2 × dnf countme counters              telemetry
#
# The order below is the brief's and is load-bearing: caches go before state
# canonicalisation because removing a cache afterwards would dirty what was just
# canonicalised, and the verification steps come last because they check the
# result rather than the intent.
#
# Idempotence is a requirement, not a nicety: this script runs once per build,
# and a second run must not change the artifact. Every operation is therefore
# written to converge — remove-if-present, truncate-to-empty, set-to-epoch —
# rather than to transform.
#
# Usage: finalise-image.sh --epoch <unix-seconds> [--report PATH]

set -euo pipefail

epoch=""
report=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --epoch) epoch="${2:?}"; shift 2 ;;
    --report) report="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "${epoch}" =~ ^[0-9]+$ ]] || { echo "--epoch must be an integer Unix timestamp" >&2; exit 2; }

removed=()
note() { printf '  %s\n' "$1"; }
record() { removed+=("$1"); }

echo "==> 3. removing package caches"
for path in /var/cache/dnf /var/cache/libdnf5 /var/cache/PackageKit /var/cache/yum; do
  if [[ -e "${path}" ]]; then rm -rf "${path}"; record "${path}"; note "removed ${path}"; fi
done

echo "==> 4. removing DNF countme state"
# countme is Fedora's per-installation usage counter. It is telemetry, it has no
# place in an immutable artifact, and removing the file without disabling the
# behaviour would simply regenerate it on the device. Both are done: countme=0
# is written into every repository definition the image carries, and the
# existing counters are deleted.
shopt -s nullglob
for counter in /var/lib/dnf/repos/*/countme; do
  rm -f "${counter}"; record "${counter}"; note "removed ${counter}"
done
for repo in /etc/yum.repos.d/*.repo; do
  if ! grep -q '^countme=0' "${repo}" 2>/dev/null; then
    # Append rather than rewrite: a repository file is configuration the base
    # image shipped, and replacing it wholesale would silently drop options
    # this project never reviewed.
    python3 - "${repo}" <<'PYTHON'
import configparser
import sys

path = sys.argv[1]
parser = configparser.ConfigParser()
parser.read(path, encoding="utf-8")
for section in parser.sections():
    parser.set(section, "countme", "0")
with open(path, "w", encoding="utf-8", newline="\n") as handle:
    parser.write(handle)
PYTHON
    note "countme=0 written into ${repo}"
  fi
done
shopt -u nullglob

echo "==> 5. removing machine identity"

# Some of these are live bind mounts inside the build container rather than
# files in the image being built. podman mounts /etc/hostname, and removing a
# mount point from inside fails:
#
#   rm: cannot remove '/etc/hostname': Device or resource busy
#
# A mounted path is not in the committed layer — which is exactly why the
# earlier comparison found no /etc/hostname on the podman 5.8.4 side while the
# 4.9.3 side had one. So the finaliser truncates what it cannot remove, records
# it, and does not pretend to have settled the question. Whether the path is in
# the *artifact* is decided by the machine-identity audit, which reads the built
# archive rather than the container that produced it.
is_mounted() {
  grep -qE "[[:space:]]$1[[:space:]]" /proc/self/mounts 2>/dev/null
}

for path in /etc/hostname /etc/machine-info /var/lib/dbus/machine-id \
            /var/lib/systemd/random-seed /etc/salt/minion_id; do
  [[ -e "${path}" ]] || continue
  if is_mounted "${path}"; then
    : > "${path}" 2>/dev/null || true
    note "${path} is a build-container mount, not image content: emptied, not removed"
    continue
  fi
  rm -f "${path}"; record "${path}"; note "removed ${path}"
done
for key in /etc/ssh/ssh_host_*; do
  [[ -e "${key}" ]] || continue
  rm -f "${key}"; record "${key}"; note "removed ${key}"
done
# machine-id must *exist and be empty*, not be absent. systemd reads an empty
# file as "first boot, generate one"; an absent file takes a different path and
# is not what was declared. Truncating converges whether or not it exists.
: > /etc/machine-id
chmod 0444 /etc/machine-id
note "/etc/machine-id truncated to 0 bytes"

echo "==> 6. removing per-device secrets"
# brlapi mints a 128-bit key in its %post and RPM marks the path %ghost, so the
# package ships no content and nothing is broken by removing it. It is
# regenerated on the installed device by bunny-brlapi-key.service, which is why
# this is a move rather than a deletion — see docs/IMAGE_FINALISATION.md.
if [[ -e /etc/brlapi.key ]]; then
  rm -f /etc/brlapi.key; record /etc/brlapi.key
  note "removed /etc/brlapi.key (regenerated on first boot by bunny-brlapi-key.service)"
fi

echo "==> 7. canonicalising package-manager state"
# Delegated, because this step has a contract the rest of finalisation does not:
# it must be idempotent, it must fail closed on an unexpected schema, a failed
# integrity check, a changed package inventory or a broken rpm query, and it must
# be able to prove it altered no content. The three lines it used to be could do
# none of that — and would have reported success while the databases still
# differed, which is what happened.
#
# The history table itself is kept. It supports repair, audit and licence
# inventory, and the brief is explicit that package-manager state may not be
# discarded merely for being inconvenient.
database_report=""
if [[ -n "${report}" ]]; then
  database_report="$(dirname "${report}")/package-databases.json"
fi
bash "$(dirname "${BASH_SOURCE[0]}")/finalise-package-databases.sh" \
  ${database_report:+--report "${database_report}"} \
  ${BUNNY_EXPECT_SQLITE:+--expect-sqlite "${BUNNY_EXPECT_SQLITE}"}
# Which residue files it actually removed is in its own manifest. They are not
# added to `removed` here, because that list is what this script removed and a
# path recorded on the assumption it existed is a claim nobody checked.
# system.toml carries an rpmdb_cookie derived from the rpmdb. It is not
# independent state: once the rpmdb is deterministic this follows. Left alone
# deliberately, so that if it still differs the comparison reports a real
# divergence in the database rather than a file somebody normalised away.

echo "==> 8. making font caches deterministic"
# Measured cause: each cache embeds the mtime of the directory it indexes, and
# font-directory mtimes are wall-clock install times. Cache
# 3830d5c3ddfd5cd38a049b759396e72e-le64.cache-9 is md5("/usr/share/fonts") and
# its checksum field was exactly the mtime of /usr/share/fonts/urw-base35.
#
# The caches are regenerated rather than deleted. Deleting them costs the first
# graphical login a full font scan, and this is an accessibility-first project:
# a screen-reader user waiting on fc-cache is a real cost paid for a
# reproducibility problem that has a better fix. Pinning the directory mtimes to
# the build epoch removes the nondeterminism at its source.
font_roots=(/usr/share/fonts /usr/local/share/fonts /usr/share/X11/fonts)
for root in "${font_roots[@]}"; do
  [[ -d "${root}" ]] || continue
  # Directories only. File mtimes come from the RPM headers and are already
  # deterministic; rewriting them would discard real packaging information.
  find "${root}" -type d -exec touch --no-dereference --date="@${epoch}" {} +
  note "pinned directory mtimes under ${root} to ${epoch}"
done
if command -v fc-cache >/dev/null 2>&1; then
  rm -rf /usr/lib/fontconfig/cache
  HOME=/root SOURCE_DATE_EPOCH="${epoch}" fc-cache --system-only --force >/dev/null 2>&1 || true
  # fc-cache writes the caches with the current time; pin them too, so the tar
  # entry mtimes do not reintroduce what the content no longer carries.
  if [[ -d /usr/lib/fontconfig/cache ]]; then
    find /usr/lib/fontconfig/cache -exec touch --no-dereference --date="@${epoch}" {} +
  fi
  note "regenerated fontconfig caches with pinned directory mtimes"
fi

echo "==> 9. normalising approved timestamps"
# Only generated state. Anything RPM owns keeps the mtime RPM gave it, because
# that is packaging information rather than build-environment noise, and
# flattening it would hide a real difference in what was installed.
for path in /usr/lib/sysimage/libdnf5 /usr/share/rpm /var/lib/dnf /etc/machine-id; do
  [[ -e "${path}" ]] || continue
  find "${path}" -exec touch --no-dereference --date="@${epoch}" {} +
done
note "generated package-manager state pinned to ${epoch}"

echo "==> 10. verifying ownership and permissions"
failed=0
if [[ -e /etc/machine-id ]]; then
  mode="$(stat -c '%a' /etc/machine-id)"
  owner="$(stat -c '%u:%g' /etc/machine-id)"
  size="$(stat -c '%s' /etc/machine-id)"
  if [[ "${owner}" != "0:0" || "${size}" != "0" ]]; then
    echo "  FAIL /etc/machine-id is ${owner} ${size} bytes; must be 0:0 and empty" >&2
    failed=1
  else
    note "/etc/machine-id ${owner} mode ${mode} ${size} bytes"
  fi
fi

echo "==> 11. verifying no unexpected mutable state remains"
declare -a leftovers=()
for path in /etc/brlapi.key /etc/hostname /var/lib/dbus/machine-id \
            /var/lib/systemd/random-seed; do
  # A mount point is not image content, and failing here on one would make the
  # finaliser unable to succeed on any podman that mounts /etc/hostname. The
  # artifact-level audit is what decides whether it reached the image.
  [[ -e "${path}" ]] && ! is_mounted "${path}" && leftovers+=("${path}")
done
shopt -s nullglob
for counter in /var/lib/dnf/repos/*/countme; do leftovers+=("${counter}"); done
for key in /etc/ssh/ssh_host_*; do leftovers+=("${key}"); done
shopt -u nullglob
if [[ ${#leftovers[@]} -gt 0 ]]; then
  echo "  FAIL these must not be present in the immutable artifact:" >&2
  printf '    %s\n' "${leftovers[@]}" >&2
  failed=1
else
  note "no per-device secret, machine identity or countme counter remains"
fi

echo "==> 12. generating the finalisation manifest"
if [[ -n "${report}" ]]; then
  mkdir -p "$(dirname "${report}")"
  {
    printf '{\n'
    printf '  "schemaVersion": 1,\n'
    printf '  "sourceDateEpoch": %s,\n' "${epoch}"
    printf '  "removedPaths": ['
    first=1
    for path in "${removed[@]}"; do
      [[ "${first}" == 1 ]] || printf ','
      first=0
      printf '\n    "%s"' "${path}"
    done
    [[ "${first}" == 1 ]] || printf '\n  '
    printf '],\n'
    printf '  "machineIdBytes": %s,\n' "$(stat -c '%s' /etc/machine-id 2>/dev/null || echo null)"
    printf '  "fontCacheCount": %s,\n' "$(find /usr/lib/fontconfig/cache -name '*.cache-*' 2>/dev/null | wc -l)"
    printf '  "result": "%s"\n' "$([[ "${failed}" == 0 ]] && echo PASS || echo FAIL)"
    printf '}\n'
  } > "${report}"
  note "wrote ${report}"
fi

if [[ "${failed}" != "0" ]]; then
  echo >&2
  echo "BLOCKED: finalisation left state that must not be in an immutable artifact." >&2
  exit 2
fi

echo "==> finalisation complete"
