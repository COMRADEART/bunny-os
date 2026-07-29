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


def validate_json() -> None:
    paths = sorted({
        *[path for path in (ROOT / "schemas").rglob("*.json")],
        *[path for path in (ROOT / "shell").rglob("*.json")],
        *[path for path in (ROOT / "build").rglob("*.json") if "out" not in path.parts],
    })
    for path in paths:
        json.loads(path.read_text(encoding="utf-8"))
    schema_paths = sorted([*(ROOT / "schemas").rglob("*.schema.json"), *(ROOT / "shell/schemas").glob("*.schema.json")])
    for path in schema_paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or not schema.get("$id") or schema.get("type") != "object":
            raise SystemExit(f"schema header is invalid: {path}")
        def resolve_local(node: object) -> None:
            if isinstance(node, dict):
                reference = node.get("$ref")
                if isinstance(reference, str) and reference.startswith("#/"):
                    target: object = schema
                    for component in reference[2:].split("/"):
                        component = component.replace("~1", "/").replace("~0", "~")
                        if not isinstance(target, dict) or component not in target:
                            raise SystemExit(f"unresolved local reference {reference} in {path}")
                        target = target[component]
                for value in node.values():
                    resolve_local(value)
            elif isinstance(node, list):
                for value in node:
                    resolve_local(value)
        resolve_local(schema)
    try:
        import jsonschema  # type: ignore
    except ImportError:
        print("SKIP: jsonschema package unavailable; JSON syntax still validated")
    else:
        for path in schema_paths:
            jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    print(f"validate: {len(paths)} JSON documents parsed; {len(schema_paths)} schemas have valid headers and local references")


def validate_python() -> None:
    paths = [path for path in ROOT.rglob("*.py") if not any(part in {"node_modules", ".selfcheck-tmp", ".git"} for part in path.parts)]
    for path in paths:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    print(f"validate: {len(paths)} Python files compiled in memory")


def validate_external() -> None:
    unit_paths = [str(path) for path in sorted((ROOT / "systemd").glob("*.*")) if path.suffix in {".service", ".socket", ".timer", ".target"}]
    if shutil.which("systemd-analyze") and os.environ.get("BUNNY_VERIFY_SYSTEMD") == "1":
        run(["systemd-analyze", "verify", *unit_paths])
    else:
        print("SKIP: systemd-analyze requires BUNNY_VERIFY_SYSTEMD=1 on an installed Fedora fixture")
    shell_paths = [str(path) for path in sorted(ROOT.rglob("*.sh")) if "node_modules" not in path.parts]
    if shutil.which("shellcheck"):
        run(["shellcheck", *shell_paths])
    else:
        print("SKIP: shellcheck unavailable on this host")
    extension = ROOT / "shell/components/gnome-shell-extension/extension.js"
    if shutil.which("node"):
        run(["node", "--check", str(extension)])
    else:
        print("SKIP: node unavailable for GNOME extension syntax parsing")


def validate_shell_assets() -> None:
    from configparser import ConfigParser
    desktop_paths = sorted({*(ROOT / "shell").rglob("*.desktop"), *(ROOT / "installer").rglob("*.desktop")})
    for path in desktop_paths:
        parser = ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read(path, encoding="utf-8")
        if not parser.has_section("Desktop Entry") or parser["Desktop Entry"].get("Type") != "Application" or not parser["Desktop Entry"].get("Name") or not parser["Desktop Entry"].get("Exec"):
            raise SystemExit(f"desktop entry is invalid: {path}")
    xml_paths = [ROOT / "shell/components/gnome-shell-extension/schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml", *sorted((ROOT / "shell/assets").rglob("*.svg")), *sorted((ROOT / "shell/icons").rglob("*.svg"))]
    for path in xml_paths:
        ET.parse(path)
    required_directories = ("session", "services", "components", "schemas", "themes", "assets", "icons")
    for name in required_directories:
        if not (ROOT / "shell" / name).is_dir():
            raise SystemExit(f"missing shell directory: shell/{name}")
    print(f"validate: {len(desktop_paths)} desktop entries and {len(xml_paths)} XML/SVG assets parsed")


def validate() -> None:
    validate_json()
    validate_python()
    validate_shell_assets()
    validate_external()
    run([sys.executable, "docs/phase-1/verify.ps1"], required=False) if False else None
    print("validate: repository-native checks passed")


def tests(pattern: str | None = None) -> None:
    argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
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
    ))
    args = parser.parse_args()
    if args.command == "audit":
        audit()
    elif args.command == "installer-audit":
        installer_audit()
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
    elif args.command.startswith("test-"):
        component_tests(args.command.removeprefix("test-"))
    else:
        tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
