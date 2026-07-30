#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Publish a retained build input to controlled content-addressed storage.
#
# The retained base, the builder image and the package snapshot currently exist
# on one machine. That is the defect this whole remediation is about, wearing a
# different hat: a second builder cannot reproduce a build from inputs it cannot
# reach, and "the operator will copy them over" is not a supply chain.
#
# Digests are the pin. The human-readable tag is a convenience reference and
# nothing reads it during a qualification build — a tag is a promise about a
# channel, not about content, and this project has already been bitten by a
# `:44` that moved.
#
# The push is refused unless the pushed manifest digest equals the retained one.
# A registry that re-encodes an image gives it a new digest, and a lock that
# recorded the new one would be recording something other than what was
# verified.
#
# Usage:
#   publish-retained-inputs.sh --kind base|builder|snapshot
#                              [--registry ghcr.io/comradeart] [--dry-run]
#
# There is no --retention-root. Each lock records the absolute location of what
# it pins, and an override would let a caller publish something other than what
# was verified. An earlier version accepted the flag and ignored it, which is
# worse than not having it.

set -euo pipefail

kind=""
registry="${BUNNY_REGISTRY:-ghcr.io/comradeart}"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kind) kind="${2:?}"; shift 2 ;;
    --registry) registry="${2:?}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "${kind}" in
  base|builder|snapshot) ;;
  *) echo "--kind must be base, builder or snapshot" >&2; exit 2 ;;
esac

for command in skopeo python3 podman curl; do
  command -v "${command}" >/dev/null 2>&1 || { echo "missing required command: ${command}" >&2; exit 3; }
done

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"

# ---------------------------------------------------------------- credentials
#
# Checked before anything is read or packed, so a missing scope costs a message
# rather than a 514 MB pack that cannot be pushed. The token itself is never
# printed: `gh auth status` masks it, and nothing here echoes the value.
# The token is read from the environment, and its scopes from the API rather
# than from a CLI.
#
# `gh` is not necessarily on this machine: the build runs on a Fedora builder and
# the credential may live in a GitHub CLI keyring on another OS entirely. Asking
# GitHub what the token carries works wherever the token does, and the answer
# comes from the service that will enforce it rather than from a client's
# summary of what it believes it has.
token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "${token}" ]] && command -v gh >/dev/null 2>&1; then
  token="$(gh auth token 2>/dev/null || true)"
fi
if [[ -z "${token}" ]]; then
  echo "BLOCKED: no GitHub token. Set GITHUB_TOKEN, or run where gh is authenticated." >&2
  exit 2
fi

headers="$(mktemp)"
trap 'rm -f "${headers}"' EXIT
identity="$(curl -sS -D "${headers}" -H "Authorization: Bearer ${token}" \
  -H "Accept: application/vnd.github+json" https://api.github.com/user)"
scopes="$(sed -n 's/^[Xx]-[Oo][Aa]uth-[Ss]copes: //p' "${headers}" | tr -d '\r')"

# Write is checked by name; read is checked by using it.
#
# GitHub's scope hierarchy grants read with write, so a token that can publish
# carries only `write:packages` and `read:packages` never appears beside it. An
# earlier version of this check required both strings and would have refused a
# token holding the access it was checking for, which is worse than no check.
case ",${scopes//, /,}," in
  *",write:packages,"*) ;;
  *)
    echo "BLOCKED: the GitHub token does not carry write:packages." >&2
    echo "  present: ${scopes:-none}" >&2
    echo >&2
    echo "The repository owner must grant it:" >&2
    echo >&2
    echo "    gh auth refresh -h github.com -s write:packages,read:packages" >&2
    echo >&2
    echo "Until then the retained inputs exist on one machine, independent" >&2
    echo "availability is not established, and the reproducibility gate stays blocked." >&2
    exit 2
    ;;
esac

if ! curl -sSf -o /dev/null -H "Authorization: Bearer ${token}" \
     "https://api.github.com/user/packages?package_type=container"; then
  echo "BLOCKED: the token carries write:packages and cannot read the packages API." >&2
  echo "  present: ${scopes}" >&2
  echo >&2
  echo "Publishing without being able to read back means the digest check after the" >&2
  echo "push cannot run, and an unverified push is not a publication." >&2
  exit 2
fi

account="$(printf '%s' "${identity}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("login",""))')"
[[ -n "${account}" ]] || { echo "BLOCKED: the token does not resolve to an account" >&2; exit 2; }

# ---------------------------------------------------------------- what to push
case "${kind}" in
  base)
    lock="build/inputs/base-image-lock.json"
    digest_field="retainedDigest"
    location_field="retainedLocation"
    repository="bunny-os-base"
    ;;
  builder)
    lock="build/inputs/builder-image-lock.json"
    digest_field="builderDigest"
    location_field=""
    repository="bunny-os-builder"
    ;;
  snapshot)
    lock="build/inputs/package-snapshot-lock.json"
    digest_field="manifestDigest"
    location_field="retainedLocation"
    repository="bunny-os-package-snapshot"
    ;;
esac

[[ -f "${lock}" ]] || { echo "BLOCKED: ${lock} is absent" >&2; exit 2; }

read_field() {
  python3 -c "
import json, sys
print(json.load(open(sys.argv[1])).get(sys.argv[2], ''))
" "${lock}" "$1"
}

