# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Programs that run *inside* a capsule, not beside one.

Everything in this package is executed by a confined process with no Bunny code
on its import path, no session bus, no network and no view of the user's home
beyond what a grant bound in. They are therefore written as if they were third
party applications: they take arguments, validate them themselves, read what
they were pointed at, write where they were told, and exit with a status.

Nothing here may import from :mod:`companion`, :mod:`trust` or :mod:`capsules`.
A program that imported the runtime would be a program that could not run in the
sandbox it exists to be run in, and the import would only be discovered on a
machine where the sandbox worked.
"""

__all__: tuple[str, ...] = ()
