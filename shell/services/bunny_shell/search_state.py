# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit search-state machine for the Bunny launcher.

The launcher search surface used to derive its appearance implicitly from
whatever ``route_intent`` and ``application_search`` happened to return: an
empty query showed an unexplained list of twelve applications, and a query
that matched nothing showed a single intent row that looked exactly like a
result. There was no state a person, a test, or an assistive technology could
name.

This module makes the state derivable rather than magical. ``SearchSnapshot``
is a frozen dataclass capturing every input to the panel; ``phase`` is a
property that returns one of five named states. The GTK layer renders from a
snapshot and never decides state on its own, so the states are reachable from
tests without importing a widget toolkit.

The five states:

NO_QUERY
    The search box is empty. The panel shows a minimal hint, not a list that
    looks like results. The previous behaviour of listing twelve applications
    on an empty query was the bug this state replaces.

SEARCHING
    A query has been entered and is being resolved. The snapshot carries no
    results while pending is true; attempting to build a pending snapshot with
    results is refused so the indicator can never lie.

RESULTS
    The query matched at least one application or approved file. The intent
    row and the matched rows are shown together.

ZERO_RESULTS
    The query is non-empty but matched no application and no file. The intent
    row remains as the ask-Bunny affordance, and the panel says so plainly
    instead of rendering an empty strip.

ERROR
    A search input raised. The panel reports the reason and invites retry.
    Error overrides every other state, including pending, so a failed search
    never freezes on "Searching…".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .launcher import ShellIntent


#: The five states a launcher search panel can be in, in the order the
#: ``phase`` property tests them. Error and pending are tested before the
#: query so a failed or in-flight search can never be misread as results.
SEARCH_PHASES = ("NO_QUERY", "SEARCHING", "RESULTS", "ZERO_RESULTS", "ERROR")


@dataclass(frozen=True)
class SearchSnapshot:
    """Every input to one render of the launcher search panel.

    A snapshot is the single source of truth for what the panel should show.
    Widgets hold the latest snapshot; ``phase`` reads it back. Nothing about
    the appearance is decided in the signal handler.
    """

    query: str
    intent: ShellIntent | None
    applications: tuple[dict[str, Any], ...] = ()
    files: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    pending: bool = False

    @property
    def phase(self) -> str:
        if self.error:
            return "ERROR"
        if self.pending:
            return "SEARCHING"
        if not self.query.strip():
            return "NO_QUERY"
        if not self.applications and not self.files:
            return "ZERO_RESULTS"
        return "RESULTS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "query": self.query,
            "intent": self.intent.as_dict() if self.intent is not None else None,
            "applicationCount": len(self.applications),
            "fileCount": len(self.files),
            "error": self.error,
            "pending": self.pending,
        }


def snapshot_for_query(
    query: str,
    *,
    intent: ShellIntent | None,
    applications: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    files: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    error: str | None = None,
    pending: bool = False,
) -> SearchSnapshot:
    """Build a snapshot from the launcher search inputs.

    ``intent`` is passed in rather than re-derived here so the GTK layer can
    route a query through ``route_intent`` once and reuse the result for both
    the intent row and the snapshot. A snapshot never lies about a search that
    has not finished: when ``pending`` is true the application and file lists
    must be empty, and building such a snapshot is refused rather than
    silently dropping the results.
    """
    application_list = list(applications)
    file_list = list(files or ())
    if pending and (application_list or file_list):
        raise ValueError("a pending snapshot must not carry results")
    return SearchSnapshot(
        query=query,
        intent=intent,
        applications=tuple(application_list),
        files=tuple(file_list),
        error=error,
        pending=pending,
    )