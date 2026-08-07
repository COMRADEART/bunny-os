#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

profile="${1:-}"
case "${profile}" in
  developer|recovery|shell|shell-test|beta) ;;
  *) echo "usage: $0 developer|recovery|shell|shell-test|beta" >&2; exit 2 ;;
esac

# One of the two channels in docs/PUBLIC_ALPHA_SCOPE.md §40. It is a label on
# the build, not a profile: the Public Alpha ships the `beta` profile — the
# installed desktop payload — with the channel set to `alpha`, because the
# profile names a package set and the channel names a promise. Validated here
# rather than passed through, so a typo produces a refusal instead of an image
# labelled with a channel nothing defines.
release_channel="${BUNNY_RELEASE_CHANNEL:-development}"
case "${release_channel}" in
  development|alpha) ;;
  *) echo "BUNNY_RELEASE_CHANNEL must be 'development' or 'alpha', not '${release_channel}'" >&2; exit 2 ;;
esac

# BUNNY_ARCHIVE_ONLY=1 stops after the normalised OCI archive and skips the
# disk-image stage.
#
# This exists so a hosted CI runner can be a real second builder. The
# reproducibility comparison compares the OCI archive, its members, the SBOM and
# the package inventory; none of those come from image-builder, which is
# Fedora-only and unavailable on a hosted Ubuntu worker. Rather than pretend a
# hosted build is impossible, or ship a hosted build that silently produces
# fewer artifacts than it claims, the mode is named and the omission is
# explicit: an archive-only build produces no qcow2 or raw image and must never
# be recorded as a candidate build.
archive_only="${BUNNY_ARCHIVE_ONLY:-0}"

required_commands=(git podman python3)
if [[ "${archive_only}" != "1" ]]; then
  required_commands+=(image-builder)
fi
for command in "${required_commands[@]}"; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "missing required build command: ${command}" >&2
    exit 3
  fi
done

# Every podman and skopeo invocation goes through these, so a caller asking for
# an isolated container store gets one everywhere rather than for the build step
# and not the pull. Two builds of a repeatability pair that shared a store would
# be one build measured twice.
podman_store_args=()
skopeo_store_args=()
if [[ -n "${BUNNY_PODMAN_ROOT:-}" ]]; then
  : "${BUNNY_PODMAN_RUNROOT:=${BUNNY_PODMAN_ROOT}/run}"
  sudo mkdir -p "${BUNNY_PODMAN_ROOT}" "${BUNNY_PODMAN_RUNROOT}"
  podman_store_args=(--root "${BUNNY_PODMAN_ROOT}" --runroot "${BUNNY_PODMAN_RUNROOT}")
  # skopeo names the same two things differently, and only on the
  # containers-storage transport.
  skopeo_store_args=("[overlay@${BUNNY_PODMAN_ROOT}+${BUNNY_PODMAN_RUNROOT}]")
fi
# `sudo podman`, not `sudo command podman`.
#
# The first version used `command` to reach past a wrapper to the binary,
# which is unnecessary — `sudo` is the command word here and `podman` is one of
# its arguments, so nothing recurses — and it is not portable. `command` is a
# shell builtin, so `sudo command …` needs an executable of that name. Fedora
# ships /usr/sbin/command and Ubuntu does not, so this worked on the local
# builder and failed on the hosted one with:
#
#   sudo: command: command not found
#
# Found by the first hosted hermetic build, which is the kind of difference a
# second builder exists to surface.
#
# The wrapper does not shadow the binary's name. A function named `podman`
# reads as the binary at every call site while quietly rewriting each call,
# and ShellCheck flags the shape (SC2032/SC2033) because a name that means two
# things is exactly how a call escapes the wrapper unnoticed.
bunny_podman() { sudo podman "${podman_store_args[@]+"${podman_store_args[@]}"}" "$@"; }

repository_root="$(git rev-parse --show-toplevel)"
cd "${repository_root}"
source_commit="$(git rev-parse HEAD)"
source_epoch="$(git show -s --format=%ct HEAD)"
base_image="${BUNNY_BASE_IMAGE:-quay.io/fedora/fedora-bootc:44}"

