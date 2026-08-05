# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The event stream and the store beneath it.

These are the tests that matter most after a crash. Every one of them describes
something that has actually happened to a file on a device that lost power, or
something an attacker would try if they could reach the store.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from companion import EVENT_SCHEMA_VERSION
from companion.errors import IntegrityError, PayloadTooLarge, SchemaError, StoreError, UnknownEventType
from companion.events import (
    GENESIS_HASH,
    TaskEvent,
    build_event,
    classification_for,
    deduplicate,
    verify_chain,
)
from companion.privacy import MAX_PAYLOAD_BYTES, MAX_STRING_LENGTH
from companion.session import CompanionSession
from companion.store import CompanionStore, RetentionPolicy

from .support import SIMPLE_REQUEST, CompanionTestCase

SESSION = "ses-000001"
TASK = "task-000001"


def event(sequence: int, previous: str, *, event_type: str = "operation_progress", **payload: object) -> TaskEvent:
    body: dict[str, object] = {"operationKey": f"op-{sequence}", "progress": 0.5}
    body.update(payload)
    return build_event(
        event_id=f"ev-{sequence:08d}",
        session_id=SESSION,
        task_id=TASK,
        sequence=sequence,
        event_type=event_type,
        timestamp="2026-01-01T00:00:00Z",
        producer="runtime",
        payload=body,
        classification="internal",
        previous_hash=previous,
    )


def chain(count: int) -> list[TaskEvent]:
    events: list[TaskEvent] = []
    previous = GENESIS_HASH
    for index in range(1, count + 1):
        current = event(index, previous)
        events.append(current)
        previous = current.event_hash
    return events


