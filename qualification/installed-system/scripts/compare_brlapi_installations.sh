#!/usr/bin/bash
# The cross-installation assertions the specification names: two keys must
# differ, and a reboot must not rotate one. Both are decided from the digests
# in the evidence records, never from the key values.
set -uo pipefail
# The repository root, resolved from this script's own location so the
# comparison reads the same evidence tree wherever it is invoked from.
cd "$(dirname "$(readlink -f "$0")")/../../.." || exit 3
python3 - <<'PY'
import json, sys
from pathlib import Path

EV = Path("qualification/installed-system/evidence/collections")
records = {}
for label, name in (
    ("installation-a", "brlapi-installation-a.json"),
    ("installation-b", "brlapi-installation-b.json"),
    ("installation-offline", "brlapi-installation-offline.json"),
    ("installation-a-after-reboot", "brlapi-installation-a-reboot.json"),
):
    path = EV / name
    records[label] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

findings = []
def check(name, ok, detail):
    findings.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

def digest(label):
    record = records.get(label)
    if not record:
        return None
    key = record.get("key") or {}
    return key.get("sha256") if key.get("present") else None

a, b, off, again = (digest(x) for x in
                    ("installation-a", "installation-b",
                     "installation-offline", "installation-a-after-reboot"))

for label in ("installation-a", "installation-b", "installation-offline"):
    d = digest(label)
    check(f"key-present:{label}", d is not None,
          "a key was minted on this installation" if d else
          "no key on this installation — first boot did not mint one")

if a and b:
    check("keys-differ:a-vs-b", a != b,
          "two installations of one archive must not share a key")
if a and off:
    check("keys-differ:a-vs-offline", a != off,
          "an offline installation must still mint its own key")
if a and again:
    check("key-stable-across-reboot", a == again,
          "a second boot must not rotate a valid key")
elif again is None and a:
    check("key-stable-across-reboot", False,
          "the rebooted installation has no key record")

result = "PASS" if findings and all(f["result"] == "PASS" for f in findings) else "FAIL"
document = {
    "schemaVersion": 1,
    "collection": "brlapi-cross-installation",
    "findings": findings,
    "keyDigests": {k: digest(k) for k in records},
    "result": result,
    "note": ("Decided from SHA-256 digests recorded by the per-installation "
             "collectors. No key value is read, compared or stored here."),
}
out = EV / "brlapi-cross-installation.json"
out.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"cross-installation: {result}")
for f in findings:
    print(f"  {f['result']:4} {f['check']}: {f['detail'][:70]}")
print(f"wrote {out}")
sys.exit(0 if result == "PASS" else 1)
PY
