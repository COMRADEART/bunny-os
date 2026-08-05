# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The privacy model, the capability binding, and the headless vertical slice."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from capability.simulate import simulate
from capability.runtime import assess

from companion.capability_bridge import capability_signals, evaluate_task, task_request_for
from companion.demo import run_demo
from companion.errors import PayloadTooLarge, SchemaError
from companion.executor import DeterministicLocalExecutor
from companion.privacy import (
    AUDIENCE_CEILING,
    DATA_CLASSES,
    MAX_PAYLOAD_BYTES,
    display_summary,
    project,
    rank,
    router_privacy,
    sanitize,
    visible_to,
)
from companion.session import CompanionSession, PrivacyPolicy
from companion.task import CompanionTask

from .support import SIMPLE_REQUEST, CompanionTestCase, remote_permissive_assessment


class PrivacyModelTests(unittest.TestCase):
    def test_the_classes_are_ordered(self) -> None:
        self.assertEqual(DATA_CLASSES, ("public", "internal", "personal", "sensitive", "secret"))
        self.assertLess(rank("internal"), rank("personal"))
        self.assertLess(rank("personal"), rank("sensitive"))

    def test_personal_maps_conservatively_onto_the_router(self) -> None:
        # The addition can only tighten a routing decision, never loosen one.
        self.assertEqual(router_privacy("personal"), "sensitive")
        self.assertEqual(router_privacy("internal"), "internal")

    def test_the_audience_ceilings_are_what_they_claim(self) -> None:
        self.assertEqual(AUDIENCE_CEILING["reviewer"], "internal")
        self.assertEqual(AUDIENCE_CEILING["remote"], "internal")
        self.assertEqual(AUDIENCE_CEILING["audit"], "internal")
        self.assertFalse(visible_to("reviewer", "personal"))
        self.assertFalse(visible_to("remote", "sensitive"))
        self.assertFalse(visible_to("audit", "personal"))
        self.assertTrue(visible_to("executor", "secret"))

    def test_credentials_are_removed_by_field_name(self) -> None:
        result = sanitize({
            "apiKey": "abc", "authorization": "Basic x", "password": "hunter2",
            "sessionCookie": "c", "privateKey": "k", "keep": "this",
        })
        self.assertEqual(result.value, {"keep": "this"})
        self.assertEqual(len(result.removed), 5)

    #: Every concept the module says is never stored. The table exists because a
    #: security review found the check was anchored with ``\b``, and ``_`` is a
    #: word character in Python — so every snake_case credential name went
    #: straight through while the camelCase equivalents were caught. Asserting
    #: one spelling per concept is what let that survive; asserting six is what
    #: stops the next alternative being added in only one shape.
    FORBIDDEN_CONCEPTS = (
        "api key", "secret key", "private key", "access token", "refresh token",
        "id token", "bearer token", "auth token", "session token", "csrf token",
        "api token", "token", "tokens", "authorization", "credential", "credentials",
        "password", "passphrase", "secret", "cookie", "api secret",
        "chain of thought", "hidden reasoning", "reasoning trace", "scratchpad",
        "internal monologue", "deliberation", "raw audio", "microphone recording",
        "waveform", "audio samples", "screen content", "screen capture",
        "framebuffer", "screenshot",
    )

    @staticmethod
    def spellings(concept: str) -> dict[str, str]:
        words = concept.split()
        return {
            "camelCase": words[0] + "".join(word.capitalize() for word in words[1:]),
            "snake_case": "_".join(words),
            "kebab-case": "-".join(words),
            "SCREAMING_SNAKE": "_".join(words).upper(),
            "dotted.case": ".".join(words),
            "prefixed_snake": "user_" + "_".join(words),
        }

    def test_every_forbidden_concept_is_caught_in_every_naming_convention(self) -> None:
        for concept in self.FORBIDDEN_CONCEPTS:
            for convention, name in self.spellings(concept).items():
                with self.subTest(concept=concept, convention=convention, field=name):
                    result = sanitize({name: "THE-SECRET-VALUE"})
                    self.assertEqual(
                        result.value, {},
                        f"{name!r} reached the store",
                    )
                    self.assertEqual(result.removed, (name,))

    #: Each forbidden concept decomposed into the English words it is made of.
    #: The convention table above is not enough on its own: the second round of
    #: security review found ``passWord`` and ``pass_word`` stored, because
    #: ``\bpasswords?\b`` is itself a compound and :func:`normalise_key` *inserts*
    #: separators — the exact mirror of the original bug. Enumerating separator
    #: placements between real word boundaries is what catches that class.
    WORD_DECOMPOSITIONS = (
        ["api", "key"], ["secret", "key"], ["private", "key"], ["access", "token"],
        ["refresh", "token"], ["id", "token"], ["bearer", "token"], ["auth", "token"],
        ["session", "token"], ["csrf", "token"], ["api", "token"], ["api", "secret"],
        ["token"], ["tokens"], ["authorization"], ["credential"], ["credentials"],
        ["pass", "word"], ["pass", "words"], ["pass", "phrase"], ["secret"], ["secrets"],
        ["cookie"], ["cookies"],
        ["chain", "of", "thought"], ["hidden", "reasoning"], ["reasoning", "trace"],
        ["scratch", "pad"], ["internal", "monologue"], ["deliberation"],
        ["raw", "audio"], ["microphone", "recording"], ["wave", "form"], ["audio", "samples"],
        ["screen", "content"], ["screen", "capture"], ["frame", "buffer"],
        ["screen", "shot"], ["screen", "shots"],
    )

    @staticmethod
    def separator_spellings(words: list[str]) -> set[str]:
        """Every way a person might write this concept."""
        import itertools

        found: set[str] = set()
        for separators in itertools.product(["", "_", "-", ".", " "], repeat=max(0, len(words) - 1)):
            joined = words[0]
            for separator, word in zip(separators, words[1:]):
                joined += separator + word
            found |= {joined, joined.upper(), joined.lower()}
        found.add(words[0] + "".join(word.capitalize() for word in words[1:]))   # camelCase
        found.add("".join(word.capitalize() for word in words))                  # PascalCase
        found.add("user_" + "_".join(words))                                     # prefixed
        found.add("my" + "".join(word.capitalize() for word in words))
        return found

    def test_no_separator_placement_splits_a_forbidden_word_apart(self) -> None:
        checked = 0
        for words in self.WORD_DECOMPOSITIONS:
            for name in sorted(self.separator_spellings(list(words))):
                checked += 1
                with self.subTest(concept=" ".join(words), field=name):
                    self.assertEqual(
                        sanitize({name: "THE-SECRET-VALUE"}).value, {},
                        f"{name!r} reached the store",
                    )
        self.assertGreater(checked, 400, "the sweep should be broad enough to be worth running")

    def test_names_that_merely_contain_a_forbidden_word_are_kept(self) -> None:
        # The check must not be so eager that it eats ordinary fields. These are
        # the near misses: a word containing "secret", a legitimate count, and a
        # digest that a naive entropy heuristic would have redacted.
        kept = sanitize({
            "secretary_name": "Ada",
            "tokenCount": 42,
            "digest": "a" * 64,
            "cookbook": "recipes",
            "passwordPolicyVersion": 3,
        })
        self.assertEqual(kept.value["secretary_name"], "Ada")
        self.assertEqual(kept.value["tokenCount"], 42)
        self.assertEqual(kept.value["digest"], "a" * 64)
        self.assertEqual(kept.value["cookbook"], "recipes")
        # A password *policy version* is a number about configuration, not a
        # password — but the name contains one, so it is removed. Documented
        # rather than special-cased: erring towards removal is the right
        # direction, and the field can be renamed.
        self.assertNotIn("passwordPolicyVersion", kept.value)

    def test_hidden_reasoning_has_nowhere_to_go(self) -> None:
        result = sanitize({"chainOfThought": "...", "scratchpad": "...", "reasoningTrace": "..."})
        self.assertEqual(result.value, {})
        self.assertEqual(len(result.removed), 3)

    def test_raw_capture_fields_are_removed(self) -> None:
        result = sanitize({"rawAudio": "…", "screenContent": "…", "microphoneRecording": "…"})
        self.assertEqual(result.value, {})

    def test_a_token_count_is_a_number_and_survives(self) -> None:
        result = sanitize({"tokenCount": 42, "tokensUsed": 7})
        self.assertEqual(result.value, {"tokenCount": 42, "tokensUsed": 7})
        # The same names holding material do not.
        material = sanitize({"tokenCount": "ghp_abcdefghijklmnopqrst"})
        self.assertEqual(material.value, {})

    def test_credentials_are_scrubbed_by_shape_whatever_the_field_is_called(self) -> None:
        result = sanitize({"note": "use sk-abcdefghijklmnopqrstuv to sign in"})
        self.assertNotIn("sk-abcdefghijklmnopqrstuv", json.dumps(result.value))
        self.assertEqual(result.scrubbed, ("note",))

    def test_a_digest_is_not_mistaken_for_a_credential(self) -> None:
        digest = "a" * 64
        result = sanitize({"digest": digest})
        self.assertEqual(result.value["digest"], digest)
        self.assertEqual(result.scrubbed, ())

    def test_an_oversized_payload_is_refused(self) -> None:
        with self.assertRaises(PayloadTooLarge):
            sanitize({"body": "x" * (MAX_PAYLOAD_BYTES + 1)})

    def test_deep_nesting_is_refused(self) -> None:
        value: object = "leaf"
        for _ in range(12):
            value = {"next": value}
        with self.assertRaises(PayloadTooLarge):
            sanitize(value)

    def test_non_finite_numbers_are_refused(self) -> None:
        with self.assertRaisesRegex(SchemaError, "non-finite"):
            sanitize({"ratio": float("inf")})

    def test_unsupported_types_are_refused(self) -> None:
        with self.assertRaisesRegex(SchemaError, "unsupported type"):
            sanitize({"when": object()})

    def test_projection_keeps_structure_and_removes_content(self) -> None:
        payload = {"recipients": ["a@example.com", "b@example.com"], "count": 2, "flag": True}
        masked = project(payload, audience="reviewer", classification="personal")
        self.assertEqual(sorted(masked), ["count", "flag", "recipients"])
        self.assertEqual(masked["recipients"], ["[withheld: personal]", "[withheld: personal]"])
        self.assertEqual(masked["count"], "[withheld: personal]")
        # Booleans and nulls survive: their presence is structure, not content.
        self.assertIs(masked["flag"], True)

    def test_a_summary_is_truncated_and_says_so(self) -> None:
        summary = display_summary("word " * 200)
        self.assertLessEqual(len(summary), 240)
        self.assertTrue(summary.endswith("…"))


class CapabilityBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assessment = assess(simulate("laptop"))
        self.session = CompanionSession.create(session_id="ses-1", title="t", now=0.0)

    def test_the_stricter_locality_wins(self) -> None:
        task = CompanionTask.create(
            task_id="task-1", session_id="ses-1", request="x", now=0.0, data_locality="any"
        )
        # The session is device-only, so the task's "any" cannot widen it.
        request = task_request_for(task, self.session)
        self.assertEqual(request.data_locality, "device-only")

    def test_the_router_is_never_told_a_task_was_pre_approved(self) -> None:
        task = CompanionTask.create(task_id="task-1", session_id="ses-1", request="x", now=0.0)
        self.assertFalse(task_request_for(task, self.session).user_approved)

    def test_the_signals_come_from_the_assessment_that_decided(self) -> None:
        signals = capability_signals(self.assessment)
        for name in (
            "localAiEligible", "usableMemoryBytes", "cpuScore", "gpuAvailable",
            "networkOnline", "networkMetered", "meteredNetworkAllowed",
            "remoteExecutionEnabled", "onBattery", "batteryPercent", "thermalThrottled",
        ):
            self.assertIn(name, signals)
        self.assertEqual(signals["gpuAvailable"], bool(self.assessment.inventory.usable_gpus))

    def test_a_decision_records_the_plan_it_was_made_against(self) -> None:
        from dataclasses import replace

        task = replace(
            CompanionTask.create(task_id="task-1", session_id="ses-1", request="count", now=0.0),
            task_type="compute",
        )
        decision = evaluate_task(task, self.session, (DeterministicLocalExecutor(),), self.assessment)
        self.assertEqual(decision.plan_id, self.assessment.plan.plan_id)
        self.assertTrue(decision.plan_fingerprint)

    def test_a_constrained_machine_still_reaches_a_decision(self) -> None:
        from dataclasses import replace

        constrained = assess(simulate("embedded-64mb"))
        task = replace(
            CompanionTask.create(task_id="task-1", session_id="ses-1", request="count", now=0.0),
            task_type="compute",
        )
        decision = evaluate_task(task, self.session, (DeterministicLocalExecutor(),), constrained)
        # The local pure executor needs nothing, so it is still eligible — and
        # the point is that the machine was *asked*, not that it said yes.
        self.assertTrue(decision.plan_id)
        self.assertIn("localAiEligible", decision.signals)


