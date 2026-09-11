#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-command host demo of the Bunny OS product-vision surfaces.

Companion speech bubbles and Visual Keys, appearance selection, outcome
routing, memory boundaries, first-run copy, and the Vosk→action→TTS
story. This is **not** a stable-release GO, **not** a pilot GO, and
**not** a booted Fedora guest.

Run from the repository root::

    python3 demos/10-product-vision/run.py
    make demo-product-vision
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

from capability.simulate import simulate
from companion.appearance import apply_appearance
from companion.memory_boundary import (
    MemoryPolicy,
    authorize_cloud_context,
    may_store,
)
from companion.onboarding.model import ONBOARDING_STEPS
from companion.outcome_router import OutcomeRequest, route_outcome
from companion.presentation import PresentationSignals
from companion.product_surface import (
    forbidden_labels_present,
    render_appearance_html,
    render_memory_html,
    render_onboarding_html,
    render_router_html,
    render_visual_html,
    render_voice_html,
    visual_demo_frames,
)
from companion.voice_story import run_voice_story
from companion.visible_trust import FORBIDDEN_LABELS
from installer.companion_flow import FIRST_RUN_STAGES, INSTALL_STAGES


def _which(name: str) -> str | None:
    return shutil.which(name)


def probe_host() -> dict[str, object]:
    kvm = Path("/dev/kvm").exists()
    qemu = _which("qemu-system-x86_64")
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or ""
    chrome = _which("google-chrome") or _which("chromium") or _which("chromium-browser")
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "kvmDevice": kvm,
        "qemu": qemu or "",
        "display": display,
        "chrome": chrome or "",
        "guestBoot": "NOT_RUN" if not (kvm and qemu) else "AVAILABLE",
        "guestBootReason": (
            "this demo does not start a guest"
            if kvm and qemu
            else "QEMU is not installed on this host"
            if kvm
            else "no /dev/kvm"
        ),
        "releaseState": "NO-GO",
        "pilots": "BLOCKED",
    }


def screenshot_html(html: Path, png: Path, chrome: str) -> dict[str, object]:
    png.parent.mkdir(parents=True, exist_ok=True)
    display = os.environ.get("DISPLAY") or ""
    ffmpeg = shutil.which("ffmpeg")
    if not display or not ffmpeg or not chrome:
        return {
            "ok": False,
            "error": "no DISPLAY, ffmpeg or Chrome; screenshot is NOT_RUN",
            "path": str(png),
        }
    profile = tempfile.mkdtemp(prefix="bunny-chrome-")
    argv = [
        chrome, "--no-sandbox", "--disable-gpu", "--disable-extensions",
        "--disable-component-update", "--disable-background-networking",
        "--no-first-run", "--no-default-browser-check", "--guest",
        f"--user-data-dir={profile}", "--window-size=1280,800",
        "--window-position=0,0", f"--app={html.resolve().as_uri()}",
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
        return {"ok": False, "error": str(exc), "path": str(png)}
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
        "path": str(png),
    }


def _signals_for(machine: str) -> PresentationSignals:
    inventory = simulate(machine)
    memory = inventory.memory.usable_available_bytes(None)
    return PresentationSignals(
        gpu_available=bool(inventory.usable_gpus),
        available_memory_bytes=memory,
        display_available=True,
        on_battery=inventory.power.on_battery,
    )


def run_unit_tests() -> dict[str, object]:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.companion.test_product_vision")
    buffer = unittest.TestResult()
    suite.run(buffer)
    failures = [f"{test.id()}: {err}" for test, err in buffer.failures + buffer.errors]
    return {
        "ok": buffer.wasSuccessful(),
        "run": buffer.testsRun,
        "failures": failures,
    }


