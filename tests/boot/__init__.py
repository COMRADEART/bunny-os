# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot-path tests.

This file is why they run.

``unittest discover`` walks a directory only if it can import it as a package.
Without an ``__init__.py`` these thirty-nine tests were skipped by
``scripts/task.py test``, and no other target ran them either — the boot suite
had no runner at all. They were cited in ``LIVE_BOOT_ROOT_CAUSE.md`` and in a
comment inside ``systemd/bunny-update-agent@.service`` as the thing that guards
a unit's ``RuntimeDirectory``/``ReadWritePaths`` pairing, and they had not
executed in the reference suite.

The project had already named this failure mode. ``RELEASE_CLOSURE_SUITES`` in
``scripts/task.py`` carries the note: *"a hyphenated directory is not an
importable Python package, so unittest discover would skip it and the tests
would silently never run. A test that does not run is worse than one in a
differently-spelled directory."* Same mechanism, different spelling of the
cause.

``tests/coverage_of_the_suite`` asserts that no test directory can go
undiscovered again.
"""
