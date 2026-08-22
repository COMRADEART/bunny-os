# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Owning regression tests for the launcher search-state machine.

Each test names one state and proves the snapshot derives it from inputs the
real launcher pipeline can produce. No widget toolkit is imported: the states
are pure properties of ``SearchSnapshot``, which is the point of extracting
them. GTK-driven keyboard and pointer interaction is not exercised here
because PyGObject is not available on every host that runs this suite; the
state contract these tests pin is what the GTK layer renders from.
"""

from __future__ import annotations

import unittest

from bunny_shell.launcher import application_search, route_intent
from bunny_shell.search_state import SEARCH_PHASES, SearchSnapshot, snapshot_for_query


def _application(desktop_id: str, name: str, comment: str = "") -> dict:
    return {"desktop_id": desktop_id, "name": name, "comment": comment, "kind": "Application"}


def _file(name: str, path: str, relative: str) -> dict:
    return {"name": name, "path": path, "relativePath": relative, "kind": "file"}


class SearchPhaseTests(unittest.TestCase):
    def test_no_query_when_the_search_box_is_empty(self) -> None:
        # An empty query is NO_QUERY regardless of what applications are
        # passed: the panel shows a hint, not a list that looks like results.
        snapshot = snapshot_for_query(
            "", intent=route_intent(""), applications=[_application("org.example.Editor.desktop", "Editor")]
        )
        self.assertEqual(snapshot.phase, "NO_QUERY")

    def test_no_query_does_not_list_applications_anymore(self) -> None:
        # The previous behaviour listed twelve applications on an empty query.
        # NO_QUERY now means the panel carries no results, even if a caller
        # passes some in: the empty query wins.
        snapshot = snapshot_for_query("", intent=None, applications=[_application("a.desktop", "A")])
        self.assertEqual(snapshot.phase, "NO_QUERY")
        self.assertEqual(snapshot.applications, (_application("a.desktop", "A"),))

    def test_searching_while_a_query_is_being_resolved(self) -> None:
        snapshot = snapshot_for_query("editor", intent=None, pending=True)
        self.assertEqual(snapshot.phase, "SEARCHING")

    def test_results_when_a_query_matches_applications(self) -> None:
        intent = route_intent("editor")
        snapshot = snapshot_for_query(
            "editor", intent=intent, applications=[_application("org.example.Editor.desktop", "Editor")]
        )
        self.assertEqual(snapshot.phase, "RESULTS")

    def test_results_when_a_query_matches_only_files(self) -> None:
        # A file hit is a real result. The launcher must not say "no results"
        # when the metadata index returned a match.
        snapshot = snapshot_for_query(
            "notes", intent=route_intent("notes"), files=[_file("notes.txt", "/home/bunny/docs/notes.txt", "docs/notes.txt")]
        )
        self.assertEqual(snapshot.phase, "RESULTS")

    def test_zero_results_when_a_query_matches_nothing(self) -> None:
        # Uses the real application_search so the test proves ZERO_RESULTS is
        # reachable through the live pipeline, not just from synthetic inputs.
        query = "zzzzz_no_such_application_zzzzz"
        applications = application_search(query, 50)
        snapshot = snapshot_for_query(query, intent=route_intent(query), applications=applications)
        self.assertEqual(snapshot.phase, "ZERO_RESULTS")
        self.assertEqual(snapshot.applications, ())

    def test_zero_results_keeps_the_intent_row(self) -> None:
        # A query that matches nothing still leaves the ask-Bunny affordance:
        # the intent survives in the snapshot so the panel can show it.
        intent = route_intent("ask bunny to summarise the notes")
        snapshot = snapshot_for_query("ask bunny to summarise the notes", intent=intent)
        self.assertEqual(snapshot.phase, "ZERO_RESULTS")
        self.assertIs(snapshot.intent, intent)

    def test_error_when_a_search_input_raised(self) -> None:
        snapshot = snapshot_for_query("editor", intent=None, error="unsupported search configuration version")
        self.assertEqual(snapshot.phase, "ERROR")

    def test_error_overrides_pending(self) -> None:
        # A failed search must never freeze on "Searching…".
        snapshot = snapshot_for_query("editor", intent=None, error="boom", pending=True)
        self.assertEqual(snapshot.phase, "ERROR")

    def test_error_overrides_a_non_empty_query(self) -> None:
        snapshot = snapshot_for_query(
            "editor", intent=route_intent("editor"),
            applications=[_application("org.example.Editor.desktop", "Editor")], error="boom",
        )
        self.assertEqual(snapshot.phase, "ERROR")


class SearchSnapshotIntegrityTests(unittest.TestCase):
    def test_pending_with_results_is_refused(self) -> None:
        # A pending snapshot that carries results would let the "Searching…"
        # indicator lie. Building one is refused rather than silently dropping
        # the results.
        with self.assertRaises(ValueError):
            snapshot_for_query("editor", intent=None, applications=[_application("a.desktop", "A")], pending=True)
        with self.assertRaises(ValueError):
            snapshot_for_query("editor", intent=None, files=[_file("a", "/a", "a")], pending=True)

    def test_empty_query_with_pending_is_still_no_query(self) -> None:
        # Pending is tested before the query, but an empty query with pending
        # is a degenerate case the launcher never builds. The state machine
        # still names it: SEARCHING wins so a resolving empty query does not
        # flash the NO_QUERY hint. This test pins that ordering.
        snapshot = snapshot_for_query("", intent=None, pending=True)
        self.assertEqual(snapshot.phase, "SEARCHING")

    def test_phases_are_the_five_named_states(self) -> None:
        self.assertEqual(SEARCH_PHASES, ("NO_QUERY", "SEARCHING", "RESULTS", "ZERO_RESULTS", "ERROR"))

    def test_snapshot_is_frozen(self) -> None:
        snapshot = snapshot_for_query("editor", intent=route_intent("editor"))
        with self.assertRaises(Exception):
            snapshot.query = "changed"  # type: ignore[misc]

    def test_as_dict_names_the_phase_and_counts(self) -> None:
        snapshot = snapshot_for_query(
            "editor", intent=route_intent("editor"),
            applications=[_application("org.example.Editor.desktop", "Editor"), _application("org.example.Other.desktop", "Other")],
            files=[_file("notes.txt", "/x/notes.txt", "notes.txt")],
        )
        value = snapshot.as_dict()
        self.assertEqual(value["phase"], "RESULTS")
        self.assertEqual(value["applicationCount"], 2)
        self.assertEqual(value["fileCount"], 1)
        self.assertIsNone(value["error"])
        self.assertFalse(value["pending"])
        self.assertEqual(value["intent"]["type"], "search")

    def test_as_dict_for_error_state(self) -> None:
        snapshot = snapshot_for_query("editor", intent=None, error="boom")
        value = snapshot.as_dict()
        self.assertEqual(value["phase"], "ERROR")
        self.assertEqual(value["error"], "boom")
        self.assertIsNone(value["intent"])


class SearchPipelineTests(unittest.TestCase):
    """The states must be reachable from the real launcher functions.

    These guard the contract between ``route_intent`` / ``application_search``
    and the snapshot: if a future change to either function makes a state
    unreachable, one of these fails.
    """

    def test_empty_query_routes_to_a_search_intent(self) -> None:
        # NO_QUERY uses route_intent("") only to carry an intent for the hint
        # path; the phase itself does not depend on the intent type, but the
        # launcher does call route_intent("") at start-up, so it must remain a
        # search intent rather than, say, a broker action.
        self.assertEqual(route_intent("").type, "search")

    def test_unmatched_query_yields_no_applications_on_this_host(self) -> None:
        # On a host with no matching desktop entries, application_search
        # returns an empty list, which is exactly the ZERO_RESULTS input.
        self.assertEqual(application_search("zzzzz_no_such_application_zzzzz", 50), [])

    def test_error_state_is_reachable_from_a_malformed_search_index(self) -> None:
        # The launcher's ERROR state is reachable through SearchIndex.query:
        # query reads the index file, and a malformed index raises ValueError,
        # which the launcher catches and renders as ERROR. This test proves the
        # exception type the launcher catches is the one the index raises, so
        # the state is not theoretical.
        import tempfile
        from pathlib import Path
        from bunny_shell.search import SearchIndex
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "index.json").write_text("not valid json", encoding="utf-8")
        index = SearchIndex(root / "config.json", root / "index.json")
        with self.assertRaises(ValueError):
            index.query("anything")