# Hermetic mode: the base, the packages and the clock all come from recorded,
# verified inputs rather than from whatever the machine can reach.
#
# The epoch is taken from the lock rather than from `git show HEAD`. Two
# builders checking out the same commit derive the same value either way, but a
# builder that checked out something else would silently get a different epoch,
# and the mismatch would surface as an unexplained archive difference instead of
# as a wrong input.
hermetic="${BUNNY_HERMETIC_BUILD:-0}"
build_mounts=()
if [[ "${hermetic}" == "1" ]]; then
  for lock in base-image-lock builder-image-lock package-snapshot-lock reproducibility-lock; do
    [[ -f "build/inputs/${lock}.json" ]] || {
      echo "hermetic build requires build/inputs/${lock}.json" >&2
      exit 4
    }
  done
  python3 scripts/supplychain.py verify-input-locks || exit 4

  source_epoch="$(python3 -c '
import json
print(json.load(open("build/inputs/reproducibility-lock.json"))["sourceDateEpoch"])
')"
  # podman cannot use an OCI-layout path as a FROM reference, so the retained
  # base is pulled into local storage first and the pulled image's own manifest
  # digest is checked against the lock. The lock is what pins the base; the tag
  # below is only a handle, and a mismatch stops the build before it starts.
  retained_layout="$(python3 -c '
import json
lock = json.load(open("build/inputs/base-image-lock.json"))
print(lock["retainedLocation"])
')"
  retained_digest="$(python3 -c '
import json
print(json.load(open("build/inputs/base-image-lock.json"))["retainedDigest"])
')"
  base_tag="localhost/bunny-os-retained-base:${retained_digest#sha256:}"
  bunny_podman pull "oci:${retained_layout}:retained" >/dev/null
  pulled_id="$(bunny_podman pull "oci:${retained_layout}:retained" 2>/dev/null | tail -1)"
  bunny_podman tag "${pulled_id}" "${base_tag}"
  observed="$(sudo skopeo inspect --raw "containers-storage:${skopeo_store_args[0]-}${base_tag}" |
    python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if [[ "${observed}" != "${retained_digest}" ]]; then
    echo "the base pulled from retention does not carry the locked digest:" >&2
    echo "  locked   ${retained_digest}" >&2
    echo "  observed ${observed}" >&2
    exit 4
  fi
  base_image="${base_tag}"
  snapshot_root="$(python3 -c '
import json
print(json.load(open("build/inputs/package-snapshot-lock.json"))["retainedLocation"])
')"

  python3 scripts/supply-chain/verify-package-snapshot.py || exit 4

  # The frozen clock comes out of the pinned builder image, by digest.
  #
  # It used to come from `find /usr/lib64 /usr/lib`, so whichever libfaketime the
  # build host happened to carry entered the qualification path. That is not a
  # theoretical hazard: libfaketime's own semantics decide whether the clock
  # freezes or merely starts at the epoch and then runs, and the second of those
  # put fifty package headers on different seconds between two builds. A library
  # that can do that to the artifact is pinned like podman is, not discovered.
  #
  # BUNNY_FAKETIME_LIBRARY still says *where* the library is, for an environment
  # that has already extracted it. It does not say *what* it is: the checksum is
  # verified against the builder lock either way, so an override cannot smuggle a
  # different library past the pin.
  expected_faketime="$(python3 -c '
import json
lock = json.load(open("build/inputs/builder-image-lock.json"))
record = lock.get("faketimeLibrary") or {}
print(record.get("sha256", ""))
')"
  if [[ -z "${expected_faketime}" ]]; then
    echo "build/inputs/builder-image-lock.json records no faketimeLibrary checksum." >&2
    echo "Rebuild the builder image with scripts/supply-chain/build-builder-image.sh; a" >&2
    echo "hermetic build cannot pin a clock the lock does not describe." >&2
    exit 4
  fi

  faketime_library="${BUNNY_FAKETIME_LIBRARY:-}"
  faketime_scratch=""
  if [[ -z "${faketime_library}" ]]; then
    builder_reference="$(python3 -c '
import json
print(json.load(open("build/inputs/builder-image-lock.json"))["builderReference"])
')"
    builder_digest="$(python3 -c '
