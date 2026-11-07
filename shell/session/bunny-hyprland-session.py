#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the primary Bunny session on Hyprland.

Hyprland is the desktop customization compositor for Bunny OS. GNOME remains
available as Bunny (GNOME) and Bunny (Safe Shell); this wrapper is what the
default ``bunny`` wayland-session entry executes.
"""

from __future__ import annotations

import os
import subprocess
import sys

HYPRLAND_CONFIG = "/usr/share/bunny-shell/hyprland/hyprland.conf"
HYPRLAND_BIN = "/usr/bin/Hyprland"


def main() -> int:
    os.environ["BUNNY_SHELL_MODE"] = "normal"
    os.environ["BUNNY_DESKTOP_COMPOSITOR"] = "hyprland"
    os.environ["XDG_CURRENT_DESKTOP"] = "Bunny:Hyprland"
    os.environ["DESKTOP_SESSION"] = "bunny"
    # Prefer the image-owned config over an empty user tree so first login is
    # a Bunny desktop, not stock Hyprland. Users can still override via
    # ~/.config/hypr once they copy or symlink intentionally.
    os.environ["XDG_CONFIG_DIRS"] = "/usr/share/bunny-shell/hyprland/xdg:" + os.environ.get(
        "XDG_CONFIG_DIRS", "/etc/xdg"
    )

    subprocess.run(
        [
            "/usr/bin/systemctl",
            "--user",
            "import-environment",
            "BUNNY_SHELL_MODE",
            "BUNNY_DESKTOP_COMPOSITOR",
            "XDG_CURRENT_DESKTOP",
            "DESKTOP_SESSION",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    # Same contract as bunny-shell-session: block on the target so a dead
    # Bunny layer is visible in the journal, but never refuse the login.
    target = subprocess.run(
        ["/usr/bin/systemctl", "--user", "start", "bunny-shell.target"],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if target.returncode != 0:
        detail = (target.stderr or target.stdout or "").strip()
        print(
            "bunny-hyprland-session: systemctl --user start "
            f"bunny-shell.target failed ({target.returncode}): {detail}",
            file=sys.stderr,
            flush=True,
        )

    if not os.path.isfile(HYPRLAND_BIN):
        print(
            f"bunny-hyprland-session: {HYPRLAND_BIN} is missing; "
            "falling back to the GNOME Bunny session wrapper",
            file=sys.stderr,
            flush=True,
        )
        os.execv(
            "/usr/libexec/bunny-shell-session",
            ["/usr/libexec/bunny-shell-session"],
        )
        return 127

    os.execv(
        HYPRLAND_BIN,
        [HYPRLAND_BIN, "--config", HYPRLAND_CONFIG],
    )
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
