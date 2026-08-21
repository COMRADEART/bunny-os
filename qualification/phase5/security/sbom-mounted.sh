#!/usr/bin/bash
# An SBOM of the Alpha Release Candidate, by the same no-copy route as the scan.
#
# §18 lists "SBOM where available" among the things an independent reviewer
# needs, and none existed for this artifact. `build/scripts/sbom.sh` requires an
# exported OCI archive, which is the path that needs tens of gigabytes and is
# why the security re-scan failed the first time.
#
# `podman mount` assembles the overlay in place; syft catalogues the mounted
# directory. No copy, no tarball, no disk.
#
# SPDX JSON, because that is the format `build/scripts/sbom.sh` produces and a
# reviewer comparing the two should not also be comparing formats.
set -uo pipefail
OUT=/home/bunny/p5-evidence/sbom
IMAGE="${1:-localhost/bunny-os-beta:e906a48793d7}"
mkdir -p "${OUT}"

command -v syft >/dev/null || { echo "syft is required" >&2; exit 3; }

echo "== free before =="; df -h / | tail -1

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT
mountpoint=$(podman mount "${container}") || exit 5
echo "mounted at ${mountpoint}"

syft version >"${OUT}/syft-version.txt" 2>&1
podman image inspect "${IMAGE}" --format '{{.Id}}' >"${OUT}/image-id.txt"

echo "== cataloguing =="
syft scan "dir:${mountpoint}" -o spdx-json >"${OUT}/candidate.spdx.json" 2>"${OUT}/syft.err"
echo "syft exit=$?"

python3 - "${OUT}/candidate.spdx.json" <<'PYTHON'
import json, sys
from collections import Counter
document = json.load(open(sys.argv[1], encoding="utf-8"))
packages = document.get("packages", [])
print("spdxVersion:", document.get("spdxVersion"))
print("packages:", len(packages))
kinds = Counter()
for package in packages:
    for reference in package.get("externalRefs", []):
        locator = reference.get("referenceLocator", "")
        if locator.startswith("pkg:"):
            kinds[locator.split("/", 1)[0].removeprefix("pkg:")] += 1
            break
for kind, count in kinds.most_common():
    print(f"  {kind}: {count}")
PYTHON

sha256sum "${OUT}/candidate.spdx.json" | tee "${OUT}/candidate.spdx.json.sha256"
echo "== free after =="; df -h / | tail -1
echo "SBOM-DONE"
