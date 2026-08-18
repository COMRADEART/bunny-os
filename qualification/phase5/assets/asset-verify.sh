#!/usr/bin/bash
# Are the two repaired assets in the built image, and does shared-mime-info
# recognise them?
#
# This is the question §3 needed a build for. The wallpaper and the companion
# portrait were rejected by GNOME Shell's loader because shared-mime-info only
# looks for the literal "<svg" in the first 256 bytes, and both files carried
# enough licence prose ahead of the root element to push it past that.
# Checking the source tree proves the source tree; only the image proves the
# image.
#
# `file --mime-type` is NOT the instrument: it is libmagic, and libmagic finds
# these files either way. The mechanism that failed is shared-mime-info, which
# GIO consults, so `gio info` is what is asked here -- against the *image's*
# /usr/share/mime, not the builder's.
#
# Runs against the mounted overlay: no copy, no disk.
set -uo pipefail
OUT=/home/bunny/p5-evidence/assets
IMAGE="${1:-localhost/bunny-os-beta:e501218f2fe0}"
mkdir -p "${OUT}"

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT
mountpoint=$(podman mount "${container}") || exit 5
echo "image:     ${IMAGE}"
echo "mounted:   ${mountpoint}"
podman image inspect "${IMAGE}" --format '{{.Id}}' | sed 's/^/image id:  /'

echo
echo "== every svg the image installs =="
mapfile -t assets < <(find "${mountpoint}/usr/share" -name '*.svg' -type f 2>/dev/null \
                        | grep -E "bunny|companion" | sort)
echo "  ${#assets[@]} found"

for asset in "${assets[@]}"; do
  rel="${asset#"${mountpoint}"}"
  size=$(stat -c %s "${asset}")
  offset=$(grep -aobm1 -- '<svg' "${asset}" | cut -d: -f1)
  echo
  echo "  ${rel}"
  echo "     size ${size} bytes, '<svg' at byte ${offset:-NONE}"
  echo "     libmagic:          $(file -b --mime-type "${asset}")"
  gio_answer=$(XDG_DATA_DIRS="${mountpoint}/usr/share" \
                 gio info -a standard::content-type "${asset}" 2>/dev/null \
               | awk -F': ' '/content-type/{print $2}')
  echo "     shared-mime-info:  ${gio_answer:-<gio unavailable>}"
  python3 - "${asset}" <<'PYTHON'
import sys, xml.etree.ElementTree as ET
try:
    root = ET.parse(sys.argv[1]).getroot()
except Exception as error:
    print(f"     XML:               UNPARSEABLE -- {error}")
else:
    print(f"     XML:               parses, root is {root.tag}")
PYTHON
done

echo
echo "== does the image carry its own mime database? =="
if [[ -f "${mountpoint}/usr/share/mime/mime.cache" ]]; then
  stat -c '  /usr/share/mime/mime.cache: %s bytes' "${mountpoint}/usr/share/mime/mime.cache"
else
  echo "  /usr/share/mime/mime.cache ABSENT"
fi

echo
echo "== release identity as the image reports it =="
if [[ -f "${mountpoint}/usr/lib/bunny-os/release.json" ]]; then
  head -20 "${mountpoint}/usr/lib/bunny-os/release.json" | sed 's/^/  /'
else
  find "${mountpoint}/usr" -name 'release.json' -path '*bunny*' 2>/dev/null | head -3 \
    | while IFS= read -r found; do
        echo "  --- ${found#"${mountpoint}"}"
        head -20 "${found}" | sed 's/^/     /'
      done
fi
grep -E '^(NAME|VERSION|PRETTY_NAME|VARIANT|BUNNY)' "${mountpoint}/usr/lib/os-release" 2>/dev/null \
  | sed 's/^/  os-release: /'

echo "ASSET-VERIFY-DONE"