def build_pages(work: Path) -> dict[str, object]:
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    visual = visual_demo_frames()
    written: dict[str, str] = {}
    leaked: list[str] = []
    for frame in visual:
        path = frames_dir / f"visual-{frame.key}.html"
        html = render_visual_html(frame)
        path.write_text(html, encoding="utf-8")
        written[f"visual-{frame.key}"] = str(path.relative_to(work))
        leaked.extend(forbidden_labels_present(html))

    appearances = {}
    for machine in ("gaming-desktop", "laptop", "embedded-64mb"):
        choice = apply_appearance(signals=_signals_for(machine))
        path = frames_dir / f"appearance-{machine}.html"
        html = render_appearance_html(choice, machine=machine)
        path.write_text(html, encoding="utf-8")
        written[f"appearance-{machine}"] = str(path.relative_to(work))
        leaked.extend(forbidden_labels_present(html))
        override = apply_appearance(
            signals=_signals_for(machine), chosen="full-3d", override=True,
        )
        appearances[machine] = {
            "recommended": choice.recommended.value,
            "effective": choice.effective.value,
            "override3dEffective": override.effective.value,
            "bounded": override.bounded,
        }

    explanations = [
        route_outcome(OutcomeRequest("summarise this note"), simulate("laptop")),
        route_outcome(
            OutcomeRequest(
                "search the web for pasta", kind="needs-network",
                offline=True, remote_allowed=True,
            ),
            simulate("offline-laptop"),
        ),
        route_outcome(
            OutcomeRequest(
                "summarise this private note", kind="private-work",
                privacy="secret", remote_allowed=True,
                local_memory_bytes=8 * 1024 ** 3,
            ),
            simulate("embedded-64mb"),
        ),
        route_outcome(
            OutcomeRequest(
                "summarise this note", local_memory_bytes=8 * 1024 ** 3,
            ),
            simulate("embedded-64mb"),
        ),
    ]
    router_html = render_router_html(explanations)
    router_path = frames_dir / "outcomes.html"
    router_path.write_text(router_html, encoding="utf-8")
    written["outcomes"] = str(router_path.relative_to(work))
    leaked.extend(forbidden_labels_present(router_html))

    policy = MemoryPolicy()
    decisions = [
        may_store("internal", "working", policy),
        may_store("internal", "session", policy),
        may_store("personal", "durable", policy),
        authorize_cloud_context(
            {"note": "hello", "secret": "nope"},
            classification="public", policy=policy,
            remote_transfer_ceiling="public", allowed_fields=("note",),
        ),
    ]
    memory_html = render_memory_html(policy, decisions)
    memory_path = frames_dir / "memory.html"
    memory_path.write_text(memory_html, encoding="utf-8")
    written["memory"] = str(memory_path.relative_to(work))
    leaked.extend(forbidden_labels_present(memory_html))

    for index, name in ((0, "onboarding-hello"), (len(ONBOARDING_STEPS) - 1, "onboarding-ready")):
        html = render_onboarding_html(step_index=index)
        path = frames_dir / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        written[name] = str(path.relative_to(work))
        leaked.extend(forbidden_labels_present(html))

    voice = run_voice_story()
    voice_html = render_voice_html(voice)
    voice_path = frames_dir / "voice.html"
    voice_path.write_text(voice_html, encoding="utf-8")
    written["voice"] = str(voice_path.relative_to(work))
    leaked.extend(forbidden_labels_present(voice_html))

    return {
        "ok": (
            not leaked
            and [frame.key for frame in visual]
            == [
                "idle", "listening", "thinking", "working", "searching",
                "downloading", "installing", "reading", "coding", "error", "success",
            ]
            and ONBOARDING_STEPS[0].title == "Hi. I'm Bunny."
            and ONBOARDING_STEPS[-1].title == "Ready"
            and "I'm Bunny" in INSTALL_STAGES[0].says
            and FIRST_RUN_STAGES[-1].says.startswith("Ready.")
            and voice.passed
            and explanations[0].target == "local"
            and explanations[1].target == "refused"
            and not any(item.allowed for item in decisions if item.scope != "working")
        ),
        "frames": written,
        "forbiddenLabelsSeen": sorted(set(leaked)),
        "appearance": appearances,
        "outcomes": [item.to_json() for item in explanations],
        "memory": {
            "policy": policy.to_json(),
            "decisions": [item.to_json() for item in decisions],
        },
        "voice": voice.to_json(),
        "onboarding": {
            "welcome": ONBOARDING_STEPS[0].title,
            "finish": ONBOARDING_STEPS[-1].title,
            "installerHello": INSTALL_STAGES[0].says,
            "firstRunReady": FIRST_RUN_STAGES[-1].says,
        },
    }


