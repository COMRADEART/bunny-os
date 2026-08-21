#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the Bunny Companion window at login, or explain why there is none.

Before this existed the runtime service started with the graphical session and
nothing started the window. A person who logged into a freshly installed machine
got a companion that was running and invisible, and the only way to see it was
``bunny-os companion shell`` in a terminal — which §1 of the Alpha brief names as
the thing that must not be necessary.

So this is the login-time client, and it is a launcher rather than the window
itself because there are four things to do before the window and one to do after:

**Consume safe mode.** A one-shot request is spent here, so the launch after a
recovered one is normal again.

**Wait for the runtime.** The window is a client; a client that starts before its
socket exists shows a disconnected companion at every login. The wait is bounded
and its expiry is a *reason*, not a hang.

**Apply the default character policy.** First boot picks the bundled character
that this machine can draw. Later boots re-run the same decision, which does
nothing unless capability rose or the user chose something — see
:mod:`companion.character.policy` for why it can only ever raise.

**Record the timeline.** §4 wants a companion-ready and a first-frame timestamp,
and the only process that knows both is this one.

Afterwards, if the window died before it was usable, count it — three in a row
arms safe mode, so the fourth login produces something a person can act on
instead of a fourth crash. That is §34's "reboot must not enter a permanent
crash loop", written down.

Exit status:

==  ==========================================================================
0   the window ran and exited normally (the user closed it)
2   the runtime never became reachable
3   the window could not be created at all — GTK missing, no display
4   the window started and failed
==  ==========================================================================

A non-zero exit is a failed unit, which is what makes the failure visible in
``systemctl --user status`` and in the recovery screen. It is deliberately not
retried for ever: ``Restart=on-failure`` with a burst limit means a machine that
cannot start a window stops trying and says so.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

# Installed layout first, then the source tree — and only when the package is
# not importable yet. The guard matters: in a process where the checkout is
# already on sys.path, inserting the installed tree in front of it makes every
# later import come from whatever build happens to be installed.
if importlib.util.find_spec("companion") is None:  # pragma: no cover - path setup
    for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
        if _candidate.is_dir() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))

from companion.character.defaults import default_character_paths  # noqa: E402
from companion.support import companion_runtime_dir, companion_state_root  # noqa: E402
from companion.support.safemode import (  # noqa: E402
    accessibility_from_environment,
    consume_safe_mode,
    record_launch_outcome,
    safe_mode_environment,
)

#: How long to wait for the runtime's socket. Long enough for a cold first boot
#: on a slow disk, short enough that a user staring at an empty desktop finds
#: out something is wrong rather than waiting indefinitely.
DEFAULT_WAIT_SECONDS = 30.0

#: How often to look. Cheap: a directory listing.
_POLL_SECONDS = 0.25

#: Where the launcher writes what it observed, for §4's boot timeline and for
#: the diagnostics bundle. Inside the state directory the unit already creates.
TIMELINE_FILE_NAME = "session-timeline.json"


def _endpoint(runtime_dir: Path) -> Path | None:
    """The runtime's socket, if one is there yet.

    Any ``*.sock`` rather than a fixed name: the protocol layer chooses the file
    name and a launcher that hard-coded it would be a second opinion about it.
    """
    try:
        entries = sorted(runtime_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.name.endswith(".sock"):
            return entry
    return None


def wait_for_runtime(
    runtime_dir: Path, *, timeout: float = DEFAULT_WAIT_SECONDS, clock=time.monotonic,
    sleep=time.sleep,
) -> tuple[Path | None, float]:
    """``(endpoint, seconds waited)``. ``None`` means it never appeared."""
    started = clock()
    while True:
        endpoint = _endpoint(runtime_dir)
        if endpoint is not None:
            return endpoint, clock() - started
        if clock() - started >= timeout:
            return None, clock() - started
        sleep(_POLL_SECONDS)


def apply_character_policy(root: Path, mode: object = None) -> dict[str, object]:
    """Choose the bundled character this machine can draw. Never raises.

    The eligible rung comes from :func:`companion.presentation.select_presentation`
    against this session's own signals — the same function the runtime uses, so
    the launcher is not a second opinion about capability either.

    ``mode`` is the user's renderer mode and lowers the ceiling further. Without
    it this function selected the 3D package on every machine that could hold a
    GL context, which is what made 3D the de-facto default before the
    polished-alpha phase made pre-rendered the stated one.
    """
    try:
        from companion.character.importer import PackageRegistry
        from companion.character.policy import apply_default_character_policy
        from companion.presentation import (
            AccessibilityPreferences, PresentationSignals, select_presentation,
        )
        from companion.character.three_d.diagnostics import three_d_environment

        environment = three_d_environment()
        signals = PresentationSignals(
            gpu_available=bool(environment.get("windowedThreeDAvailable")),
            display_available=bool(environment.get("graphicalSession")),
            headless=not environment.get("graphicalSession"),
            available_memory_bytes=_available_memory(),
        )
        preferences = accessibility_from_environment()
        recommendation = select_presentation(signals, preferences)
        registry = PackageRegistry(root / "characters", built_in_paths=default_character_paths())
        decision = apply_default_character_policy(
            registry, eligible=recommendation.eligible, mode=mode
        )
        return decision.to_json()
    except Exception as error:
        return {"error": f"{error}", "applied": False}


def _render_mode(root: Path) -> object:
    """The renderer mode from settings, or the default. Never raises.

    Settings are read on the path that opens the companion window, so an
    unreadable file must cost the user their *preference* and not their
    companion — the default is pre-rendered, which is also the safest thing to
    fall back to.
    """
    try:
        from companion.settings import load_settings

        return load_settings(root).character.mode()
    except Exception:
        from companion.character.modes import DEFAULT_MODE

        return DEFAULT_MODE


def _available_memory() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1]) * 1024
    except OSError:
        return None
    return None


