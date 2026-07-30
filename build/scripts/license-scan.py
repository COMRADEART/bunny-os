#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply the repository redistribution policy to an SPDX JSON SBOM."""

import argparse
import json
from pathlib import Path
import re


NOASSERTION = "NOASSERTION"


def effective_license(package: dict[str, object]) -> str:
    """Prefer a real concluded license, then the declared SPDX expression."""
    for field in ("licenseConcluded", "licenseDeclared"):
        value = package.get(field)
        if isinstance(value, str) and value.strip() and value != NOASSERTION:
            return value
    return NOASSERTION


def package_identity(package: dict[str, object]) -> tuple[str, str]:
    return (str(package.get("name", "unknown")), str(package.get("versionInfo", "UNKNOWN")))


def purls(package: dict[str, object]) -> list[str]:
    values = []
    for reference in package.get("externalRefs", []):
        if not isinstance(reference, dict):
            continue
        value = reference.get("referenceLocator")
        if isinstance(value, str) and value.startswith("pkg:"):
            values.append(value)
    return values


def covered_noassertion_packages(sbom: dict[str, object]) -> dict[str, str]:
    """Explain NOASSERTION records that are provenance aliases, not new license gaps.

    Syft emits both an RPM record and records inferred from files owned by that RPM.
    The inferred records may omit their license even though SPDX relationships bind
    them to the licensed distribution package. It can also emit duplicate identities,
    the described OCI document root, and a synthetic linux-kernel record alongside
    the licensed Fedora kernel RPM. Keep those records visible in the report while
    reserving release failure for unresolved components.
    """
    packages = [value for value in sbom.get("packages", []) if isinstance(value, dict)]
    by_id = {str(value.get("SPDXID")): value for value in packages if value.get("SPDXID")}
    known_identities = {package_identity(value) for value in packages if effective_license(value) != NOASSERTION}
    covered: dict[str, str] = {}

    for value in packages:
        package_id = str(value.get("SPDXID", ""))
        if package_id and effective_license(value) == NOASSERTION and package_identity(value) in known_identities:
            covered[package_id] = "duplicate-identity-with-declared-license"

    for relationship in sbom.get("relationships", []):
        if not isinstance(relationship, dict):
            continue
        parent_id = str(relationship.get("spdxElementId", ""))
        child_id = str(relationship.get("relatedSpdxElement", ""))
        comment = str(relationship.get("comment", ""))
        parent = by_id.get(parent_id)
        if (
            comment.startswith("ownership-by-file-overlap:")
            and child_id in by_id
            and parent is not None
            and (effective_license(parent) != NOASSERTION or package_identity(parent) in known_identities)
        ):
            covered[child_id] = f"licensed-owner:{parent.get('name', 'unknown')}"
        if parent_id == "SPDXRef-DOCUMENT" and relationship.get("relationshipType") == "DESCRIBES":
            covered[child_id] = "spdx-described-artifact"

    licensed_kernels = {
        str(value.get("versionInfo", "UNKNOWN"))
        for value in packages
        if value.get("name") in {"kernel", "kernel-core"} and effective_license(value) != NOASSERTION
    }
    for value in packages:
        package_id = str(value.get("SPDXID", ""))
        version = str(value.get("versionInfo", "UNKNOWN"))
        if (
            package_id
            and effective_license(value) == NOASSERTION
            and any(item.startswith("pkg:generic/linux-kernel@") for item in purls(value))
            and any(version == kernel_version or version.startswith(f"{kernel_version}.") for kernel_version in licensed_kernels)
        ):
            covered[package_id] = "licensed-fedora-kernel-rpm"

    return covered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sbom", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    policy = json.loads(Path("build/license-policy.json").read_text(encoding="utf-8"))
    sbom = json.loads(args.sbom.read_text(encoding="utf-8"))
    findings = []
    unknown = []
    covered = covered_noassertion_packages(sbom)
    covered_report = []
    packages = [value for value in sbom.get("packages", []) if isinstance(value, dict)]
    for package in packages:
        license_value = effective_license(package)
        name = str(package.get("name", "unknown"))
        package_id = str(package.get("SPDXID", ""))
        if license_value == NOASSERTION:
            if package_id in covered:
                covered_report.append({"package": name, "reason": covered[package_id]})
            else:
                unknown.append(name)
        if any(re.search(pattern, license_value) for pattern in policy["prohibitedLicensePatterns"]):
            findings.append({"package": name, "license": license_value})
    report = {
        "schemaVersion": 1,
        "packages": len(packages),
        "coveredNoAssertion": sorted(covered_report, key=lambda value: (value["package"], value["reason"])),
        "unknownLicenses": sorted(unknown),
        "prohibited": findings,
    }
    args.sbom.with_name("license-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if findings or (args.release and policy["failOnNoAssertionInRelease"] and unknown):
        raise SystemExit("license policy failed; inspect license-report.json")
    print(f"license scan: {report['packages']} packages, {len(unknown)} unresolved, no prohibited markers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

