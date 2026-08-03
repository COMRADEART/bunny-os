#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the dsq-2 scenario authority.

dsq-2 gets its own authority file rather than editing dsq-1's, for two
reasons. dsq-1's records are frozen evidence about the b9c317d archive and
their binding is checked against the context they were written under, so
changing that context would invalidate every one of them. And the two
scenarios describe different disks: a dsq-1 record imported against the
corrected archive would be the specific fraud Stage 3 rejection 19 names.

Everything measured about the host toolchain is recorded here, so a run can
refuse a disk, a firmware or a scenario version it was not authorised for
instead of quietly measuring the wrong thing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

SCENARIO_VERSION = "dsq-2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_version(argv: list[str]) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"UNAVAILABLE: {exc}"
    return (out.stdout or out.stderr).strip().splitlines()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True,
                        help="Commit Q — the installed-system target")
    parser.add_argument("--archive-commit", required=True,
                        help="Commit O — the archive target Q was built from")
    parser.add_argument("--source-archive-digest", required=True)
    parser.add_argument("--installation-artifact", type=Path, required=True)
    # The 4M variants and the versioned machine type, not the unsuffixed
    # names: this is the firmware dsq-1 measured on this host, and dsq-2 has
    # to boot the same firmware or the two scenarios are not comparable. The
    # unsuffixed OVMF names do not exist here at all, and bare `q35` is an
    # alias that follows the QEMU version, so pinning it would silently change
    # machine on the next upgrade.
    parser.add_argument("--ovmf-code", type=Path,
                        default=Path("/usr/share/edk2/ovmf/OVMF_CODE_4M.qcow2"))
    parser.add_argument("--ovmf-vars-template", type=Path,
                        default=Path("/usr/share/edk2/ovmf/OVMF_VARS_4M.qcow2"))
    parser.add_argument("--machine-type", default="pc-q35-10.2")
    parser.add_argument("--cpu-mode", default="host")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    artifact = args.installation_artifact
    if not artifact.is_file():
        print(f"REFUSED: {artifact} does not exist")
        return 2
    digest = sha256_file(artifact)

    context = {
        "schemaVersion": 1,
        "scenarioVersion": SCENARIO_VERSION,
        "scenarioName": "first-login and display-stack requalification",
        "sourceCommit": args.source_commit,
        "archiveCommit": args.archive_commit,
        "sourceArchiveDigest": args.source_archive_digest,
        "installationArtifact": artifact.name,
        "installationArtifactDigest": digest,
        "machineType": args.machine_type,
        "cpuMode": args.cpu_mode,
        "ovmfCodePath": str(args.ovmf_code),
        "ovmfCodeDigest": sha256_file(args.ovmf_code),
        "ovmfVarsTemplatePath": str(args.ovmf_vars_template),
        "ovmfVarsTemplateDigest": sha256_file(args.ovmf_vars_template),
        "qemuPath": shutil.which("qemu-system-x86_64"),
        "qemuVersion": tool_version(["qemu-system-x86_64", "--version"]),
        "swtpmVersion": tool_version(["swtpm", "--version"]),
        "guestfishVersion": tool_version(["guestfish", "--version"]),
        "journalctlVersion": tool_version(["journalctl", "--version"]),
        "supersedes": {
            "scenarioVersion": "dsq-1",
            "note": ("dsq-1 measured the b9c317d archive, in which "
                     "bunny-first-boot.service failed on 60 of 60 fresh homes "
                     "and chronyd failed on 1 of 60 boots. Its records remain "
                     "evidence about that archive and are not evidence about "
                     "this one."),
        },
        "testFixture": {
            "loginAccountIsTestInjected": True,
            "note": ("Every dsq-2 boot injects a qualification-only account "
                     "into its own overlay. The Bunny artifact ships no "
                     "account and no default credential."),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"wrote {args.output}")
    print(json.dumps({"scenarioVersion": SCENARIO_VERSION,
                      "installationArtifactDigest": digest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
