# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``bunny-os companion`` command group, attached to the management CLI.

A thin adapter. The commands themselves live in :mod:`companion.cli`, inside the
package they operate on, so that the tests exercise the same code the CLI runs
rather than a parallel implementation that has to be kept in step with it.

Like ``bunny-os capability``, these commands are local and go nowhere near the
broker: the companion store is the user's own, they need no privilege the caller
does not already have, and they must work on a machine whose broker is not
running — which is exactly the machine somebody is inspecting when a companion
task went wrong.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

# Installed layout first, then the source tree, matching bin/bunny-os.
for candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[3]):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from companion import cli as companion_cli  # noqa: E402
from companion.errors import CompanionError  # noqa: E402

__all__ = ["CompanionError", "add_arguments", "dispatch"]


def add_arguments(subparsers: argparse._SubParsersAction) -> None:
    companion_cli.add_arguments(subparsers)


def dispatch(args: argparse.Namespace) -> Any:
    return companion_cli.dispatch(args)
