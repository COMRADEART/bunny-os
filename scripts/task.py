#!/usr/bin/env python3
"""Cross-platform entry point for Bunny OS repository checks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.paths import display_path  # noqa: E402
from release.validation import run_validators  # noqa: E402
REQUIRED_DOCS = (
    "README.md", "ARCHITECTURE.md", "docs/CURRENT_STATE_AUDIT.md", "docs/IMAGE_ARCHITECTURE.md",
    "docs/FILESYSTEM_LAYOUT.md", "docs/BUNNY_INTEGRATION_CONTRACT.md", "docs/PRIVILEGED_BROKER.md",
    "docs/BOOT_ARCHITECTURE.md", "docs/OS_SANDBOX_INTEGRATION.md", "docs/NETWORK_SECURITY.md",
    "docs/USER_AND_PRIVILEGE_MODEL.md", "docs/TPM_AND_DEVICE_TRUST.md", "docs/PRIVACY_MODEL.md",
    "docs/THREAT_MODEL.md", "docs/BUILDING.md", "docs/DEVELOPER_IMAGE.md", "docs/RECOVERY.md",
    "docs/UPDATES.md", "docs/HARDWARE_SUPPORT.md", "docs/TESTING.md", "docs/KNOWN_LIMITATIONS.md",
    "docs/ROADMAP.md", "IMPLEMENTATION_REPORT.md", "SECURITY_REVIEW.md", "TEST_REPORT.md",
    "IMAGE_BUILD_REPORT.md", "VM_TEST_REPORT.md", "KNOWN_LIMITATIONS.md", "NEXT_PHASE.md", "PHASE_1_REPORT.md",
    "docs/DESKTOP_BASELINE_AUDIT.md", "docs/BUNNY_SHELL.md", "docs/LAUNCHER.md", "docs/WORKSPACES.md",
    "docs/DESKTOP_SEARCH.md", "docs/BUNNY_TERMINAL.md", "docs/SYSTEM_SETTINGS.md", "docs/NOTIFICATIONS.md",
    "docs/APPROVAL_CENTRE.md", "docs/PRIVACY_DASHBOARD.md", "docs/DESIGN_SYSTEM.md", "docs/VISUAL_IDENTITY.md",
    "docs/ACCESSIBILITY.md", "docs/MULTI_MONITOR.md", "docs/SAFE_SHELL.md", "docs/PERFORMANCE.md",
    "PHASE_2_REPORT.md", "SHELL_SECURITY_REVIEW.md", "DESKTOP_PERFORMANCE_REPORT.md", "ACCESSIBILITY_REPORT.md",
)
PHASE3_DOCS = (
    "docs/INSTALLATION_BASELINE_AUDIT.md", "docs/INSTALLATION.md", "docs/INSTALLER_ARCHITECTURE.md",
    "docs/INSTALLER_PROTOCOL.md", "docs/PARTITIONING.md", "docs/DISK_ENCRYPTION.md", "docs/RECOVERY_KEYS.md",
    "docs/SECURE_BOOT.md", "docs/DUAL_BOOT.md", "docs/OFFLINE_INSTALLATION.md", "docs/FIRST_RUN.md",
    "docs/HARDWARE_PROVISIONING.md", "docs/DRIVERS.md", "docs/NVIDIA.md", "docs/APPLICATIONS.md",
    "docs/FLATPAK.md", "docs/OEM_MODE.md", "docs/AUTOMATED_INSTALLATION.md", "docs/BETA_IMAGES.md",
    "docs/KNOWN_ISSUES.md",
    "docs/adr/ADR-010-installer-framework.md", "docs/adr/ADR-011-encryption-and-unlock.md",
    "docs/adr/ADR-012-application-distribution.md", "docs/adr/ADR-013-driver-provisioning.md",
    "docs/adr/ADR-014-first-run-architecture.md", "docs/adr/ADR-015-dual-boot-policy.md",
    "PHASE_3_REPORT.md", "INSTALLER_SECURITY_REVIEW.md", "INSTALLATION_TEST_REPORT.md",
    "HARDWARE_COMPATIBILITY_REPORT.md", "BETA_IMAGE_REPORT.md", "FIRST_RUN_ACCESSIBILITY_REPORT.md",
    "INSTALLER_PERFORMANCE_REPORT.md",
)
PHASE5_DOCS = (
    "docs/PHASE_5_BASELINE.md", "docs/BETA_OPERATIONS.md", "docs/TRIAGE_PROCESS.md", "docs/BUG_LIFECYCLE.md",
    "docs/UPDATE_COMPATIBILITY.md", "docs/SUPPORT_POLICY.md", "docs/RELEASE_LIFECYCLE.md",
    "docs/BRANCHING_AND_RELEASES.md", "docs/STABLE_RELEASE_BLOCKERS.md", "docs/GETTING_STARTED.md",
    "docs/VERIFY_DOWNLOAD.md", "docs/SYSTEM_REQUIREMENTS.md", "docs/HARDWARE_COMPATIBILITY.md",
    "docs/ROLLBACK.md", "docs/PRIVACY.md", "docs/DIAGNOSTICS.md", "docs/TROUBLESHOOTING.md",
    "docs/REPORTING_BUGS.md", "docs/STABLE_FAQ.md", "PHASE_5_REPORT.md", "BETA_FEEDBACK_REPORT.md",
    "INSTALLER_RELIABILITY_REPORT.md", "UPDATE_RELIABILITY_REPORT.md", "ROLLBACK_QUALIFICATION_REPORT.md",
    "RECOVERY_QUALIFICATION_REPORT.md", "STABLE_HARDWARE_SUPPORT_REPORT.md", "STABLE_CANDIDATE_SECURITY_REVIEW.md",
    "STABLE_CANDIDATE_PRIVACY_REVIEW.md", "STABLE_CANDIDATE_ACCESSIBILITY_REVIEW.md",
    "LONG_DURATION_TEST_REPORT.md", "STABLE_RELEASE_CHECKLIST.md", "STABLE_RELEASE_GO_NO_GO.md",
)


def run(argv: list[str], *, required: bool = True) -> int:
    print("+", " ".join(argv), flush=True)
    value = subprocess.run(argv, cwd=ROOT, check=False).returncode
    if required and value:
        raise SystemExit(value)
    return value


def audit() -> None:
    missing = [name for name in REQUIRED_DOCS if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("missing Phase 1 documents:\n" + "\n".join(missing))
    audit_text = (ROOT / "docs/CURRENT_STATE_AUDIT.md").read_text(encoding="utf-8")
    for heading in ("Repository tree", "Broken scripts", "Missing dependencies", "Security gaps", "Integration gaps"):
        if heading.lower() not in audit_text.lower():
            raise SystemExit(f"baseline audit is missing section: {heading}")
    print(f"audit: {len(REQUIRED_DOCS)} required documents present")


def installer_audit() -> None:
    missing = [name for name in PHASE3_DOCS if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("missing Phase 3 documents:\n" + "\n".join(missing))
    baseline = (ROOT / "docs/INSTALLATION_BASELINE_AUDIT.md").read_text(encoding="utf-8").lower()
    for phrase in ("current image formats", "partition", "bootloader", "encryption readiness", "secure boot readiness", "dual-boot risks", "installation blockers"):
        if phrase not in baseline:
            raise SystemExit(f"installation baseline audit is missing: {phrase}")
    print(f"installer-audit: {len(PHASE3_DOCS)} required Phase 3 documents present")


def phase5_audit() -> None:
    missing = [name for name in PHASE5_DOCS if not (ROOT / name).is_file()]
    demo_root = ROOT / "demos/05-stable-qualification"
    required_demos = (
        "README.md", "beta-feedback-triage.md", "reproduce-issue.md", "installer-regression.md",
        "update-regression.md", "rollback-qualification.md", "recovery-qualification.md", "hardware-validation.md",
        "privacy-regression.md", "accessibility-regression.md", "build-stable-rc.md", "verify-stable-rc.md",
        "stable-gate.md", "troubleshooting.md", "demo-5-minutes.md", "demo-15-minutes.md", "demo-30-minutes.md",
    )
    missing.extend(f"demos/05-stable-qualification/{name}" for name in required_demos if not (demo_root / name).is_file())
    if missing:
        raise SystemExit("missing Phase 5 documents:\n" + "\n".join(missing))
    print(f"phase5-audit: {len(PHASE5_DOCS)} reports/guides and {len(required_demos)} demos present")


def validate() -> None:
    """Run every repository validator and report each one separately.

    This used to be four functions whose failures all collapsed into one
    Boolean. The source gate then reported `repositoryValidation: FAIL` with a
    description naming JSON, schemas and Python, when what had failed was
    ShellCheck on one line of one file. Every validator now names itself and the
    files it rejected, and the machine-readable form is written for the gate.
    """
    report = run_validators(ROOT)
    print("repository validation:", "PASS" if report.passed else "FAIL")
    print(report.render())

    destination = ROOT / "build/out/qualification/repository-validation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"wrote {display_path(destination, ROOT)}")

    if not report.passed:
        raise SystemExit(
            "repository validation failed: "
            + ", ".join(outcome.name for outcome in report.failing)
        )


def tests(pattern: str | None = None) -> None:
    # The top-level directory must be the repository root, not "tests". With
    # "tests" as the top level it lands on sys.path, and test packages such as
    # tests/sync and tests/oem then shadow the real sync/ and oem/ packages.
    argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", str(ROOT)]
    if pattern:
        argv.extend(["-p", pattern])
    run(argv)
    if pattern is None:
        installer_tests()


def installer_tests(pattern: str | None = None) -> None:
    argv = [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests/installer")]
    if pattern:
        argv.extend(["-p", pattern])
    run(argv)


def phase5_tests(pattern: str | None = None) -> None:
    argv = [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests/operations")]
    if pattern:
        argv.extend(["-p", pattern])
    run(argv)


#: The blocker-closure suites. Three of them carry underscores where the brief
#: writes hyphens: a hyphenated directory is not an importable Python package,
#: so ``unittest discover`` would skip it and the tests would silently never
#: run. A test that does not run is worse than one in a differently-spelled
#: directory.
RELEASE_CLOSURE_SUITES = (
    "security",
    "licensing",
    "reproducibility",
    "signing",
    "recovery",
    "release",
    "hardware_evidence",
    "accessibility_evidence",
    "pilot_gates",
    # Added by the qualification evidence closure. Underscores because these are
    # imported as Python packages.
    "reachability",
    "review_evidence",
    # Added by the CI portability repair. These are the regressions that keep
    # the evidence model honest across environments: commit binding, CVE
    # regeneration, protected-gate exit codes, archive-only refusal and hosted
    # evidence import.
    "portability",
)


def release_closure_tests() -> None:
    """Run every release blocker closure suite, in order."""
    for component in RELEASE_CLOSURE_SUITES:
        start = ROOT / "tests" / component
        if not start.is_dir():
            raise SystemExit(f"missing release closure suite: tests/{component}")
        run([sys.executable, "-m", "unittest", "discover", "-s", str(start), "-t", str(ROOT)])


def component_tests(component: str) -> None:
    start = ROOT / "tests" / component
    if not start.is_dir():
        raise SystemExit(f"unknown test component: {component}")
    if component == "installer":
        installer_tests()
    else:
        run([sys.executable, "-m", "unittest", "discover", "-s", str(start), "-t", str(ROOT)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=(
        "audit", "validate", "test", "test-security", "test-broker", "test-shell", "test-launcher",
        "test-search", "test-workspace", "test-panel", "test-notifications", "test-approvals", "test-settings",
        "test-terminal", "test-accessibility", "test-performance", "test-desktop-security", "installer-audit",
        "test-installer", "test-storage", "test-encryption", "test-dual-boot", "test-first-run",
        "test-app-distribution", "test-installer-security",
        "phase5-audit", "test-phase5", "test-installer-regressions", "test-update-regressions",
        "test-rollbacks", "test-recovery-qualification", "test-migrations", "test-multi-user",
        "test-bunny-disabled", "test-local-only", "test-privacy-regressions", "test-accessibility-regressions",
        "test-hardware-matrix", "test-hardware-report", "test-diagnostics", "test-redaction",
        "test-crash-reporting", "test-network-privacy", "test-application-catalogue", "test-release-signing",
        "phase7-audit", "test-oem", "test-factory", "test-device-identity", "test-enrolment",
        "test-policy", "test-fleet", "test-multitenancy", "test-sync", "test-sync-crypto",
        "test-device-revocation", "test-remote-wipe", "test-airgap", "test-kiosk",
        "test-decommission", "test-pilot",
        "test-release-closure", "test-licensing", "test-reproducibility", "test-signing",
        "test-release", "test-hardware-evidence", "test-accessibility-evidence", "test-pilot-gates",
        "test-capability", "test-companion",
        "test-trust", "test-capsules", "test-app-catalog", "test-capsule-task", "test-capsule-phase",
        "test-model-studio", "test-model-bridge",
    ))
    args = parser.parse_args()
    if args.command == "audit":
        audit()
    elif args.command == "installer-audit":
        installer_audit()
    elif args.command == "phase5-audit":
        phase5_audit()
    elif args.command == "validate":
        validate()
    elif args.command == "test-security":
        tests("test_security*.py")
    elif args.command == "test-broker":
        tests("test_broker*.py")
    elif args.command == "test-desktop-security":
        component_tests("security")
    elif args.command == "test-installer":
        component_tests("installer")
    elif args.command == "test-storage" or args.command == "test-dual-boot":
        installer_tests("test_storage.py")
    elif args.command == "test-encryption":
        installer_tests("test_encryption.py")
    elif args.command == "test-first-run":
        installer_tests("test_first_run.py")
    elif args.command == "test-app-distribution":
        installer_tests("test_applications.py")
    elif args.command == "test-installer-security":
        installer_tests("test_security.py")
    elif args.command == "test-phase5":
        phase5_tests()
    elif args.command == "test-installer-regressions":
        phase5_tests("test_installer_journal.py")
    elif args.command == "test-update-regressions":
        phase5_tests("test_compatibility.py")
    elif args.command == "test-rollbacks" or args.command == "test-recovery-qualification" or args.command == "test-migrations":
        phase5_tests("test_preservation.py")
    elif args.command == "test-multi-user" or args.command == "test-bunny-disabled" or args.command == "test-local-only":
        phase5_tests("test_modes.py")
    elif args.command == "test-privacy-regressions" or args.command == "test-diagnostics" or args.command == "test-redaction" or args.command == "test-network-privacy":
        phase5_tests("test_redaction.py")
    elif args.command == "test-accessibility-regressions":
        phase5_tests("test_qualification.py")
    elif args.command == "test-hardware-matrix" or args.command == "test-hardware-report":
        phase5_tests("test_hardware.py")
    elif args.command == "test-crash-reporting":
        phase5_tests("test_crash.py")
    elif args.command == "test-application-catalogue":
        phase5_tests("test_catalogue.py")
    elif args.command == "test-release-signing":
        phase5_tests("test_candidate.py")
    elif args.command == "phase7-audit":
        run([sys.executable, "scripts/phase7.py", "audit"])
    elif args.command == "test-device-identity":
        component_tests("identity")
    elif args.command == "test-sync-crypto":
        component_tests("cryptography")
    elif args.command == "test-device-revocation":
        # Revocation spans two subsystems: sync key rotation and organisation
        # decommissioning. Both must pass for revocation to be meaningful.
        component_tests("sync")
        component_tests("decommission")
    elif args.command == "test-remote-wipe":
        component_tests("fleet")
    elif args.command == "test-release-closure":
        release_closure_tests()
    elif args.command == "test-hardware-evidence":
        component_tests("hardware_evidence")
    elif args.command == "test-accessibility-evidence":
        component_tests("accessibility_evidence")
    elif args.command == "test-pilot-gates":
        component_tests("pilot_gates")
    elif args.command == "test-app-catalog":
        component_tests("app_catalog")
    elif args.command == "test-capsule-task":
        component_tests("capsule_task")
    elif args.command == "test-model-bridge":
        # The runtime model bridge. Needs no model, GPU, inference server or
        # network; the real runtime slice skips unless
        # BUNNY_MODEL_BRIDGE_HEAVY=1.
        component_tests("model_bridge")
    elif args.command == "test-model-studio":
        # Bunny Model Studio. Nothing here needs torch, a GPU or the network;
        # the one test that trains a real model skips unless
        # BUNNY_MODEL_STUDIO_HEAVY=1, so this target never downloads anything.
        component_tests("model_studio")
    elif args.command == "test-capsule-phase":
        # The whole of the Companion/Capsule/Trust phase, in the order a failure
        # is cheapest to read: the permission layer first, then what it is used
        # to build, then the catalogue that feeds it, then the slice that joins
        # all three, then the surfaces. A capsule failure caused by a trust
        # regression should be reported by the trust suite, not by the slice.
        for component in ("trust", "capsules", "app_catalog", "capsule_task"):
            component_tests(component)
        run([sys.executable, "-m", "unittest", "tests.shell.test_companion_surfaces"])
        run([sys.executable, "-m", "unittest", "tests.installer.test_companion_flow"])
    elif args.command.startswith("test-"):
        component_tests(args.command.removeprefix("test-"))
    else:
        tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