locked_digest="$(read_field "${digest_field}")"
[[ -n "${locked_digest}" ]] || { echo "BLOCKED: ${lock} has no ${digest_field}" >&2; exit 2; }

if [[ "${kind}" == "builder" ]]; then
  reference="$(read_field builderReference)"
  layout="${reference%@sha256:*}"
  layout_tag="builder"
  human_tag="$(read_field sourceCommit)"
  human_tag="${human_tag:0:12}"
else
  layout="$(read_field "${location_field}")"
  layout_tag="retained"
  if [[ "${kind}" == "snapshot" ]]; then
    human_tag="$(read_field snapshotId)"
    layout_tag=""
  else
    human_tag="fedora-bootc-44-${locked_digest#sha256:}"
    human_tag="${human_tag:0:32}"
  fi
fi

destination="${registry}/${repository}"
echo "publishing ${kind}"
echo "  lock       ${lock}"
echo "  digest     ${locked_digest}"
echo "  source     ${layout}"
echo "  registry   ${destination}:${human_tag}"
echo

if [[ "${dry_run}" == "1" ]]; then
  echo "--dry-run: nothing was pushed"
  exit 0
fi

printf '%s' "${token}" \
  | skopeo login --username "${account}" --password-stdin ghcr.io >/dev/null
echo "authenticated to ghcr.io as ${account}"

pushed_digest=""

if [[ "${kind}" == "snapshot" ]]; then
  # The snapshot is 474 RPMs, its repodata, the Fedora keys that verify them and
  # the signed manifest — a directory, not an image. It is published as a
  # single-layer OCI image built FROM scratch rather than through a dedicated
  # artifact tool.
  #
  # ORAS is the obvious alternative and the brief names it as one option. It is
  # not used because it would have to be added to the builder image, changing
  # the builder digest and therefore the pin every qualification build asserts,
  # to gain a media type nothing here reads. skopeo and podman are already
  # pinned, already classified output-affecting, and produce an artifact that is
  # content-addressed, pullable by digest and verifiable with the same tooling
  # as the other two inputs. If a future consumer needs the artifact media type,
  # that is a reviewed builder-image change rather than a side effect of a push.
  [[ -d "${layout}" ]] || { echo "BLOCKED: the snapshot at ${layout} is absent" >&2; exit 2; }
  scratch="$(mktemp -d)"
  trap 'rm -rf "${scratch}"' EXIT
  containerfile="${scratch}/Containerfile"
  cat > "${containerfile}" <<'DOCKERFILE'
FROM scratch
COPY snapshot /snapshot
LABEL art.comrade.bunny-os.input="package-snapshot" \
      art.comrade.bunny-os.contract="1.0.0" \
      org.opencontainers.image.title="Bunny OS retained package snapshot"
DOCKERFILE
  # A copy rather than a mount: podman build needs the content inside its
  # context, and the snapshot must not be modified by being published.
  cp -a "${layout}" "${scratch}/snapshot"
  snapshot_tag="localhost/bunny-os-package-snapshot:${human_tag}"
  epoch="$(python3 -c '
import json
print(json.load(open("build/inputs/reproducibility-lock.json"))["sourceDateEpoch"])
')"
  podman build --file "${containerfile}" --tag "${snapshot_tag}" \
    --timestamp "${epoch}" "${scratch}"
  skopeo copy --preserve-digests "containers-storage:${snapshot_tag}" \
    "docker://${destination}:${human_tag}"
  pushed_digest="$(skopeo inspect --no-tags --raw "docker://${destination}:${human_tag}" |
    python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  # The snapshot's own manifestDigest describes the signed snapshot manifest,
  # not the OCI wrapper around it, so the two are recorded separately rather
  # than compared. Conflating them would either fail always or check nothing.
  echo "  snapshot manifest digest (signed content) ${locked_digest}"
  echo "  OCI wrapper digest (registry)             ${pushed_digest}"
else
  [[ -d "${layout}" ]] || { echo "BLOCKED: the OCI layout at ${layout} is absent" >&2; exit 2; }
  skopeo copy --preserve-digests "oci:${layout}:${layout_tag}" \
    "docker://${destination}:${human_tag}"
  pushed_digest="$(skopeo inspect --no-tags --raw "docker://${destination}:${human_tag}" |
    python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if [[ "${pushed_digest}" != "${locked_digest}" ]]; then
    echo "BLOCKED: the registry returned a different manifest digest:" >&2
    echo "  retained ${locked_digest}" >&2
    echo "  pushed   ${pushed_digest}" >&2
    echo >&2
    echo "A registry that re-encodes an image gives it a new identity. Recording the new" >&2
    echo "digest would record something other than what was verified." >&2
    exit 5
  fi
  echo "  pushed digest matches the lock: ${pushed_digest}"
fi

python3 scripts/supply-chain/write-publication-lock.py \
  --kind "${kind}" \
  --registry "${destination}" \
  --tag "${human_tag}" \
  --pushed-digest "${pushed_digest}" \
  --locked-digest "${locked_digest}" \
  --source-layout "${layout}" \
  --publisher "${account}" \
  --lock build/inputs/input-publication-lock.json

echo
echo "published ${destination}@${pushed_digest}"
echo "Qualification builds must use the digest. The tag ${human_tag} is a convenience"
echo "reference and nothing reads it during a build."
