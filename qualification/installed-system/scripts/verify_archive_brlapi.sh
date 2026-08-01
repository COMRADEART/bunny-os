#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prove the BrlAPI correction is inside a qualified archive, before any disk
# is written from it.
#
# Three passes of this project each found a different reason one file did not
# exist on an installed system: the program was never installed, the service
# was never enabled, and the unit skipped itself when the file was corrupt.
# Every one of those was invisible in the archive until somebody booted a
# machine. This reads the archive's own layers and answers, at the artifact
# level, whether the thing that mints the key can run at all:
#
#     the helper exists, is executable, is root-owned and is not writable
#     the unit ships
#     the activation symlink exists where systemd will look
#     the preset ships
#     and no key is baked into the image, because a shared per-device secret
#     is the defect that started all of this
#
# Usage: verify_archive_brlapi.sh <bunny-os.oci.tar> [--json OUT]

set -uo pipefail

archive="${1:-}"
output=""
[[ $# -ge 2 && "$2" == "--json" ]] && output="${3:-}"
if [[ -z "${archive}" || ! -f "${archive}" ]]; then
  echo "usage: verify_archive_brlapi.sh <bunny-os.oci.tar> [--json OUT]" >&2
  exit 2
fi

python3 - "${archive}" "${output}" <<'PY'
import gzip, json, sys, tarfile

archive, output = sys.argv[1], sys.argv[2]
outer = tarfile.open(archive)
index = json.load(outer.extractfile("index.json"))
manifest_digest = index["manifests"][0]["digest"].split(":")[1]
manifest = json.load(outer.extractfile(f"blobs/sha256/{manifest_digest}"))
layers = [l["digest"].split(":")[1] for l in manifest["layers"]]

wanted = {
    "usr/libexec/bunny-brlapi-key": None,
    "usr/lib/systemd/system/bunny-brlapi-key.service": None,
    "usr/lib/systemd/system-preset/60-bunny-os.preset": None,
    "etc/systemd/system/sysinit.target.wants/bunny-brlapi-key.service": None,
    "etc/brlapi.key": None,
}
for blob in layers:
    handle = outer.extractfile(f"blobs/sha256/{blob}")
    head = handle.read(2)
    handle = outer.extractfile(f"blobs/sha256/{blob}")
    stream = gzip.open(handle) if head == b"\x1f\x8b" else handle
    try:
        inner = tarfile.open(fileobj=stream, mode="r|")
        for member in inner:
            name = member.name.lstrip("./")
            if name in wanted:
                wanted[name] = {
                    "type": {tarfile.REGTYPE: "file", tarfile.SYMTYPE: "symlink",
                             tarfile.LNKTYPE: "hardlink"}.get(member.type, str(member.type)),
                    "mode": oct(member.mode),
                    "uid": member.uid,
                    "size": member.size,
                    "linkname": member.linkname,
                    "layer": blob[:12],
                }
    except tarfile.TarError:
        pass

helper = wanted["usr/libexec/bunny-brlapi-key"]
unit = wanted["usr/lib/systemd/system/bunny-brlapi-key.service"]
link = wanted["etc/systemd/system/sysinit.target.wants/bunny-brlapi-key.service"]
preset = wanted["usr/lib/systemd/system-preset/60-bunny-os.preset"]
key = wanted["etc/brlapi.key"]

assertions = []
def check(name, ok, expected, observed):
    assertions.append({"name": name, "expected": expected, "observed": observed,
                       "result": "PASS" if ok else "FAIL"})

check("helper-installed", helper is not None,
      "/usr/libexec/bunny-brlapi-key in the archive",
      "present" if helper else "absent")
if helper:
    mode = int(helper["mode"], 8)
    check("helper-executable", bool(mode & 0o111), "executable", helper["mode"])
    check("helper-not-writable", not (mode & 0o022),
          "not group- or world-writable", helper["mode"])
    check("helper-root-owned", helper["uid"] == 0, "uid 0", f"uid {helper['uid']}")
check("unit-shipped", unit is not None, "the unit is in the archive",
      "present" if unit else "absent")
check("activation-symlink-present", link is not None,
      "sysinit.target.wants carries the unit",
      (link["linkname"] if link else "absent"))
check("preset-shipped", preset is not None, "the preset is in the archive",
      "present" if preset else "absent")
check("no-key-baked-into-image", key is None,
      "no /etc/brlapi.key in the archive",
      "absent" if key is None else "PRESENT — the image carries a shared secret")

result = "PASS" if all(a["result"] == "PASS" for a in assertions) else "FAIL"
document = {
    "schemaVersion": 1,
    "collection": "brlapi-archive-verification",
    "archive": archive.rsplit("/", 1)[-1],
    "assertions": assertions,
    "result": result,
    "note": ("Read from the archive's own layers. This establishes that the "
             "thing which mints the key can run; whether it did is an "
             "installed-system question, answered separately."),
}
print(f"brlapi archive verification: {result}")
for a in assertions:
    print(f"  {a['result']:4} {a['name']}: {a['observed']}")
if output:
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(f"wrote {output}")
sys.exit(0 if result == "PASS" else 1)
PY
