#!/usr/bin/python3
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
    subprocess.run(
        ["/usr/bin/systemctl", "--user", target_action, "--no-block", "bunny-shell.target"],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    os.execv("/usr/bin/gnome-session", ["/usr/bin/gnome-session", "--session=gnome"])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
