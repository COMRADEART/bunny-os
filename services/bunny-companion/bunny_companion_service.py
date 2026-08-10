#!/usr/bin/python3
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
import importlib.util
import sys

# Installed layout first, then the source tree, matching bin/bunny-os.
# Only when the package is not importable yet.
#
# For a standalone invocation nothing is importable, so this behaves exactly as
# it always has: the installed tree first, the checkout as a fallback.
#
# The guard is for the other case. In a process that already works — a test
# run, another tool that imported this one — the checkout is already on
# ``sys.path``, so the loop skipped it as already-present and inserted the
# *installed* tree in front of it. Every import after that came from whatever
# build happened to be installed, which on a qualification host is a build from
# an earlier phase. It fails loudly when that build is missing a module and
# silently when it is not, and the silent case is a whole test suite passing
# against code nobody changed.
if importlib.util.find_spec("companion") is None:
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


def _options() -> ServiceOptions:
    """How this runtime is built, which safe mode is allowed to reduce.

    The safe-mode file is read here rather than inherited from an environment,
    because systemd starts this process and there is no parent to inherit from.
    It lives inside the ``StateDirectory`` the unit already creates, so it is
    readable under ``ProtectSystem=strict`` without a new ``ReadWritePaths``.

    Safe mode composes flags that already existed — ``speech_enabled``,
    ``desktop_enabled``, ``voice_enabled`` — rather than introducing a reduced
    code path of its own. A mode with its own path would need its own tests to
    prove it still worked; a mode that is a combination of specified flags
    inherits theirs.
    """
    root = _state_root()
    try:
        from companion.settings import load_settings

        settings = load_settings(root)
        options = ServiceOptions(
            root=root,
            preferences=settings.accessibility_preferences(),
            # Constructing either subsystem opens no device and starts no
            # capture. Keep the objects available so an Off→On setting applies
            # live; the preference is the fail-closed gate.
            voice_enabled=True,
            voice_preferences=settings.voice_preferences(),
            speech_enabled=True,
            speech_preferences=settings.speech_preferences(),
        )
    except Exception as exc:  # pragma: no cover - settings cannot block login
        print(
            f"bunny-companion-service: voice settings not applied ({exc}); using safe defaults",
            file=sys.stderr,
        )
        options = ServiceOptions(root=root)
    try:
        from companion.support.safemode import (
            local_only_configuration, read_safe_mode, service_overrides,
        )

        state = read_safe_mode(root)
        overrides = service_overrides(state, root)
    except Exception as exc:  # pragma: no cover - safe mode must never block a start
        print(f"bunny-companion-service: safe mode not consulted: {exc}", file=sys.stderr)
        return options
    if not overrides:
        return options
    import dataclasses

    options = dataclasses.replace(options, **overrides)
    try:
        from companion.agents.config import default_configuration, load_agent_configuration

        try:
            configuration = load_agent_configuration(root)
        except Exception:
            configuration = default_configuration(root)
        options = dataclasses.replace(
            options, agent_configuration=local_only_configuration(configuration),
        )
    except Exception as exc:  # pragma: no cover
        print(
            f"bunny-companion-service: safe mode could not filter providers ({exc}); "
            "the agent runtime is disabled instead",
            file=sys.stderr,
        )
        options = dataclasses.replace(options, agents_enabled=False)
    print(
        "bunny-companion-service: SAFE MODE — no microphone, no desktop actions, "
        "no spoken output, no remote provider",
        file=sys.stderr,
    )
    return options


def main() -> int:
    # Before anything probes the desktop. This service is started while
    # graphical-session.target is being reached, which on a measured boot was
    # two seconds before gnome-session imported WAYLAND_DISPLAY — so without
    # this it spends the whole session believing there is no display and
    # refusing every action that needs one. See
    # companion.desktop.environment.adopt_graphical_environment.
    from companion.desktop.environment import adopt_graphical_environment

    adopted = adopt_graphical_environment()
    if adopted:
        print(
            "bunny-companion-service: adopted the session's display from "
            f"{', '.join(f'{key}={value}' for key, value in sorted(adopted.items()))}",
            file=sys.stderr,
        )

    try:
        service = CompanionService(_options()).start()
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
