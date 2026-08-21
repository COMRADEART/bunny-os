#!/usr/bin/bash
# Scan the candidate without expanding it.
#
# The first attempt used `grype podman:...`, which hands the image to
# stereoscope, which writes every layer out as a tarball into /tmp and needs
# tens of gigabytes. It failed with "no space left on device" against a 7.8 GB
# tmpfs, and the host volume has 8.6 GB free, so a larger TMPDIR is not the fix.
#
# `podman create` + `podman mount` assembles the image's overlay in place and
# hands back a merged directory. No copy, no tarball, effectively no disk.
# `grype dir:` then reads the RPM database and the filesystem directly.
#
# The container is created with no command and never started; `podman mount`
# only needs it to exist.
set -uo pipefail
OUT=/home/bunny/p5-evidence/security
IMAGE="${1:-localhost/bunny-os-beta:e906a48793d7}"
mkdir -p "${OUT}"

command -v grype >/dev/null || { echo "grype is required" >&2; exit 3; }

echo "== free space before =="
df -h / | tail -1

echo "== image identity =="
podman image inspect "${IMAGE}" --format '{{.Id}}' | tee "${OUT}/image-id.txt"

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT

mountpoint=$(podman mount "${container}") || exit 5
echo "mounted at ${mountpoint}"
echo "== free space after mounting =="
df -h / | tail -1

echo "== rpm database present? =="
# `find`, not `ls`: the repository's shellcheck gate runs with no severity
# floor, so SC2012 at info level fails it.
find "${mountpoint}/usr/lib/sysimage/rpm" -maxdepth 1 -type f 2>/dev/null | head -3

echo "== scanning (only-fixed, the same scope as security-scan.sh) =="
grype "dir:${mountpoint}" --only-fixed --output json \
  >"${OUT}/candidate-fixed.json" 2>"${OUT}/candidate-fixed.err"
echo "only-fixed exit=$?"

echo "== scanning (everything) =="
grype "dir:${mountpoint}" --output json \
  >"${OUT}/candidate-all.json" 2>"${OUT}/candidate-all.err"
echo "all exit=$?"

for f in "${OUT}/candidate-fixed.json" "${OUT}/candidate-all.json"; do
  echo "--- $(basename "${f}") ---"
  python3 - "${f}" <<'PYTHON'
import json, sys
from collections import Counter
try:
    document = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as error:
    print("unreadable:", error)
    raise SystemExit(0)
matches = document.get("matches", [])
severities = Counter(m["vulnerability"]["severity"] for m in matches)
print("total:", len(matches))
for name in ("Critical", "High", "Medium", "Low", "Negligible", "Unknown"):
    if severities.get(name):
        print(f"  {name}: {severities[name]}")
PYTHON
done

echo "== free space after =="
df -h / | tail -1
echo "SCAN-MOUNTED-DONE"
