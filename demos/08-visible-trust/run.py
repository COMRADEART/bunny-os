#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-command host demo of the visible Trust / approval path.

This is the strongest honest demonstration this cloud host can give. It does
**not** boot a Fedora image, does **not** claim a stable-release GO, and does
**not** relabel missing KVM evidence as PASS.

What it does:

1. Probe the host (KVM, QEMU, Podman, GTK, Chrome, display).
2. Run capability inspect/plan against a simulated laptop.
3. Run the headless Companion demo, granted and denied.
4. Prove an approval is not a runtime timeout (the cold-first-request clock).
5. Draw the production Trust prompt, bind screenshots to state transitions,
   and drive Allow / Deny by the same accessible names the guest harness
   presses.

Run from the repository root::

    python3 demos/08-visible-trust/run.py
    make demo-visible-trust
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools/bunny-os") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/bunny-os"))

from companion.demo import run_demo
from companion.trust_surface import ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME
from companion.visible_trust import (
    FORBIDDEN_LABELS,
    JOURNEY_REQUEST,
    VISIBLE_STATES,
    decide_journey,
    demo_prompt,
    forbidden_labels_present,
    frames_for,
)


BUNNY = ROOT / "tools/bunny-os/bin/bunny-os"


def _which(name: str) -> str | None:
    return shutil.which(name)


def probe_host() -> dict[str, object]:
    qemu = _which("qemu-system-x86_64")
    podman = _which("podman")
    kvm = Path("/dev/kvm").exists()
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or ""
    gtk = False
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gtk = True
    except Exception:
        gtk = False
    chrome = _which("google-chrome") or _which("chromium") or _which("chromium-browser")
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "kvmDevice": kvm,
        "qemu": qemu or "",
        "podman": podman or "",
        "display": display,
        "gtk4": gtk,
        "chrome": chrome or "",
        "canBootGuest": bool(kvm and qemu),
        "guestBoot": "NOT_RUN" if not (kvm and qemu) else "AVAILABLE",
        "guestBootReason": (
            "QEMU is not installed on this host"
            if kvm and not qemu
            else "no /dev/kvm"
            if not kvm
            else "QEMU/KVM present; this demo still does not start a guest"
        ),
        "releaseState": "NO-GO",
        "pilots": "BLOCKED",
    }


