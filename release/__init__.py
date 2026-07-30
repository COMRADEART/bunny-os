"""Release blocker closure: evidence, gates, and fail-closed dispositions.

This package exists to close the blockers that prevent a signed stable Bunny OS
release, not to add product features. Every module here follows the same rule as
``operations/qualification.py``: absent evidence is blocking, and no code path
converts an unmeasured thing into a passing thing.

The package is standard-library only, like ``operations/``, ``enterprise/``,
``oem/`` and ``sync/``, so every gate runs on any development host.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

#: Evidence result vocabulary, shared with ``operations.qualification.STATUSES``
#: so the two records cannot drift into disagreeing about what "passing" means.
RESULTS = ("PASS", "FAIL", "BLOCKED", "UNKNOWN", "NOT_RUN")

#: Results that permit a gate to proceed. Everything else blocks, including
#: ``UNKNOWN`` — the brief is explicit that unknown evidence remains blocking.
PASSING_RESULTS = frozenset({"PASS"})

__all__ = ["SCHEMA_VERSION", "RESULTS", "PASSING_RESULTS"]
