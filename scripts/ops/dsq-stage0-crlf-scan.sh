#!/usr/bin/env bash
# Scan all tracked qualification evidence for digest attestation mismatches:
# any tracked file whose bytes no longer match a sha256 recorded in a
# record.json/manifest in the same evidence tree.
set -u
cd /root/bunny-os
python3 - <<'EOF'
import hashlib, json, os, glob

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

bad = ok = 0
for rec in glob.glob('qualification/**/record.json', recursive=True) + \
           glob.glob('qualification/**/*manifest*.json', recursive=True):
    try:
        data = json.load(open(rec))
    except Exception as e:
        print(f'UNPARSEABLE {rec}: {e}')
        continue
    d = os.path.dirname(rec)
    def walk(obj):
        global bad, ok
        if isinstance(obj, dict):
            # common shapes: {"file": name, "sha256": h} or {name: {"sha256": h}}
            if 'sha256' in obj and isinstance(obj.get('sha256'), str):
                name = obj.get('file') or obj.get('path') or obj.get('name')
                if name:
                    p = os.path.join(d, name)
                    if os.path.isfile(p):
                        actual = sha256(p)
                        if actual != obj['sha256']:
                            bad += 1
                            print(f'MISMATCH {p}: actual {actual[:12]} recorded {obj["sha256"][:12]}')
                        else:
                            ok += 1
            for k, v in obj.items():
                if isinstance(v, dict) and 'sha256' in v and isinstance(v['sha256'], str) and os.path.isfile(os.path.join(d, k)):
                    p = os.path.join(d, k)
                    actual = sha256(p)
                    if actual != v['sha256']:
                        bad += 1
                        print(f'MISMATCH {p}: actual {actual[:12]} recorded {v["sha256"][:12]}')
                    else:
                        ok += 1
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(data)
print(f'checked digests: ok={ok} mismatched={bad}')
EOF
