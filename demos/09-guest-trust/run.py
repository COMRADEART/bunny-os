#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-command guest Trust / approval demo.

A Fedora 44 image-builder host with a composed shell-test QCOW2 boots Bunny
OS twice and drives granted + denied through AT-SPI. This cloud Ubuntu host
typically has KVM and (after install) QEMU/Podman but no ``image-builder``,
so the same command records an honest NOT_RUN instead of inventing a guest.

Run from the repository root::

    python3 demos/09-guest-trust/run.py
    make demo-guest-trust
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from companion.trust_surface import ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME


OVMF_CANDIDATES = (
    os.environ.get("BUNNY_OVMF_CODE") or "",
    os.environ.get("OVMF_CODE") or "",
    "/usr/share/OVMF/OVMF_CODE.fd",
    "/usr/share/OVMF/OVMF_CODE_4M.fd",
    "/usr/share/edk2/ovmf/OVMF_CODE.fd",
    "/usr/share/qemu/OVMF.fd",
)

FORBIDDEN_LABELS = ("Always allow everything", "alwaysAllowEverything")
JOURNEYS = ("granted", "denied")
DRIVER = ROOT / "build/scripts/desktop-drive.py"
STORY = ROOT / "build/scripts/vm-desktop-story.sh"
GUEST_BOOT = ROOT / "build/scripts/vm-guest-trust.sh"


def _which(name: str) -> str | None:
    return shutil.which(name)


def _kvm_writable() -> bool:
    path = Path("/dev/kvm")
    if not path.exists():
        return False
    try:
        mode = path.stat().st_mode
        if os.access(path, os.R_OK | os.W_OK):
            return True
        return bool(mode & stat.S_IROTH and mode & stat.S_IWOTH)
    except OSError:
        return False


def find_firmware() -> str:
    for candidate in OVMF_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def find_qcow(profile: str = "shell-test") -> str:
    forced = os.environ.get("BUNNY_DESKTOP_IMAGE") or ""
    if forced and Path(forced).is_file():
        return forced
    root = ROOT / "build/out" / profile
    if not root.is_dir():
        return ""
    for path in sorted(root.rglob("*.qcow2")):
        if "desktop-story" in path.parts or "guest-trust" in path.parts:
            continue
        return str(path)
    return ""


def probe_host() -> dict[str, object]:
    qemu = _which("qemu-system-x86_64")
    podman = _which("podman")
    guestfish = _which("guestfish")
    image_builder = _which("image-builder")
    firmware = find_firmware()
    qcow = find_qcow()
    kvm = Path("/dev/kvm").exists()
    kvm_rw = _kvm_writable()
    missing: list[str] = []
    if not kvm:
        missing.append("/dev/kvm")
    elif not kvm_rw:
        missing.append("writable /dev/kvm")
    if not qemu:
        missing.append("qemu-system-x86_64")
    if not firmware:
        missing.append("OVMF firmware")
    if not guestfish:
        missing.append("guestfish")
    if not qcow:
        missing.append("shell-test qcow2")
    if not image_builder and not qcow:
        missing.append("image-builder")
    can_boot = bool(kvm and kvm_rw and qemu and firmware and guestfish and qcow)
    if can_boot:
        guest_boot = "AVAILABLE"
        reason = "QEMU/KVM, firmware, guestfish and a QCOW2 are present; this demo will boot"
    elif qcow:
        guest_boot = "BLOCKED"
        reason = "a QCOW2 exists but the host cannot boot it: " + ", ".join(missing)
    else:
        guest_boot = "NOT_RUN"
        reason = (
            "no composed Bunny OS disk; image-builder is a Fedora 44 package "
            "and is not available on this host"
            if not image_builder
            else "image-builder is present but no QCOW2 has been composed yet"
        )
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "osRelease": _os_release(),
        "kvmDevice": kvm,
        "kvmWritable": kvm_rw,
        "qemu": qemu or "",
        "podman": podman or "",
        "guestfish": guestfish or "",
        "imageBuilder": image_builder or "",
        "firmware": firmware,
        "qcow": qcow,
        "missing": missing,
        "canBootGuest": can_boot,
        "guestBoot": guest_boot,
        "guestBootReason": reason,
        "releaseState": "NO-GO",
        "pilots": "BLOCKED",
        "accessibleNames": {
            "allow": ALLOW_ACCESSIBLE_NAME,
            "deny": DENY_ACCESSIBLE_NAME,
        },
    }


