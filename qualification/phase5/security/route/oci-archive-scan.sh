#!/usr/bin/bash
# The scan that was called blocked, run.
#
# The first attempt at `grype podman:` failed with "no space left on device"
# and the diagnosis written at the time was wrong twice over:
#
#   * the failure was against /tmp, which is tmpfs -- RAM, 7.8 GB -- not a disk;
#   * "the host volume has 8.6 GB free" conflated Windows C: with the ext4
#     volume this builder actually writes to. Measured since: 20 GiB written
#     inside WSL grew the vhdx by zero bytes and moved C: free space by zero
#     bytes, because the vhdx is already 731.5 GB on disk with ~380 GB of that
#     allocated and free.
#
# So: point TMPDIR at real disk, export the archive, and scan it by the same
# route build/scripts/security-scan.sh uses. That is the only route that can
# be compared to Phase 4's number without an argument about granularity.
set -uo pipefail
OUT=/home/bunny/p5-evidence/security-archive
IMAGE="${1:-localhost/bunny-os-beta:e906a48793d7}"
WORK=/home/bunny/p5-work
mkdir -p "${OUT}" "${WORK}"
export TMPDIR="${WORK}/tmp"
mkdir -p "${TMPDIR}"

command -v grype >/dev/null || { echo "grype is required" >&2; exit 3; }

echo "== where /tmp and TMPDIR live =="
findmnt -no FSTYPE,SIZE,TARGET /tmp || true
echo "TMPDIR=${TMPDIR} on $(findmnt -no FSTYPE -T "${TMPDIR}")"

echo
echo "== free space before =="
df -h / | tail -1

archive="${WORK}/candidate.oci.tar"
echo
echo "== exporting the candidate as an oci-archive =="
if [[ -f "${archive}" ]]; then
  echo "  already present: $(du -h "${archive}" | cut -f1)"
else
  podman save --format oci-archive -o "${archive}" "${IMAGE}"
  echo "  save exit=$?"
fi
ls -la "${archive}"
sha256sum "${archive}" | tee "${OUT}/archive.sha256"

echo
echo "== free space after the export =="
df -h / | tail -1

echo
echo "== grype oci-archive, --only-fixed (the release gate's own route) =="
grype "oci-archive:${archive}" --only-fixed --output json \
  >"${OUT}/archive-fixed.json" 2>"${OUT}/archive-fixed.err"
echo "exit=$?"
tail -3 "${OUT}/archive-fixed.err"

echo
echo "== grype oci-archive, unfiltered =="
grype "oci-archive:${archive}" --output json \
  >"${OUT}/archive-all.json" 2>"${OUT}/archive-all.err"
echo "exit=$?"
tail -3 "${OUT}/archive-all.err"

python3 /home/bunny/p5-ops/scan-summary.py \
  "${OUT}/archive-fixed.json" "${OUT}/archive-all.json"

echo
echo "== free space after =="
df -h / | tail -1
echo "OCI-ARCHIVE-SCAN-DONE"
