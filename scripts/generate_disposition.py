#!/usr/bin/env python3
"""Seed the vulnerability disposition record from a Grype report.

The scanner facts — advisory, package, installed version, fixed version — are
copied verbatim. The *judgement* fields are seeded from measured image facts
where those facts were actually established, and left at ``unknown`` where they
were not. Seeding a judgement as ``unknown`` is deliberate: a record that has
never been reviewed must not be able to validate as reviewed.

Run with ``--check`` in CI to confirm the recorded dispositions still cover the
current scan, rather than silently rewriting them.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release.vulnerability import load_grype_findings

#: Carrier binaries established by evidence/reachability/beta-binaries.txt and
#: evidence/reachability/beta-facts.txt. Everything here was measured on the
#: built beta image, not inferred from package lists.
CONTAINER_STACK_PACKAGES = {
    "github.com/containers/podman/v5",
    "github.com/containers/storage",
    "github.com/containers/image/v5",
    "github.com/containers/common",
    "github.com/opencontainers/runc",
    "github.com/opencontainers/selinux",
    "github.com/docker/docker",
    "github.com/moby/buildkit",
    "github.com/sigstore/fulcio",
    "google.golang.org/grpc",
    "golang.org/x/crypto",
    "golang.org/x/net",
    "golang.org/x/text",
    "go.opentelemetry.io/otel",
    "github.com/containernetworking/plugins",
}

REACHABILITY_EVIDENCE = "evidence/reachability/beta-facts.txt"
BINARIES_EVIDENCE = "evidence/reachability/beta-binaries.txt"
PERMISSIONS_EVIDENCE = "evidence/reachability/beta-permissions.txt"


def seed_finding(row: dict[str, Any]) -> dict[str, Any]:
    package = row["package"]
    container_stack = package in CONTAINER_STACK_PACKAGES
    kernel = row.get("packageType") == "linux-kernel"

    if container_stack:
        return {
            **{k: row[k] for k in ("advisoryId", "package", "installedVersion", "scannerSeverity", "fixedVersion")},
            "sourceRepository": "fedora-44 (base image quay.io/fedora/fedora-bootc:44)",
            "fromBaseImage": True,
            "directlyRequired": True,
            "runtimeReachability": "installed-not-executed",
            "privilegeLevel": "unprivileged-user",
            "networkExposure": "none",
            "exploitPrerequisites": (
                "A local user must invoke podman, skopeo, bootc or toolbox and drive it to the "
                "affected code path; no unit is enabled that reaches it automatically."
            ),
            "mitigation": (
                "No podman or bootc unit is enabled: /etc/systemd/system contains no podman or "
                "bootc symlink, podman.socket is not in sockets.target.wants, and "
                "bootc-fetch-apply-updates.timer is not enabled. Binaries are 0755 root:root with "
                "no setuid bit. SELinux targeted policy is enforcing."
            ),
            "remediationPath": (
                "Fedora must rebuild podman, skopeo and bootc against patched Go modules. The "
                "packages are in the base image, not in build/packages/, so they cannot be "
                "updated or removed from this repository: bootc requires podman and skopeo, and "
                "rpm-ostree requires skopeo."
            ),
            "waiverEligible": False,
            "reviewer": None,
            "evidence": f"{BINARIES_EVIDENCE}, {REACHABILITY_EVIDENCE}, {PERMISSIONS_EVIDENCE}",
            "disposition": "Unknown",
        }

    if kernel:
        return {
            **{k: row[k] for k in ("advisoryId", "package", "installedVersion", "scannerSeverity", "fixedVersion")},
            "sourceRepository": "fedora-44 kernel",
            "fromBaseImage": True,
            "directlyRequired": True,
            "runtimeReachability": "executed-by-default",
            "privilegeLevel": "kernel",
            "networkExposure": "none",
            "exploitPrerequisites": (
                "Scanner reports a fixed version in a much older series than the installed kernel; "
                "whether the installed kernel carries the fix has not been confirmed against the "
                "Fedora changelog."
            ),
            "mitigation": "SELinux targeted policy enforcing; no unprivileged user namespace changes made.",
            "remediationPath": (
                "Confirm against the Fedora kernel changelog whether the installed series carries "
                "the fix. Grype's linux-kernel classifier compares against upstream stable series "
                "and is unreliable across major versions."
            ),
            "waiverEligible": False,
            "reviewer": None,
            "evidence": "evidence/vulnerability/beta-grype.json",
            "disposition": "Unknown",
        }

    return {
        **{k: row[k] for k in ("advisoryId", "package", "installedVersion", "scannerSeverity", "fixedVersion")},
        "sourceRepository": "unclassified",
        "fromBaseImage": True,
        "directlyRequired": False,
        "runtimeReachability": "unknown",
        "privilegeLevel": "unknown",
        "networkExposure": "unknown",
        "exploitPrerequisites": "not analysed",
        "mitigation": "none recorded",
        "remediationPath": "requires analysis",
        "waiverEligible": False,
        "reviewer": None,
        "evidence": "evidence/vulnerability/beta-grype.json",
        "disposition": "Unknown",
    }


def seed_reachability(finding: dict[str, Any]) -> dict[str, Any]:
    """Seed the ten-question reachability review for one finding."""
    container_stack = finding["package"] in CONTAINER_STACK_PACKAGES
    if not container_stack:
        answer = lambda a, e: {"answer": a, "evidence": e}  # noqa: E731
        return {
            "advisoryId": finding["advisoryId"],
            "package": finding["package"],
            "answers": {
                name: answer("unknown", "not analysed in this bounded review")
                for name in (
                    "binaryInstalled",
                    "runsByDefault",
                    "listensOnSocket",
                    "unprivilegedInvocation",
                    "bunnyOrPluginInvocation",
                    "sandboxLimitsExposure",
                    "vulnerableCodePathActive",
                    "packageRemovable",
                    "functionalityIsolable",
                    "systemdOrSelinuxControl",
                )
            },
            "outcome": "Unknown",
            "reviewer": "Bunny OS maintainer (self-assessment)",
            "reviewedAt": "2026-07-29T00:00:00Z",
            "notes": "Outside the bounded scope of the container-stack review.",
        }

    return {
        "advisoryId": finding["advisoryId"],
        "package": finding["package"],
        "answers": {
            "binaryInstalled": {
                "answer": "yes",
                "evidence": f"{BINARIES_EVIDENCE}: podman 45220848 B, skopeo 26035008 B, bootc 17397824 B, toolbox 12651096 B at /usr/sbin",
            },
            "runsByDefault": {
                "answer": "no",
                "evidence": f"{REACHABILITY_EVIDENCE}: find /etc/systemd -name '*podman*' -o -name '*bootc*' returns nothing; no preset enables either",
            },
            "listensOnSocket": {
                "answer": "no",
                "evidence": f"{REACHABILITY_EVIDENCE}: podman.socket is a unix socket at %t/podman/podman.sock and is absent from sockets.target.wants",
            },
            "unprivilegedInvocation": {
                "answer": "yes",
                "evidence": f"{PERMISSIONS_EVIDENCE}: /usr/sbin/podman 755 root:root, no setuid; rootless invocation is possible",
            },
            "bunnyOrPluginInvocation": {
                "answer": "no",
                "evidence": "services/ exposes typed fixed backends only; the broker has no generic exec path and no backend invokes a container runtime",
            },
            "sandboxLimitsExposure": {
                "answer": "yes",
                "evidence": "selinux-policy-targeted enforcing; Bunny units carry systemd sandboxing. This confines the blast radius, it does not remove the code",
            },
            "vulnerableCodePathActive": {
                "answer": "unknown",
                "evidence": (
                    "Not determined. Establishing whether the specific vulnerable function in the "
                    "vendored Go module is linked and reachable requires per-CVE symbol analysis "
                    "of a 45 MB stripped binary, which this bounded review did not perform."
                ),
            },
            "packageRemovable": {
                "answer": "no",
                "evidence": (
                    f"{REACHABILITY_EVIDENCE}: rpm -q --whatrequires podman returns bootc and "
                    "toolbox; --whatrequires skopeo returns bootc and rpm-ostree. Removing them "
                    "removes the update mechanism."
                ),
            },
            "functionalityIsolable": {
                "answer": "no",
                "evidence": "bootc uses the same libraries in-process to fetch and stage updates; the code cannot be isolated from the update path",
            },
            "systemdOrSelinuxControl": {
                "answer": "yes",
                "evidence": "No enabled unit reaches the code automatically; SELinux confines what a rootless invocation can do",
            },
        },
        "outcome": "Unknown",
        "reviewer": "Bunny OS maintainer (self-assessment)",
        "reviewedAt": "2026-07-29T00:00:00Z",
        "notes": (
            "Nine of ten questions are answered with measured evidence. The tenth — whether the "
            "vulnerable code path is compiled in and active — is not, so the outcome is Unknown "
            "and remains blocking. An unanswered question is not a negative answer."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grype", type=Path, default=ROOT / "evidence/vulnerability/beta-grype.json")
    parser.add_argument("--profile", default="beta")
    parser.add_argument("--image", required=True)
    parser.add_argument("--base-digest", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--scanned-at", required=True)
    parser.add_argument("--scanner", default="grype 0.116.1")
    parser.add_argument("--out", type=Path, default=ROOT / "operations/data/vulnerability-disposition.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    document = json.loads(args.grype.read_text(encoding="utf-8"))
    rows = load_grype_findings(document, fixable_only=True)

    seen: set[tuple[str, str]] = set()
    findings: list[dict[str, Any]] = []
    for row in rows:
        key = (row["advisoryId"], row["package"])
        if key in seen:
            continue
        seen.add(key)
        findings.append(seed_finding(row))

    serious = [f for f in findings if f["scannerSeverity"] in ("Critical", "High")]
    payload = {
        "schemaVersion": 1,
        "profile": args.profile,
        "imageReference": args.image,
        "baseImageDigest": args.base_digest,
        "sourceCommit": args.commit,
        "scannedAt": args.scanned_at,
        "scanner": args.scanner,
        "findings": findings,
        "reachability": [seed_reachability(f) for f in serious],
    }

    if args.check:
        existing = json.loads(args.out.read_text(encoding="utf-8"))
        recorded = {(f["advisoryId"], f["package"]) for f in existing.get("findings", [])}
        current = seen
        added = sorted(current - recorded)
        removed = sorted(recorded - current)
        if added or removed:
            print("vulnerability disposition is out of date")
            for item in added:
                print(f"  new finding not dispositioned: {item[0]} {item[1]}")
            for item in removed:
                print(f"  dispositioned finding no longer present: {item[0]} {item[1]}")
            return 2
        print(f"vulnerability disposition covers all {len(current)} fixable findings")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.out}: {len(findings)} fixable findings, {len(serious)} Critical/High reachability reviews")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
