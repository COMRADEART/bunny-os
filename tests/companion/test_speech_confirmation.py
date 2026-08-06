# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The confirmation ledger: one yes, about the right words, in the right session."""

from __future__ import annotations

import unittest

from companion.clock import FrozenClock
from companion.speech.confirmation import ConfirmationLedger, MAX_PENDING
from companion.speech.transcript import FinalTranscript


def _final(request_id: str = "speechreq-1", *, session_id: str = "session-1",
           text: str = "count the words") -> FinalTranscript:
    return FinalTranscript(
        request_id=request_id, session_id=session_id, text=text,
        provider_id="scripted", implementation_id="scripted/test",
    )


class Holding(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FrozenClock()
        self.ledger = ConfirmationLedger(clock=self.clock)

    def test_a_held_transcript_waits_and_expires_on_the_monotonic_clock(self) -> None:
        entry, refusal = self.ledger.hold(_final(), lifetime_seconds=10.0)
        self.assertIsNotNone(entry)
        self.assertEqual(refusal, "")
        self.clock.advance(11.0)
        submission, reason = self.ledger.confirm("speechreq-1", session_id="session-1")
        self.assertIsNone(submission)
        self.assertIn("lapsed", reason)

    def test_the_ledger_is_bounded(self) -> None:
        for index in range(MAX_PENDING):
            entry, _ = self.ledger.hold(_final(f"speechreq-{index}"))
            self.assertIsNotNone(entry)
        overflow, refusal = self.ledger.hold(_final("speechreq-overflow"))
        self.assertIsNone(overflow)
        self.assertIn("refused", refusal)

    def test_a_second_final_for_one_request_supersedes_the_first(self) -> None:
        self.ledger.hold(_final(text="first take"))
        entry, _ = self.ledger.hold(_final(text="second take"))
        self.assertIsNotNone(entry)
        submission, _ = self.ledger.confirm("speechreq-1", session_id="session-1")
        self.assertEqual(submission.text, "second take")


class Confirming(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FrozenClock()
        self.ledger = ConfirmationLedger(clock=self.clock)
        self.ledger.hold(_final(), cancellation_token="speechtok-1")

    def test_a_confirmation_is_answered_once(self) -> None:
        first, _ = self.ledger.confirm(
            "speechreq-1", session_id="session-1", cancellation_token="speechtok-1",
        )
        self.assertIsNotNone(first)
        second, reason = self.ledger.confirm(
            "speechreq-1", session_id="session-1", cancellation_token="speechtok-1",
        )
        self.assertIsNone(second)
        self.assertIn("once", reason)

    def test_a_cross_session_confirmation_is_refused(self) -> None:
        submission, reason = self.ledger.confirm(
            "speechreq-1", session_id="session-other", cancellation_token="speechtok-1",
        )
        self.assertIsNone(submission)
        self.assertIn("different session", reason)

    def test_a_missing_token_is_refused(self) -> None:
        submission, reason = self.ledger.confirm("speechreq-1", session_id="session-1")
        self.assertIsNone(submission)
        self.assertIn("token", reason)

    def test_a_stale_reviewed_digest_is_refused(self) -> None:
        submission, reason = self.ledger.confirm(
            "speechreq-1", session_id="session-1",
            cancellation_token="speechtok-1",
            reviewed_digest="sha256:not-what-is-waiting",
        )
        self.assertIsNone(submission)
        self.assertIn("changed since it was reviewed", reason)

    def test_the_matching_digest_confirms(self) -> None:
        entry = self.ledger.get("speechreq-1")
        submission, _ = self.ledger.confirm(
            "speechreq-1", session_id="session-1",
            cancellation_token="speechtok-1",
            reviewed_digest=entry.transcript.text_digest,
        )
        self.assertIsNotNone(submission)

    def test_an_edit_is_marked_and_the_original_words_are_not_submitted(self) -> None:
        submission, _ = self.ledger.confirm(
            "speechreq-1", session_id="session-1",
            cancellation_token="speechtok-1",
            text="count the words carefully",
        )
        self.assertEqual(submission.text, "count the words carefully")
        self.assertTrue(submission.transcript.user_edited)

    def test_confirming_with_the_same_text_is_not_an_edit(self) -> None:
        submission, _ = self.ledger.confirm(
            "speechreq-1", session_id="session-1",
            cancellation_token="speechtok-1",
            text="count the words",
        )
        self.assertFalse(submission.transcript.user_edited)

    def test_an_unknown_request_is_refused_with_the_fact(self) -> None:
        submission, reason = self.ledger.confirm("speechreq-ghost", session_id="session-1")
        self.assertIsNone(submission)
        self.assertIn("no transcript waiting", reason)


class RejectingAndRetrying(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ConfirmationLedger(clock=FrozenClock())
        self.ledger.hold(_final())

    def test_a_rejection_is_idempotent_and_final(self) -> None:
        first, _ = self.ledger.reject("speechreq-1")
        second, detail = self.ledger.reject("speechreq-1")
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn("already", detail)
        submission, reason = self.ledger.confirm("speechreq-1", session_id="session-1")
        self.assertIsNone(submission)
        self.assertIn("rejected", reason)

    def test_a_confirmed_transcript_cannot_be_rejected_afterwards(self) -> None:
        submission, _ = self.ledger.confirm("speechreq-1", session_id="session-1")
        self.assertIsNotNone(submission)
        rejected, reason = self.ledger.reject("speechreq-1")
        self.assertFalse(rejected)
        self.assertIn("already confirmed", reason)

    def test_the_immediate_flag_travels_with_the_entry(self) -> None:
        ledger = ConfirmationLedger(clock=FrozenClock())
        entry, _ = ledger.hold(_final("speechreq-imm"), immediate=True)
        self.assertTrue(entry.immediate)
        submission, _ = ledger.confirm(
            "speechreq-imm", session_id="session-1",
            confirmed_by="immediate-preference",
        )
        self.assertEqual(submission.confirmed_by, "immediate-preference")

    def test_describe_never_includes_the_words(self) -> None:
        document = self.ledger.describe()
        self.assertNotIn("count the words", str(document))
        self.assertFalse(document["submitsDirectly"])
        self.assertTrue(document["confirmationDefault"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
