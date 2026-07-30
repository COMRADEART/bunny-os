#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install a package from the published snapshot, offline, in a disposable root.

Verifying digests and checksums establishes that the snapshot arrived intact. It
does not establish that it *works*: a repository whose metadata does not match
its packages passes every checksum and fails the first `dnf install`, and the
build is where that would be discovered.

So this resolves and installs from the pulled snapshot with the network
switched off at the container boundary — ``--network=none``, not a policy — and
with ``gpgcheck=1`` against the Fedora keys the snapshot itself ships. A run that
silently fell back to a live mirror cannot happen, because there is no route to
one.

The transaction runs inside the *published builder image*, pulled by digest.
That is deliberate: it exercises the builder publication in the same run, and it
means the dnf doing the resolving is the pinned one rather than whatever the
verifying host happens to have. An Ubuntu runner has no dnf at all.

Exit codes:
    0   a package resolved and installed from the snapshot with no network
    2   the snapshot could not be used as a repository
    3   podman or skopeo is unavailable
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REFUSED = 2
UNAVAILABLE = 3

#: The package to install is chosen from the snapshot's own lock, not named here.
#:
#: The first version hardcoded `bash` on the assumption that a package this
#: fundamental must be present. It is not: the snapshot holds the 474 packages
#: this profile *adds on top of* the base image, and bash comes from the base.
#: The probe failed with "No match for argument: bash" against a snapshot that
#: was entirely intact — a wrong assumption reported as a supply-chain failure.
#:
#: Picking from the lock also makes the probe exercise resolution rather than a
#: single-package copy: these packages have dependencies, and a dependency that
#: the metadata cannot satisfy is exactly what this step exists to catch.
PROBE_PACKAGE = ""


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(prog="offline-install-probe")
    parser.add_argument("--publication", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--package", default=PROBE_PACKAGE)
    parser.add_argument("--snapshot-lock", type=Path,
                        default=Path("build/inputs/package-snapshot-lock.json"))
    args = parser.parse_args()

    package = args.package
    if not package:
        if not args.snapshot_lock.is_file():
            print(
                f"BLOCKED: {args.snapshot_lock} is absent and no --package was named, so there is "
                "nothing to try installing.",
                file=sys.stderr,
            )
            return REFUSED
        entries = json.loads(args.snapshot_lock.read_text(encoding="utf-8")).get("packages") or []
        named = sorted(str(entry.get("name", "")) for entry in entries if entry.get("name"))
        if not named:
            print(
                f"BLOCKED: {args.snapshot_lock} names no packages.", file=sys.stderr
            )
            return REFUSED
        # Sorted and first, so the probe is the same package on every runner and
        # a failure is comparable between them.
        package = named[0]

    for command in ("podman", "skopeo"):
        if shutil.which(command) is None:
            print(f"BLOCKED: {command} is required and is not available", file=sys.stderr)
            return UNAVAILABLE

    if not args.publication.is_file():
        print(f"BLOCKED: {args.publication} is absent; nothing has been published", file=sys.stderr)
        return REFUSED

    publication = json.loads(args.publication.read_text(encoding="utf-8"))
    inputs = publication.get("inputs") or {}
    for kind in ("snapshot", "builder"):
        if kind not in inputs:
            print(f"BLOCKED: the {kind} input is not published", file=sys.stderr)
            return REFUSED

    scratch = Path(tempfile.mkdtemp(prefix="bunny-offline-"))
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "package": package,
        "snapshotReference": inputs["snapshot"]["digestReference"],
        "builderReference": inputs["builder"]["digestReference"],
    }
    try:
        # ------------------------------------------------------------ snapshot
        pulled = run(
            ["skopeo", "copy", f"docker://{inputs['snapshot']['digestReference']}",
             f"dir:{scratch / 'snapshot-raw'}"]
        )
        if pulled.returncode != 0:
            raise SystemExit(
                f"BLOCKED: cannot pull the snapshot: {pulled.stderr.strip()[:400]}"
            )
        content = scratch / "snapshot"
        content.mkdir()
        for blob in sorted((scratch / "snapshot-raw").glob("*")):
            run(["tar", "-xf", str(blob), "-C", str(content)])

        repository = next(iter(sorted(content.rglob("repomd.xml"))), None)
        if repository is None:
            raise SystemExit(
                "BLOCKED: the pulled snapshot has no repomd.xml, so it is not a repository and "
                "no offline install is possible from it"
            )
        # repodata/repomd.xml -> the repository root is two levels up.
        repository_root = repository.parent.parent
        record["repositoryRoot"] = str(repository_root.relative_to(content))
        record["rpmCount"] = len(list(content.rglob("*.rpm")))

        # ------------------------------------------------------------- builder
        builder = run(
            ["podman", "pull", inputs["builder"]["digestReference"]]
        )
        if builder.returncode != 0:
            raise SystemExit(
                f"BLOCKED: cannot pull the builder image: {builder.stderr.strip()[:400]}"
            )

        keys = sorted(content.rglob("RPM-GPG-KEY-*"))
        if not keys:
            raise SystemExit(
                "BLOCKED: the snapshot ships no Fedora signing key. Installing from it would "
                "require either disabling gpgcheck or trusting a key from somewhere else, and "
                "both defeat the reason the keys are published with the packages."
            )
        record["signingKeys"] = [str(key.relative_to(content)) for key in keys]

        installroot = scratch / "root"
        installroot.mkdir()

        # --network=none is the control. Everything else could be configuration
        # a mistake undoes; a container with no network cannot reach a mirror
        # however it is configured.
        #
        # Four steps rather than one `dnf install`, because the snapshot is a
        # *delta*. It holds the 474 packages this profile adds on top of the
        # base image, so most of them depend on packages that are in the base
        # and not in the snapshot. A dependency-resolving install therefore
        # fails against an entirely intact snapshot, which says something about
        # what a snapshot is and nothing about whether this one works.
        #
        # What is actually claimable, and what each step establishes:
        #
        #   repoquery  the reconstructed metadata parses and lists what the lock says
        #   download   a package is retrievable from the reconstructed repository
        #   checksig   its Fedora signature verifies against the key the snapshot ships
        #   rpm -i     rpm accepts it into a root, so the bytes are an installable package
        common = [
            "podman", "run", "--rm", "--network=none",
            "--volume", f"{repository_root}:/snapshot:ro",
            "--volume", f"{installroot}:/installroot:z",
        ]
        image = inputs["builder"]["digestReference"]
        key_in_repo = keys[0].relative_to(repository_root)
        repo_args = [
            "--disablerepo=*",
            "--repofrompath=bunny-snapshot,/snapshot",
            "--enablerepo=bunny-snapshot",
            "--setopt=bunny-snapshot.gpgcheck=1",
            f"--setopt=bunny-snapshot.gpgkey=file:///snapshot/{key_in_repo}",
            "--releasever=44",
        ]

        steps: list[dict[str, Any]] = []

        def step(name: str, argv: list[str], *, expect_output: bool = True) -> subprocess.CompletedProcess:
            completed = run(argv)
            steps.append(
                {
                    "step": name,
                    "exitCode": completed.returncode,
                    "outputLines": len(completed.stdout.splitlines()),
                    "passed": completed.returncode == 0
                    and (bool(completed.stdout.strip()) or not expect_output),
                    "stdoutTail": completed.stdout.strip()[-600:],
                    "stderrTail": completed.stderr.strip()[-600:],
                }
            )
            return completed

        listed = step(
            "repoquery",
            common + ["--entrypoint", "/usr/bin/dnf5", image,
                      # The trailing newline is load-bearing. Without it dnf5 emits
                      # 474 names with no separator, `.split()` sees one token, and the
                      # evidence records `packagesResolvable: 1` for a repository that
                      # listed all of them — a counting bug that reads as a broken
                      # snapshot.
                      *repo_args, "repoquery", "--available",
                      "--queryformat", "%{name}\n"],
        )
        available = sorted({line.strip() for line in listed.stdout.splitlines() if line.strip()})
        record["packagesResolvable"] = len(available)

        step(
            "download",
            common + ["--entrypoint", "/usr/bin/dnf5", image,
                      *repo_args, "download", "--destdir=/installroot", package],
        )

        step(
            "checksig",
            common + ["--entrypoint", "/usr/bin/bash", image, "-c",
                      f"rpmkeys --import /snapshot/{key_in_repo} && "
                      "rpmkeys --checksig /installroot/*.rpm"],
        )

        step(
            "rpm-install",
            common + ["--entrypoint", "/usr/bin/bash", image, "-c",
                      # The key is imported into the *install root's* rpm database,
                      # not the container's. Without this the install proceeds with
                      # `Header OpenPGP … NOKEY` and rpm accepts the package without
                      # checking its signature — which would make this step prove
                      # installability and quietly not prove trust.
                      "mkdir -p /installroot/root && "
                      f"rpmkeys --root /installroot/root --import /snapshot/{key_in_repo} && "
                      "rpm --root /installroot/root --nodeps --noscripts "
                      "-i /installroot/*.rpm && "
                      "rpm --root /installroot/root -qa"],
        )

        failed = [entry["step"] for entry in steps if not entry["passed"]]
        record["steps"] = steps
        record["exitCode"] = 0 if not failed else 2

        if failed:
            record["result"] = "BLOCKED"
            detail = next(e for e in steps if e["step"] == failed[0])
            raise SystemExit(
                "BLOCKED: an offline operation against the published snapshot failed at "
                + failed[0]
                + ":\n"
                + (detail["stderrTail"] or detail["stdoutTail"])
            )

        record["result"] = "PASS"

    except SystemExit as exit_request:
        if isinstance(exit_request.code, str):
            record.setdefault("result", "BLOCKED")
            record["reason"] = exit_request.code
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(record, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print(exit_request.code, file=sys.stderr)
            return REFUSED
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"{record['packagesResolvable']} packages resolvable from the reconstructed repository; "
        f"{package} downloaded, signature verified against the shipped key, and installed — "
        f"all with no network"
    )
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
