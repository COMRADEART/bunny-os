# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The published schemas describe what the runtime actually writes.

Two separate checks. The structural ones run everywhere: the schemas parse, and
their enumerations agree with the constants the code branches on — which is the
failure that actually happens, a state or an event type added in one place and
not the other. The conformance check needs ``jsonschema`` and is skipped where
it is absent, following the repository's existing convention; skipping the
*check* is acceptable, silently skipping the *property* is not, which is why the
enumeration comparison is unconditional.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from companion.events import EVENT_TYPES
from companion.privacy import DATA_CLASSES
from companion.reviewer import CATEGORIES, SEVERITIES, ReviewObservation
from companion.session import LOCALITY_PREFERENCES, SESSION_STATUSES
from companion.states import STATES
from companion.task import CANCELLATION_CAUSES, CANCELLATION_STATES, OPERATION_STATES, TASK_TYPES

from .support import FULL_REQUEST, CompanionTestCase

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def load(name: str) -> dict:
    return json.loads((SCHEMAS / f"companion-core-{name}.schema.json").read_text(encoding="utf-8"))


class SchemaAgreementTests(unittest.TestCase):
    """The schema's enumerations and the code's constants are the same list."""

    def test_the_event_schema_lists_every_event_type(self) -> None:
        schema = load("event")
        self.assertEqual(
            sorted(schema["properties"]["eventType"]["enum"]), sorted(EVENT_TYPES)
        )

    def test_the_task_schema_lists_every_state(self) -> None:
        schema = load("task")
        self.assertEqual(sorted(schema["properties"]["state"]["enum"]), sorted(STATES))
        self.assertEqual(sorted(schema["properties"]["taskType"]["enum"]), sorted(TASK_TYPES))
        self.assertEqual(
            sorted(schema["properties"]["cancellationState"]["enum"]), sorted(CANCELLATION_STATES)
        )
        self.assertEqual(
            sorted(schema["properties"]["cancellationCause"]["enum"]), sorted(CANCELLATION_CAUSES)
        )
        self.assertEqual(
            sorted(schema["properties"]["operations"]["items"]["properties"]["status"]["enum"]),
            sorted(OPERATION_STATES),
        )

    def test_the_data_classes_agree_everywhere_they_appear(self) -> None:
        self.assertEqual(sorted(load("event")["properties"]["classification"]["enum"]), sorted(DATA_CLASSES))
        self.assertEqual(sorted(load("task")["properties"]["classification"]["enum"]), sorted(DATA_CLASSES))

    def test_the_session_schema_agrees_on_status_and_locality(self) -> None:
        schema = load("session")
        self.assertEqual(sorted(schema["properties"]["status"]["enum"]), sorted(SESSION_STATUSES))
        self.assertEqual(
            sorted(schema["properties"]["localityPreference"]["enum"]), sorted(LOCALITY_PREFERENCES)
        )

    def test_the_remote_ceiling_cannot_be_secret_in_the_schema_either(self) -> None:
        enum = load("session")["properties"]["privacyPolicy"]["properties"]["maximumRemoteClassification"]["enum"]
        self.assertNotIn("secret", enum)

    def test_the_observation_schema_matches_the_reviewer_contract(self) -> None:
        schema = load("reviewer-observation")
        self.assertEqual(sorted(schema["properties"]["severity"]["enum"]), sorted(SEVERITIES))
        self.assertEqual(sorted(schema["properties"]["category"]["enum"]), sorted(CATEGORIES))
        # The brief's example is a valid observation.
        example = schema["examples"][0]
        observation = ReviewObservation(
            reviewer_id=example["reviewerId"], severity=example["severity"],
            category=example["category"], summary=example["summary"],
            suggested_action=example["suggestedAction"],
            evidence_event_ids=tuple(example["evidenceEventIds"]),
        )
        self.assertEqual(observation.to_json(), example)


class SchemaConformanceTests(CompanionTestCase):
    """What the runtime writes validates against what the schemas say."""

    def setUp(self) -> None:
        super().setUp()
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema is not installed; the enumeration checks still ran")

    def test_a_completed_task_run_conforms_end_to_end(self) -> None:
        import jsonschema

        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Schema conformance")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "completed")

        jsonschema.validate(runtime.session(session.session_id).to_json(), load("session"))
        jsonschema.validate(finished.to_json(), load("task"))
        for event in runtime.events(session.session_id):
            jsonschema.validate(event.to_json(), load("event"))

        observations = [
            event.payload for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "reviewer_observation" and not event.payload.get("absent")
        ]
        self.assertTrue(observations)
        for payload in observations:
            jsonschema.validate(
                {key: payload[key] for key in (
                    "reviewerId", "severity", "category", "summary", "suggestedAction", "evidenceEventIds",
                ) if key in payload},
                load("reviewer-observation"),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
