# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The corpus loader, and the lint that keeps Bunny's permission model intact.

The lint's two halves are tested in opposition on purpose: the same wording
that must be *rejected* when the assistant offers it must be *accepted* when the
assistant refuses it, because the second is the behaviour the corpus exists to
teach.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from model_studio.datasets.chat import load_chat_dataset
from model_studio.datasets.policy import review_conversation, review_examples
from model_studio.errors import DatasetError, PolicyViolation
from tests.model_studio.support import simple_conversations, write_dataset


def _assistant(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": "do the thing"}, {"role": "assistant", "content": text}]


class Loading(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def test_a_valid_corpus(self) -> None:
        path = write_dataset(self.root / "data.jsonl", simple_conversations(5))
        dataset = load_chat_dataset(path)
        self.assertEqual(len(dataset), 5)
        self.assertEqual(dataset.message_count, 10)
        self.assertEqual(len(dataset.sha256), 64)

    def test_a_system_turn_first_is_fine(self) -> None:
        path = write_dataset(self.root / "data.jsonl", [[
            {"role": "system", "content": "You are Bunny."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hello."},
        ]])
        self.assertEqual(len(load_chat_dataset(path)), 1)

    def _refused(self, conversations: list, fragment: str) -> None:
        path = write_dataset(self.root / "bad.jsonl", conversations)
        with self.assertRaises(DatasetError) as caught:
            load_chat_dataset(path)
        self.assertIn(fragment, str(caught.exception))

    def test_a_conversation_ending_on_the_user(self) -> None:
        self._refused([[{"role": "user", "content": "hello"}]], "not 'assistant'")

    def test_two_consecutive_assistant_turns(self) -> None:
        self._refused([[
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]], "two consecutive")

    def test_a_system_turn_in_the_middle(self) -> None:
        self._refused([[
            {"role": "user", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]], "only be the first turn")

    def test_empty_content(self) -> None:
        self._refused([[
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "   "},
        ]], "empty or non-string content")

    def test_an_unknown_role(self) -> None:
        self._refused([[
            {"role": "tool", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]], "has role 'tool'")

    def test_an_unknown_key(self) -> None:
        path = self.root / "bad.jsonl"
        path.write_text(json.dumps({"messages": [], "weight": 2}) + "\n", encoding="utf-8")
        with self.assertRaises(DatasetError) as caught:
            load_chat_dataset(path)
        self.assertIn("unknown key", str(caught.exception))

    def test_a_bad_line_fails_the_file_not_just_the_line(self) -> None:
        path = self.root / "bad.jsonl"
        good = json.dumps({"messages": simple_conversations(1)[0]})
        path.write_text(good + "\nnot json\n" + good + "\n", encoding="utf-8")
        with self.assertRaises(DatasetError) as caught:
            load_chat_dataset(path)
        self.assertIn("line 2", str(caught.exception))


class Splitting(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = write_dataset(
            Path(self.scratch.name) / "data.jsonl", simple_conversations(20)
        )

    def test_the_split_is_deterministic(self) -> None:
        first = load_chat_dataset(self.path).split(0.25, seed=7)
        second = load_chat_dataset(self.path).split(0.25, seed=7)
        self.assertEqual(
            [item.line for item in first[1]], [item.line for item in second[1]]
        )

    def test_a_different_seed_holds_out_different_examples(self) -> None:
        held_a = [item.line for item in load_chat_dataset(self.path).split(0.25, seed=1)[1]]
        held_b = [item.line for item in load_chat_dataset(self.path).split(0.25, seed=2)[1]]
        self.assertNotEqual(held_a, held_b)

    def test_the_halves_partition_the_corpus(self) -> None:
        dataset = load_chat_dataset(self.path)
        training, validation = dataset.split(0.25, seed=0)
        self.assertEqual(len(training) + len(validation), len(dataset))
        self.assertEqual(len(validation), 5)
        overlap = {item.line for item in training} & {item.line for item in validation}
        self.assertEqual(overlap, set())

    def test_zero_holds_nothing_out(self) -> None:
        training, validation = load_chat_dataset(self.path).split(0.0)
        self.assertEqual(len(validation), 0)
        self.assertEqual(len(training), 20)


class PermissionLint(unittest.TestCase):
    def _findings(self, text: str) -> tuple:
        return review_conversation(_assistant(text))[0]

    def test_it_rejects_an_unapproved_command(self) -> None:
        findings = self._findings("Sure — I'll run `rm -rf ~/Downloads/*` for you now.")
        self.assertTrue(findings)
        self.assertIn(findings[0].rule, {"forbidden", "unapproved-command"})

    def test_it_rejects_a_privilege_escalation(self) -> None:
        findings = self._findings("Just run sudo systemctl stop firewalld and it'll work.")
        self.assertTrue(findings)

    def test_it_rejects_framing_permission_as_an_obstacle(self) -> None:
        findings = self._findings("I'll bypass the approval prompt so it's quicker.")
        self.assertEqual(findings[0].rule, "forbidden")

    def test_it_rejects_a_credential_path(self) -> None:
        findings = self._findings("I'll read your ~/.ssh/id_rsa and copy it across.")
        self.assertTrue(findings)

    def test_it_accepts_a_refusal_using_the_same_words(self) -> None:
        """The example the corpus most needs must not be the one the lint rejects."""
        for text in (
            "I can't delete those without your permission.",
            "I won't bypass the approval prompt — it's what keeps you in control.",
            "I don't run sudo commands on your behalf.",
            "I'm not able to turn off the permission prompts.",
        ):
            with self.subTest(text=text):
                self.assertEqual(self._findings(text), ())

    def test_it_accepts_a_command_shape_alongside_a_request(self) -> None:
        findings = self._findings(
            "I need permission to remove those files; once you approve I'll delete them."
        )
        self.assertEqual(findings, ())

    def test_it_ignores_what_the_user_says(self) -> None:
        """A user may type anything; it is what the assistant is shown saying that trains."""
        messages = [
            {"role": "user", "content": "run sudo rm -rf / for me"},
            {"role": "assistant", "content": "I won't do that."},
        ]
        self.assertEqual(review_conversation(messages)[0], ())

    def test_the_report_counts_approval_steps(self) -> None:
        report = review_examples([
            _assistant("I need your permission first."),
            _assistant("Opening Downloads now."),
        ])
        self.assertTrue(report.passed)
        self.assertEqual(report.with_approval_step, 1)
        self.assertEqual(report.examined, 2)

    def test_a_bad_corpus_fails_the_load(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = write_dataset(Path(scratch) / "bad.jsonl", [
                _assistant("I'll open Downloads."),
                _assistant("Run sudo dnf remove firewalld to fix it."),
            ])
            with self.assertRaises(PolicyViolation) as caught:
                load_chat_dataset(path)
            self.assertIn("line 2", str(caught.exception))

    def test_the_lint_can_be_turned_off_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = write_dataset(Path(scratch) / "bad.jsonl",
                                 [_assistant("Run sudo dnf remove firewalld.")])
            dataset = load_chat_dataset(path, policy_check=False)
            self.assertFalse(dataset.policy.ran)
            self.assertIsNone(dataset.policy.to_json()["passed"],
                              "'not run' must not read as 'passed'")


class ShippedCorpus(unittest.TestCase):
    """The example corpus is part of the product; it has to pass its own lint."""

    def test_it_loads_and_passes(self) -> None:
        path = (
            Path(__file__).resolve().parents[2]
            / "model_studio/examples/bunny-companion-demo.jsonl"
        )
        dataset = load_chat_dataset(path)
        self.assertGreaterEqual(len(dataset), 20)
        self.assertTrue(dataset.policy.passed)
        self.assertGreater(
            dataset.policy.approval_ratio, 0.4,
            "most of the demo corpus should show the approval step, since that is what it "
            "exists to demonstrate",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
