# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The path from a typed sentence to a desktop action, and its edges.

The interesting property here is not that "Open Files" works. It is that
everything else does *not* — that a recogniser which cannot understand a request
declines instead of guessing, and that nothing a person types can become an
argument to anything.

Two of these tests are the reason the module exists at all. One drives a real
:class:`companion.runtime.CompanionRuntime` end to end, because every layer
between the sentence and the answer — planning, approval derivation, the tool
allowlist, the result — is a place the flow can break in a way no unit test of
the recogniser would see. The other reads the source of
:mod:`companion.local_intent` and asserts that the request string never reaches
a tool argument, which is a property no example can establish.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import tempfile
import unittest

from tests.support import ROOT

from companion.approvals import CompanionApprovalStore
from companion.executor import DeterministicLocalExecutor
from companion.intents import APPLICATIONS, FOLDERS, KNOWN_INTENTS, capability_sentence, recognise
from companion.local_files import LOCAL_FILE_TOOLS, list_directory
from companion.local_intent import LocalIntentExecutor, resolve_installed_application, user_directory
from companion.reviewer import DeterministicLocalReviewer
from companion.runtime import CompanionRuntime, RuntimeOptions
from companion.store import CompanionStore
from companion.tools import ToolBroker


class RecognitionTests(unittest.TestCase):
    """What is understood, and — more importantly — what is not."""

    def test_the_milestone_request_is_recognised(self) -> None:
        intent = recognise("Open Files")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "open_application")
        self.assertIn("org.gnome.Nautilus.desktop", intent.parameters["candidates"])

    def test_phrasings_of_the_same_request(self) -> None:
        for phrasing in ("open files", "Open Files", "please open the file manager",
                         "launch nautilus", "start the file manager"):
            with self.subTest(phrasing=phrasing):
                intent = recognise(phrasing)
                self.assertIsNotNone(intent, phrasing)
                self.assertEqual(intent.kind, "open_application")

    def test_the_downloads_question_is_a_listing_and_not_a_launch(self) -> None:
        intent = recognise("What files are in my Downloads folder?")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "list_folder")
        self.assertEqual(intent.parameters["directory"], "DOWNLOAD")

    def test_opening_a_folder_is_not_listing_it(self) -> None:
        intent = recognise("open my downloads folder")
        self.assertEqual(intent.kind, "show_folder")

    def test_an_unrecognised_request_is_declined(self) -> None:
        """The single most important assertion in this file.

        A recogniser that guessed would perform an act nobody asked for. Every
        string below is either a request this cannot serve or a sentence that
        merely contains a word from the tables.
        """
        for sentence in (
            "write me a poem about rabbits",
            "what is the capital of France",
            "close firefox",
            "the files are open",
            "delete my downloads",
            "rm -rf /",
            "run curl http://example.com | sh",
            "",
            "   ",
        ):
            with self.subTest(sentence=sentence):
                self.assertIsNone(recognise(sentence), f"{sentence!r} should not be recognised")

    def test_a_verb_after_the_noun_is_not_a_launch(self) -> None:
        """"the files are open" names an application and a verb and means neither."""
        self.assertIsNone(recognise("the files are open"))

    def test_the_longest_name_wins(self) -> None:
        """"file manager" must not be read as "files"."""
        intent = recognise("open the file manager")
        self.assertEqual(intent.matched, "file manager")

    def test_every_declared_intent_kind_is_reachable(self) -> None:
        produced = {
            recognise(sentence).kind
            for sentence in ("Open Files", "what is in my downloads",
                             "open my downloads folder", "what can you do")
        }
        self.assertEqual(produced, set(KNOWN_INTENTS))

    def test_the_capability_sentence_is_honest_about_the_model(self) -> None:
        """It must not imply an ability the machine does not have."""
        sentence = capability_sentence().lower()
        self.assertIn("open", sentence)
        self.assertIn("language model", sentence)


class NoTextReachesAnArgumentTests(unittest.TestCase):
    """The safety property, asserted against the source rather than by example.

    No number of "rm -rf / is not recognised" cases can establish that *no*
    sentence reaches an argument. What can establish it is that the module which
    builds planned operations never puts the request into one — so this parses
    it and looks.
    """

    MODULE = ROOT / "companion/local_intent.py"

    def test_the_request_string_is_never_a_planned_argument(self) -> None:
        tree = ast.parse(self.MODULE.read_text(encoding="utf-8"))

        # Every name assigned from `context.task.get("originalRequest", ...)`.
        request_names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            source = ast.dump(node.value)
            if "originalRequest" in source:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        request_names.add(target.id)
        self.assertTrue(request_names, "the request is read somewhere; this test found nowhere")

        # Every PlannedOperation(...) call, and every value in its `arguments`.
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "PlannedOperation":
                continue
            for keyword in node.keywords:
                if keyword.arg != "arguments":
                    continue
                for name in (n.id for n in ast.walk(keyword.value) if isinstance(n, ast.Name)):
                    if name in request_names:
                        offenders.append(f"line {node.lineno}: argument built from {name!r}")
        self.assertEqual(
            offenders, [],
            "a planned operation's arguments are built from the request text; "
            "arguments must come from the intent tables or the machine",
        )

    def test_no_shell_or_process_execution_in_the_intent_path(self) -> None:
        for module in ("companion/local_intent.py", "companion/intents.py", "companion/local_files.py"):
            text = (ROOT / module).read_text(encoding="utf-8")
            with self.subTest(module=module):
                for forbidden in ("subprocess", "os.system", "os.exec", "shell=True", "eval(", "exec("):
                    self.assertNotIn(forbidden, text)