def _os_release() -> str:
    path = Path("/etc/os-release")
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    for key in ("PRETTY_NAME", "NAME"):
        for line in text.splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def kvm_smoke() -> dict[str, object]:
    """Prove KVM acceleration, not a Bunny guest."""
    qemu = _which("qemu-system-x86_64")
    if not qemu:
        return {"ok": False, "status": "NOT_RUN", "reason": "qemu-system-x86_64 is not installed"}
    if not Path("/dev/kvm").exists():
        return {"ok": False, "status": "NOT_RUN", "reason": "/dev/kvm is absent"}
    argv = [
        qemu,
        "-machine", "q35,accel=kvm",
        "-cpu", "max",
        "-m", "64",
        "-display", "none",
        "-nographic",
        "-nodefaults",
        "-serial", "none",
        "-monitor", "none",
        "-S",
    ]
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=6, check=False,
        )
    except subprocess.TimeoutExpired:
        # -S waits for a continue that never comes; timeout means KVM started.
        return {"ok": True, "status": "PASS", "reason": "QEMU accepted accel=kvm (timed wait)"}
    except OSError as exc:
        return {"ok": False, "status": "FAIL", "reason": str(exc)}
    stderr = (completed.stderr or "")[-500:]
    if completed.returncode == 0:
        return {"ok": True, "status": "PASS", "reason": "QEMU accel=kvm exited 0", "stderr": stderr}
    permission = "Permission denied" in stderr or "kvm" in stderr.lower()
    return {
        "ok": False,
        "status": "FAIL" if not permission else "BLOCKED",
        "reason": stderr.strip() or f"qemu exit {completed.returncode}",
        "stderr": stderr,
    }


def run_deadline_tests() -> dict[str, object]:
    from tests.shell.test_desktop_shell import ApprovalIsNotASlowAnswerTests

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(ApprovalIsNotASlowAnswerTests)
    buffer = unittest.TestResult()
    suite.run(buffer)
    failures = [f"{test.id()}: {err}" for test, err in buffer.failures + buffer.errors]
    return {
        "ok": buffer.wasSuccessful(),
        "run": buffer.testsRun,
        "failures": failures,
    }


def run_harness_tests() -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.shell.test_guest_trust_harness"],
        cwd=ROOT, text=True, capture_output=True, timeout=120, check=False,
    )
    ran = 0
    for line in (completed.stderr or "").splitlines() + (completed.stdout or "").splitlines():
        if line.startswith("Ran ") and " test" in line:
            try:
                ran = int(line.split()[1])
            except ValueError:
                ran = 0
    return {
        "ok": completed.returncode == 0,
        "run": ran,
        "failures": [] if completed.returncode == 0 else [
            (completed.stderr or completed.stdout)[-4000:]
        ],
    }


def fedora_commands() -> list[str]:
    return [
        "sudo dnf install -y git make podman image-builder osbuild-selinux "
        "qemu-system-x86 edk2-ovmf guestfs-tools ShellCheck",
        "# add the operator to the kvm group so /dev/kvm is writable",
        "make build-shell-test-image",
        "python3 demos/09-guest-trust/run.py",
        "# equivalent: make demo-guest-trust",
        "# optional: BUNNY_DESKTOP_IMAGE=build/out/shell/<file>.qcow2 make demo-guest-trust",
    ]


