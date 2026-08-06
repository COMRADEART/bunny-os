# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The stream contract: one assembler enforces §11, whatever the adapter meant.

The assembler never repairs a stream, because a repaired stream is a stream
whose order the record invented. So every test of a violation asserts a
:class:`StreamViolation` and a failed generation, never a patched-up output —
and the happy path asserts that the only route to a final result runs through
``finalize``, which re-digests everything received. Events are minted through
the :class:`StreamEventFactory` the worker hands adapters, because that is the
production path: an adapter cannot mint its own sequence numbers, so the tests
do not either, except where the lie under test is exactly a minted-then-reused
event (the :class:`~tests.companion.agents_support.MisorderedStreamAdapter`
shape).
"""

from __future__ import annotations

import hashlib
import unittest
from typing import Callable

from companion.agents.adapter import StreamEventFactory
from companion.agents.errors import AgentSchemaError, StreamViolation
from companion.agents.stream import (
    MAX_DELTA_BYTES,
    MAX_EVENTS_PER_SECOND,
    StreamAssembler,
    StreamEvent,
)

REQUEST_ID = "gen-000001"
PROVIDER_ID = "local.scripted"


def _factory(monotonic: Callable[[], float] | None = None) -> StreamEventFactory:
    return StreamEventFactory(
        request_id=REQUEST_ID, provider_id=PROVIDER_ID,
        monotonic=monotonic if monotonic is not None else (lambda: 0.0),
    )


def _assembler(*, maximum_output_bytes: int = 64 * 1024,
               maximum_events: int | None = None) -> StreamAssembler:
    if maximum_events is None:
        return StreamAssembler(
            request_id=REQUEST_ID, provider_id=PROVIDER_ID,
            maximum_output_bytes=maximum_output_bytes,
        )
    return StreamAssembler(
        request_id=REQUEST_ID, provider_id=PROVIDER_ID,
        maximum_output_bytes=maximum_output_bytes, maximum_events=maximum_events,
    )


class AssemblyHappyPath(unittest.TestCase):
    """A well-ordered stream accumulates, finalizes, and accounts for itself."""

    def test_a_complete_stream_assembles_into_a_digested_output(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        self.assertEqual(sink.provisional_text(), "")
        sink.accept(events.delta("Hello "))
        self.assertEqual(sink.provisional_text(), "Hello ")
        sink.accept(events.delta("world"))
        self.assertEqual(sink.provisional_text(), "Hello world")
        sink.accept(events.usage({"inputUnits": 7, "outputUnits": 11}))
        sink.accept(events.completed())
        output = sink.finalize()
        self.assertTrue(output.completed)
        self.assertFalse(output.cancelled)
        self.assertEqual(output.text, "Hello world")
        self.assertEqual(
            output.digest, hashlib.sha256(b"Hello world").hexdigest())
        self.assertEqual(output.event_count, 5)
        self.assertEqual(output.usage, {"inputUnits": 7, "outputUnits": 11})

    def test_structured_deltas_accumulate_separately_and_carry_the_digest(self) -> None:
        """When structured output exists, it is what the digest attests to."""
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        sink.accept(events.structured('{"summary"'))
        sink.accept(events.structured(': "fine"}'))
        sink.accept(events.completed())
        output = sink.finalize()
        self.assertEqual(output.structured_text, '{"summary": "fine"}')
        self.assertEqual(output.text, "")
        self.assertEqual(
            output.digest, hashlib.sha256(b'{"summary": "fine"}').hexdigest())

    def test_a_cancelled_stream_finalizes_as_cancelled_not_completed(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        sink.accept(events.delta("partial"))
        sink.accept(events.cancelled("the user let go"))
        output = sink.finalize()
        self.assertTrue(output.cancelled)
        self.assertFalse(output.completed)
        self.assertEqual(output.detail, "the user let go")
        # The partial text survives as provisional history, never as a result.
        self.assertEqual(output.text, "partial")

    def test_a_failed_stream_finalizes_as_neither_completed_nor_cancelled(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        sink.accept(events.failed("the endpoint went away"))
        output = sink.finalize()
        self.assertFalse(output.completed)
        self.assertFalse(output.cancelled)
        self.assertEqual(output.terminal_kind, "generation_failed")


class OrderingViolations(unittest.TestCase):
    """Each way a stream can lie about order, refused by name."""

    def test_a_first_event_that_is_not_generation_started_is_refused(self) -> None:
        events = _factory()
        with self.assertRaises(StreamViolation) as caught:
            _assembler().accept(events.delta("eager"))
        self.assertIn("generation_started", str(caught.exception))

    def test_a_second_generation_started_is_refused(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        with self.assertRaises(StreamViolation):
            sink.accept(events.started())

    def test_a_duplicate_sequence_is_refused(self) -> None:
        # The MisorderedStreamAdapter shape: the same minted event, replayed.
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        first = events.delta("one")
        sink.accept(first)
        with self.assertRaises(StreamViolation) as caught:
            sink.accept(first)
        self.assertIn("duplicate or a gap", str(caught.exception))

    def test_a_sequence_gap_is_refused(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        events.delta("swallowed")  # minted, never delivered: the gap
        with self.assertRaises(StreamViolation):
            sink.accept(events.delta("after the gap"))

    def test_an_event_after_the_terminal_event_is_refused(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        sink.accept(events.completed())
        with self.assertRaises(StreamViolation) as caught:
            sink.accept(events.delta("posthumous"))
        self.assertIn("after terminal", str(caught.exception))

    def test_finalize_before_a_terminal_event_is_refused(self) -> None:
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        sink.accept(events.delta("in flight"))
        with self.assertRaises(StreamViolation):
            sink.finalize()

    def test_an_event_naming_another_stream_is_refused(self) -> None:
        foreign = StreamEventFactory(
            request_id="gen-999999", provider_id=PROVIDER_ID, monotonic=lambda: 0.0)
        with self.assertRaises(StreamViolation):
            _assembler().accept(foreign.started())


class BoundViolations(unittest.TestCase):
    """The stream's ceilings: bytes, events, rate and encoding."""

    def test_output_beyond_the_declared_byte_bound_is_refused(self) -> None:
        events = _factory()
        sink = _assembler(maximum_output_bytes=8)
        sink.accept(events.started())
        sink.accept(events.delta("123456"))
        with self.assertRaises(StreamViolation) as caught:
            sink.accept(events.delta("789"))
        self.assertIn("byte bound", str(caught.exception))

    def test_more_events_than_the_ceiling_is_refused(self) -> None:
        events = _factory()
        sink = _assembler(maximum_events=3)
        sink.accept(events.started())
        sink.accept(events.delta("one"))
        sink.accept(events.delta("two"))
        with self.assertRaises(StreamViolation):
            sink.accept(events.delta("three"))

    def test_a_delta_carrying_an_unpaired_surrogate_is_refused(self) -> None:
        """The shape a byte-sliced decode produces when the decoder was not incremental."""
        events = _factory()
        sink = _assembler()
        sink.accept(events.started())
        with self.assertRaises(StreamViolation) as caught:
            sink.accept(events.delta("split code point \ud800"))
        self.assertIn("surrogate", str(caught.exception))

    def test_more_events_per_second_than_the_bound_is_refused(self) -> None:
        # Every event carries the same monotonic stamp, so the whole burst
        # lands in one rolling window.
        events = _factory(lambda: 0.0)
        sink = _assembler()
        sink.accept(events.started())
        with self.assertRaises(StreamViolation) as caught:
            for _ in range(MAX_EVENTS_PER_SECOND):
                sink.accept(events.delta("x"))
        self.assertIn("one second", str(caught.exception))


