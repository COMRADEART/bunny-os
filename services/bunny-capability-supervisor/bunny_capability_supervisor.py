#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The installed entry point for the capability supervisor.

Deliberately thin. Everything it does is in :mod:`capability.supervisor`; this
exists so that the unit's ``ExecStart`` names one absolute path that does not
change when the package layout does, and so that the installed program and the
importable module cannot drift apart.

The one thing it does add is the search path. On an installed system the
capability package lives at ``/usr/lib/bunny-os/python``, which is not on
``sys.path`` for a bare interpreter; in a source checkout it is the repository
root. Both are tried, installed first, so a developer running this out of a
checkout gets the checkout's code and an installed system never picks up a
stray copy from a working directory it happens to have been started in.
"""

from __future__ import annotations

from pathlib import Path
import sys

#: Installed layout first, then the source tree. Matches bin/bunny-os so that
#: the two front ends resolve the same package on the same machine.
for candidate in (
    Path("/usr/lib/bunny-os/python"),
    Path(__file__).resolve().parents[2],
):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from capability.supervisor import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