def write_walkthrough(work: Path, report: dict[str, object]) -> Path:
    host = report["host"]
    pages = report["pages"]
    lines = [
        "# Product-vision host demo walkthrough",
        "",
        "This is a **host-runnable** demonstration of the Companion face,",
        "appearance modes, outcome routing, memory boundaries, first-run copy,",
        "and the offline voice story. It is not a booted Fedora guest, not",
        "hardware evidence, and not a stable-release GO.",
        "",
        f"- Host guest boot: `{host['guestBoot']}` — {host['guestBootReason']}",
        f"- Stable release: `{host['releaseState']}`",
        f"- Pilots: `{host['pilots']}`",
        "",
        "## What to show a reviewer",
        "",
        "1. Visual Keys in `frames/visual-*.html` — speech bubbles for ordinary",
        "   actions, state transitions, activity-reactive scenes.",
        "2. Appearance in `frames/appearance-*.html` — Full 3D / Lightweight 2D /",
        "   Minimal, recommended from simulated hardware, override bounded.",
        "3. Outcomes in `frames/outcomes.html` — local vs offline refuse vs",
        "   memory pressure; no model shop.",
        "4. Memory in `frames/memory.html` — session/durable/cloud off by default.",
        "5. First run `frames/onboarding-hello.html` → `onboarding-ready.html`.",
        "6. Voice `frames/voice.html` — Vosk→action→TTS with honest NOT_RUN.",
        "",
        "## Unit tests",
        "",
        f"- tests run: {report['tests']['run']}",
        f"- result: {'PASS' if report['tests']['ok'] else 'FAIL'}",
        "",
        "## Surfaces",
        "",
        f"- pages: {'PASS' if pages['ok'] else 'FAIL'}",
        f"- forbidden labels: {pages['forbiddenLabelsSeen'] or 'none'}",
        f"- onboarding: {pages['onboarding']['welcome']} → {pages['onboarding']['finish']}",
        f"- voice STT: {[s['status'] for s in pages['voice']['steps'] if s['name']=='speech-to-text']}",
        "",
        "Appearance (simulated machines, labelled as such):",
        "",
    ]
    for machine, item in pages["appearance"].items():
        lines.append(
            f"- `{machine}`: recommended `{item['recommended']}`, "
            f"effective `{item['effective']}`; 3D override effective "
            f"`{item['override3dEffective']}` (bounded={item['bounded']})"
        )
    lines.extend([
        "",
        "Outcomes:",
        "",
    ])
    for item in pages["outcomes"]:
        lines.append(f"- {item['outcome']}: `{item['target']}` — {item['headline']}")
    lines.extend([
        "",
        "## Still needs Fedora + KVM / hardware / reviews / keys",
        "",
        "- Guest AT-SPI photograph of these surfaces inside Bunny Shell",
        "- Physical microphone + packaged Vosk model for a live STT PASS",
        "- Physical Secure Boot / TPM / Orca qualification",
        "- Independent security / privacy / accessibility reviews",
        "- Production signing keys",
        "",
        "None of those are claimed by this run. `gate-stable-release` is NO-GO.",
        "Pilots remain BLOCKED.",
        "",
    ])
    path = work / "WALKTHROUGH.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    del argv
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    work = ROOT / "demos/10-product-vision/out" / stamp
    work.mkdir(parents=True, exist_ok=True)
    latest = ROOT / "demos/10-product-vision/out/latest"
    print(f"product-vision demo → {work}", flush=True)

    host = probe_host()
    print(f"host: kvm={host['kvmDevice']} qemu={host['qemu'] or 'ABSENT'} "
          f"chrome={bool(host['chrome'])} guest={host['guestBoot']}")

    tests = run_unit_tests()
    print(f"unit tests: {tests['run']} run, {'PASS' if tests['ok'] else 'FAIL'}")
    for item in tests["failures"]:
        print(f"  FAIL {item}")

    pages = build_pages(work)
    print(f"surfaces: {'PASS' if pages['ok'] else 'FAIL'}")

    screenshots: dict[str, object] = {}
    chrome = str(host["chrome"])
    shot_names = [
        "visual-idle", "visual-listening", "visual-thinking", "visual-working",
        "visual-searching", "visual-success",
        "appearance-laptop", "appearance-embedded-64mb", "outcomes", "memory",
        "onboarding-hello", "onboarding-ready", "voice",
    ]
    if chrome:
        for name in shot_names:
            html = work / "frames" / f"{name}.html"
            if not html.is_file():
                continue
            png = work / "screenshots" / f"{name}.png"
            screenshots[name] = screenshot_html(html, png, chrome)
        shots = sum(1 for item in screenshots.values() if item.get("ok"))
        print(f"screenshots: {shots}/{len(screenshots)} via Chrome")
    else:
        print("screenshots: NOT_RUN (Chrome not installed)")

    report = {
        "demo": "product-vision-host",
        "honest": True,
        "stableRelease": "NO-GO",
        "pilots": "BLOCKED",
        "guestBoot": host["guestBoot"],
        "host": host,
        "tests": tests,
        "pages": pages,
        "screenshots": {
            name: {"ok": item.get("ok"), "bytes": item.get("bytes"), "error": item.get("error")}
            for name, item in screenshots.items()
        },
        "forbiddenLabels": list(FORBIDDEN_LABELS),
        "passed": bool(tests["ok"] and pages["ok"]),
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
    print("stable release: NO-GO (unchanged)")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