class EventConstructionRefusals(unittest.TestCase):
    """§11 begins at the event type: a malformed event is not representable."""

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="model_thought", request_id=REQUEST_ID,
                        provider_id=PROVIDER_ID, sequence=1, monotonic=0.0)

    def test_sequence_numbers_begin_at_one(self) -> None:
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="generation_started", request_id=REQUEST_ID,
                        provider_id=PROVIDER_ID, sequence=0, monotonic=0.0)

    def test_an_event_without_its_request_or_provider_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="generation_started", request_id="",
                        provider_id=PROVIDER_ID, sequence=1, monotonic=0.0)
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="generation_started", request_id=REQUEST_ID,
                        provider_id="", sequence=1, monotonic=0.0)

    def test_an_oversized_payload_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="usage_update", request_id=REQUEST_ID,
                        provider_id=PROVIDER_ID, sequence=1, monotonic=0.0,
                        payload={"blob": "x" * 9000})

    def test_a_delta_without_text_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="output_delta", request_id=REQUEST_ID,
                        provider_id=PROVIDER_ID, sequence=1, monotonic=0.0,
                        payload={})

    def test_a_delta_beyond_the_delta_byte_bound_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            StreamEvent(kind="output_delta", request_id=REQUEST_ID,
                        provider_id=PROVIDER_ID, sequence=1, monotonic=0.0,
                        payload={"text": "x" * (MAX_DELTA_BYTES + 1)})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
