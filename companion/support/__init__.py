# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a person reaches for when Bunny does not work.

Three surfaces, and they are separate because they are needed at different
moments by people in different states:

:mod:`~companion.support.safemode`
    a reduced companion that starts when the normal one cannot. Its job is to
    get *something* on the screen, so the machine stops being a machine with no
    companion and becomes a machine with a limited one.
:mod:`~companion.support.diagnose`
    what is wrong, in one screen, with the actions that fix the common causes.
    Read by somebody whose companion started and is behaving badly.
:mod:`~companion.support.export`
    a file to send somebody else. Read by nobody locally; written so that a
    stranger can read it and so that the person sending it can check first.

All three run **without the runtime**. That is the constraint that shapes them:
the failure they exist for is "the runtime did not start", and a diagnostic that
needed the runtime to answer would be unavailable exactly when it is wanted.
They read the store, the units and the machine directly.

None of them uploads anything. §38 is explicit — no automatic crash collection —
and the export writes a file the user opens, reads and decides about.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["companion_state_root", "companion_runtime_dir"]


def companion_state_root() -> Path:
    """Where the companion keeps its store, resolved the same way everywhere.

    A fourth copy of this resolution would be a fourth place for it to drift, so
    this is deliberately identical to ``companion.cli.default_root`` and to the
    service entry point's ``_state_root``. Those two cannot import this module
    — one is a console entry point and the other runs before the package is on
    the path — which is why the duplication exists at all and why it is called
    out here rather than left to be discovered.
    """
    override = os.environ.get("BUNNY_COMPANION_ROOT")
    if override:
        return Path(override)
    state = os.environ.get("STATE_DIRECTORY")
    if state:
        return Path(state.split(":")[0])
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured) if configured else Path.home() / ".local" / "state"
    return base / "bunny-os" / "companion"


def companion_runtime_dir() -> Path:
    """Where the socket lives. ``RuntimeDirectory=`` in the unit creates it."""
    runtime = os.environ.get("RUNTIME_DIRECTORY")
    if runtime:
        return Path(runtime.split(":")[0])
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / "bunny-companion"
    if hasattr(os, "getuid"):
        return Path(f"/run/user/{os.getuid()}/bunny-companion")
    # No XDG_RUNTIME_DIR and no uid: a development host that is not the target.
    # A path that does not exist, rather than the working directory, because a
    # diagnostic that listed the current directory as "the runtime directory"
    # once printed a repository tree into a bug report.
    return Path("bunny-companion-runtime-directory-unavailable")
