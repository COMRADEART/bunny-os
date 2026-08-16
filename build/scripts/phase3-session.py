#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a declared list of probe commands against a logged-in session.

The Phase 3 persistence journeys are sequences of questions and settings
writes — "read the system report", "set character.scale", "read it back" —
that differ per run. Encoding each sequence in its own driver would mean a
new script per journey; this one takes the sequence as data:

    phase3-session.py --control <sock> --script <steps.json> --output <out.json>

``steps.json`` is a JSON array of probe requests, sent in order, each answer
recorded verbatim. A request may carry ``"label"`` for the record and
``"sleep"`` (seconds, host-side) for settling. The probe's own vocabulary is
the boundary: this driver adds no verbs, so what a journey can do is exactly
what ``desktop-probe.py`` answers, and the record shows every request beside
its answer.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

_HERE = Path(__file__).resolve().parent


def _load_drive():
    specification = importlib.util.spec_from_file_location(
        "desktop_drive", _HERE / "desktop-drive.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(prog="phase3-session")
    parser.add_argument("--control", required=True)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ready-wait", type=float, default=780.0)
    arguments = parser.parse_args()

    steps = json.loads(arguments.script.read_text(encoding="utf-8"))
    if not isinstance(steps, list):
        print("the script must be a JSON array of probe requests", file=sys.stderr)
        return 2

    drive = _load_drive()
    record: dict = {"schemaVersion": 1, "script": str(arguments.script), "steps": []}

    def save(status: str) -> int:
        record["status"] = status
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(record, indent=1, sort_keys=True),
                                    encoding="utf-8")
        print(f"session record: {arguments.output} ({status})")
        return 0 if status == "complete" else 7

    try:
        control = drive.Control(arguments.control)
    except OSError as exc:
        record["error"] = f"cannot reach the control socket: {exc}"
        return save("no-control-channel")

    control.ask_nothing({"command": "hello"})
    print("waiting for the guest to report ready...")
    ready = control.read(timeout=arguments.ready_wait)
    if ready is None or ready.get("event") != "ready":
        record["error"] = "the guest never reported ready"
        record["lastMessage"] = ready
        control.close()
        return save("guest-never-ready")
    record["ready"] = {"controlCount": ready.get("controlCount")}

    failed = False
    for index, step in enumerate(steps):
        request = dict(step)
        settle = float(request.pop("sleep", 0) or 0)
        label = request.get("label", f"step-{index}")
        print(f"  -> {label}: {request.get('command')}")
        answer = control.ask(request, timeout=float(request.pop("timeout", 300)))
        record["steps"].append({"request": step, "answer": answer})
        if answer is None:
            failed = True
            record["error"] = f"no answer to {label}; the session stopped talking"
            break
        if settle:
            time.sleep(settle)

    try:
        control.ask_nothing({"command": "done"})
        control.close()
    except Exception:  # noqa: BLE001
        pass
    return save("failed" if failed else "complete")


if __name__ == "__main__":
    raise SystemExit(main())
