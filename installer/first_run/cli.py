# SPDX-License-Identifier: GPL-3.0-or-later
"""First-run launcher with a useful non-GTK status fallback."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .state import FirstRunState


def default_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "bunny-os/first-run.json"


def main() -> int:
    parser = argparse.ArgumentParser(prog="bunny-first-run")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--state", type=Path, default=default_path())
    args = parser.parse_args()
    state = FirstRunState(args.state)
    if args.status:
        value = state.load()
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    from .app import run

    return run(state)


if __name__ == "__main__":
    raise SystemExit(main())
