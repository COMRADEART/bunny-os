#!/usr/bin/bash
# The §3 asset check, with a negative control.
#
# Content-only sniffing against the image's own shared-mime-info database, on
# the repaired file and on the file as it was before the repair. Without the
# control this proves nothing: a check that passes on both the broken and the
# fixed input has not measured the fix.
set -uo pipefail
OUT=/home/bunny/p5-evidence/assets
IMAGE="${1:-localhost/bunny-os-beta:e501218f2fe0}"
TREE=/root/bunny-os
mkdir -p "${OUT}"

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT
mountpoint=$(podman mount "${container}") || exit 5
echo "image:   ${IMAGE}"
export XDG_DATA_DIRS="${mountpoint}/usr/share"
echo "mime db: ${XDG_DATA_DIRS}/mime/mime.cache"

echo
echo "== the repaired assets, as installed in the image =="
mapfile -t installed < <(find "${mountpoint}/usr/share" -type f -name '*.svg' 2>/dev/null \
                           | grep -E '/backgrounds/bunny-os/|bunny-os/companion' | sort)
if (( ${#installed[@]} == 0 )); then
  echo "  NONE FOUND under /usr/share -- widening the search"
  mapfile -t installed < <(find "${mountpoint}" -xdev -type f -name 'bunny-nocturne.svg' \
                             -o -xdev -type f -name 'default-bunny.svg' 2>/dev/null | sort)
fi
python3 /home/bunny/p5-ops/sniff-check.py "${installed[@]}"

echo
echo "== where the companion portrait ended up =="
find "${mountpoint}" -xdev -name 'default-bunny.svg' 2>/dev/null | sed "s|${mountpoint}|  |" | head -5
echo "  (nothing above means the image does not install it)"

echo
echo "== NEGATIVE CONTROL: the same files as they were before the repair =="
control="${OUT}/control"
rm -rf "${control}"
mkdir -p "${control}"
cd "${TREE}" || exit 1
for path in shell/assets/wallpapers/bunny-nocturne.svg shell/assets/companion/default-bunny.svg; do
  name=$(basename "${path}")
  # The commit before the repair. If the file did not exist there, skip it.
  if git show "e906a48793d7:${path}" >"${control}/${name}" 2>/dev/null; then
    echo "  recovered ${path} at e906a48793d7"
  else
    rm -f "${control}/${name}"
    echo "  ${path} not present at e906a48793d7"
  fi
done
mapfile -t controls < <(find "${control}" -type f -name '*.svg' | sort)
if (( ${#controls[@]} > 0 )); then
  python3 /home/bunny/p5-ops/sniff-check.py "${controls[@]}"
else
  echo "  no control files recovered"
fi

echo "SNIFF-VERIFY-DONE"
