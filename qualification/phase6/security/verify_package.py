#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the security review package against itself.

Run by a reviewer before reading anything:

    python qualification/phase6/security/verify_package.py

Section 4 asks for a package that is self-contained and checkable. A document
that asserts counts and digests is checkable only if something re-derives them,
so this does: it re-reads the inventory, recounts it, confirms every referenced
file exists, and confirms that nothing has been quietly dispositioned.

It deliberately does NOT hash the disk images. They live on the build host, not
in the repository, and a verifier that silently skipped an absent 13 GB file
would report success for a check it did not perform. Image digests are reported
as claims, with the file that recorded the measurement named, so the reviewer
knows exactly which part of the chain they still have to close themselves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

SUBJECT_DIGEST = "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d"
SUBJECT_COMMIT = "e906a48793d74544b39c14cc3e35e0654f5311e2"

#: What the package claims, so a drift between prose and data is caught.
CLAIMED = {
    "distinctAdvisories": 80,
    "Critical": 8,
    "High": 36,
    "Medium": 29,
    "Low": 6,
    "Unknown": 1,
}

REFERENCED = (
    "qualification/phase6/security/REVIEW_PACKAGE.md",
    "qualification/phase6/security/PIPEFAIL_CORRECTION.md",
    "qualification/phase6/security/symbol_probe.py",
    "qualification/phase6/security/exposure_probe.py",
    "qualification/phase6/security/pipefail_control.sh",
    "qualification/phase6/security/evidence/symbols.json",
    "qualification/phase6/security/evidence/exposure.json",
    "qualification/phase6/baseline/BASELINE.md",
    "qualification/phase6/baseline/baseline.json",
    "qualification/phase6/baseline/freeze.log",
    "qualification/phase6/update/evidence/refusal-qualification.json",
    "qualification/phase5/security/candidate-disposition-matrix.json",
    "qualification/phase5/security/SCAN_ROUTE_DISCREPANCY.md",
    "qualification/phase5/signing/SIGNING_CONFORMANCE.md",
    "UPDATE_TRUST_ARCHITECTURE_DECISION.md",
    "docs/adr/ADR-027-base-image-security-decision.md",
)

#: The one Critical the measurement says fails both tests. Named here so that a
#: future change to either probe that quietly drops it is caught.
SURVIVING_CRITICAL = "GHSA-p77j-4mvh-x3m3"

failures: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print("  [%s] %s%s" % ("ok  " if ok else "FAIL", label, (" -- " + detail) if detail else ""))
    if not ok:
        failures.append(label)


print("Security review package -- self-check")
print("Repository root: %s" % ROOT)
print()

print("1. Referenced files exist")
for reference in REFERENCED:
    check(reference, (ROOT / reference).is_file())

print()
print("2. The inventory says what the package says it says")
matrix_path = ROOT / "qualification/phase5/security/candidate-disposition-matrix.json"
if matrix_path.is_file():
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = matrix["rows"]
    check("bound to the subject commit",
          matrix["scope"]["candidateCommit"] == SUBJECT_COMMIT,
          matrix["scope"]["candidateCommit"][:12])
    check("distinct advisories = %d" % CLAIMED["distinctAdvisories"],
          len(rows) == CLAIMED["distinctAdvisories"], "found %d" % len(rows))
    for severity in ("Critical", "High", "Medium", "Low", "Unknown"):
        actual = sum(1 for row in rows if row["severity"] == severity)
        check("%s = %d" % (severity, CLAIMED[severity]),
              actual == CLAIMED[severity], "found %d" % actual)
    not_pending = sorted({row["status"] for row in rows} - {"PENDING_REVIEW"})
    check("every row is still PENDING_REVIEW", not not_pending,
          ("found " + ", ".join(not_pending)) if not_pending else "80/80")
else:
    check("inventory present", False)

print()
print("3. The exposure measurement supports the package's per-advisory table")
symbols_path = HERE / "evidence" / "symbols.json"
if symbols_path.is_file():
    symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    binaries = symbols["binaries"]
    check("podman and skopeo were both measured",
          any("podman" in name for name in binaries) and any("skopeo" in name for name in binaries))

    podman = binaries.get("/usr/bin/podman", {})
    skopeo = binaries.get("/usr/bin/skopeo", {})
    versions = podman.get("buildInfoVersionsOfInterest", {})
    check("podman embeds x/crypto v0.53.0 (above the v0.52.0 fix)",
          versions.get("golang.org/x/crypto") == ["v0.53.0"],
          str(versions.get("golang.org/x/crypto")))
    check("podman embeds grpc v1.72.2 (below the v1.73.0 fix)",
          versions.get("google.golang.org/grpc") == ["v1.72.2"],
          str(versions.get("google.golang.org/grpc")))
    check("skopeo links no x/crypto ssh package",
          skopeo.get("sshPackagePathsPresent") == [],
          "%d present" % len(skopeo.get("sshPackagePathsPresent", [])))
    check("podman DOES link x/crypto ssh packages (the Phase 5 correction)",
          len(podman.get("sshPackagePathsPresent", [])) > 0,
          "%d present" % len(podman.get("sshPackagePathsPresent", [])))

    surviving = podman.get("advisories", {}).get(SURVIVING_CRITICAL, {})
    check("%s has its named symbols present in podman" % SURVIVING_CRITICAL,
          surviving.get("symbolsPresent", 0) == surviving.get("symbolsNamed", -1)
          and surviving.get("symbolsNamed", 0) > 0,
          "%s/%s" % (surviving.get("symbolsPresent"), surviving.get("symbolsNamed")))

    # Exactly one Critical should fail BOTH tests. If a probe change makes that
    # two, or zero, the package's central claim has moved and must be rewritten.
    def vulnerable_version(detail):
        embedded, fixed = detail.get("embeddedVersions") or [], detail.get("fixedVersion")
        if not embedded or not fixed:
            return None

        def parts(value):
            return tuple(int(p) for p in value.lstrip("v").split(".")[:3])
        return any(parts(v) < parts(fixed) for v in embedded)

    both = set()
    for name, entry in binaries.items():
        for advisory, detail in entry.get("advisories", {}).items():
            if vulnerable_version(detail) and detail.get("symbolsPresent", 0) > 0:
                both.add(advisory)
    check("exactly one Critical fails both the version and the symbol test",
          both == {SURVIVING_CRITICAL}, "found %s" % (sorted(both) or "none"))
else:
    check("symbols.json present", False)

print()
print("4. Claims this verifier cannot close, stated rather than skipped")
for claim, where in (
    ("qcow2 / raw / oci.tar / ISO digests", "qualification/phase6/baseline/freeze.log"),
    ("base and builder image digests", "the artifact's provenance.json on the build host"),
    ("that the scanner was run as described", "qualification/phase5/security/route/"),
):
    print("  [note] %s -- recorded in %s, not re-derived here" % (claim, where))
    notes.append(claim)

print()
if failures:
    print("PACKAGE SELF-CHECK FAILED -- %d check(s):" % len(failures))
    for item in failures:
        print("  - %s" % item)
    sys.exit(1)

print("PACKAGE SELF-CHECK PASSED.")
print("%d claim(s) remain for the reviewer to close against the build host." % len(notes))
print()
print("This says the package is internally consistent. It says nothing about")
print("whether the findings are acceptable -- that is the review.")
