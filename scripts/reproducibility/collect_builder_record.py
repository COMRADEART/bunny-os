#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Emit a schema-2 builder record and a CI provenance record.

Supersedes ``collect-builder-record.sh`` for the independence model. The shell
collector emits the legacy schema-1 record, whose strongest available dimension
was ``environmentId`` — a hash of the workspace path. That was enough to *refuse*
a same-host claim and not enough to *support* an independent one, because a
second directory is not a trust boundary.

This collector records the boundary instead. ``administratorBoundary`` answers
"who can change this builder", and it is derived from facts the builder cannot
choose: on a hosted runner it is the CI provider and repository; on a local
machine it is the salted account-and-machine pair.

Nothing here is self-asserted where it can be measured. ``builderType`` is
inferred from the environment and can be overridden only to a value consistent
with what was detected — a local machine cannot declare itself hosted CI.

Usage::

    collect_builder_record.py builder-record --builder-id local-fedora
    collect_builder_record.py provenance --profile beta --artifact-dir build/out/beta
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: Files whose contents pin what a build consumes. Their hashes go into every
#: builder record so a comparison can tell "different inputs" from "different
#: environment" without re-reading the tree.
DEPENDENCY_LOCK_FILES = (
    "build/Containerfile",
    "build/license-policy.json",
    "build/packages/applications.txt",
    "build/packages/common.txt",
    "build/packages/desktop.txt",
    "build/packages/developer.txt",
    "build/packages/installer.txt",
    "build/packages/minimal.txt",
    "build/packages/protected.txt",
    "build/packages/recovery.txt",
    "build/packages/shell.txt",
)

SALT_DEFAULT = "bunny-os-reproducibility"


