# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Path rendering for human-readable output.

``Path.relative_to`` is a partial function. It raises ``ValueError`` when the
path is not under the root, which makes it correct for a containment check and
wrong for a progress message. The repository used it for both, so writing a
report outside the working tree — which CI does deliberately, into
``$RUNNER_TEMP``, so that a drill artifact can never be mistaken for a committed
one — crashed the tool after its work was complete.

The two uses are separated here. ``display_path`` never raises: a path under the
root renders relative, anything else renders absolute. Containment checks keep
calling ``relative_to`` directly and keep raising, because there the exception is
the check. Every call site in the repository is classified in
``docs/CI_PORTABILITY_BASELINE.md``; only the display-only ones use this module.

Relative output is rendered POSIX-style so a message reads identically on a
Windows development host and an Ubuntu runner. Absolute output keeps the
platform's own separator, because an absolute path is only useful in the form the
platform will accept back.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath

__all__ = ["display_path", "is_within"]


def display_path(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    """Render ``path`` for display, relative to ``root`` when it lies under it.

    Both operands are resolved first, so a symlink is described by its target and
    a relative path is interpreted against the current working directory. This
    function is for messages only: it makes no assertion about where the path is
    allowed to be, and callers that need that assertion must check it separately.
    """
    resolved = Path(path).resolve()
    try:
        return PurePath(resolved.relative_to(Path(root).resolve())).as_posix()
    except ValueError:
        return str(resolved)


def is_within(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """Whether ``path`` resolves to a location under ``root``.

    The boolean form of the containment check, for callers that report several
    offending paths rather than raising on the first. Callers that should stop at
    the first offender keep using ``relative_to`` and its exception.
    """
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True
