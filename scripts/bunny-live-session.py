#!/usr/bin/python3
"""Create the fixed, unprivileged live-session identity on ephemeral media."""

from __future__ import annotations

import os
from pathlib import Path
import pwd
import subprocess


LIVE_USER = "bunny-live"
MARKER = Path("/run/bunny-installer/live-session")


def main() -> int:
    if Path("/usr/lib/bunny-os/release.json").is_file():
        # The image profile check prevents this unit from being enabled in the
        # installed beta payload.  Refuse if the live-media marker directory is
        # unavailable rather than creating a conventional persistent account.
        Path("/run/bunny-installer").mkdir(parents=True, exist_ok=True, mode=0o755)
    try:
        account = pwd.getpwnam(LIVE_USER)
    except KeyError:
        subprocess.run(
            ["/usr/sbin/useradd", "--uid", "1000", "--create-home", "--shell", "/usr/bin/bash", "--comment", "Bunny OS Live Session", LIVE_USER],
            check=True,
            env={"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
        subprocess.run(["/usr/bin/passwd", "--lock", LIVE_USER], check=True, env={"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8"})
        account = pwd.getpwnam(LIVE_USER)
    # The §42 setup driver autostarts in this account's session and reports
    # over /dev/ttyS0 (root:dialout 0660). `useradd --groups dialout` is not an
    # option: on an ostree image that group lives in /usr/lib/group, which
    # nss-altfiles serves to getent while shadow-utils reads only /etc/group -
    # "group 'dialout' does not exist", measured in the image, and the failed
    # unit left the medium drawing gnome-initial-setup instead of the live
    # session. The root half hands the device to the account instead.
    # Best-effort: a machine with no ttyS0 is one where nothing was listening.
    try:
        os.chown("/dev/ttyS0", account.pw_uid, -1)
    except OSError:
        pass
    descriptor = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        os.write(descriptor, f"uid={account.pw_uid}\nprofile=live\n".encode("ascii"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
