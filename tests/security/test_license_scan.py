from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT


SCRIPT = ROOT / "build/scripts/license-scan.py"


def package(package_id: str, name: str, license_declared: str = "NOASSERTION", version: str = "1") -> dict[str, object]:
    return {
        "SPDXID": package_id,
        "name": name,
        "versionInfo": version,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": license_declared,
        "externalRefs": [],
    }


class LicenseScanTests(unittest.TestCase):
    def run_scan(self, sbom: dict[str, object], release: bool = True) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.spdx.json"
            path.write_text(json.dumps(sbom), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), str(path)]
            if release:
                command.append("--release")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            report = json.loads(path.with_name("license-report.json").read_text(encoding="utf-8"))
            return result, report

    def test_declared_license_is_used_when_concluded_is_noassertion(self) -> None:
        result, report = self.run_scan({"packages": [package("SPDXRef-Package-app", "app", "MIT")]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["unknownLicenses"], [])

    def test_release_scan_fails_for_an_uncovered_unknown(self) -> None:
        result, report = self.run_scan({"packages": [package("SPDXRef-Package-app", "app")]})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["unknownLicenses"], ["app"])

    def test_syft_owned_component_is_covered_by_licensed_rpm(self) -> None:
        owner = package("SPDXRef-Package-rpm-tool", "tool", "Apache-2.0")
        child = package("SPDXRef-Package-go-dependency", "example.org/dependency")
        sbom = {
            "packages": [owner, child],
            "relationships": [
                {
                    "spdxElementId": owner["SPDXID"],
                    "relatedSpdxElement": child["SPDXID"],
                    "relationshipType": "OTHER",
                    "comment": "ownership-by-file-overlap: package owns the discovered binary",
                }
            ],
        }
        result, report = self.run_scan(sbom)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["unknownLicenses"], [])
        self.assertEqual(
            report["coveredNoAssertion"],
            [{"package": "example.org/dependency", "reason": "licensed-owner:tool"}],
        )


if __name__ == "__main__":
    unittest.main()
