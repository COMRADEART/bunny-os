#!/usr/bin/env bash
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
# Usage: normalise-oci-archive.sh <archive.tar> <source-date-epoch>

set -euo pipefail

archive="${1:?archive path is required}"
epoch="${2:?SOURCE_DATE_EPOCH is required}"

[[ -f "${archive}" ]] || { echo "archive not found: ${archive}" >&2; exit 2; }
[[ "${epoch}" =~ ^[0-9]+$ ]] || { echo "SOURCE_DATE_EPOCH must be an integer: ${epoch}" >&2; exit 2; }

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

printf 'normalised %s (mtime pinned to %s)\n' "$(basename "${archive}")" "${epoch}"