def _hash(text: str, *, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{text}".encode("utf-8")).hexdigest()[:32]


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command(argv: list[str], *, default: str = "absent") -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return default
    line = (result.stdout or result.stderr or "").strip().splitlines()
    return line[0].strip().replace('"', "") if line else default


def _git(*args: str, default: str = "unknown") -> str:
    value = _command(["git", "-C", str(ROOT), *args], default=default)
    return value or default


def detect_builder_type() -> str:
    """Infer the execution environment. Deliberately not a free choice."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # A self-hosted runner shares the workflow API with a hosted one, so the
        # distinction comes from the label GitHub sets on the runner itself.
        labels = (os.environ.get("RUNNER_ENVIRONMENT") or "").casefold()
        return "self-hosted-ci" if labels == "self-hosted" else "hosted-ci"
    if os.environ.get("CI_JOB_ID") or os.environ.get("GITLAB_CI"):
        return "hosted-ci"
    if os.environ.get("BUNNY_CLOUD_PROVIDER"):
        return "cloud-vm"
    if os.environ.get("BUNNY_PHYSICAL_BUILDER") == "1":
        return "physical-builder"
    return "local-machine"


def administrator_boundary(builder_type: str, *, salt: str) -> str:
    """Name who can change this builder.

    A hosted runner is administered by the CI provider under a repository's
    settings; a local machine is administered by whoever holds the account. Both
    are hashed, because the boundary needs to compare equal or unequal and does
    not need to be legible in a committed evidence file.
    """
    if builder_type in {"hosted-ci", "self-hosted-ci"}:
        provider = "github-actions" if os.environ.get("GITHUB_ACTIONS") else "ci"
        repository = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("CI_PROJECT_PATH") or "unknown"
        runner = os.environ.get("RUNNER_NAME") or "hosted"
        return _hash(f"{provider}:{repository}:{builder_type}:{runner}", salt=salt)
    if builder_type == "cloud-vm":
        provider = os.environ.get("BUNNY_CLOUD_PROVIDER") or "unknown"
        account = os.environ.get("BUNNY_CLOUD_ACCOUNT") or "unknown"
        return _hash(f"cloud:{provider}:{account}", salt=salt)
    machine = ""
    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            machine = candidate.read_text(encoding="utf-8").strip()
            break
        except OSError:
            continue
    if not machine:
        machine = platform.node() or "unknown"
    account = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    return _hash(f"local:{account}@{machine}", salt=salt)


def environment_id(*, salt: str) -> str:
    workspace = os.environ.get("BUNNY_WORKTREE") or str(ROOT)
    storage = os.environ.get("CONTAINERS_STORAGE_ROOT") or "default"
    return _hash(f"{workspace}:{storage}", salt=salt)


_VERSION_NUMBER = re.compile(r"\b(\d+\.\d+(?:\.\d+)*)\b")


def _tool_version(argv: list[str]) -> str:
    """The tool's version number, not its banner.

    Raw --version banners embed distribution build details: Fedora's skopeo
    appends a git commit Ubuntu's build of the same release cannot share, and
    syft's multi-line report begins "Application: syft", which is what an
    earlier record captured as the version. Two builders comparing banners
    compare distributions, and the independence evaluator would refuse a pair
    whose tools are the same versions differently packaged. The version number
    is the claim the comparison needs. A missing tool records "absent" —
    absence is a version, not a gap.
    """
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return "absent"
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return "absent"
    match = _VERSION_NUMBER.search(output)
    if match:
        return match.group(1)
    return output.splitlines()[0].strip().replace('"', "")


def toolchain() -> dict[str, str]:
    return {
        "podman": _tool_version(["podman", "--version"]),
        "skopeo": _tool_version(["skopeo", "--version"]),
        "image-builder": _tool_version(["image-builder", "--version"]),
        "syft": _tool_version(["syft", "version", "-o", "text"]),
        "grype": _tool_version(["grype", "version", "-o", "text"]),
        "python3": platform.python_version(),
        "tar": _tool_version(["tar", "--version"]),
    }


def dependency_lock_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in DEPENDENCY_LOCK_FILES:
        target = ROOT / relative
        hashes[relative] = _file_digest(target) if target.is_file() else "absent"
    return hashes


def _now() -> str:
    stamp = os.environ.get("BUNNY_EVALUATION_TIME")
    if stamp:
        return stamp
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def builder_record(args: argparse.Namespace) -> dict[str, Any]:
    salt = os.environ.get("BUNNY_MACHINE_ID_SALT", SALT_DEFAULT)
    detected = detect_builder_type()
    declared = args.builder_type or detected
    if declared != detected:
        # A record may narrow what was detected (a local machine declaring
        # itself a dedicated physical builder) but never claim a boundary it
        # does not have.
        allowed = {("local-machine", "physical-builder"), ("hosted-ci", "self-hosted-ci")}
        if (detected, declared) not in allowed:
            raise SystemExit(
                f"refusing to record builderType={declared!r}: the environment is {detected!r}. "
                "A builder cannot declare a trust boundary it does not have."
            )
    base = os.environ.get("BUNNY_BASE_IMAGE", "")
    return {
        "schemaVersion": 2,
        "builderId": args.builder_id,
        "environmentId": environment_id(salt=salt),
        "sourceCommit": _git("rev-parse", "HEAD"),
        "baseImageDigest": base,
        "architecture": platform.machine() or "unknown",
        "operatingSystem": _os_release(),
        "kernelVersion": platform.release() or "unknown",
        "builderType": declared,
        "cloudProvider": os.environ.get("BUNNY_CLOUD_PROVIDER") or None,
        "cloudRunner": os.environ.get("RUNNER_NAME") or os.environ.get("CI_RUNNER_ID") or None,
        "workflowRunId": _workflow_run_id(),
        "administratorBoundary": administrator_boundary(declared, salt=salt),
        "buildStartedAt": args.started_at or _now(),
        "buildCompletedAt": args.completed_at or _now(),
        "toolchain": toolchain(),
        "dependencyLockHashes": dependency_lock_hashes(),
    }


def _workflow_run_id() -> str | None:
    run = os.environ.get("GITHUB_RUN_ID") or os.environ.get("CI_JOB_ID")
    if not run:
        return None
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    # The attempt is part of the identity: a re-run is a different build with a
    # warm cache and a different clock, and must not be mistaken for the first.
    return f"{run}.{attempt}" if attempt else str(run)


def _os_release() -> str:
    try:
        fields = dict(
            line.split("=", 1)
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        identifier = fields.get("ID", "").strip('"')
        version = fields.get("VERSION_ID", "").strip('"')
        if identifier:
            return f"{identifier}-{version}" if version else identifier
    except OSError:
        pass
    return f"{platform.system().casefold()}-{platform.release()}"


def provenance(args: argparse.Namespace) -> dict[str, Any]:
    directory = Path(args.artifact_dir)
    if not directory.is_dir():
        raise SystemExit(f"artifact directory does not exist: {directory}")
    artifacts: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"provenance.json", "ci-provenance.json", "SHA256SUMS"}:
            continue
        artifacts[str(path.relative_to(directory)).replace(os.sep, "/")] = _file_digest(path)
    if not artifacts:
        raise SystemExit(f"no artifacts found under {directory}; provenance would describe nothing")

    generated = _datetime.datetime.now(_datetime.timezone.utc)
    expires = generated + _datetime.timedelta(days=args.valid_days)
    return {
        "schemaVersion": 1,
        "repository": os.environ.get("GITHUB_REPOSITORY", "COMRADEART/bunny-os"),
        "workflow": os.environ.get("BUNNY_WORKFLOW_PATH", ".github/workflows/independent-builder.yml"),
        "workflowRef": os.environ.get("GITHUB_REF") or None,
        "workflowRunId": _workflow_run_id() or "local",
        "workflowRunAttempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
        "runnerImage": os.environ.get("ImageOS") or os.environ.get("RUNNER_IMAGE") or _os_release(),
        "runnerArchitecture": os.environ.get("RUNNER_ARCH") or platform.machine() or "unknown",
        "kernelVersion": platform.release() or "unknown",
        "containerRuntime": toolchain()["podman"],
        "imageBuilderVersion": toolchain()["image-builder"],
        "sourceCommit": _git("rev-parse", "HEAD"),
        "baseImageDigest": os.environ.get("BUNNY_BASE_IMAGE", ""),
        "generatedAt": generated.isoformat().replace("+00:00", "Z"),
        "expiresAt": expires.isoformat().replace("+00:00", "Z"),
        "cacheDisabled": os.environ.get("BUNNY_CACHES_DISABLED") == "1",
        "artifacts": artifacts,
        "dependencyLockHashes": dependency_lock_hashes(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect_builder_record")
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("builder-record")
    record.add_argument("--builder-id", required=True)
    record.add_argument("--builder-type", choices=(
        "local-machine", "hosted-ci", "self-hosted-ci", "cloud-vm", "physical-builder",
    ))
    record.add_argument("--started-at")
    record.add_argument("--completed-at")
    record.add_argument("--output", type=Path)

    prov = commands.add_parser("provenance")
    prov.add_argument("--profile", required=True)
    prov.add_argument("--artifact-dir", required=True)
    prov.add_argument("--valid-days", type=int, default=90)
    prov.add_argument("--output", type=Path)

    args = parser.parse_args()
    payload = builder_record(args) if args.command == "builder-record" else provenance(args)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