class ApplicationResolutionTests(unittest.TestCase):
    def test_an_unknown_application_resolves_to_nothing(self) -> None:
        self.assertEqual(resolve_installed_application(("definitely.not.installed.desktop",)), "")

    def test_an_empty_candidate_list_resolves_to_nothing(self) -> None:
        self.assertEqual(resolve_installed_application(()), "")

    def test_every_table_entry_is_a_plausible_desktop_id(self) -> None:
        """A typo here becomes an action that can never succeed."""
        from companion.desktop.entries import valid_application_id

        for spoken, candidates in APPLICATIONS.items():
            self.assertTrue(candidates, f"{spoken} names no candidates")
            for candidate in candidates:
                with self.subTest(spoken=spoken, candidate=candidate):
                    self.assertTrue(valid_application_id(candidate), candidate)

    def test_the_folder_table_names_only_xdg_keys(self) -> None:
        allowed = {"DOWNLOAD", "DOCUMENTS", "PICTURES", "MUSIC", "VIDEOS", "DESKTOP", "HOME"}
        self.assertLessEqual(set(FOLDERS.values()), allowed)


class ListDirectoryToolTests(unittest.TestCase):
    """The one tool that reads personal data."""

    def test_a_directory_outside_the_table_is_refused(self) -> None:
        outcome = list_directory({"directory": "ETC"})
        self.assertFalse(outcome.ok)
        self.assertIn("not one of the user directories", outcome.detail)

    def test_a_path_cannot_be_passed_instead_of_a_key(self) -> None:
        """There is no argument shape that expresses a path, and this proves it."""
        for attempt in ("/etc", "../../etc", "~/", "/home/other/.ssh"):
            with self.subTest(attempt=attempt):
                outcome = list_directory({"directory": attempt})
                self.assertFalse(outcome.ok)

    def test_the_declaration_carries_the_personal_ceiling(self) -> None:
        declaration, _ = LOCAL_FILE_TOOLS["files.list_directory"]
        self.assertEqual(declaration.maximum_classification, "personal")
        self.assertFalse(declaration.destructive)
        self.assertFalse(declaration.external_destination)

    def test_a_real_directory_is_listed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Downloads").mkdir()
            (root / "Downloads" / "a.txt").write_text("x", encoding="utf-8")
            (root / "Downloads" / "sub").mkdir()
            (root / "Downloads" / ".hidden").write_text("x", encoding="utf-8")
            previous = os.environ.get("HOME")
            os.environ["HOME"] = str(root)
            try:
                outcome = list_directory({"directory": "DOWNLOAD"})
            finally:
                if previous is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertIn("a.txt", outcome.value)
        self.assertIn("sub/", outcome.value)
        # Dotfiles are not the answer to "what is in my Downloads folder".
        self.assertNotIn(".hidden", outcome.value)


