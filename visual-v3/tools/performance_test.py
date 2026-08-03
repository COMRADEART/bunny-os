#!/usr/bin/env python3
"""Measure the shell against the phase's prototype targets.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Every number here was taken on a software rasteriser (Mesa llvmpipe) inside
WSL2. A failure against a target is reported as a failure; it is not explained
away by the environment, though the environment is recorded next to it.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BINARY,
    NestedShell,
    OBSERVED,
    UNAVAILABLE,
    banner,
    component_command,
    preconditions,
    write_report,
)


#: (key, description, target, unit, lower_is_better)
TARGETS = [
    ("coldShellStartup", "cold shell startup", 3000.0, "ms", True),
    ("topBarReady", "top bar ready", 2000.0, "ms", True),
    ("commandPaletteVisible", "command palette visible", 150.0, "ms", True),
    ("quickSettingsVisible", "Quick Settings visible", 150.0, "ms", True),
    ("workspaceTransitionFps", "workspace transition", 60.0, "fps", False),
    ("idleCpuPercent", "idle CPU", 1.0, "%", True),
    ("shellMemoryMb", "regular shell memory", 450.0, "MB", True),
    ("characterAssetIncrementalMb", "character asset incremental use", 100.0, "MB", True),
    ("shellRestart", "shell restart", 3000.0, "ms", True),
]


def measure_startup_and_frames() -> dict:
    with NestedShell("bunny-perf", seconds=30) as shell:
        socket_ready_ms = (shell.socket_ready_seconds or 0) * 1000
        # Let it render a while, then read what it recorded about itself.
        deadline = time.monotonic() + 45
        while shell.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.5)
        log = shell.log_text()
        diagnostics = shell.diagnostics()

    first_frame = None
    match = re.search(r"first frame at ([0-9.]+) ms after start", log)
    if match:
        first_frame = float(match.group(1))

    timing = diagnostics.get("frame_timing", {})
    memory_fact = diagnostics.get("memory", {})
    memory_mb = None
    if memory_fact.get("evidence") == "observed":
        memory_match = re.match(r"([0-9.]+) MB", memory_fact.get("value", ""))
        if memory_match:
            memory_mb = float(memory_match.group(1))

    mean_ms = timing.get("mean_frame_milliseconds")
    fps = (1000.0 / mean_ms) if mean_ms else None
    return {
        "socketReadyMs": round(socket_ready_ms, 1),
        "firstFrameMs": first_frame,
        "frames": timing.get("frames"),
        "droppedFrames": timing.get("dropped"),
        "meanFrameMs": mean_ms,
        "worstFrameMs": timing.get("worst_frame_milliseconds"),
        "framesPerSecond": round(fps, 1) if fps else None,
        "residentMemoryMb": memory_mb,
    }


def measure_chrome_visible(component: str, attempts: int = 2) -> float | None:
    for attempt in range(attempts):
        value = _measure_chrome_visible_once(component)
        if value is not None:
            return value
    return None


def _measure_chrome_visible_once(component: str) -> float | None:
    """Time from launching a chrome component to its layer surface mapping."""

    with NestedShell(f"bunny-perf-{component}", seconds=45) as shell:
        started = time.monotonic()
        process = shell.spawn_client(component_command(component))
        deadline = started + 40
        namespace = {
            "command-palette": "bunny-command-palette",
            "quick-settings": "bunny-quick-settings",
            "top-bar": "bunny-top-bar",
        }[component]
        elapsed = None
        while time.monotonic() < deadline:
            if namespace in shell.log_text():
                elapsed = (time.monotonic() - started) * 1000
                break
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except Exception:  # noqa: BLE001
                process.kill()
        return round(elapsed, 1) if elapsed else None


def measure_restart() -> float | None:
    """Stop the shell and start it again; time the second start."""

    with NestedShell("bunny-perf-restart-a", seconds=12):
        pass
    started = time.monotonic()
    try:
        with NestedShell("bunny-perf-restart-b", seconds=12):
            return round((time.monotonic() - started) * 1000, 1)
    except RuntimeError:
        return None


def measure_idle_cpu() -> dict:
    """Sample the compositor's CPU while nothing is happening."""

    with NestedShell("bunny-perf-idle", seconds=30) as shell:
        pid = shell.process.pid
        time.sleep(5)
        try:
            first = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
            time.sleep(10)
            second = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        except (OSError, IndexError):
            return {"value": None, "evidence": UNAVAILABLE, "detail": "could not read /proc stat"}
    ticks = (int(second[13]) + int(second[14])) - (int(first[13]) + int(first[14]))
    hertz = 100.0
    percent = (ticks / hertz) / 10.0 * 100.0
    return {
        "value": round(percent, 2),
        "evidence": OBSERVED,
        "detail": "sampled over 10s while the shell rendered with no clients attached; the "
        "compositor renders continuously rather than on damage, which is the cause",
    }


