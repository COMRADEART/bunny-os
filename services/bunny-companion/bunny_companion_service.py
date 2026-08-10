#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import sys

system = Path("/usr/lib/bunny-os/python")
sys.path.insert(0, str(system if system.exists() else Path(__file__).resolve().parents[2]))

from companion.cli import main

raise SystemExit(main("bunny-companion-service"))
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point for the Bunny Companion runtime user service.

Starts exactly one :class:`companion.service.CompanionService` and blocks. It
takes no arguments and reads no configuration beyond the XDG variables systemd
already sets, because a service whose behaviour depended on a command line would
have a second place for its behaviour to be defined and the unit file would stop
being the whole answer.

A second instance refuses to bind and exits 3, rather than displacing the one
that is running: two runtimes over one store would both drive tasks and both
believe they held the executor lease.
"""

from __future__ import annotations

from pathlib import Path
import os
import signal
import sys

# Installed layout first, then the source tree, matching bin/bunny-os.
for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[2]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from companion.protocol import DuplicateRuntime  # noqa: E402
from companion.service import CompanionService, ServiceOptions, StartupFailed  # noqa: E402


def _state_root() -> Path:
    """Where the store lives. ``StateDirectory=`` in the unit creates it."""
    override = os.environ.get("BUNNY_COMPANION_ROOT")
    if override:
        return Path(override)
    state = os.environ.get("STATE_DIRECTORY")
    if state:
        # systemd may pass a colon-separated list; the unit declares one.
        return Path(state.split(":")[0])
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured) if configured else Path.home() / ".local" / "state"
    return base / "bunny-os" / "companion"


def main() -> int:
    try:
        service = CompanionService(ServiceOptions(root=_state_root())).start()
    except DuplicateRuntime as exc:
        print(f"bunny-companion-service: {exc}", file=sys.stderr)
        return 3
    except StartupFailed as exc:
        # Names the step, because "it did not start" and "it did not start at
        # initialise-durable-state" are different problems for whoever reads the
        # journal, and the service has already released everything it held.
        print(
            f"bunny-companion-service: start-up failed at {exc.step}: {exc.cause}",
            file=sys.stderr,
        )
        return 4 if isinstance(exc.cause, OSError) else 5
    except OSError as exc:
        print(f"bunny-companion-service: the endpoint could not be bound: {exc}", file=sys.stderr)
        return 4

    def _shutdown(_signum: int, _frame: object) -> None:
        # Closing releases the socket and stops the worker. Whatever a task had
        # already written is durable — the store fsyncs before it acknowledges
        # an append — so there is nothing to flush and nothing to lose.
        service.close()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(
        "bunny-companion-service: listening on "
        f"{service.server.describe()['endpoint']} ({service.server.describe()['transport']})",
        file=sys.stderr,
    )
    try:
        service.serve_forever()
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