def maybe_build_image(host: dict[str, object]) -> dict[str, object]:
    if host.get("qcow"):
        return {"ok": True, "status": "SKIP", "reason": "QCOW2 already present"}
    if not host.get("imageBuilder"):
        return {
            "ok": False,
            "status": "NOT_RUN",
            "reason": "image-builder is not installed (Fedora 44 package; not shipped on Ubuntu)",
        }
    print("image-builder present and no QCOW2; composing shell-test...", flush=True)
    completed = subprocess.run(
        ["make", "build-shell-test-image"],
        cwd=ROOT, text=True, capture_output=True, timeout=8 * 3600, check=False,
    )
    qcow = find_qcow()
    return {
        "ok": completed.returncode == 0 and bool(qcow),
        "status": "PASS" if completed.returncode == 0 and qcow else "FAIL",
        "exit": completed.returncode,
        "qcow": qcow,
        "stderrTail": (completed.stderr or "")[-4000:],
        "stdoutTail": (completed.stdout or "")[-2000:],
    }


def run_guest_journeys(work: Path, host: dict[str, object]) -> dict[str, object]:
    if not host.get("canBootGuest") and not host.get("qcow"):
        return {
            "ok": False,
            "status": str(host.get("guestBoot") or "NOT_RUN"),
            "reason": str(host.get("guestBootReason") or ""),
            "journeys": {name: {"status": "NOT_RUN"} for name in JOURNEYS},
        }
    if not host.get("canBootGuest"):
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": str(host.get("guestBootReason") or "host cannot boot a guest"),
            "journeys": {name: {"status": "BLOCKED"} for name in JOURNEYS},
        }
    destination = work / "guest"
    destination.mkdir(parents=True, exist_ok=True)
    print("booting granted then denied Trust journeys...", flush=True)
    completed = subprocess.run(
        ["bash", str(GUEST_BOOT), str(destination)],
        cwd=ROOT, text=True, capture_output=True, timeout=4 * 3600, check=False,
    )
    journeys: dict[str, object] = {}
    for name in JOURNEYS:
        journeys[name] = summarise_journey(destination / name, name)
    ok = completed.returncode == 0 and all(
        isinstance(item, dict) and item.get("status") == "PASS" for item in journeys.values()
    )
    return {
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "exit": completed.returncode,
        "stdoutTail": (completed.stdout or "")[-4000:],
        "stderrTail": (completed.stderr or "")[-4000:],
        "journeys": journeys,
    }


