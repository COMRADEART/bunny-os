#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Rewrite an OCI archive so its digest depends only on its contents.
#
# podman save stamps tar entry mtimes with the wall-clock time of archive
# creation, so two builds of the same commit produce archives whose contents
# are byte-identical but whose digests differ. A verifier comparing checksums
# between builders would correctly reject them.
#
# Everything that can vary between runs without the contents changing is
# pinned: entry order, mtimes, ownership, and the pax headers that carry
# atime/ctime. The blobs themselves are already content-addressed and already
# reproducible, so nothing inside is touched.
#
# Both digests are recorded, and that is the point of the manifest. The
# normalisation replaces the archive in place, so without a record the raw
# digest — the one podman actually produced — is gone, and a comparison can only
# ever see the normalised form. The reproducibility evaluation distinguishes
# those two cases: a raw difference that survives normalisation is semantic, and
# one that does not is a packing artefact that has to be explained rather than
# silently absorbed. It cannot make that distinction against a number nobody
# wrote down.
#
# Usage: normalise-oci-archive.sh <archive.tar> <source-date-epoch> [manifest.json]

set -euo pipefail

archive="${1:?archive path is required}"
epoch="${2:?SOURCE_DATE_EPOCH is required}"
manifest="${3:-$(dirname "${archive}")/normalisation.json}"

[[ -f "${archive}" ]] || { echo "archive not found: ${archive}" >&2; exit 2; }
[[ "${epoch}" =~ ^[0-9]+$ ]] || { echo "SOURCE_DATE_EPOCH must be an integer: ${epoch}" >&2; exit 2; }

raw_digest="$(sha256sum "${archive}" | awk '{print $1}')"

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

tar -xf "${archive}" -C "${workdir}"

# Name the top-level entries explicitly rather than archiving ".".
#
# Archiving "." emits a leading "./" on every entry, and syft rejects that:
# "potential path traversal attack with entry: ./". podman save does not emit
# it, so normalisation must not introduce it. Caught by running syft against a
# normalised archive rather than by assuming a repack is transparent.
mapfile -t entries < <(cd "${workdir}" && find . -mindepth 1 -maxdepth 1 -printf '%P\n' | sort)
[[ ${#entries[@]} -gt 0 ]] || { echo "archive unpacked to nothing: ${archive}" >&2; exit 3; }

# --sort=name fixes entry order; --mtime pins timestamps; --owner/--group with
# --numeric-owner removes the builder's identity; the pax option drops atime
# and ctime, which GNU tar would otherwise emit as varying extended headers.
tar --create \
    --file "${archive}.normalised" \
    --directory "${workdir}" \
    --sort=name \
    --format=posix \
    --pax-option='exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime' \
    --mtime="@${epoch}" \
    --owner=0 --group=0 --numeric-owner \
    "${entries[@]}"

mv "${archive}.normalised" "${archive}"

normalised_digest="$(sha256sum "${archive}" | awk '{print $1}')"

# Idempotence, checked by inspecting what normalisation pins rather than by
# doing it twice.
#
# Repacking a second time and comparing digests is the obvious check and it
# costs three extra copies of a 1.8 GB archive on disk. Reading the tar headers
# answers the same question — a second pass can only change the archive if some
# property is not yet at its pinned value — and it answers it more usefully,
# because it names the property and the entry rather than reporting two
# different digests.
python3 - "${archive}" "${epoch}" <<'PYTHON'
import sys
import tarfile

archive, epoch = sys.argv[1], int(sys.argv[2])
problems = []
names = []
with tarfile.open(archive, "r:") as handle:
    for member in handle:
        names.append(member.name)
        if member.mtime != epoch:
            problems.append(f"{member.name}: mtime {member.mtime} is not the epoch {epoch}")
        if member.uid or member.gid:
            problems.append(f"{member.name}: owned by {member.uid}:{member.gid}, not 0:0")
        if member.uname or member.gname:
            problems.append(f"{member.name}: carries owner names {member.uname!r}/{member.gname!r}")
        for key in ("atime", "ctime"):
            if key in (member.pax_headers or {}):
                problems.append(f"{member.name}: retains a pax {key} header")
        if len(problems) > 20:
            break

if names != sorted(names):
    first = next(
        (a for a, b in zip(names, sorted(names)) if a != b), "<unknown>"
    )
    problems.append(f"entries are not in sorted order; first out of order: {first}")

if problems:
    print(
        "BLOCKED: the normalised archive still carries properties normalisation pins, so a\n"
        "second pass would change it and the digest a verifier sees would depend on how many\n"
        "times normalisation ran:",
        file=sys.stderr,
    )
    for problem in problems[:20]:
        print(f"  {problem}", file=sys.stderr)
    raise SystemExit(4)
PYTHON

mkdir -p "$(dirname "${manifest}")"
cat > "${manifest}" <<JSON
{
  "schemaVersion": 1,
  "archive": "$(basename "${archive}")",
  "sourceDateEpoch": ${epoch},
  "rawDigest": "${raw_digest}",
  "normalisedDigest": "${normalised_digest}",
  "idempotent": true,
  "changed": $([[ "${raw_digest}" == "${normalised_digest}" ]] && echo false || echo true),
  "normalisedProperties": [
    "entry order (--sort=name)",
    "entry mtimes (--mtime=@${epoch})",
    "entry ownership (--owner=0 --group=0 --numeric-owner)",
    "pax atime and ctime extended headers (deleted)"
  ],
  "notNormalised": [
    "blob contents",
    "index.json",
    "the OCI manifest and config",
    "SQLite databases",
    "package-manager state",
    "machine identity",
    "product content"
  ],
  "note": "Only the archive wrapper is rewritten. Nothing inside is touched, which is what makes a surviving difference a difference in the image rather than in how it was packed."
}
JSON

printf 'normalised %s (mtime pinned to %s)\n' "$(basename "${archive}")" "${epoch}"
printf '  raw        %s\n' "${raw_digest}"
printf '  normalised %s\n' "${normalised_digest}"
printf '  wrote %s\n' "${manifest}"
