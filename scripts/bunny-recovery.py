#!/usr/bin/python3
"""Conventional, Bunny-independent Phase 1 recovery console."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ENV = {"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root"}
MARKER = Path("/var/lib/bunny-os/recovery/scheduled.json")


def run(argv: list[str]) -> None:
    subprocess.run(argv, env=ENV, check=False)


def confirm(prompt: str) -> bool:
    return input(f"{prompt} Type YES to continue: ").strip() == "YES"


def disable_bunny() -> None:
    if not confirm("Disable Bunny Desktop autostart for every local user?"):
        return
    for home in Path("/home").iterdir():
        link = home / ".config/systemd/user/graphical-session.target.wants/bunny-desktop.service"
        if link.is_symlink():
            link.unlink()
            print(f"Disabled {link}")


def disable_plugins() -> None:
    if not confirm("Disable third-party Bunny plugins for every local user?"):
        return
    users = Path("/var/lib/bunny/users")
    if not users.is_dir():
        return
    for user in users.iterdir():
        source = user / "plugins"
        destination = user / "plugins.disabled-by-recovery"
        if source.is_dir() and not source.is_symlink() and not destination.exists():
            source.rename(destination)
            print(f"Disabled {source}")


def main() -> int:
    mode = "recovery"
    try:
        mode = json.loads(MARKER.read_text(encoding="utf-8")).get("mode", mode)
        MARKER.unlink()
    except (OSError, json.JSONDecodeError):
        pass
    print(f"Bunny OS offline recovery ({mode}); Bunny Core and Desktop are not running.")
    while True:
        print("\n1 version/deployments  2 filesystem inventory  3 select previous deployment")
        print("4 disable Bunny autostart  5 disable plugins  6 export diagnostics  7 safe graphics")
        print("8 reboot  9 power off")
        choice = input("recovery> ").strip()
        if choice == "1":
            run(["/usr/bin/bunny-os", "--json", "version"])
            run(["/usr/bin/bootc", "status"])
        elif choice == "2":
            run(["/usr/bin/lsblk", "--fs"])
            run(["/usr/bin/systemd-repart", "--dry-run=yes"])
        elif choice == "3" and confirm("Select the previous bootc deployment?"):
            run(["/usr/bin/bootc", "rollback"])
        elif choice == "4":
            disable_bunny()
        elif choice == "5":
            disable_plugins()
        elif choice == "6":
            run(["/usr/bin/bunny-os", "logs", "export", "--since-minutes", "1440"])
        elif choice == "7" and confirm("Create a one-shot nomodeset boot entry and reboot?"):
            result = subprocess.run(["/usr/libexec/bunny-safe-graphics"], env=ENV, check=False)
            if result.returncode == 0:
                run(["/usr/bin/systemctl", "reboot"])
                return 0
        elif choice == "8" and confirm("Reboot now?"):
            run(["/usr/bin/systemctl", "reboot"])
            return 0
        elif choice == "9" and confirm("Power off now?"):
            run(["/usr/bin/systemctl", "poweroff"])
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