class PrivacyThroughTheRuntimeTests(CompanionTestCase):
    def test_a_secret_task_never_reaches_a_remote_executor(self) -> None:
        from .support import RemoteExecutor

        runtime = self.started(
            executors=(RemoteExecutor(),),
            assessment=remote_permissive_assessment(),
        )
        session = runtime.create_session(
            "Secret", privacy_policy=PrivacyPolicy(allow_remote=True), locality_preference="any"
        )
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST, classification="secret")
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        self.assertEqual(final.executor_id, "")

    def test_no_credential_ever_reaches_the_store(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Credentials")
        task = runtime.submit_task(
            session.session_id,
            "Count the words and validate, my api key is ghp_abcdefghijklmnopqrst",
        )
        runtime.run_task(session.session_id, task.task_id)
        events_path = self.root / "store" / "sessions" / session.session_id / "events.jsonl"
        text = events_path.read_text(encoding="utf-8")
        self.assertNotIn("ghp_abcdefghijklmnopqrst", text)
        task_path = self.root / "store" / "sessions" / session.session_id / "tasks" / f"{task.task_id}.json"
        self.assertNotIn("ghp_abcdefghijklmnopqrst", task_path.read_text(encoding="utf-8"))

    def test_the_store_holds_no_chain_of_thought_field(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime)
        text = (self.root / "store" / "sessions" / session.session_id / "events.jsonl").read_text(encoding="utf-8")
        for forbidden in ("chainOfThought", "scratchpad", "reasoningTrace", "rawAudio", "screenContent"):
            self.assertNotIn(forbidden, text)


class VerticalSliceTests(unittest.TestCase):
    def test_the_whole_slice_passes_with_no_provider(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        report = run_demo(Path(directory.name))
        self.assertTrue(report.passed, f"failed steps: {report.failures}")
        self.assertEqual([item["step"] for item in report.steps], list(range(1, 22)))
        self.assertTrue(all(item["ok"] for item in report.steps))

        final = {item["step"]: item for item in report.steps}
        self.assertEqual(final[6]["executorId"], "local.deterministic")
        self.assertEqual(final[8]["action"], "interrupt_user_work")
        self.assertTrue(final[20]["chainVerified"])
        self.assertEqual(final[21]["resultBefore"], final[21]["resultAfter"])
        self.assertEqual(final[21]["outputDigestsBefore"], final[21]["outputDigestsAfter"])
        self.assertEqual(report.to_json()["provider"], "none")

    def test_the_slice_is_reproducible(self) -> None:
        first_dir = tempfile.TemporaryDirectory()
        second_dir = tempfile.TemporaryDirectory()
        self.addCleanup(first_dir.cleanup)
        self.addCleanup(second_dir.cleanup)

        first = run_demo(Path(first_dir.name))
        second = run_demo(Path(second_dir.name))
        # Same request, same clock, same ids, same machine: the same chain.
        self.assertEqual(
            [step.get("tipHash") for step in first.steps],
            [step.get("tipHash") for step in second.steps],
        )

    def test_refusing_consent_stops_the_slice_and_performs_nothing(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        report = run_demo(Path(directory.name), grant_approval=False)
        self.assertTrue(report.passed, f"failed steps: {report.failures}")
        steps = {item["step"]: item for item in report.steps}
        self.assertIn("denied", steps[9]["decisions"])
        self.assertFalse(steps[10]["noticePublished"])
        self.assertEqual(steps[10]["state"], "blocked")

    def test_the_slice_runs_on_a_constrained_machine(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        report = run_demo(Path(directory.name), machine="embedded-64mb")
        self.assertTrue(report.passed, f"failed steps: {report.failures}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
