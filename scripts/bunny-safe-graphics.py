#!/usr/bin/python3
"""Create a one-shot BLS entry with conservative graphics kernel arguments."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile


ENV = {"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root"}
SAFE_ENTRY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}(?:\.conf)?\Z")
ENTRIES = Path("/boot/loader/entries")


def main() -> int:
    result = subprocess.run(["/usr/bin/bootctl", "get-default"], env=ENV, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False)
    entry_id = result.stdout.strip()
    if result.returncode != 0 or not SAFE_ENTRY.fullmatch(entry_id) or entry_id.startswith("@"):
        print("Cannot identify a concrete default Boot Loader Specification entry.")
        return 2
    filename = entry_id if entry_id.endswith(".conf") else f"{entry_id}.conf"
    source = ENTRIES / filename
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 1024 * 1024:
        print("Default boot entry is missing, linked, or too large.")
        return 2
    lines = source.read_text(encoding="utf-8", errors="strict").splitlines()
    options = [index for index, line in enumerate(lines) if line.startswith("options ")]
    if len(options) != 1:
        print("Default boot entry does not have exactly one options line.")
        return 2
    title = next((index for index, line in enumerate(lines) if line.startswith("title ")), None)
    if title is not None:
        lines[title] = "title Bunny OS (one-shot safe graphics)"
    arguments = lines[options[0]].split()[1:]
    for argument in ("nomodeset", "systemd.unit=graphical.target"):
        if argument not in arguments:
            arguments.append(argument)
    lines[options[0]] = "options " + " ".join(arguments)
    destination = ENTRIES / "bunny-safe-graphics.conf"
    descriptor, temporary = tempfile.mkstemp(prefix=".bunny-safe-graphics.", dir=ENTRIES)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    selected = subprocess.run(["/usr/bin/bootctl", "set-oneshot", "bunny-safe-graphics.conf"], env=ENV, timeout=10, check=False)
    if selected.returncode != 0:
        try:
            destination.unlink()
        except OSError:
            pass
        print("Bootloader rejected the one-shot safe-graphics entry.")
        return 2
    print("One-shot safe graphics is selected. The next boot adds nomodeset; later boots return to the normal entry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