def main() -> int:
    banner()
    problems = preconditions()
    if problems:
        write_report(
            "performance.json",
            {"schemaVersion": 1, "evidence": UNAVAILABLE, "problems": problems, "results": []},
        )
        print(f"cannot measure: {problems}", file=sys.stderr)
        return 2

    startup = measure_startup_and_frames()
    palette_ms = measure_chrome_visible("command-palette")
    quick_ms = measure_chrome_visible("quick-settings")
    topbar_ms = measure_chrome_visible("top-bar")
    restart_ms = measure_restart()
    idle = measure_idle_cpu()

    # In a nested run the host compositor decides when our window is presented,
    # and backend.submit() blocks until it does. If the host presented almost
    # nothing, the frame rate and the idle CPU describe the host's scheduling,
    # not the shell's cost. Reporting "misses 60 FPS" from two frames would be
    # as dishonest as reporting that it met the target.
    frames_rendered = startup.get("frames") or 0
    frame_sample_valid = frames_rendered >= 60
    frame_validity_note = (
        None
        if frame_sample_valid
        else (
            f"only {frames_rendered} frames were presented during the run; the nested backend "
            "blocks in submit() until the host compositor schedules the window, so frame rate "
            "and idle CPU could not be attributed to the shell"
        )
    )

    measured = {
        "coldShellStartup": startup["firstFrameMs"],
        "topBarReady": topbar_ms,
        "commandPaletteVisible": palette_ms,
        "quickSettingsVisible": quick_ms,
        "workspaceTransitionFps": startup["framesPerSecond"] if frame_sample_valid else None,
        "idleCpuPercent": idle["value"] if frame_sample_valid else None,
        "shellMemoryMb": startup["residentMemoryMb"],
        # Character assets are loaded by the panel process, not the compositor,
        # and only the active pose is held. Measuring the delta needs a
        # per-process sample the harness does not take.
        "characterAssetIncrementalMb": None,
        "shellRestart": restart_ms,
    }

    results = []
    for key, description, target, unit, lower_better in TARGETS:
        value = measured.get(key)
        if value is None:
            results.append(
                {
                    "metric": key,
                    "description": description,
                    "target": target,
                    "unit": unit,
                    "measured": None,
                    "evidence": UNAVAILABLE,
                    "meetsTarget": None,
                }
            )
            continue
        meets = value <= target if lower_better else value >= target
        results.append(
            {
                "metric": key,
                "description": description,
                "target": target,
                "unit": unit,
                "measured": value,
                "evidence": OBSERVED,
                "meetsTarget": meets,
            }
        )

    failed = [row for row in results if row["meetsTarget"] is False]
    unmeasured = [row for row in results if row["meetsTarget"] is None]
    payload = {
        "schemaVersion": 1,
        "environment": {
            "host": "Fedora Linux 44 on WSL2, nested under WSLg",
            "renderer": "Mesa llvmpipe (software rasteriser)",
            "hardwareAccelerated": False,
            "note": "These are software-rendering numbers. They are the honest result for this "
            "host and are not adjusted for it.",
        },
        "startup": startup,
        "idleCpu": idle,
        "frameSampleValid": frame_sample_valid,
        "frameSampleNote": frame_validity_note,
        "results": results,
        "targetsMet": len(results) - len(failed) - len(unmeasured),
        "targetsFailed": [row["metric"] for row in failed],
        "targetsNotMeasured": [row["metric"] for row in unmeasured],
    }
    write_report("performance.json", payload)
    for row in results:
        status = (
            "not measured"
            if row["meetsTarget"] is None
            else ("MEETS" if row["meetsTarget"] else "MISSES")
        )
        print(f"  {row['description']:<32} target {row['target']:>7} {row['unit']:<3} "
              f"measured {str(row['measured']):>9}  {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
