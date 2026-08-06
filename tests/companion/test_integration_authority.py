# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One of each: runtime, event model, store, approval authority, executor.

§22's "integration authority" list. Most of these are checks that a *second*
implementation does not exist — which is what the whole integration was for, and
which is exactly the kind of property that quietly stops being true.
"""

from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest

from companion import EVENT_SCHEMA_VERSION, SESSION_SCHEMA_VERSION, TASK_SCHEMA_VERSION
from companion.approvals import CompanionApprovalStore
from companion.coordination import ExecutorLeases
from companion.errors import CoordinationLimitExceeded, ReviewerViolation
from companion.events import EVENT_TYPES, TaskEvent
from companion.protocol import DuplicateRuntime
from companion.service import CompanionService, ServiceOptions
from companion.store import CompanionStore
from companion.tools import ToolBroker

from .support import SIMPLE_REQUEST, CompanionTestCase, ToolCallingReviewer

PACKAGE = Path(__file__).resolve().parents[2] / "companion"


def _modules() -> list[tuple[str, ast.Module]]:
    """Every module in the package, parsed.

    Parsed rather than read as text. These are structural claims about the code
    — "nothing imports sqlite3", "nothing passes ``shell=True``" — and a check
    that greps for the string finds every docstring that *explains* why the
    thing is not done. The first version of this file failed on its own prose.
    """
    return [
        (path.name, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(PACKAGE.glob("*.py"))
    ]


def _imported(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _called(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            names.add(f"{target.value.id}.{target.attr}")
    return names


class SingleImplementationTests(unittest.TestCase):
    """There is one of each thing, and the tree can be read to check it."""

    def test_there_is_one_class_that_drives_tasks(self) -> None:
        """Identified by what it *does*, not by what it is called.

        A class is a runtime here if it can submit and run a task. Matching on
        the name found ``DuplicateRuntime``, which is an exception — and would
        have gone on matching a second real runtime called ``TaskEngine``.
        """
        found = []
        for name, tree in _modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = {
                    item.name for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                if {"submit_task", "run_task"} <= methods:
                    found.append(f"{name}:{node.name}")
        self.assertEqual(found, ["runtime.py:CompanionRuntime"])

    def test_there_is_one_durable_store_and_one_event_record(self) -> None:
        stores, events = [], []
        for name, tree in _modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = {
                    item.name for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                if {"save_task", "load_task"} <= methods:
                    stores.append(f"{name}:{node.name}")
                if {"hashed_material", "computed_hash"} <= methods:
                    events.append(f"{name}:{node.name}")
        self.assertEqual(stores, ["store.py:CompanionStore"])
        self.assertEqual(events, ["events.py:TaskEvent"])

    def test_nothing_in_the_package_imports_a_database(self) -> None:
        """§8's persistence decision, enforced rather than documented.

        The default is the append-only event store, and the way a SQLite
        dependency would actually arrive is not a decision record being
        overturned — it is an import somebody adds to one module. ``migration``
        is the exception and is named: it *reads* a donor database, read-only,
        and never writes one.
        """
        offenders = []
        for name, tree in _modules():
            if name == "migration.py":
                continue
            for banned in ("sqlite3", "psycopg", "psycopg2", "sqlalchemy", "pymongo"):
                if banned in _imported(tree):
                    offenders.append(f"{name}: {banned}")
        self.assertEqual(offenders, [])

    def test_nothing_unpickles_evaluates_or_reaches_a_shell(self) -> None:
        offenders = []
        for name, tree in _modules():
            if {"pickle", "marshal", "shelve"} & _imported(tree):
                offenders.append(f"{name}: unpickles")
            called = _called(tree)
            for banned in ("eval", "exec", "compile", "os.system", "os.popen", "subprocess.getoutput"):
                if banned in called:
                    offenders.append(f"{name}: {banned}")
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "shell" and not (
                        isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                    ):
                        offenders.append(f"{name}: shell= was passed")
        self.assertEqual(offenders, [])

    def test_the_schema_versions_are_declared_in_exactly_one_place(self) -> None:
        self.assertEqual((SESSION_SCHEMA_VERSION, TASK_SCHEMA_VERSION, EVENT_SCHEMA_VERSION), (1, 1, 2))
        for path in sorted(PACKAGE.glob("*.py")):
            if path.name == "__init__.py":
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("EVENT_SCHEMA_VERSION = ", source, path.name)

    def test_the_presentation_layer_never_imports_the_store_or_the_broker(self) -> None:
        """The projection decides nothing, so it is given nothing to decide with.

        Checked against the *imports* rather than the text: both files discuss
        the store at length in their docstrings, and a check that reads prose is
        a check that fails when somebody explains themselves properly.
        """
        forbidden = {"store", "tools", "runtime", "service", "executor", "cancellation", "recovery"}
        for name in ("presentation.py", "gtk_shell.py"):
            tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
            reached = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    reached.add(node.module.lstrip("."))
                elif isinstance(node, ast.Import):
                    reached.update(alias.name for alias in node.names)
            self.assertEqual(
                sorted(reached & forbidden), [], f"{name} imports a decision-making module"
            )

    def test_the_gtk_module_can_be_imported_without_a_display(self) -> None:
        import companion.gtk_shell as shell

        self.assertTrue(hasattr(shell, "CompanionViewModel"))
        source = (PACKAGE / "gtk_shell.py").read_text(encoding="utf-8")
        # GTK is imported inside a function, so the view model — which is the
        # whole of the behaviour — is testable on a build machine.
        self.assertNotIn("\nimport gi", source)
        self.assertIn("def _gtk()", source)


class OneAuthorityTests(CompanionTestCase):
    def test_one_executor_holds_a_task_and_a_second_is_refused(self) -> None:
        leases = ExecutorLeases()
        leases.acquire("task-1", "local.deterministic", now=1.0)
        with self.assertRaises(CoordinationLimitExceeded):
            leases.acquire("task-1", "somebody.else", now=2.0)
        leases.release("task-1")
        leases.acquire("task-1", "somebody.else", now=3.0)

    def test_a_reviewer_cannot_execute_a_tool_even_holding_a_broker(self) -> None:
        broker = ToolBroker()
        reviewer = ToolCallingReviewer(broker=broker)
        runtime = self.started(reviewers=(reviewer,))
        session = runtime.create_session("Hostile reviewer")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        self.assertTrue(broker.refusals)
        self.assertIn("ReviewerViolation", reviewer.raised)
        self.assertTrue(all(item["caller"].startswith("reviewer:") for item in broker.refusals))

    def test_the_broker_refuses_every_caller_that_is_not_the_runtime(self) -> None:
        broker = ToolBroker()
        for caller in ("reviewer:x", "user", "policy", "supervisor", "ui", "client"):
            with self.assertRaises(ReviewerViolation, msg=caller):
                broker.invoke("text.count_words", {"text": "x"}, caller=caller)

    def test_a_task_id_is_never_reused_within_a_store(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Duplicates")
        first = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        second = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        self.assertNotEqual(first.task_id, second.task_id)
        self.assertEqual(len(set(runtime.store.task_ids(session.session_id))), 2)

    def test_one_event_stream_carries_everything_about_a_session(self) -> None:
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("One stream")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        events = runtime.store.read_stream(session.session_id).events
        self.assertTrue(events)
        # Contiguous, hash-linked, and every type from the one vocabulary.
        self.assertEqual([item.sequence for item in events], list(range(1, len(events) + 1)))
        for event in events:
            self.assertIn(event.event_type, EVENT_TYPES)
            self.assertIsInstance(event, TaskEvent)
        directory = runtime.store.session_directory(session.session_id)
        streams = sorted(path.name for path in directory.glob("*.jsonl"))
        self.assertEqual(streams, ["events.jsonl"])

    def test_one_approval_store_answers_for_the_whole_runtime(self) -> None:
        runtime = self.started()
        self.assertIs(runtime.approvals, runtime.gate.store)
        self.assertIsInstance(runtime.approvals, CompanionApprovalStore)


class OneServiceTests(unittest.TestCase):
    def test_a_second_service_on_one_endpoint_is_refused(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        endpoint = root / "runtime" / "runtime.sock"
        service = CompanionService(ServiceOptions(
            root=root, endpoint=endpoint, machine="laptop", consent_wait_seconds=2.0,
        )).start()
        self.addCleanup(service.close)
        with self.assertRaises(DuplicateRuntime):
            CompanionService(ServiceOptions(root=root, endpoint=endpoint, machine="laptop"))

    def test_the_service_owns_exactly_one_runtime_and_one_store(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        service = CompanionService(ServiceOptions(
            root=root, endpoint=root / "runtime" / "runtime.sock",
            machine="laptop", consent_wait_seconds=2.0,
        )).start()
        self.addCleanup(service.close)
        self.assertIs(service.gateway.runtime, service.runtime)
        self.assertIsInstance(service.runtime.store, CompanionStore)
        self.assertEqual(service.runtime.store.root, root / "store")
        # The consent source the runtime asks is the one the Approval Centre
        # answers. Two of them would be an approval nobody could deliver.
        self.assertIs(service.runtime.gate.consent, service.consent)
        self.assertIs(service.gateway.consent, service.consent)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
