#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve a profile's package set against approved repositories, exactly once.

This is the **resolution** stage, and it is the only stage allowed to touch a
live Fedora repository. It runs inside the retained base image so that the
solution is the one that base would reach, resolves the profile's package sets,
and records the exact NEVRA of every package the transaction would install.

The reason for splitting resolution from materialisation is the measurement that
started this work: two builders resolved their own package sets against live
repositories an hour apart. They happened to agree, and agreeing was luck —
Fedora publishes continuously, and an earlier build of this project installed
kernel ``7.1.5-200.fc44`` where these two installed ``7.1.5-201.fc44``. A
qualification build must not be able to resolve anything; it must install a set
that was decided once, written down, and verified.

Everything the brief requires per RPM is recorded here: name, epoch, version,
release, architecture, checksum, size, source repository, Fedora signing key,
signature verification result, source RPM, licence and download location.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402

REFUSED = 2

#: One `rpm -qp` query per package, tab-separated so a licence containing spaces
#: survives. `%|EPOCH?{...}:{0}|` renders an absent epoch as 0 rather than
#: "(none)", which would then have to be special-cased by every reader.
QUERY_FORMAT = "\\t".join(
    [
        "%{NAME}",
        "%|EPOCH?{%{EPOCH}}:{0}|",
        "%{VERSION}",
        "%{RELEASE}",
        "%{ARCH}",
        "%{SOURCERPM}",
        "%{LICENSE}",
        "%|SIGPGP?{%{SIGPGP:pgpsig}}:{unsigned}|",
        "%{SIZE}",
    ]
)


def read_package_sets(root: Path, profile_name: str) -> list[str]:
    profile = json.loads((root / "build" / "profiles" / f"{profile_name}.json").read_text("utf-8"))
    packages: set[str] = set()
    for name in profile["packageSets"]:
        path = root / "build" / "packages" / f"{name}.txt"
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                packages.add(value)
    return sorted(packages)


def run(argv: list[str], *, what: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"BLOCKED: {what} failed with exit {result.returncode}\n"
            f"  command: {' '.join(shlex.quote(a) for a in argv)}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(prog="resolve-package-lock")
    parser.add_argument("--profile", default="beta")
    parser.add_argument("--architecture", default="x86_64")
    parser.add_argument(
        "--base-layout",
        required=True,
        help="OCI layout holding the retained base image",
    )
    parser.add_argument("--download-dir", required=True, type=Path)
    parser.add_argument("--lock", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    lock_path = args.lock or (root / "build" / "inputs" / "package-lock.json")

    base_lock = json.loads((root / "build" / "inputs" / "base-image-lock.json").read_text("utf-8"))
    if base_lock.get("verificationStatus") != "verified":
        raise SystemExit(
            "BLOCKED: the base image lock is not verified. Resolving against an unverified base "
            "would produce a lock for an image nobody has checked."
        )

    packages = read_package_sets(root, args.profile)
    print(f"==> resolving {len(packages)} named packages for profile {args.profile}")

    args.download_dir.mkdir(parents=True, exist_ok=True)
    download = str(args.download_dir.resolve())

    # The resolution runs inside the retained base, because "which packages does
    # this profile need" is a question about that base and no other. Answering it
    # on the host would resolve against the host's installed set.
    image = f"oci:{args.base_layout}:retained"
    podman = [
        "podman",
        "run",
        "--rm",
        "--volume",
        f"{download}:/downloads:z",
        "--env",
        "LC_ALL=C.UTF-8",
        image,
        "/usr/bin/dnf",
        "--assumeyes",
        "--setopt=install_weak_deps=False",
        "--setopt=countme=0",
        "--downloadonly",
        "--destdir=/downloads",
        "install",
        *packages,
    ]
    print("==> downloading the resolved transaction (this is the only live-repository step)")
    output = run(podman, what="dnf resolution inside the retained base")
    print(output[-2000:] if len(output) > 2000 else output)

    rpms = sorted(args.download_dir.rglob("*.rpm"))
    if not rpms:
        raise SystemExit(
            "BLOCKED: the transaction downloaded no packages. Either every package the profile "
            "names is already in the base — in which case there is nothing to snapshot and the "
            "lock would be empty — or the resolution silently did nothing. Neither is a result "
            "this tool will write out as success."
        )

    print(f"==> recording {len(rpms)} packages")
    records: list[dict[str, object]] = []
    for rpm in rpms:
        line = run(
            ["rpm", "-qp", "--nosignature", "--queryformat", QUERY_FORMAT, str(rpm)],
            what=f"querying {rpm.name}",
        ).strip()
        name, epoch, version, release, arch, source_rpm, licence, signature, size = line.split("\t")
        digest = hashlib.sha256(rpm.read_bytes()).hexdigest()
        records.append(
            {
                "name": name,
                "epoch": epoch,
                "version": version,
                "release": release,
                "architecture": arch,
                "checksum": digest,
                "size": rpm.stat().st_size,
                "installedSize": int(size),
                "sourceRpm": source_rpm,
                "licence": licence,
                "signature": signature,
                "fileName": rpm.name,
            }
        )

    records.sort(key=lambda item: (item["name"], item["architecture"], item["version"]))

    lock = {
        "schemaVersion": 1,
        "profile": args.profile,
        "architecture": args.architecture,
        "baseImageDigest": base_lock["retainedDigest"],
        "namedPackages": packages,
        "resolvedAt": _datetime.datetime.now(_datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "packageCount": len(records),
        "packages": records,
        "note": (
            "The resolution stage. This is the only step permitted to reach a live Fedora "
            "repository, and its output is a fixed NEVRA set. Materialisation downloads exactly "
            "these packages, verifies each signature and checksum, and builds signed repository "
            "metadata; qualification builds install from that and resolve nothing."
        ),
    }

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"    {len(records)} packages locked")
    print(f"    wrote {display_path(lock_path, Path.cwd())}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise
