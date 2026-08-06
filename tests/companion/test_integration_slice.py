# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§23's vertical slice, as a gate rather than a demonstration.

The slice itself lives in :mod:`companion.vertical_slice` so that
``bunny-os companion run-integration-slice`` and this test run the *same*
twenty-seven steps. A slice that only existed inside a test would be a slice
nobody could run on a machine that was misbehaving.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.gtk_shell import CompanionViewModel
from companion.protocol import CompanionClient
from companion.service import CompanionService, ServiceOptions
from companion.vertical_slice import SLICE_REQUEST, run_slice


class VerticalSliceTests(unittest.TestCase):
    """One slice run, many assertions.

    The slice is deterministic and expensive: it starts two services and makes
    several hundred connections. Running it once per *test* meant three runs
    here and three more in the character suite, which on the loopback developer
    transport walks through the host's ephemeral port range and fails for a
    reason that has nothing to do with the companion.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls._directory.name)
        cls.report = run_slice(cls.root, speak=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._directory.cleanup()

    def test_the_whole_provider_free_slice_passes(self) -> None:
        document = self.report.to_json()
        self.assertTrue(
            document["passed"],
            "failed steps: " + "; ".join(
                f"{item['step']} {item['name']}: {item}"
                for item in document["steps"] if not item["ok"]
            ),
        )
        self.assertEqual([item["step"] for item in document["steps"]], sorted(
            item["step"] for item in document["steps"]
        ))
        self.assertEqual(len(document["steps"]), 27)
        self.assertEqual(document["network"], "none")
        self.assertEqual(document["provider"], "none")
        self.assertEqual(document["credentials"], "none")
        # And it says what it did not cover rather than leaving it to be assumed.
        self.assertFalse(document["gtkWidgetsExercised"])

    def test_the_slice_proves_the_binding_check_by_failing_it_first(self) -> None:
        step = next(item for item in self.report.to_json()["steps"] if item["step"] == 12)
        self.assertTrue(step["ok"])
        self.assertEqual(step["code"], "approval_mismatch")
        self.assertEqual(step["altered"], "destination")

    def test_the_slice_answers_more_than_one_question(self) -> None:
        """The reviewer forces a replan, which supersedes the first consent."""
        step = next(item for item in self.report.to_json()["steps"] if item["step"] == 11)
        self.assertGreaterEqual(len(step["approvals"]), 2)
        self.assertEqual(step["error"], "")


class ClientLifecycleTests(unittest.TestCase):
    """§7's list, exercised through the client's own behaviour."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.endpoint = self.root / "runtime" / "runtime.sock"
        self.service = CompanionService(ServiceOptions(
            root=self.root, endpoint=self.endpoint, machine="laptop", consent_wait_seconds=5.0,
        )).start()
        self.addCleanup(self.service.close)

    def _model(self) -> CompanionViewModel:
        return CompanionViewModel(client=CompanionClient(self.endpoint, timeout=15.0))

    def test_a_fresh_client_attaches_to_a_task_it_did_not_start(self) -> None:
        starter = self._model()
        self.assertTrue(starter.connect())
        self.assertTrue(starter.submit("Count the words in this note and validate the count."))
        task_id = starter.task_id
        self.assertTrue(self.service.gateway.drain(timeout=20.0))

        # A completely separate client, told nothing.
        observer = self._model()
        self.assertTrue(observer.connect())
        self.assertEqual(observer.task_id, task_id)
        self.assertEqual(observer.state.phase, "success")
        self.assertTrue(observer.state.result_summary)

    def test_the_client_rebuilds_the_same_state_it_was_served(self) -> None:
        model = self._model()
        model.connect()
        model.submit("Count the words in this note and validate the count.")
        self.assertTrue(self.service.gateway.drain(timeout=20.0))
        model.refresh(full=True)
        self.assertEqual(model.replayed_phase, model.state.phase)

    def test_the_text_only_view_is_a_complete_surface(self) -> None:
        model = self._model()
        model.connect()
        model.submit("Count the words in this note and validate the count.")
        self.assertTrue(self.service.gateway.drain(timeout=20.0))
        model.refresh()
        text = model.text_only_view()
        # Everything a person needs, without a picture: what it is doing, the
        # result, the privacy boundary, the reviewer, and the authority note.
        self.assertIn("Bunny has finished.", text)
        self.assertIn("Privacy:", text)
        self.assertIn("Executor: local.deterministic", text)
        self.assertIn("Reviewer", text)
        self.assertIn("Reviewers observe only", text)
        self.assertIn(model.state.result_summary, text)

    def test_a_disconnected_client_says_so_and_blames_nothing_on_the_task(self) -> None:
        model = self._model()
        model.connect()
        model.submit("Count the words in this note and validate the count.")
        self.assertTrue(self.service.gateway.drain(timeout=20.0))
        model.refresh()
        completed = model.state.result_summary

        self.service.close()
        model.refresh()
        self.assertEqual(model.phase, "disconnected")
        self.assertIn("cannot reach the companion runtime", model.caption())
        self.assertIn("unaffected", model.caption())
        # The client holds nothing durable, so what it last saw is all it has —
        # and it does not pretend that is the current truth.
        self.assertEqual(model.state.result_summary, completed)

    def test_the_client_never_writes_to_the_store(self) -> None:
        model = self._model()
        model.connect()
        model.submit("Count the words in this note and validate the count.")
        self.assertTrue(self.service.gateway.drain(timeout=20.0))
        before = sorted(path.name for path in self.root.rglob("*") if path.is_file())
        for _ in range(5):
            model.refresh()
            model.text_only_view()
            model.task_rows()
            model.observation_cards()
            model.approval_cards()
        after = sorted(path.name for path in self.root.rglob("*") if path.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