def write_timeline(root: Path, record: dict[str, object]) -> None:
    """Record what this login did, for the boot timeline and diagnostics.

    Best effort and never fatal: a launcher that refused to open a window
    because it could not write a measurement would have its priorities the wrong
    way round.
    """
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / TIMELINE_FILE_NAME
        path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        os.chmod(path, 0o600)
    except OSError:
        pass


def _monotonic_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000.0, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunny-companion-window",
        description="Start the Bunny Companion window for this session.",
    )
    parser.add_argument(
        "--wait-seconds", type=float, default=DEFAULT_WAIT_SECONDS,
        help="how long to wait for the companion runtime's socket",
    )
    parser.add_argument(
        "--text-only", action="store_true",
        help="open the text-only window; used by the recovery surface",
    )
    parser.add_argument(
        "--no-character-policy", action="store_true",
        help="do not apply the default-character policy on this start",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="do everything except open the window, and print what would happen",
    )
    arguments = parser.parse_args(argv)

    started = time.monotonic()
    root = companion_state_root()
    runtime_dir = companion_runtime_dir()

    safe = consume_safe_mode(root)
    os.environ.update(safe_mode_environment(safe, root))
    if safe.enabled:
        print(f"bunny-companion-window: {safe.lines()[0]}", file=sys.stderr)

    endpoint, waited = wait_for_runtime(runtime_dir, timeout=max(0.0, arguments.wait_seconds))
    record: dict[str, object] = {
        "schemaVersion": 1,
        "safeMode": safe.to_json(),
        "runtimeWaitSeconds": round(waited, 3),
        "runtimeReachable": endpoint is not None,
        "endpoint": str(endpoint) if endpoint else "",
        "companionReadyMs": _monotonic_ms(started),
    }
    if endpoint is None:
        record["outcome"] = "runtime-unreachable"
        write_timeline(root, record)
        record_launch_outcome(succeeded=False, root=root)
        print(
            f"bunny-companion-window: the companion runtime did not appear in {runtime_dir} "
            f"within {arguments.wait_seconds:.0f}s. Open Bunny Diagnostics from the "
            "applications list, or run: bunny-os companion diagnose",
            file=sys.stderr,
        )
        return 2

    if not arguments.no_character_policy and not safe.enabled:
        record["characterPolicy"] = apply_character_policy(root, mode=_render_mode(root))
    else:
        record["characterPolicy"] = {
            "applied": False,
            "reason": "safe mode" if safe.enabled else "disabled by --no-character-policy",
        }
    record["characterReadyMs"] = _monotonic_ms(started)

    if arguments.dry_run:
        record["outcome"] = "dry-run"
        write_timeline(root, record)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0

    preferences = accessibility_from_environment(prefer_text_only=bool(arguments.text_only))
    try:
        from companion.gtk_shell import run as run_shell
    except Exception as error:
        record["outcome"] = "gtk-unavailable"
        record["error"] = f"{error}"
        write_timeline(root, record)
        record_launch_outcome(succeeded=False, root=root)
        print(f"bunny-companion-window: the window toolkit is unavailable: {error}", file=sys.stderr)
        return 3

    record["windowStartMs"] = _monotonic_ms(started)
    write_timeline(root, record)
    try:
        code = run_shell(endpoint, preferences=preferences)
    except Exception as error:
        record["outcome"] = "window-failed"
        record["error"] = f"{error}"
        record["windowEndMs"] = _monotonic_ms(started)
        write_timeline(root, record)
        record_launch_outcome(succeeded=False, root=root)
        print(f"bunny-companion-window: the window failed: {error}", file=sys.stderr)
        return 4

    # A window that ran long enough to be used is a successful launch, whatever
    # it exited with. The threshold exists because a GTK application that fails
    # during `activate` still returns an exit code rather than raising, and a
    # crash loop made of clean exits is still a crash loop.
    elapsed = time.monotonic() - started
    usable = elapsed >= 3.0 and code == 0
    record["outcome"] = "closed" if usable else "exited-early"
    record["exitCode"] = code
    record["windowEndMs"] = _monotonic_ms(started)
    write_timeline(root, record)
    record_launch_outcome(succeeded=usable, root=root)
    return 0 if code == 0 else 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
