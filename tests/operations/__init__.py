# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Operations tests: the issue ledger, the matrices, the evidence records.

This file is why they run inside ``scripts/task.py test``.

Without an ``__init__.py``, ``unittest discover`` could not import the
directory and skipped its fifteen modules and 114 tests. They were reachable
only through ``make test-phase5``, a separate target somebody has to remember,
and they were absent from every "the reference suite is green" statement this
project has made.

The package is ``tests.operations`` and the top-level directory is the
repository root, so it does not shadow the real ``operations`` package. That
distinction is the reason ``tests()`` passes ``-t ROOT``: with ``tests`` as the
top level it lands on ``sys.path`` and ``tests/sync`` and ``tests/oem`` shadow
the real ``sync/`` and ``oem/``.

``make test-phase5`` still works and is still the way to run these alone.
"""
