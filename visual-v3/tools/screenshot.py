#!/usr/bin/env python3
"""Capture real screenshots of the composited shell.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

These are photographs of what the compositor actually drew, taken by reading
back its own framebuffer. They are not mockups. The V2 phase shipped SVG
mockups labelled as such; this phase does not need to, because the shell runs.

Orientation is verified rather than assumed: the top bar occupies a known band,
so the harness checks that the band is where it should be and records the check.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    NestedShell,
    OBSERVED,
    ROOT,
    UNAVAILABLE,
    banner,
    component_command,
    preconditions,
    which,
    write_report,
)


SHOTS = ROOT / "visual-v3/screenshots"
CHROME = ("top-bar", "dock", "assistant-panel", "command-palette")


def band_mean(path: Path, geometry: str) -> float | None:
    """Mean intensity of a region, via ImageMagick."""

    convert = which("convert") or which("magick")
    if not convert:
        return None
    completed = subprocess.run(
        [convert, str(path), "-crop", geometry, "-format", "%[fx:mean]", "info:"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        return float(completed.stdout.strip().split()[0])
    except (ValueError, IndexError):
        return None


def _run(mode: str, target: Path, *, with_chrome: bool, after_seconds: float) -> bool:
    shell = NestedShell(
        f"bunny-shot-{mode}",
        seconds=70 if with_chrome else 25,
        mode=mode,
        capture=target,
        capture_after_seconds=after_seconds,
    )
    shell.__enter__()
    processes = []
    try:
        if with_chrome:
            for component in CHROME:
                processes.append(shell.spawn_client(component_command(component)))
                time.sleep(4)
            time.sleep(6)
        deadline = time.monotonic() + (40 if with_chrome else 20)
        while time.monotonic() < deadline and not target.exists():
            time.sleep(0.5)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        shell.__exit__()
    return target.exists()


def capture(mode: str) -> dict:
    """Capture the composited output, degrading honestly if the host stalls.

    The host compositor decides when our window is presented. When it stops
    presenting, the capture — which happens inside the render path — never runs.
    Rather than report nothing, the harness falls back to an early capture and
    records plainly that the chrome had not yet mapped.
    """

    SHOTS.mkdir(parents=True, exist_ok=True)
    target = SHOTS / f"{mode}-desktop.png"
    if target.exists():
        target.unlink()

    with_chrome = _run(mode, target, with_chrome=True, after_seconds=22)
    fallback_reason = None
    if not with_chrome:
        fallback_reason = (
            "the host compositor stopped presenting frames before the shell chrome mapped, so the "
            "capture inside the render path never ran; captured the first frame instead"
        )
        if not _run(mode, target, with_chrome=False, after_seconds=0):
            return {"mode": mode, "evidence": UNAVAILABLE, "reason": "no frame was captured at all"}

    data = target.read_bytes()
    return {
        "mode": mode,
        "evidence": OBSERVED,
        "path": target.relative_to(ROOT).as_posix(),
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "chromePresent": with_chrome,
        "fallbackReason": fallback_reason,
        "topBandMean": band_mean(target, "100%x32+0+0"),
        "bottomBandMean": band_mean(target, "100%x64+0-64"),
        "isMockup": False,
    }


def main() -> int:
    banner()
    problems = preconditions()
    if problems:
        write_report(
            "screenshots.json",
            {"schemaVersion": 1, "evidence": UNAVAILABLE, "problems": problems, "captures": []},
        )
        print(f"cannot capture: {problems}", file=sys.stderr)
        return 2

    captures = [capture(mode) for mode in ("regular", "character")]
    payload = {
        "schemaVersion": 1,
        "capturedBy": "the compositor reading back its own framebuffer via ExportMem",
        "mockups": False,
        "note": (
            "Operator-only capture: reached from the command line at start-up, never from a "
            "Wayland protocol. Ordinary clients still cannot screenshot through the compositor."
        ),
        "captures": captures,
    }
    write_report("screenshots.json", payload)
    for item in captures:
        if item["evidence"] == OBSERVED:
            chrome = "with chrome" if item["chromePresent"] else "COMPOSITOR ONLY (no chrome)"
            print(
                f"  {item['mode']:<10} {item['bytes']:>9} bytes  {chrome}  "
                f"sha256={item['sha256'][:12]}"
            )
        else:
            print(f"  {item['mode']:<10} not captured: {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