class EventRecordTests(unittest.TestCase):
    def test_an_event_seals_and_verifies_itself(self) -> None:
        first = event(1, GENESIS_HASH)
        self.assertEqual(first.event_hash, first.computed_hash())
        self.assertEqual(TaskEvent.from_json(first.to_json()), first)

    def test_an_unknown_event_type_is_refused(self) -> None:
        with self.assertRaises(UnknownEventType):
            event(1, GENESIS_HASH, event_type="task_teleported")

    def test_a_missing_required_payload_field_is_refused(self) -> None:
        with self.assertRaisesRegex(SchemaError, "requires payload fields"):
            build_event(
                event_id="ev-00000001", session_id=SESSION, task_id=TASK, sequence=1,
                event_type="operation_started", timestamp="2026-01-01T00:00:00Z",
                producer="runtime", payload={"name": "x"}, classification="internal",
                previous_hash=GENESIS_HASH,
            )

    def test_an_oversized_payload_is_refused_rather_than_truncated(self) -> None:
        with self.assertRaises(PayloadTooLarge):
            event(1, GENESIS_HASH, note="x" * (MAX_STRING_LENGTH + 1))
        with self.assertRaises(PayloadTooLarge):
            event(1, GENESIS_HASH, blocks=["y" * 1024] * ((MAX_PAYLOAD_BYTES // 1024) + 2))

    def test_a_tampered_payload_breaks_its_own_hash(self) -> None:
        document = event(1, GENESIS_HASH).to_json()
        document["payload"]["progress"] = 0.9
        with self.assertRaisesRegex(IntegrityError, "was altered"):
            TaskEvent.from_json(document)

    def test_a_future_schema_version_is_refused_rather_than_guessed(self) -> None:
        document = event(1, GENESIS_HASH).to_json()
        document["schemaVersion"] = EVENT_SCHEMA_VERSION + 1
        with self.assertRaisesRegex(SchemaError, "newer than this build"):
            TaskEvent.from_json(document)

    def test_a_bad_producer_is_refused(self) -> None:
        with self.assertRaisesRegex(SchemaError, "producer must be"):
            build_event(
                event_id="ev-00000001", session_id=SESSION, task_id=TASK, sequence=1,
                event_type="operation_progress", timestamp="2026-01-01T00:00:00Z",
                producer="the-management", payload={"operationKey": "op", "progress": 0.1},
                classification="internal", previous_hash=GENESIS_HASH,
            )

    def test_credentials_are_removed_before_an_event_exists(self) -> None:
        record = event(1, GENESIS_HASH, apiKey="secret-value", note="Bearer abcdefghijklmnop")
        self.assertNotIn("apiKey", record.payload)
        self.assertNotIn("abcdefghijklmnop", json.dumps(record.payload))
        self.assertEqual(record.redactions, ("apiKey", "note"))

    def test_the_redaction_record_is_inside_the_hash(self) -> None:
        record = event(1, GENESIS_HASH, apiKey="x")
        document = record.to_json()
        document["redactions"] = []
        with self.assertRaises(IntegrityError):
            TaskEvent.from_json(document)

    def test_a_mixed_payload_reveals_only_its_declared_runtime_fields(self) -> None:
        # `session_created` carries a title the user wrote *and* the policy that
        # was in force. Classifying the whole event at the title's level
        # withheld the policy from the audit audience — which is the audience
        # whose job is to check a claim like "nothing was permitted to leave".
        record = build_event(
            event_id="ev-00000001", session_id=SESSION, task_id="", sequence=1,
            event_type="session_created", timestamp="2026-01-01T00:00:00Z", producer="user",
            payload={
                "title": "MY-PRIVATE-TITLE",
                "privacyPolicy": {"allowRemote": False},
                "localityPreference": "device-only",
            },
            classification="personal", previous_hash=GENESIS_HASH,
            internal_fields=("privacyPolicy", "localityPreference"),
        )
        audit = record.view("audit")["payload"]
        self.assertEqual(audit["title"], "[withheld: personal]")
        self.assertEqual(audit["localityPreference"], "device-only")
        self.assertIs(audit["privacyPolicy"]["allowRemote"], False)

        # And the user's own surface, cleared for `personal`, sees the title.
        self.assertEqual(record.view("ui")["payload"]["title"], "MY-PRIVATE-TITLE")

    def test_the_runtime_field_list_is_inside_the_hash(self) -> None:
        # Otherwise an attacker could widen it and make a payload readable.
        record = build_event(
            event_id="ev-00000001", session_id=SESSION, task_id="", sequence=1,
            event_type="session_created", timestamp="2026-01-01T00:00:00Z", producer="user",
            payload={"title": "t", "privacyPolicy": {}, "localityPreference": "device-only"},
            classification="personal", previous_hash=GENESIS_HASH,
            internal_fields=("privacyPolicy",),
        )
        document = record.to_json()
        document["internalFields"] = ["privacyPolicy", "title"]
        with self.assertRaises(IntegrityError):
            TaskEvent.from_json(document)

    def test_an_event_that_declares_no_runtime_fields_withholds_everything(self) -> None:
        # The safe default, and the reason the list names what is *safe to
        # reveal* rather than what is sensitive: an unnamed key is treated as
        # the user's material, so forgetting one over-classifies.
        record = event(1, GENESIS_HASH)
        self.assertEqual(record.internal_fields, ())
        secret = build_event(
            event_id="ev-00000001", session_id=SESSION, task_id=TASK, sequence=1,
            event_type="result_created", timestamp="2026-01-01T00:00:00Z", producer="runtime",
            payload={"resultId": "r-1", "detail": "the answer"},
            classification="secret", previous_hash=GENESIS_HASH,
        )
        rendered = secret.view("audit")["payload"]
        self.assertEqual(rendered["resultId"], "[withheld: secret]")
        self.assertEqual(rendered["detail"], "[withheld: secret]")

    def test_runtime_events_stay_internal_so_review_is_possible(self) -> None:
        self.assertEqual(classification_for("capability_checked", "personal"), "internal")
        self.assertEqual(classification_for("result_created", "personal"), "personal")
        # Never raised above the task's own class.
        self.assertEqual(classification_for("capability_checked", "public"), "public")


class ChainTests(unittest.TestCase):
    def test_a_good_chain_verifies(self) -> None:
        verify_chain(chain(5))

    def test_a_gap_is_detected(self) -> None:
        events = chain(4)
        del events[2]
        with self.assertRaisesRegex(IntegrityError, "gap or a reorder"):
            verify_chain(events)

    def test_a_reorder_is_detected(self) -> None:
        events = chain(4)
        events[1], events[2] = events[2], events[1]
        with self.assertRaisesRegex(IntegrityError, "gap or a reorder"):
            verify_chain(events)

    def test_an_exact_duplicate_deduplicates(self) -> None:
        events = chain(3)
        kept = deduplicate([*events, events[1]])
        self.assertEqual(len(kept), 3)

    def test_an_id_cannot_be_changed_without_breaking_the_hash(self) -> None:
        # The id is part of the hashed material, so an event cannot be
        # re-labelled after the fact. This is why a conflicting pair has to be
        # constructed rather than edited into existence.
        document = event(1, GENESIS_HASH).to_json()
        document["eventId"] = "ev-99999999"
        with self.assertRaisesRegex(IntegrityError, "was altered"):
            TaskEvent.from_json(document)

    def test_two_different_events_sharing_an_id_are_a_conflict(self) -> None:
        first = build_event(
            event_id="ev-00000001", session_id=SESSION, task_id=TASK, sequence=1,
            event_type="operation_progress", timestamp="2026-01-01T00:00:00Z", producer="runtime",
            payload={"operationKey": "op-a", "progress": 0.1}, classification="internal",
            previous_hash=GENESIS_HASH,
        )
        # Same id, different content, each internally consistent: two writers
        # that both believed they were first.
        second = build_event(
            event_id="ev-00000001", session_id=SESSION, task_id=TASK, sequence=1,
            event_type="operation_progress", timestamp="2026-01-01T00:00:00Z", producer="runtime",
            payload={"operationKey": "op-b", "progress": 0.9}, classification="internal",
            previous_hash=GENESIS_HASH,
        )
        self.assertNotEqual(first.event_hash, second.event_hash)
        with self.assertRaisesRegex(IntegrityError, "share the id"):
            deduplicate([first, second])


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.store = CompanionStore(self.root / "store")
        self.store.initialise()
        self.store.save_session(CompanionSession.create(session_id=SESSION, title="t", now=0.0))

    def fill(self, count: int) -> list[TaskEvent]:
        events = chain(count)
        self.store.append_many(events)
        return events

    @staticmethod
    def legacy_event(**overrides: object) -> dict:
        """A version 0 record, correctly sealed under version 0's own rule.

        Version 0 predates the redaction record and the audit reference, so it
        hashed a smaller field set. Sealing the fixture properly matters: a
        migration that accepted an unauthenticated record would re-seal whatever
        the file happened to say, which is the laundering path a security review
        found and which :func:`_verify_before_migrating` now closes.
        """
        from companion.events import _material, _seal

        document = {
            "schemaVersion": 0,
            "eventId": "ev-00000001",
            "sessionId": SESSION,
            "taskId": TASK,
            "sequence": 1,
            "eventType": "operation_progress",
            "timestamp": "2026-01-01T00:00:00Z",
            "producer": "runtime",
            "payload": {"operationKey": "op-1", "progress": 0.25},
            "classification": "internal",
            "previousHash": GENESIS_HASH,
        }
        document.update(overrides)  # type: ignore[arg-type]
        material = _material(
            schema_version=int(document["schemaVersion"]),
            event_id=str(document["eventId"]), session_id=str(document["sessionId"]),
            task_id=str(document["taskId"]), sequence=int(document["sequence"]),
            event_type=str(document["eventType"]), timestamp=str(document["timestamp"]),
            producer=str(document["producer"]), payload=dict(document["payload"]),
            classification=str(document["classification"]), audit_reference="",
            redactions=[], internal_fields=[], previous_hash=str(document["previousHash"]),
        )
        document["eventHash"] = _seal(material, int(document["schemaVersion"]))
        return document

    def test_appends_are_read_back_in_order(self) -> None:
        self.fill(4)
        read = self.store.read_stream(SESSION)
        self.assertEqual([item.sequence for item in read.events], [1, 2, 3, 4])
        self.assertEqual(self.store.tip(SESSION), (4, read.events[-1].event_hash))

    def test_a_replayed_event_is_refused(self) -> None:
        events = self.fill(2)
        with self.assertRaisesRegex(IntegrityError, "replay or was built against a stale tip"):
            self.store.append(events[1])

    def test_an_out_of_order_event_is_refused(self) -> None:
        events = self.fill(2)
        ahead = event(9, events[-1].event_hash)
        with self.assertRaisesRegex(IntegrityError, "expects 3"):
            self.store.append(ahead)

    def test_a_truncated_final_record_is_dropped_and_reported(self) -> None:
        self.fill(3)
        path = self.store._events_path(SESSION)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write('{"schemaVersion":1,"eventId":"ev-000')
        read = self.store.read_stream(SESSION)
        self.assertEqual(len(read.events), 3)
        self.assertEqual(read.incomplete_tail, 1)
        self.assertIn("interrupted append", read.warnings[0])

    def test_appending_after_a_truncation_repairs_the_file(self) -> None:
        self.fill(2)
        path = self.store._events_path(SESSION)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write('{"partial')
        tip, previous = self.store.tip(SESSION)
        self.store.append(event(tip + 1, previous))
        read = self.store.read_stream(SESSION)
        self.assertEqual(read.incomplete_tail, 0)
        self.assertEqual([item.sequence for item in read.events], [1, 2, 3])

    def test_corruption_in_the_middle_raises_rather_than_being_dropped(self) -> None:
        self.fill(4)
        path = self.store._events_path(SESSION)
        lines = path.read_text(encoding="utf-8").splitlines()
        document = json.loads(lines[1])
        document["payload"]["progress"] = 0.99
        lines[1] = json.dumps(document, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        with self.assertRaises(IntegrityError):
            self.store.read_stream(SESSION)

    def test_unparseable_json_in_the_middle_is_not_treated_as_a_partial_write(self) -> None:
        self.fill(3)
        path = self.store._events_path(SESSION)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = "{not json"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(IntegrityError, "not the last line"):
            self.store.read_stream(SESSION)

    def test_retention_prunes_the_front_and_leaves_a_verifiable_anchor(self) -> None:
        store = CompanionStore(self.root / "store", retention=RetentionPolicy(maximum_events=100, retained_events=4))
        self.fill(10)
        dropped = store.prune(SESSION)
        self.assertEqual(dropped, 6)
        read = store.read_stream(SESSION)
        self.assertEqual(len(read.events), 4)
        self.assertEqual(read.anchor_sequence, 6)
        self.assertEqual([item.sequence for item in read.events], [7, 8, 9, 10])
        # The remaining chain still verifies against the recorded anchor, and a
        # further append continues it.
        tip, previous = store.tip(SESSION)
        store.append(event(tip + 1, previous))
        self.assertEqual(len(store.read_stream(SESSION).events), 5)

    def test_the_event_ceiling_refuses_rather_than_wrapping(self) -> None:
        store = CompanionStore(self.root / "store", retention=RetentionPolicy(maximum_events=3, retained_events=2))
        store.append_many(chain(3))
        tip, previous = store.tip(SESSION)
        with self.assertRaisesRegex(StoreError, "ceiling"):
            store.append(event(tip + 1, previous))

    def test_a_migration_reseals_and_records_what_it_did(self) -> None:
        # A version 0 record: no redaction list, no audit reference. Written by
        # hand because no supported build produces one any more, which is the
        # situation a migration exists for.
        path = self.store._events_path(SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy = self.legacy_event()
        path.write_text(json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")

        # A version 0 record cannot even be represented by this build, let alone
        # verified — which is the honest failure mode. It is refused on read,
        # and migration is the only thing that makes it readable.
        with self.assertRaisesRegex(SchemaError, "schemaVersion must be positive"):
            self.store.read_stream(SESSION)

        record = self.store.migrate(SESSION)
        self.assertEqual(record["migrated"], 1)
        self.assertEqual(record["fromVersions"], [0])
        self.assertEqual(record["toVersion"], EVENT_SCHEMA_VERSION)
        self.assertEqual(record["originalTipHash"], legacy["eventHash"])
        self.assertNotEqual(record["newTipHash"], record["originalTipHash"])

        read = self.store.read_stream(SESSION)
        self.assertEqual(len(read.events), 1)
        self.assertEqual(read.events[0].schema_version, EVENT_SCHEMA_VERSION)
        stream = json.loads(self.store._stream_path(SESSION).read_text(encoding="utf-8"))
        self.assertEqual(len(stream["migrations"]), 1)

    def test_a_store_written_under_an_older_hashing_rule_still_reads(self) -> None:
        # The regression that matters most in this file. A field was once added
        # to version 1's hashed material without moving the version, and every
        # event the previous build had written then failed its own hash: the
        # integrity system reported legitimate data as tampering, `validate()`
        # said inconsistent, and `migrate()` refused to help because it saw no
        # version change to act on. There was no recovery path.
        #
        # A record is authenticated against the rule of the version it declares,
        # so a version 1 chain — sealed without `internalFields` — must read.
        from companion.events import _material, _seal

        document = {
            "schemaVersion": 1,
            "eventId": "ev-00000001",
            "sessionId": SESSION,
            "taskId": TASK,
            "sequence": 1,
            "eventType": "operation_progress",
            "timestamp": "2026-01-01T00:00:00Z",
            "producer": "runtime",
            "payload": {"operationKey": "op-1", "progress": 0.5},
            "classification": "internal",
            "auditReference": "",
            "redactions": [],
            "previousHash": GENESIS_HASH,
        }
        document["eventHash"] = _seal(
            _material(
                schema_version=1, event_id="ev-00000001", session_id=SESSION, task_id=TASK,
                sequence=1, event_type="operation_progress", timestamp="2026-01-01T00:00:00Z",
                producer="runtime", payload=document["payload"], classification="internal",
                audit_reference="", redactions=[], internal_fields=[],
                previous_hash=GENESIS_HASH,
            ),
            1,
        )
        path = self.store._events_path(SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")

        read = self.store.read_stream(SESSION)
        self.assertEqual(len(read.events), 1)
        self.assertEqual(read.events[0].schema_version, 1)
        self.assertEqual(read.events[0].internal_fields, ())

        # And it migrates forward to the current version rather than being stuck.
        record = self.store.migrate(SESSION)
        self.assertEqual(record["fromVersions"], [1])
        self.assertEqual(record["toVersion"], EVENT_SCHEMA_VERSION)
        migrated = self.store.read_stream(SESSION)
        self.assertEqual(migrated.events[0].schema_version, EVENT_SCHEMA_VERSION)

    def test_every_hashed_field_set_is_a_distinct_version(self) -> None:
        # The guard against repeating the mistake: two versions covering the
        # same fields would mean a field was added without moving the version.
        from companion.events import HASHED_FIELDS_BY_VERSION

        sets = {version: frozenset(fields) for version, fields in HASHED_FIELDS_BY_VERSION.items()}
        self.assertEqual(len(set(sets.values())), len(sets))
        self.assertIn(EVENT_SCHEMA_VERSION, sets)
        # Each version is a superset of the one before: fields are added, and a
        # field that disappeared would make an old record unverifiable.
        for version in sorted(sets)[1:]:
            self.assertLess(sets[version - 1], sets[version])

    def test_a_tampered_chain_cannot_be_laundered_through_a_migration(self) -> None:
        # A security review found that `migrate()` re-sealed every record without
        # checking the chain first. A tampered stream that `read_stream` refuses
        # came out of a migration verifying perfectly, with the attacker's edit
        # correctly hashed and the audit record's `originalTipHash` read from the
        # attacker's own file. Marking records as an older version was the way in.
        path = self.store._events_path(SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy = self.legacy_event()
        legacy["payload"]["progress"] = 0.99  # the edit, after the hash was sealed
        path.write_text(json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")

        with self.assertRaisesRegex(IntegrityError, "does not match its own hash"):
            self.store.migrate(SESSION)
        # And it is still refused on read, so the tamper has nowhere to go.
        with self.assertRaises(Exception):
            self.store.read_stream(SESSION)

    def test_a_version_with_no_known_hashing_rule_is_not_migrated(self) -> None:
        # The other half of the same door: an attacker cannot reach a version
        # whose rule this build does not implement, and therefore cannot reach a
        # version with no verification.
        path = self.store._events_path(SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        unknown = self.legacy_event()
        unknown["schemaVersion"] = -1
        path.write_text(json.dumps(unknown, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(IntegrityError, "hashing rule this build does not implement"):
            self.store.migrate(SESSION)

    def test_a_newer_schema_is_not_migrated_downwards(self) -> None:
        document = event(1, GENESIS_HASH).to_json()
        document["schemaVersion"] = EVENT_SCHEMA_VERSION + 1
        path = self.store._events_path(SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(StoreError, "downgrade is not a migration"):
            self.store.migrate(SESSION)

    def test_a_store_from_the_future_is_refused(self) -> None:
        metadata = json.loads(self.store.metadata_path.read_text(encoding="utf-8"))
        metadata["schemaVersion"] = 99
        self.store.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(StoreError, "does not understand"):
            self.store.metadata()

    def test_validate_reports_a_projection_that_lags_the_stream(self) -> None:
        self.fill(3)
        report = self.store.validate(SESSION)
        self.assertFalse(report.consistent)
        self.assertIn("stream is authoritative", report.problems[0])

    def test_a_traversal_identifier_is_refused(self) -> None:
        for bad in ("../escape", "a/b", ""):
            with self.assertRaises(StoreError):
                self.store.session_directory(bad)


class ReplayTests(CompanionTestCase):
    def test_a_completed_task_replays_to_the_same_result(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime, SIMPLE_REQUEST)
        before = [
            event.payload for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "result_created"
        ]
        runtime.stop()

        restarted = self.started()
        replayed = restarted.store.read_stream(session.session_id)
        verify_chain(replayed.events)
        after = [
            event.payload for event in restarted.events(session.session_id, task_id=task.task_id)
            if event.event_type == "result_created"
        ]
        self.assertEqual(before, after)
        self.assertEqual(replayed.incomplete_tail, 0)

    def test_an_export_never_exceeds_the_audience_it_names(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime, SIMPLE_REQUEST)
        exported = runtime.store.export(session.session_id, audience="reviewer")
        text = json.dumps(exported)
        self.assertNotIn(task.original_request, text)
        self.assertIn("[withheld: personal]", text)
        # The audit audience is equally bounded.
        audit = json.dumps(runtime.store.export(session.session_id, audience="audit"))
        self.assertNotIn(task.original_request, audit)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