import json
print(json.load(open("build/inputs/builder-image-lock.json"))["builderDigest"])
')"
    builder_layout="${builder_reference%@sha256:*}"
    if [[ ! -d "${builder_layout}" ]]; then
      echo "the builder image layout ${builder_layout} is not present on this machine." >&2
      echo "Pull it from the controlled registry by digest, or rebuild it." >&2
      exit 4
    fi
    builder_tag="localhost/bunny-os-builder-pinned:${builder_digest#sha256:}"
    builder_id="$(bunny_podman pull "oci:${builder_layout}:builder" 2>/dev/null | tail -1)"
    bunny_podman tag "${builder_id}" "${builder_tag}"
    observed_builder="$(sudo skopeo inspect --raw "containers-storage:${skopeo_store_args[0]-}${builder_tag}" |
      python3 -c 'import hashlib,sys; print("sha256:"+hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
    if [[ "${observed_builder}" != "${builder_digest}" ]]; then
      echo "the builder image pulled from retention does not carry the locked digest:" >&2
      echo "  locked   ${builder_digest}" >&2
      echo "  observed ${observed_builder}" >&2
      exit 4
    fi
    faketime_scratch="$(mktemp -d)"
    trap '[[ -n "${faketime_scratch:-}" ]] && rm -rf "${faketime_scratch}" || true' EXIT
    bunny_podman run --rm --network=none --entrypoint /usr/bin/cp \
      --volume "${faketime_scratch}:/out:z" "${builder_tag}" \
      /usr/local/lib/bunny-faketime/libfaketime.so.1 /out/libfaketime.so.1
    sudo chown "$(id -u):$(id -g)" "${faketime_scratch}/libfaketime.so.1"
    faketime_library="${faketime_scratch}/libfaketime.so.1"
  fi

  if [[ ! -f "${faketime_library}" ]]; then
    echo "hermetic build requires libfaketime; without it the rpm database records" >&2
    echo "wall-clock install times and the build cannot reproduce. ${faketime_library}" >&2
    echo "does not exist." >&2
    exit 4
  fi
  observed_faketime="$(sha256sum "${faketime_library}" | awk '{print $1}')"
  if [[ "${observed_faketime}" != "${expected_faketime}" ]]; then
    echo "the libfaketime library does not match the builder lock:" >&2
    echo "  locked   ${expected_faketime}" >&2
    echo "  observed ${observed_faketime}  (${faketime_library})" >&2
    echo >&2
    echo "Two builders must freeze the clock with the same library. A different build of" >&2
    echo "libfaketime can freeze differently, and the artifact would differ for a reason" >&2
    echo "nothing in the evidence would name." >&2
    exit 4
  fi

  build_mounts=(
    --volume "${snapshot_root}:/snapshot:ro"
    --volume "${faketime_library}:/run/bunny-faketime.so:ro"
  )
  echo "hermetic build"
  echo "  base     ${base_image}"
  echo "  snapshot ${snapshot_root}"
  echo "  epoch    ${source_epoch}"
fi
if [[ "${BUNNY_RELEASE_BUILD:-0}" == "1" && ! "${base_image}" =~ @sha256:[a-f0-9]{64}$ ]]; then
  echo "release builds require BUNNY_BASE_IMAGE pinned with @sha256:<digest>" >&2
  exit 4
fi
if [[ "${BUNNY_RELEASE_BUILD:-0}" == "1" ]]; then
  [[ -n "${BUNNY_IMAGE_BUILDER_VERSION:-}" && -n "${BUNNY_PODMAN_VERSION:-}" ]] || {
    echo "release builds require exact BUNNY_IMAGE_BUILDER_VERSION and BUNNY_PODMAN_VERSION" >&2
    exit 4
  }
  python3 build/scripts/verify-toolchain.py \
    --image-builder "${BUNNY_IMAGE_BUILDER_VERSION}" \
    --podman "${BUNNY_PODMAN_VERSION}"
  [[ -f build/repositories/fedora-44-snapshot.repo ]] || {
    echo "release builds require reviewed build/repositories/fedora-44-snapshot.repo" >&2
    exit 4
  }
fi

tag="localhost/bunny-os-${profile}:${source_commit:0:12}"
output="${repository_root}/build/out/${profile}"
if [[ -d "${output}" && -n "$(find "${output}" -mindepth 1 -print -quit)" ]]; then
  echo "output directory is not empty: ${output}; archive it before a new evidence run" >&2
  exit 5
fi
mkdir -p "${output}"

hermetic_args=()
if [[ "${hermetic}" == "1" ]]; then
  expected_sqlite="$(python3 -c '
import json
record = json.load(open("build/inputs/builder-image-lock.json")).get("sqlite") or {}
print(record.get("libraryVersion", ""))
')"
  if [[ -z "${expected_sqlite}" ]]; then
    echo "build/inputs/builder-image-lock.json records no SQLite identity; rebuild the" >&2
    echo "builder image. The database finaliser refuses to run against an unpinned SQLite." >&2
    exit 4
  fi
  hermetic_args=(
    --build-arg "BUNNY_SNAPSHOT_ROOT=/snapshot"
    --build-arg "BUNNY_FAKETIME_LIBRARY=/run/bunny-faketime.so"
    --build-arg "BUNNY_EXPECT_SQLITE=${expected_sqlite}"
  )
fi

