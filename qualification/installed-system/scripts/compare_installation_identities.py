#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare machine-specific state across two installations of one archive.

The immutable archive must carry no identity; every installation must mint
its own. Both halves are tested here, offline, from two installed disks that
each booted at least once: values that must DIFFER between installations
(identities, secrets), values that must be ABSENT from the archive and
present after first boot, and permissions the generated secrets must carry.

The disks are read through libguestfs, read-only. Secret material is never
copied into evidence: for key files this records existence, owner, mode and
a salted digest — enough to prove two installations differ without retaining
either secret. The salt is per-comparison and discarded, so the digests
cannot be correlated with any later record either.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

#: Paths that must differ between two installations. (path, kind, note)
MUST_DIFFER = (
    ("/etc/machine-id", "identity", "systemd machine identity, minted at first boot"),
    ("/etc/brlapi.key", "secret", "BRLTTY API key, minted by bunny-brlapi-key.service"),
    ("/var/lib/systemd/random-seed", "secret", "boot entropy seed"),
)

#: SSH host keys: compared as a group because the set present depends on the
#: sshd configuration; every one present on both sides must differ.
SSH_KEY_GLOB = "/etc/ssh/ssh_host_*_key"

#: Expected access for generated secrets: (glob, owner, group, mode-mask)
SECRET_PERMISSIONS = (
    ("/etc/brlapi.key", "0", None, 0o137),   # at most 0640, root-owned
    ("/etc/ssh/ssh_host_*_key", "0", None, 0o177),  # at most 0600
)


def guestfish(disk: Path, *commands: str) -> str:
    result = subprocess.run(
        ["guestfish", "--ro", "-a", str(disk), "-i", *commands],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"guestfish on {disk.name}: {result.stderr.strip()[:300]}")
    return result.stdout


def read_state(disk: Path, salt: bytes) -> dict:
    state: dict = {"disk": disk.name, "files": {}}

    def probe(path: str) -> dict | None:
        try:
            exists = guestfish(disk, "exists", path).strip()
        except RuntimeError as exc:
            return {"error": str(exc)}
        if exists != "true":
            return None
        stat = guestfish(disk, "statns", path)
        fields = dict(
            line.strip().split(": ", 1)
            for line in stat.splitlines() if ": " in line
        )
        try:
            content = subprocess.run(
                ["guestfish", "--ro", "-a", str(disk), "-i", "download", path, "/dev/stdout"],
                capture_output=True, check=True,
            ).stdout
        except subprocess.CalledProcessError:
            content = b""
        return {
            "present": True,
            "mode": oct(int(fields.get("st_mode", "0")) & 0o7777),
            "uid": fields.get("st_uid"),
            "gid": fields.get("st_gid"),
            "size": int(fields.get("st_size", "0")),
            # Salted: proves difference, retains nothing recoverable.
            "saltedDigest": hashlib.sha256(salt + content).hexdigest(),
        }

    for path, kind, note in MUST_DIFFER:
        state["files"][path] = probe(path)

    ssh_keys = guestfish(disk, "glob-expand", SSH_KEY_GLOB).strip().splitlines()
    state["sshHostKeys"] = {}
    for key in ssh_keys:
        key = key.strip()
        if key:
            state["sshHostKeys"][key] = probe(key)

    hostname = guestfish(disk, "cat", "/etc/hostname") if guestfish(
        disk, "exists", "/etc/hostname").strip() == "true" else ""
    state["hostname"] = hostname.strip()

    fs_uuids = guestfish(disk, "list-filesystems")
    state["filesystems"] = fs_uuids.strip()
    return state


def main() -> int:
    parser = argparse.ArgumentParser(prog="compare_installation_identities")
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--archive-manifest", type=Path,
                        help="fileDigests dimension of the qualified archive, to prove "
                             "identity paths are absent from the immutable root")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    salt = os.urandom(32)  # per-comparison, discarded with the process
    first = read_state(args.first, salt)
    second = read_state(args.second, salt)

    findings: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        findings.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    for path, kind, note in MUST_DIFFER:
        a, b = first["files"].get(path), second["files"].get(path)
        if not a or not b or not a.get("present") or not b.get("present"):
            check(f"present:{path}", False,
                  f"{note}: absent on at least one installation — first boot did not mint it")
            continue
        check(f"present:{path}", True, note)
        check(f"differs:{path}", a["saltedDigest"] != b["saltedDigest"],
              f"{kind} must be unique per installation")

    shared_keys = set(first["sshHostKeys"]) & set(second["sshHostKeys"])
    for key in sorted(shared_keys):
        a, b = first["sshHostKeys"][key], second["sshHostKeys"][key]
        if a and b and a.get("present") and b.get("present"):
            check(f"differs:{key}", a["saltedDigest"] != b["saltedDigest"],
                  "SSH host keys must be unique per installation")

    import fnmatch
    for glob, uid, gid, forbidden in SECRET_PERMISSIONS:
        for state in (first, second):
            pool = {**state["files"], **state["sshHostKeys"]}
            for path, record in pool.items():
                if record and record.get("present") and fnmatch.fnmatch(path, glob):
                    mode = int(record["mode"], 8)
                    check(f"mode:{state['disk']}:{path}",
                          (mode & forbidden) == 0 and record.get("uid") == uid,
                          f"mode {record['mode']}, uid {record.get('uid')}; "
                          f"forbidden bits {oct(forbidden)}")

    if args.archive_manifest and args.archive_manifest.is_file():
        manifest = json.loads(args.archive_manifest.read_text(encoding="utf-8"))
        archive_paths = manifest if isinstance(manifest, dict) else {}
        for path, kind, note in MUST_DIFFER:
            in_archive = path.lstrip("/") in archive_paths or path in archive_paths
            check(f"absent-from-archive:{path}", not in_archive,
                  "identity material must not ship in the immutable root")

    result = "PASS" if all(f["result"] == "PASS" for f in findings) else "FAIL"
    document = {
        "schemaVersion": 1,
        "first": first["disk"],
        "second": second["disk"],
        "findings": findings,
        "hostnames": [first["hostname"], second["hostname"]],
        "result": result,
        "note": (
            "Secret material is never retained: differences are proven through "
            "per-comparison salted digests, and the salt dies with this process."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"per-installation identity comparison: {result}")
    for finding in findings:
        if finding["result"] == "FAIL":
            print(f"  FAIL {finding['check']}: {finding['detail']}")
    print(f"wrote {args.output}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
