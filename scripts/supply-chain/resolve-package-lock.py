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
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402

REFUSED = 2

#: One `rpm -qp` query per package, tab-separated so a licence containing spaces
#: survives. `%|EPOCH?{...}:{0}|` renders an absent epoch as 0 rather than
#: "(none)", which would then have to be special-cased by every reader.
#:
#: The signature is read from **RSAHEADER**, not SIGPGP. Fedora signs the
#: package header with RSA; `SIGPGP` is the legacy whole-file signature and
#: Fedora does not populate it. Querying SIGPGP returned "(none)" for all 474
#: packages, which would have written a lock recording every Fedora package as
#: unsigned — a claim that is both false and, in a supply-chain lock, exactly
#: the wrong direction to be wrong in. DSAHEADER and SIGPGP are kept as
#: fallbacks for a repository that signs differently.
SIGNATURE_EXPRESSION = (
    "%|RSAHEADER?{%{RSAHEADER:pgpsig}}:"
    "{%|DSAHEADER?{%{DSAHEADER:pgpsig}}:"
    "{%|SIGPGP?{%{SIGPGP:pgpsig}}:{unsigned}|}|}|"
)

QUERY_FORMAT = "\\t".join(
    [
        "%{NAME}",
        "%|EPOCH?{%{EPOCH}}:{0}|",
        "%{VERSION}",
        "%{RELEASE}",
        "%{ARCH}",
        "%{SOURCERPM}",
        "%{LICENSE}",
        SIGNATURE_EXPRESSION,
        "%{SIZE}",
    ]
)

#: `RSA/SHA256, <date>, Key ID <hex>` — the key id is the part that identifies
#: which Fedora key signed the package, and it is what the snapshot records.
_KEY_ID = re.compile(r"Key ID ([0-9a-f]{16})", re.IGNORECASE)


#: Run inside the retained base to produce the exact transaction set.
#:
#: dnf5 rejects `--destdir` on `install` — it exists only on `download` and
#: `upgrade` — and `dnf download --resolve` answers a subtly different question
#: than "what would installing these packages pull in". So the transaction is
#: run with `--downloadonly`, which populates the libdnf5 cache with precisely
#: the packages the transaction would install, and the cache is then copied out.
#:
#: The cache directory name carries the repository id, which is how each package
#: gets attributed to the repository it actually came from rather than to a
#: repository somebody assumed.
_RESOLVE_SCRIPT = r"""
set -euo pipefail
shift || true
/usr/bin/dnf --assumeyes --setopt=install_weak_deps=False --setopt=countme=0 \
    install --downloadonly "$@"
mkdir -p /downloads
found=0
while IFS= read -r rpm; do
    # The repository id goes in a directory name, not in the file name. A first
    # attempt joined them with `%%` and `rpm -qp` read that as a format escape,
    # collapsed it to a single `%`, and then could not open the file it had just
    # been given.
    repo="$(basename "$(dirname "$(dirname "${rpm}")")")"
    mkdir -p "/downloads/${repo}"
    cp -n "${rpm}" "/downloads/${repo}/$(basename "${rpm}")"
    found=$((found + 1))
done < <(find /var/cache/libdnf5 -type f -name '*.rpm')
echo "copied ${found} packages out of the transaction cache"
"""


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
    #
    # The base is pulled *from retention*, not from upstream, and the pulled
    # image's own digest is checked against the lock. That makes this step a
    # standing test of the mirror: if retention were broken, resolution would
    # fail here rather than silently fall back to quay.io.
    print("==> pulling the base from controlled retention")
    pulled = run(
        ["podman", "pull", f"oci:{args.base_layout}:retained"],
        what="pulling the retained base",
    ).strip().splitlines()[-1]

    inspected = json.loads(
        run(["podman", "image", "inspect", pulled], what="inspecting the pulled base")
    )[0]
    digests = set(inspected.get("RepoDigests") or []) | {inspected.get("Digest", "")}
    expected = base_lock["retainedDigest"]
    if not any(expected in str(value) for value in digests):
        raise SystemExit(
            f"BLOCKED: the image pulled from retention does not carry the retained digest.\n"
            f"  expected {expected}\n"
            f"  observed {sorted(str(v) for v in digests)}\n"
            "The mirror and the lock describe different images."
        )
    print(f"    retained digest confirmed: {expected}")

    podman = [
        "podman",
        "run",
        "--rm",
        "--volume",
        f"{download}:/downloads:z",
        "--env",
        "LC_ALL=C.UTF-8",
        pulled,
        "/usr/bin/bash",
        "-c",
        _RESOLVE_SCRIPT,
        "resolve",
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

    print(f"==> recording {len(rpms)} packages and checking every signature")
    records: list[dict[str, object]] = []
    unsigned: list[str] = []
    unverified: list[str] = []
    for rpm in rpms:
        line = run(
            ["rpm", "-qp", "--nosignature", "--queryformat", QUERY_FORMAT, str(rpm)],
            what=f"querying {rpm.name}",
        ).strip()
        name, epoch, version, release, arch, source_rpm, licence, signature, size = line.split("\t")
        digest = hashlib.sha256(rpm.read_bytes()).hexdigest()
        # dnf5 names its cache directory `<repoid>-<hash>`. Both are recorded:
        # the id is what a repository definition calls itself, and the hash is
        # what distinguishes two configurations of the same id.
        cache_directory = rpm.parent.name
        repository = re.sub(r"-[0-9a-f]{8,}$", "", cache_directory) or cache_directory
        file_name = rpm.name

        key_match = _KEY_ID.search(signature)
        signing_key = key_match.group(1).lower() if key_match else ""
        if not signing_key:
            unsigned.append(rpm.name)

        # The authoritative check, not the header tag. `rpmkeys --checksig`
        # verifies the signature against the keys rpm trusts and reports
        # "digests signatures OK" only when both hold. A header that merely
        # *claims* a signature is not a verified signature, and the difference
        # is the whole reason this step exists.
        checked = subprocess.run(
            ["rpmkeys", "--checksig", str(rpm)],
            capture_output=True,
            text=True,
        )
        verified = checked.returncode == 0 and "signatures OK" in checked.stdout
        if not verified:
            unverified.append(f"{rpm.name}: {checked.stdout.strip() or checked.stderr.strip()}")
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
                "sourceRepository": repository,
                "repositoryCacheKey": cache_directory,
                "sourceRpm": source_rpm,
                "licence": licence,
                "signature": signature,
                "signingKey": signing_key,
                "signatureVerified": verified,
                "fileName": file_name,
            }
        )

    if unsigned:
        raise SystemExit(
            f"BLOCKED: {len(unsigned)} packages carry no signature key id:\n  "
            + "\n  ".join(unsigned[:20])
            + "\nEvery RPM must retain its original trusted signature. A snapshot built from "
            "unsigned packages would trade supply-chain integrity for reproducibility, which is "
            "the wrong direction."
        )
    if unverified:
        raise SystemExit(
            f"BLOCKED: {len(unverified)} packages failed signature verification:\n  "
            + "\n  ".join(unverified[:20])
            + "\nImport the Fedora signing keys (rpmkeys --import) and re-run. A package whose "
            "signature does not verify must never reach a snapshot."
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
    keys = sorted({str(item["signingKey"]) for item in records})
    print(f"    {len(records)} packages locked, every signature verified")
    print(f"    signing keys: {', '.join(keys)}")
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