# Two builds of one commit must not share a layer.
#
# podman keys its build cache on the instruction and the context digest, and two
# fresh clones of one commit produce the same both. Without --no-cache the second
# build of a repeatability pair reuses the first build's layers wholesale and
# produces a byte-identical archive because it *is* the first archive — a
# comparison that can only ever pass, which is worse than one that fails.
#
# --root and --runroot, when the caller sets them, put each build in its own
# store as well. That is the stronger property and it costs a full base-image
# copy per build; --no-cache is the one that is always on, because it is the one
# that makes the comparison mean anything.
cache_args=(--no-cache)

# Clamp every layer's timestamps at commit, not just the ones a RUN step can
# reach.
#
# The in-container mtime pass cannot fix a COPY layer: `COPY build /tmp/bunny-os`
# writes the build context with the wall-clock time of the copy, a later step
# deletes /tmp/bunny-os, and the deletion does not remove the earlier layer's
# bytes. Measured on two builds — layer 65 of 80, 87 members, every one differing
# in mtime alone:
#
#   A  tmp/bunny-os/build/Containerfile   1785444473
#   B  tmp/bunny-os/build/Containerfile   1785444758
#
# --rewrite-timestamp clamps rather than sets: anything older than the epoch keeps
# its own mtime, which matters because file mtimes inside RPMs are packaging
# information and flattening them would discard a real difference in what was
# installed. --timestamp would set them all and is the wrong tool here.
timestamp_args=(--source-date-epoch "${source_epoch}" --rewrite-timestamp)

bunny_podman build \
  "${cache_args[@]}" \
  "${timestamp_args[@]}" \
  --file build/Containerfile \
  --tag "${tag}" \
  "${build_mounts[@]+"${build_mounts[@]}"}" \
  --build-arg "BASE_IMAGE=${base_image}" \
  --build-arg "BUNNY_PROFILE=${profile}" \
  --build-arg "BUNNY_OS_VERSION=0.1.0" \
  --build-arg "BUNNY_IMAGE_VERSION=0.1.0-${profile}.${source_commit:0:12}" \
  --build-arg "BUNNY_SOURCE_COMMIT=${source_commit}" \
  --build-arg "SOURCE_DATE_EPOCH=${source_epoch}" \
  --build-arg "BUNNY_RELEASE_BUILD=${BUNNY_RELEASE_BUILD:-0}" \
  --build-arg "BUNNY_RELEASE_CHANNEL=${release_channel}" \
  "${hermetic_args[@]+"${hermetic_args[@]}"}" \
  . 2>&1 | tee "${output}/oci-build.log"

bunny_podman image inspect "${tag}" | tee "${output}/oci-inspect.json" >/dev/null
bunny_podman save --format oci-archive --output "${output}/bunny-os.oci.tar" "${tag}"
sudo chown "$(id -u):$(id -g)" "${output}/bunny-os.oci.tar"

# Normalise the archive wrapper so the artifact digest is reproducible.
#
# Measured: two builds of one commit produced identical blobs, an identical
# index.json and identical file contents, but different archive digests,
# because podman save stamps tar entry mtimes with the wall-clock time of
# archive creation rather than honouring SOURCE_DATE_EPOCH. The image was
# already deterministic; only the wrapper was not. See
# REPRODUCIBLE_BUILD_REPORT.md.
bash "${repository_root}/build/scripts/normalise-oci-archive.sh" \
  "${output}/bunny-os.oci.tar" "${source_epoch}" "${output}/normalisation.json"
if [[ "${archive_only}" == "1" ]]; then
  printf 'BUNNY_ARCHIVE_ONLY=1: skipped image-builder; no qcow2 or raw image produced\n' \
    | tee "${output}/image-builder.log"
else
  image_types=(qcow2)
  if [[ "${profile}" == "beta" ]]; then
    image_types=(qcow2 raw)
  fi
  (
    cd "${output}"
    for image_type in "${image_types[@]}"; do
      sudo image-builder build --bootc-ref "${tag}" --bootc-default-fs ext4 "${image_type}"
    done
  ) 2>&1 | tee "${output}/image-builder.log"
fi
sudo chown -R "$(id -u):$(id -g)" "${output}"

provenance_arguments=(
  --profile "${profile}"
  --output "${output}"
  --source-commit "${source_commit}"
  --source-date-epoch "${source_epoch}"
  --base-image "${base_image}"
  --image-reference "${tag}"
)
if [[ "${archive_only}" == "1" ]]; then
  provenance_arguments+=(--archive-only)
fi
python3 build/scripts/write-build-provenance.py "${provenance_arguments[@]}"
