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

#: What to install. `bash` is in the snapshot, pulls a handful of dependencies,
#: and exercises resolution rather than a single-package copy — a probe that
#: installed something dependency-free would not test the metadata.
PROBE_PACKAGE = "bash"


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(prog="offline-install-probe")
    parser.add_argument("--publication", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--package", default=PROBE_PACKAGE)
    args = parser.parse_args()

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
        "package": args.package,
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
        transaction = run([
            "podman", "run", "--rm", "--network=none",
            "--entrypoint", "/usr/bin/dnf5",
            "--volume", f"{repository_root}:/snapshot:ro",
            "--volume", f"{installroot}:/installroot:z",
            inputs["builder"]["digestReference"],
            "--assumeyes",
            f"--installroot=/installroot",
            "--disablerepo=*",
            "--repofrompath=bunny-snapshot,/snapshot",
            "--enablerepo=bunny-snapshot",
            "--setopt=bunny-snapshot.gpgcheck=1",
            f"--setopt=bunny-snapshot.gpgkey=file:///snapshot/{keys[0].relative_to(repository_root)}",
            "--setopt=install_weak_deps=False",
            "--releasever=44",
            "install", args.package,
        ])
        record["exitCode"] = transaction.returncode
        record["stdoutTail"] = transaction.stdout.strip()[-2000:]
        record["stderrTail"] = transaction.stderr.strip()[-2000:]

        if transaction.returncode != 0:
            record["result"] = "BLOCKED"
            raise SystemExit(
                "BLOCKED: an offline install from the published snapshot failed:\n"
                + (transaction.stderr.strip()[-1500:] or transaction.stdout.strip()[-1500:])
            )

        installed = sorted(
            path.name for path in (installroot / "usr/bin").glob("*")
        ) if (installroot / "usr/bin").is_dir() else []
        record["installedBinaries"] = installed[:40]
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
        f"installed {args.package} from {record['rpmCount']} published RPMs with no network, "
        f"gpgcheck=1 against {len(record['signingKeys'])} shipped key(s)"
    )
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
