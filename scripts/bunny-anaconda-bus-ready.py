#!/usr/bin/python3
"""Hold bunny-anaconda-bus.service at "starting" until its address exists.

The backend preflights its executor the moment it starts, and unit ordering
alone would race dbus-daemon's write of the address file: After= waits for
"started", and a Type=simple daemon is "started" the moment it forks. This
runs as ExecStartPost, so "started" only happens once the address is real.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

ADDRESS = Path("/run/anaconda/bus.address")


def main() -> int:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            if ADDRESS.stat().st_size > 0:
                return 0
        except OSError:
            pass
        time.sleep(0.1)
    sys.stderr.write("the bus address was never written\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
