#!/usr/bin/python3
"""Apply the repository redistribution policy to an SPDX JSON SBOM."""

import argparse
import json
from pathlib import Path
import re


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sbom", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    policy = json.loads(Path("build/license-policy.json").read_text(encoding="utf-8"))
    sbom = json.loads(args.sbom.read_text(encoding="utf-8"))
    findings = []
    unknown = []
    for package in sbom.get("packages", []):
        license_value = package.get("licenseConcluded") or package.get("licenseDeclared") or "NOASSERTION"
        name = package.get("name", "unknown")
        if license_value == "NOASSERTION":
            unknown.append(name)
        if any(re.search(pattern, license_value) for pattern in policy["prohibitedLicensePatterns"]):
            findings.append({"package": name, "license": license_value})
    report = {"schemaVersion": 1, "packages": len(sbom.get("packages", [])), "unknownLicenses": sorted(unknown), "prohibited": findings}
    args.sbom.with_name("license-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if findings or (args.release and policy["failOnNoAssertionInRelease"] and unknown):
        raise SystemExit("license policy failed; inspect license-report.json")
    print(f"license scan: {report['packages']} packages, {len(unknown)} unresolved, no prohibited markers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