def run_capability() -> dict[str, object]:
    inspect = subprocess.run(
        [sys.executable, str(BUNNY), "--json", "capability", "inspect", "--simulate", "laptop"],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    plan = subprocess.run(
        [sys.executable, str(BUNNY), "--json", "capability", "plan", "--simulate", "laptop"],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    explain = subprocess.run(
        [sys.executable, str(BUNNY), "capability", "explain", "companion", "--simulate", "laptop"],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    return {
        "ok": inspect.returncode == 0 and plan.returncode == 0,
        "inspectExit": inspect.returncode,
        "planExit": plan.returncode,
        "explainExit": explain.returncode,
        "inspect": _maybe_json(inspect.stdout),
        "plan": _maybe_json(plan.stdout),
        "explainHead": explain.stdout.strip().splitlines()[:12],
        "stderr": (inspect.stderr + plan.stderr + explain.stderr)[-2000:],
    }


def run_companion_slices(work: Path) -> dict[str, object]:
    granted = run_demo(work / "companion-granted", grant_approval=True)
    denied = run_demo(work / "companion-denied", grant_approval=False)
    return {
        "ok": granted.passed and denied.passed,
        "granted": granted.to_json(),
        "denied": denied.to_json(),
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


def _maybe_json(text: str) -> object:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:2000]


def write_frames(prompt, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=True)
    frames = frames_for(prompt)
    written: dict[str, str] = {}
    for state, frame in frames.items():
        html_path = destination / f"{state}.html"
        text_path = destination / f"{state}.txt"
        html_path.write_text(frame.html, encoding="utf-8")
        text_path.write_text(frame.text + "\n", encoding="utf-8")
        written[state] = str(html_path.relative_to(destination))
    return written


def screenshot_html(html: Path, png: Path, chrome: str) -> dict[str, object]:
    """Photograph one Trust frame on the host display.

    Headless ``--screenshot`` hangs in this environment (it collides with the
    already-running Chrome debugging session). A headed window on ``DISPLAY``
    plus ``ffmpeg`` x11grab is the path that actually produces a PNG here.
    """
    png.parent.mkdir(parents=True, exist_ok=True)
    display = os.environ.get("DISPLAY") or ""
    ffmpeg = shutil.which("ffmpeg")
    if not display or not ffmpeg:
        return {
            "ok": False,
            "error": "no DISPLAY or ffmpeg; Chrome headless screenshot is NOT_RUN",
            "path": str(png),
        }
    profile = tempfile.mkdtemp(prefix="bunny-chrome-")
    argv = [
        chrome,
        "--no-sandbox",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-component-update",
        "--disable-background-networking",
        "--no-first-run",
        "--no-default-browser-check",
        "--guest",
        f"--user-data-dir={profile}",
        "--window-size=1280,800",
        "--window-position=0,0",
        f"--app={html.resolve().as_uri()}",
    ]
    proc = None
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3.5)
        grab = subprocess.run(
            [
                ffmpeg, "-y", "-f", "x11grab", "-video_size", "1280x720",
                "-i", f"{display}.0", "-frames:v", "1", "-update", "1", str(png),
            ],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if proc is not None:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        return {"ok": False, "error": str(exc)}
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    return {
        "ok": grab.returncode == 0 and png.is_file() and png.stat().st_size > 1000,
        "returncode": grab.returncode,
        "bytes": png.stat().st_size if png.is_file() else 0,
        "stderr": grab.stderr[-400:],
    }


def run_visible_journey(work: Path, chrome: str) -> dict[str, object]:
    prompt = demo_prompt()
    frames_dir = work / "frames"
    written = write_frames(prompt, frames_dir)
    asking_html = (frames_dir / "waiting_for_approval.html").read_text(encoding="utf-8")
    leaked = forbidden_labels_present(asking_html)
    screenshots: dict[str, object] = {}
    if chrome:
        for state in VISIBLE_STATES:
            html = frames_dir / f"{state}.html"
            png = work / "screenshots" / f"{state}.png"
            screenshots[state] = screenshot_html(html, png, chrome)
            screenshots[state]["path"] = str(png.relative_to(work))
    else:
        for state in VISIBLE_STATES:
            screenshots[state] = {"ok": False, "error": "chrome not installed", "path": ""}

    granted, granted_prompt = decide_journey(ALLOW_ACCESSIBLE_NAME, work / "gate-granted")
    denied, _denied_prompt = decide_journey(DENY_ACCESSIBLE_NAME, work / "gate-denied")
    unknown, _ = decide_journey("Always allow everything", work / "gate-unknown")

    transitions = [
        {"from": "idle", "to": "thinking", "cause": f"typed {JOURNEY_REQUEST!r}"},
        {"from": "thinking", "to": "waiting_for_approval",
         "cause": "runtime reached a permission question; deadline suspended"},
        {"from": "waiting_for_approval", "to": "granted",
         "cause": f"pressed {ALLOW_ACCESSIBLE_NAME!r}",
         "allowed": granted.allowed, "reasonCode": granted.reason_code},
        {"from": "waiting_for_approval", "to": "denied",
         "cause": f"pressed {DENY_ACCESSIBLE_NAME!r}",
         "allowed": denied.allowed, "reasonCode": denied.reason_code},
        {"from": "waiting_for_approval", "to": "denied",
         "cause": "unknown / forbidden name denies",
         "allowed": unknown.allowed, "reasonCode": unknown.reason_code},
    ]
    return {
        "ok": (
            granted.allowed
            and not denied.allowed
            and not unknown.allowed
            and not leaked
                    and asking_html.count(f'aria-label="{ALLOW_ACCESSIBLE_NAME}"') == 1
                    and asking_html.count(f'aria-label="{DENY_ACCESSIBLE_NAME}"') == 1
            and 'autofocus' in asking_html
        ),
        "request": JOURNEY_REQUEST,
        "headline": prompt.headline,
        "spoken": prompt.spoken,
        "gateHeadline": granted_prompt.headline,
        "frames": written,
        "screenshots": screenshots,
        "forbiddenLabelsSeen": leaked,
        "granted": {"allowed": granted.allowed, "reasonCode": granted.reason_code,
                    "scope": granted.scope, "grantId": granted.grant_id},
        "denied": {"allowed": denied.allowed, "reasonCode": denied.reason_code},
        "unknownNameDenies": {"allowed": unknown.allowed, "reasonCode": unknown.reason_code},
        "transitions": transitions,
        "accessibleNames": [DENY_ACCESSIBLE_NAME, ALLOW_ACCESSIBLE_NAME],
    }


def write_walkthrough(work: Path, report: dict[str, object]) -> Path:
    host = report["host"]
    visible = report["visibleTrust"]
    lines = [
        "# Visible Trust demo walkthrough",
        "",
        "This is a **host-runnable** demonstration. It is not a booted Fedora",
        "guest, not hardware evidence, and not a stable-release GO.",
        "",
        f"- Host guest boot: `{host['guestBoot']}` — {host['guestBootReason']}",
        f"- Stable release: `{host['releaseState']}`",
        f"- Pilots: `{host['pilots']}`",
        "",
        "## What to show a reviewer",
        "",
        "1. The Trust prompt HTML at `frames/waiting_for_approval.html`",
        "   (Deny focused, accessible names match the guest harness).",
        "2. Screenshots in `screenshots/` bound to idle → thinking →",
        "   waiting_for_approval → granted / denied / failed.",
        "3. This log: capability, companion granted/denied, deadline tests.",
        "",
        "## Capability",
        "",
        f"- inspect/plan: {'PASS' if report['capability']['ok'] else 'FAIL'}",
        "",
        "## Companion (headless, no display)",
        "",
        f"- granted slice: {'PASS' if report['companion']['granted']['passed'] else 'FAIL'}",
        f"- denied slice: {'PASS' if report['companion']['denied']['passed'] else 'FAIL'}",
        "",
        "## Approval is not a timeout",
        "",
        f"- tests run: {report['deadline']['run']}",
        f"- result: {'PASS' if report['deadline']['ok'] else 'FAIL'}",
        "",
        "## Visible Trust journey",
        "",
        f"- request: {visible['request']}",
        f"- headline (drawn): {visible['headline']}",
        f"- granted by accessible name: allowed={visible['granted']['allowed']} "
        f"({visible['granted']['reasonCode']})",
        f"- denied by accessible name: allowed={visible['denied']['allowed']} "
        f"({visible['denied']['reasonCode']})",
        f"- forbidden label press: allowed={visible['unknownNameDenies']['allowed']} "
        f"({visible['unknownNameDenies']['reasonCode']})",
        "",
        "State transitions:",
        "",
    ]
    for item in visible["transitions"]:
        lines.append(f"- `{item['from']}` → `{item['to']}` — {item['cause']}")
    lines.extend([
        "",
        "## Still needs Fedora + KVM hardware",
        "",
        "- `make build-shell-image` / `vm-desktop-story.sh --journey granted`",
        "- AT-SPI press inside a GNOME session (`desktop-drive.py`)",
        "- `BUNNY_SESSION_READY` observed on a booted guest",
        "- Physical Secure Boot / TPM / Orca qualification",
        "",
        "None of those are claimed by this run.",
        "",
    ])
    path = work / "WALKTHROUGH.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    del argv
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    work = ROOT / "demos/08-visible-trust/out" / stamp
    work.mkdir(parents=True, exist_ok=True)
    latest = ROOT / "demos/08-visible-trust/out/latest"
    print(f"visible-trust demo → {work}", flush=True)

    host = probe_host()
    print(f"host: kvm={host['kvmDevice']} qemu={host['qemu'] or 'ABSENT'} "
          f"podman={host['podman'] or 'ABSENT'} chrome={bool(host['chrome'])} "
          f"guest={host['guestBoot']}")

    capability = run_capability()
    print(f"capability: {'PASS' if capability['ok'] else 'FAIL'}")

    companion = run_companion_slices(work / "companion")
    print(f"companion granted/denied: {'PASS' if companion['ok'] else 'FAIL'}")

    deadline = run_deadline_tests()
    print(f"deadline tests: {deadline['run']} run, {'PASS' if deadline['ok'] else 'FAIL'}")
    for item in deadline["failures"]:
        print(f"  FAIL {item}")

    visible = run_visible_journey(work, str(host["chrome"]))
    print(f"visible trust: {'PASS' if visible['ok'] else 'FAIL'}")
    if host["chrome"]:
        shots = sum(1 for item in visible["screenshots"].values() if item.get("ok"))
        print(f"screenshots: {shots}/{len(VISIBLE_STATES)} via Chrome")
    else:
        print("screenshots: NOT_RUN (Chrome not installed)")

    report = {
        "demo": "visible-trust-host",
        "honest": True,
        "stableRelease": "NO-GO",
        "pilots": "BLOCKED",
        "guestBoot": host["guestBoot"],
        "host": host,
        "capability": {"ok": capability["ok"], "explainHead": capability.get("explainHead"),
                       "inspectExit": capability["inspectExit"], "planExit": capability["planExit"]},
        "companion": companion,
        "deadline": deadline,
        "visibleTrust": visible,
        "passed": bool(
            capability["ok"] and companion["ok"] and deadline["ok"] and visible["ok"]
        ),
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
    print("stable release: NO-GO (unchanged)")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
