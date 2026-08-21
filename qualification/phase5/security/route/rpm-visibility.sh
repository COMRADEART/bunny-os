#!/usr/bin/bash
# Did the Phase 4 scan ever look at an RPM?
#
# The retained Phase 4 result -- evidence/vulnerability/beta-grype.json -- has
# 143 matches, and every one of them is a go-module or the kernel. Not one rpm.
# The Phase 5 scan of the mounted candidate has 89 rpm matches, sourced from
# /usr/share/rpm/rpmdb.sqlite.
#
# If that is right, the Phase 4 vulnerability position never covered glibc,
# openssl, systemd or anything else the distribution ships -- and a release
# gate that reports "59 fixable findings" while blind to the entire RPM set is
# reporting a number that means less than it looks.
#
# This establishes where the rpm database actually lives in the image, and
# whether it is reachable other than through a symlink, because a cataloguer
# walking a tar is exactly what a symlink can hide a file from.
set -uo pipefail
OUT=/home/bunny/p5-evidence/security-rpm
IMAGE="${1:-localhost/bunny-os-beta:e906a48793d7}"
mkdir -p "${OUT}"

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT
mountpoint=$(podman mount "${container}") || exit 5
echo "mounted at ${mountpoint}"

echo
echo "== where the rpm database lives =="
for candidate in /usr/share/rpm /usr/lib/sysimage/rpm /var/lib/rpm; do
  target="${mountpoint}${candidate}"
  if [[ -L "${target}" ]]; then
    echo "  ${candidate}: SYMLINK -> $(readlink "${target}")"
  elif [[ -d "${target}" ]]; then
    count=$(find "${target}" -maxdepth 1 -type f | wc -l)
    echo "  ${candidate}: directory, ${count} files"
    find "${target}" -maxdepth 1 -type f -printf "      %f %s bytes\n" | head -5
  else
    echo "  ${candidate}: absent"
  fi
done

echo
echo "== is /usr/bin/podman the same inode as an ostree object? =="
if [[ -f "${mountpoint}/usr/bin/podman" ]]; then
  stat -c '  /usr/bin/podman inode=%i links=%h size=%s' "${mountpoint}/usr/bin/podman"
fi
if [[ -d "${mountpoint}/sysroot/ostree/repo/objects" ]]; then
  echo "  /sysroot/ostree/repo/objects EXISTS in the image"
  find "${mountpoint}/sysroot/ostree/repo/objects" -maxdepth 2 -type f 2>/dev/null | wc -l \
    | sed 's/^/    objects: /'
  stat -c '  8cc9b02 object inode=%i links=%h size=%s' \
    "${mountpoint}/sysroot/ostree/repo/objects/8c/c9b0248b19238b5f375ee6f7c986efc7ef8cdd360140254e41c478cd91b933.file" \
    2>/dev/null || echo "  (that object is not present)"
else
  echo "  /sysroot/ostree/repo/objects ABSENT in the image"
fi

echo "RPM-VISIBILITY-DONE"