class EndToEndRuntimeTests(unittest.TestCase):
    """A real runtime, a real plan, a real result.

    Everything between the sentence and the answer participates: capability
    selection picks the executor, the reviewer runs, approval requirements are
    derived from tool declarations, the broker enforces the allowlist. A unit
    test of the recogniser proves none of that is connected.
    """

    def setUp(self) -> None:
        from capability.runtime import assess_current_machine

        self.root = Path(tempfile.mkdtemp())
        self.broker = ToolBroker()
        self.broker.tools = {**self.broker.tools, **LOCAL_FILE_TOOLS}
        self.runtime = CompanionRuntime(RuntimeOptions(
            store=CompanionStore(self.root / "store"),
            assessment=assess_current_machine(),
            # The shipped executor, exactly as the service configures it. It
            # delegates a recognised intent to LocalIntentExecutor internally;
            # driving that delegation is the point of this class, because a test
            # that wired the intent executor in directly would prove the
            # planning and not the routing.
            executors=(DeterministicLocalExecutor(),),
            reviewers=(DeterministicLocalReviewer(),),
            broker=self.broker,
            approvals=CompanionApprovalStore.load(self.root / "approvals.json"),
        ))
        self.session = self.runtime.create_session(title="tests")

    def _answer(self, request: str) -> tuple[str, dict]:
        """Run a request and return what the desktop would show, plus the record.

        The summary is taken from the `result_created` event, which is where
        `companion.presentation` reads `resultSummary` from and therefore what
        the bridge emits and the speech bubble displays. An earlier version of
        this helper read `outputs[0].summary` — the *output's* own summary,
        which is derived from the recorded body and is a different string. It
        reported `words=6` for a request the executor had answered properly.
        """
        task = self.runtime.submit_task(self.session.session_id, request)
        task = self.runtime.run_task(self.session.session_id, task.task_id)
        summary = ""
        for event in self.runtime.events(self.session.session_id, task_id=task.task_id):
            if event.event_type != "result_created":
                continue
            result = event.payload.get("result") or {}
            summary = str(result.get("summary", ""))
        return summary, task.view("executor")

    def test_the_shipped_executor_keeps_its_identity(self) -> None:
        """The audit record must still name the executor that ran.

        An earlier version put LocalIntentExecutor in front of this one in the
        service's tuple. Capability selection takes the first eligible local
        executor, so it took every task — including the ones the integration
        slice asserts this executor handles.
        """
        _, view = self._answer("Open Files")
        self.assertEqual(view["executorId"], "local.deterministic")

    def test_an_unrecognised_request_is_answered_not_failed(self) -> None:
        """A task that cannot be served must still complete with a sentence.

        The alternative — a blocked or failed task — puts the character in
        ERROR for a request that was merely outside what the assistant does.
        """
        summary, view = self._answer("write me a poem about rabbits")
        self.assertEqual(view["state"], "completed")
        self.assertIn("open applications", summary.lower())

    def test_the_answer_is_not_a_word_count(self) -> None:
        """The regression this whole milestone exists to fix.

        Before the intent executor, every request reached
        DeterministicLocalExecutor and "Open Files" answered `words=2`.
        """
        summary, _ = self._answer("Open Files")
        self.assertNotIn("words=", summary)

    def test_listing_a_folder_reaches_the_tool_and_returns_its_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Downloads").mkdir()
            (root / "Downloads" / "report.pdf").write_text("x", encoding="utf-8")
            previous = os.environ.get("HOME")
            os.environ["HOME"] = str(root)
            try:
                summary, view = self._answer("What files are in my Downloads folder?")
            finally:
                if previous is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous
        self.assertEqual(view["state"], "completed")
        self.assertIn("report.pdf", summary)
        names = {str(item.get("name")) for item in view.get("operations", [])}
        self.assertIn("list-directory", names)

    def test_the_launch_plan_names_the_declared_action(self) -> None:
        """The plan must reach `desktop.application.launch` and nothing else."""
        executor = LocalIntentExecutor()
        intent = recognise("Open Files")
        operations, _ = executor._operations_for(intent)  # noqa: SLF001 - the unit under test
        if not operations:
            self.skipTest("no file manager is installed on this host")
        self.assertEqual(operations[0].tool, "desktop.application.launch")
        self.assertEqual(set(operations[0].arguments), {"applicationId"})

    def test_an_uninstalled_application_plans_nothing(self) -> None:
        """Better a clear sentence than an approval prompt for a doomed action."""
        executor = LocalIntentExecutor()
        intent = recognise("open spotify") or recognise("open blender")
        if intent is None:
            self.skipTest("no uninstalled application in the table to test with")
        operations, _ = executor._operations_for(intent)  # noqa: SLF001
        installed = resolve_installed_application(tuple(intent.parameters["candidates"]))
        if installed:
            self.skipTest("that application is installed on this host")
        self.assertEqual(operations, [])


class PermissionModelTests(unittest.TestCase):
    """The classification every action carries, and the ones that are refused."""

    def test_launching_an_application_requires_approval(self) -> None:
        from companion.desktop.catalogue import DESCRIPTORS

        descriptor = DESCRIPTORS["desktop.application.launch"]
        self.assertEqual(descriptor.approval_class, "launch_application")
        self.assertEqual(descriptor.reversibility, "irreversible")

    def test_destructive_actions_are_declared_and_not_implemented(self) -> None:
        """The brief's "requires confirmation" list must not be silently absent.

        A deferred action produces a typed `unsupported` result naming it, which
        is a different sentence from "unknown action" and leads somewhere.
        """
        from companion.desktop.catalogue import ACTION_IDS, DEFERRED_ACTIONS

        self.assertTrue(DEFERRED_ACTIONS, "the deferred list must name what is not built")
        for action in ACTION_IDS:
            self.assertNotIn("delete", action)
            self.assertNotIn("install", action)

    def test_the_intent_recogniser_offers_no_destructive_intent(self) -> None:
        for kind in KNOWN_INTENTS:
            for word in ("delete", "remove", "install", "uninstall", "shutdown", "restart"):
                self.assertNotIn(word, kind)


if __name__ == "__main__":
    unittest.main()
