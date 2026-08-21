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
    parser.add_argument("--choices", type=Path,
                        help="the setup choices document; defaults to the one the "
                             "installer wrote to the target")
    parser.add_argument("--skip-apply", action="store_true",
                        help="do not apply the setup choices (for inspection only)")
    parser.add_argument("--apply-only", action="store_true",
                        help="apply the setup choices, report, and exit without a window")
    args = parser.parse_args()

    # §30: the desktop must already reflect what was chosen during installation
    # by the time onboarding closes — so this runs *before* the wizard, not
    # after it, and it runs whether or not the person ever finishes.
    #
    # It is deliberately not conditional on the wizard succeeding. A person who
    # dismisses first run in the first second still gets the theme, the text
    # scale and the Companion mode they asked for during setup; §28's promise is
    # about what installation collected, not about what onboarding completes.
    applied = None
    if not args.skip_apply:
        from installer.first_run.apply import apply_all, load_choices, record_applied
        from installer.setup_state import CHOICES_ON_TARGET

        choices = load_choices(args.choices or CHOICES_ON_TARGET)
        if choices is None:
            # A system installed some other way, or from before setup wrote
            # this. Saying so beats silently onboarding with defaults nobody
            # chose and then reporting that preferences persisted.
            print(json.dumps({
                "schemaVersion": 1, "applied": 0, "total": 0,
                "reason": "no setup choices document; nothing to apply",
            }, sort_keys=True))
        else:
            applied = apply_all(choices, dry_run=args.apply_only)
            if not args.apply_only:
                applied["recordedAt"] = str(record_applied(applied))
            print(json.dumps(applied, indent=2, sort_keys=True))
    if args.apply_only:
        return 0

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
