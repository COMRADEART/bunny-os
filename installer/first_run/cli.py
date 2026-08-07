# SPDX-License-Identifier: GPL-3.0-or-later
"""First-run launcher with a useful non-GTK status fallback."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def default_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "bunny-os/first-run.json"


def main() -> int:
    parser = argparse.ArgumentParser(prog="bunny-first-run")
    parser.add_argument("--status", action="store_true",
                        help="print the resumable state and exit")
    parser.add_argument("--describe", action="store_true",
                        help="print every page and what it would say on this machine")
    parser.add_argument("--state", type=Path, default=default_path())
    args = parser.parse_args()

    from .alpha import AlphaFirstRun, run

    session = AlphaFirstRun(args.state)
    session.load()
    if args.status:
        print(json.dumps({
            "schemaVersion": 2,
            "currentStep": session.model.step.step_id,
            "completed": session.complete,
            "answers": session.model.answers,
        }, indent=2, sort_keys=True))
        return 0
    if args.describe:
        # The text form of the whole wizard. §26 forbids essential information
        # existing only in a graphical surface, and this is also what the gate
        # reads: a wizard that can only be inspected by opening it can only be
        # checked by a person looking at one.
        views = []
        for step in session.model.steps:
            session.model.go_to(step.step_id)
            views.append(session.model.view().to_json())
        print(json.dumps({"schemaVersion": 2, "steps": views}, indent=2, sort_keys=True))
        return 0
    return run(args.state)


if __name__ == "__main__":
    raise SystemExit(main())