def summarise_journey(work: Path, expected: str) -> dict[str, object]:
    report_path = work / "interaction.json"
    if not report_path.is_file():
        return {"status": "NOT_RUN", "reason": f"no interaction.json under {work}"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    journey = report.get("journey") or {}
    screens = work / "screens"
    shots = sorted(p.name for p in screens.glob("*") if p.suffix.lower() in {".png", ".ppm"}) if screens.is_dir() else []
    prompt_shot = any("trust-prompt" in name or "asking" in name or "state-" in name for name in shots)
    pressed = journey.get("pressed") or ""
    wanted = ALLOW_ACCESSIBLE_NAME if expected == "granted" else DENY_ACCESSIBLE_NAME
    protocol_shortcut = "resolve_approval" in json.dumps(journey)
    passed = (
        report.get("status") == "complete"
        and journey.get("approvalVisible") is True
        and pressed == wanted
        and prompt_shot
        and not protocol_shortcut
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "reportStatus": report.get("status"),
        "decision": journey.get("decision"),
        "ready": (journey.get("ready") or {}).get("ok"),
        "activated": journey.get("activated"),
        "approvalVisible": journey.get("approvalVisible"),
        "pressed": pressed,
        "wanted": wanted,
        "statesBeforeApproval": journey.get("statesBeforeApproval"),
        "statesAfterApproval": journey.get("statesAfterApproval"),
        "screenshots": shots,
        "promptPhotographed": prompt_shot,
        "usedResolveApproval": protocol_shortcut,
        "interaction": str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else str(report_path),
    }


def write_walkthrough(work: Path, report: dict[str, object]) -> Path:
    host = report["host"]
    guest = report["guest"]
    smoke = report["kvmSmoke"]
    lines = [
        "# Guest Trust journey",
        "",
        "This document is evidence. A missing guest is recorded as NOT_RUN or "
        "BLOCKED, never as PASS.",
        "",
        f"- captured: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"- host: {host.get('osRelease') or host.get('platform')}",
        f"- stable release: {host.get('releaseState')}",
        f"- pilots: {host.get('pilots')}",
        "",
        "## Host probe",
        "",
        f"- `/dev/kvm`: {'PASS' if host.get('kvmDevice') else 'ABSENT'}"
        f" (writable={'yes' if host.get('kvmWritable') else 'no'})",
        f"- QEMU: {host.get('qemu') or 'ABSENT'}",
        f"- OVMF: {host.get('firmware') or 'ABSENT'}",
        f"- Podman: {host.get('podman') or 'ABSENT'}",
        f"- guestfish: {host.get('guestfish') or 'ABSENT'}",
        f"- image-builder: {host.get('imageBuilder') or 'ABSENT'}",
        f"- QCOW2: {host.get('qcow') or 'ABSENT'}",
        f"- KVM smoke: {smoke.get('status')} — {smoke.get('reason')}",
        f"- guest boot: **{host.get('guestBoot')}** — {host.get('guestBootReason')}",
        f"- probePassed: {report.get('probePassed')}",
        f"- guestPassed: {report.get('guestPassed')}",
        f"- passed: {report.get('passed')}",
        "",
        "`report.passed` is **guest Trust success only** (`guestPassed`). "
        "`report.probePassed` is the host harness. NOT_RUN/BLOCKED is not a "
        "guest PASS. Set `BUNNY_GUEST_TRUST_PROBE_OK=1` if a dashboard still "
        "wants the old probe-only `passed` bit. This is **not** a "
        "stable-release GO.",
        "",
        "## Host regressions (no guest required)",
        "",
        f"- Approval is not a timeout: {'PASS' if report['deadline']['ok'] else 'FAIL'} "
        f"({report['deadline']['run']} tests)",
        f"- Guest Trust harness contract: {'PASS' if report['harness']['ok'] else 'FAIL'} "
        f"({report['harness']['run']} tests)",
        f"- Accessible names: `{ALLOW_ACCESSIBLE_NAME}` / `{DENY_ACCESSIBLE_NAME}`",
        "",
        "## Guest journeys (AT-SPI, not resolve_approval)",
        "",
    ]
    journeys = (guest.get("journeys") or {}) if isinstance(guest, dict) else {}
    for name in JOURNEYS:
        item = journeys.get(name) or {"status": "NOT_RUN"}
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- result: **{item.get('status')}**")
        if item.get("reason"):
            lines.append(f"- reason: {item['reason']}")
        if item.get("pressed"):
            lines.append(f"- pressed: `{item.get('pressed')}` (want `{item.get('wanted')}`)")
        if item.get("approvalVisible") is not None:
            lines.append(f"- approval visible: {item.get('approvalVisible')}")
        if item.get("screenshots"):
            lines.append(f"- screenshots: {', '.join(item['screenshots'][:12])}")
        lines.append("")
    lines.extend([
        "## Still needs a Fedora 44 image-builder host",
        "",
        "These commands finish the guest photograph. They are not claimed here.",
        "",
        "```text",
        *fedora_commands(),
        "```",
        "",
        "Deny-by-default is unchanged. There is no Always allow everything control.",
        "",
    ])
    path = work / "WALKTHROUGH.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    del argv
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    work = ROOT / "demos/09-guest-trust/out" / stamp
    work.mkdir(parents=True, exist_ok=True)
    latest = ROOT / "demos/09-guest-trust/out/latest"
    print(f"guest-trust demo → {work}", flush=True)

    host = probe_host()
    print(
        f"host: os={host['osRelease']!r} kvm={host['kvmDevice']} "
        f"qemu={host['qemu'] or 'ABSENT'} podman={host['podman'] or 'ABSENT'} "
        f"image-builder={host['imageBuilder'] or 'ABSENT'} "
        f"qcow={bool(host['qcow'])} guest={host['guestBoot']}",
        flush=True,
    )

    smoke = kvm_smoke()
    print(f"kvm smoke: {smoke['status']} — {smoke['reason']}", flush=True)

    deadline = run_deadline_tests()
    print(f"deadline tests: {deadline['run']} run, {'PASS' if deadline['ok'] else 'FAIL'}", flush=True)
    for item in deadline["failures"]:
        print(f"  FAIL {item}", flush=True)

    harness = run_harness_tests()
    print(f"harness tests: {harness['run']} run, {'PASS' if harness['ok'] else 'FAIL'}", flush=True)
    for item in harness["failures"]:
        print(f"  FAIL {item}", flush=True)

    build = maybe_build_image(host)
    print(f"image compose: {build['status']} — {build.get('reason') or build.get('qcow') or ''}", flush=True)
    if build.get("qcow"):
        host["qcow"] = build["qcow"]
        host["canBootGuest"] = bool(
            host.get("kvmDevice") and host.get("kvmWritable") and host.get("qemu")
            and host.get("firmware") and host.get("guestfish") and host.get("qcow")
        )
        if host["canBootGuest"]:
            host["guestBoot"] = "AVAILABLE"
            host["guestBootReason"] = "QCOW2 composed; this demo will boot"

    guest = run_guest_journeys(work, host)
    print(f"guest journeys: {guest['status']}", flush=True)

    host_ok = bool(deadline["ok"] and harness["ok"])
    guest_status = str(guest.get("status") or "NOT_RUN")
    probe_passed = host_ok
    guest_passed = guest_status == "PASS"
    # Top-level ``passed`` is guest Trust success only. An honest NOT_RUN must
    # not look like a guest PASS. Set BUNNY_GUEST_TRUST_PROBE_OK=1 to restore
    # the old meaning (host harness OK and guest is PASS/NOT_RUN/BLOCKED).
    if os.environ.get("BUNNY_GUEST_TRUST_PROBE_OK") == "1":
        passed = probe_passed and guest_status in {"PASS", "NOT_RUN", "BLOCKED"}
    else:
        passed = guest_passed
    report = {
        "demo": "guest-trust-journey",
        "honest": True,
        "stableRelease": "NO-GO",
        "pilots": "BLOCKED",
        "guestBoot": host["guestBoot"],
        "host": host,
        "kvmSmoke": smoke,
        "deadline": deadline,
        "harness": harness,
        "imageCompose": {k: v for k, v in build.items() if k not in {"stdoutTail", "stderrTail"}},
        "guest": {
            "status": guest.get("status"),
            "ok": guest.get("ok"),
            "reason": guest.get("reason"),
            "journeys": guest.get("journeys"),
        },
        "probePassed": probe_passed,
        "guestPassed": guest_passed,
        "passed": passed,
        "summary": {
            "hostRegressions": "PASS" if host_ok else "FAIL",
            "kvmSmoke": smoke.get("status"),
            "imageCompose": build.get("status"),
            "guestGranted": (guest.get("journeys") or {}).get("granted", {}).get("status", "NOT_RUN") if isinstance(guest.get("journeys"), dict) else "NOT_RUN",
            "guestDenied": (guest.get("journeys") or {}).get("denied", {}).get("status", "NOT_RUN") if isinstance(guest.get("journeys"), dict) else "NOT_RUN",
            "stableRelease": "NO-GO",
            "pilots": "BLOCKED",
        },
        "fedoraCommands": fedora_commands(),
    }
    (work / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    walkthrough = write_walkthrough(work, report)
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(work.name, target_is_directory=True)
    print(f"report: {work / 'report.json'}")
    print(f"walkthrough: {walkthrough}")
    print(f"latest: {latest}")
    print(f"probePassed={probe_passed} guestPassed={guest_passed} passed={passed}")
    print("stable release: NO-GO (unchanged)")
    if os.environ.get("BUNNY_GUEST_TRUST_REQUIRE") == "1" and guest_status != "PASS":
        return 2
    if not probe_passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
