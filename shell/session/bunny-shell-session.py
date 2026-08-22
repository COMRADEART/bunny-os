#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the Bunny or Bunny Safe Shell GNOME session."""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    mode = "safe" if "--safe" in sys.argv[1:] else "normal"
    os.environ["BUNNY_SHELL_MODE"] = mode
    os.environ["XDG_CURRENT_DESKTOP"] = "Bunny:GNOME"
    os.environ["DESKTOP_SESSION"] = "bunny-safe" if mode == "safe" else "bunny"
    subprocess.run(
        ["/usr/bin/systemctl", "--user", "import-environment", "BUNNY_SHELL_MODE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION"],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    target_action = "stop" if mode == "safe" else "start"
    # Blocking, and its answer is recorded. --no-block here is how a dead target
    # survived every gate: the start job was queued and never checked, so a
    # target that failed (or was reaped a second later) looked identical to one
    # that came up. A failure is written to the journal and the GNOME session
    # still starts — a broken Bunny layer must never block the login — but the
    # journal now says so instead of the desktop quietly losing its status
    # producer and search timer.
    target = subprocess.run(
        ["/usr/bin/systemctl", "--user", target_action, "bunny-shell.target"],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if target.returncode != 0:
        detail = (target.stderr or target.stdout or "").strip()
        print(
            f"bunny-shell-session: systemctl --user {target_action} "
            f"bunny-shell.target failed ({target.returncode}): {detail}",
            file=sys.stderr,
            flush=True,
        )
    os.execv("/usr/bin/gnome-session", ["/usr/bin/gnome-session", "--session=gnome"])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
