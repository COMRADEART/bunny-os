# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured output validation: named schemas, no coercion, refusal with a reason.

The §12 argument these tests collect: a provider's output is validated against
schemas only this build names, and validation never edits the output into
validity, because edited output is output nobody produced. So every refusal
test asserts both the :class:`StructuredOutputInvalid` and its ``reason`` —
the reason is what the bounded repair attempt is allowed to tell the model —
and the pass-through test asserts byte-for-byte agreement with ``json.loads``,
because "accepted" must mean "accepted as written".
"""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any

from companion.agents.errors import StructuredOutputInvalid
from companion.agents.structured import (
    MAX_STRUCTURED_BYTES,
    OBSERVATIONS_SCHEMA_REFERENCE,
    PLAN_SCHEMA_REFERENCE,
    RepairRecord,
    parse_structured,
    repair_instruction,
)


def _plan_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "summary": "count the words in the note",
        "operations": [
            {
                "name": "count-words",
                "tool": "text.count_words",
                "arguments": {"text": "the note", "count": "5", "strict": True},
            },
        ],
    }
    document.update(overrides)
    return document


def _observations_document() -> dict[str, Any]:
    return {
        "observations": [
            {"severity": "info", "category": "correctness", "summary": "looks right"},
        ],
    }


class ValidDocuments(unittest.TestCase):
    def test_a_valid_plan_parses_and_the_digest_pins_the_text(self) -> None:
        text = json.dumps(_plan_document())
        value, digest = parse_structured(text, PLAN_SCHEMA_REFERENCE)
        self.assertEqual(value, _plan_document())
        self.assertEqual(
            digest, hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_valid_observations_parse(self) -> None:
        text = json.dumps(_observations_document())
        value, _ = parse_structured(text, OBSERVATIONS_SCHEMA_REFERENCE)
        self.assertEqual(value, _observations_document())

    def test_schema_free_arguments_pass_through_exactly_as_written(self) -> None:
        """Never coerces: the string "5" stays a string, the bool stays a bool."""
        text = json.dumps(_plan_document())
        value, _ = parse_structured(text, PLAN_SCHEMA_REFERENCE)
        self.assertEqual(value, json.loads(text))
        arguments = value["operations"][0]["arguments"]
        self.assertIsInstance(arguments["count"], str)
        self.assertIsInstance(arguments["strict"], bool)


class Refusals(unittest.TestCase):
    """Every refusal is a named reason; nothing is repaired in place."""

    def _refused(self, document: Any, reference: str = PLAN_SCHEMA_REFERENCE,
                 *, text: str | None = None) -> StructuredOutputInvalid:
        material = text if text is not None else json.dumps(document)
        with self.assertRaises(StructuredOutputInvalid) as caught:
            parse_structured(material, reference)
        return caught.exception

    def test_text_that_is_not_json_is_refused(self) -> None:
        refusal = self._refused(None, text="{nope")
        self.assertEqual(refusal.reason, "invalid-json")

    def test_an_unknown_schema_reference_names_nothing(self) -> None:
        refusal = self._refused(_plan_document(), "agent-plan/99")
        self.assertEqual(refusal.reason, "unknown-schema-reference")

    def test_an_additional_field_at_the_top_level_is_refused(self) -> None:
        refusal = self._refused(_plan_document(shellCommand="rm -rf /"))
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_an_additional_field_inside_an_operation_is_refused(self) -> None:
        document = _plan_document()
        document["operations"][0]["unattended"] = True
        refusal = self._refused(document)
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_a_missing_required_field_is_refused(self) -> None:
        document = _plan_document()
        del document["summary"]
        refusal = self._refused(document)
        self.assertEqual(refusal.reason, "schema-mismatch")
        self.assertIn("summary", str(refusal))

    def test_operations_as_an_object_instead_of_an_array_is_refused(self) -> None:
        refusal = self._refused(_plan_document(operations={"name": "sneaky"}))
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_an_oversized_summary_is_refused_not_shortened(self) -> None:
        refusal = self._refused(_plan_document(summary="s" * 241))
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_more_than_eight_operations_is_refused(self) -> None:
        operation = _plan_document()["operations"][0]
        refusal = self._refused(_plan_document(operations=[dict(operation) for _ in range(9)]))
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_a_traversal_shaped_operation_name_is_refused(self) -> None:
        document = _plan_document()
        document["operations"][0]["name"] = "../etc"
        refusal = self._refused(document)
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_an_invented_observation_severity_is_refused(self) -> None:
        document = _observations_document()
        document["observations"][0]["severity"] = "catastrophic"
        refusal = self._refused(document, OBSERVATIONS_SCHEMA_REFERENCE)
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_a_control_character_in_a_string_is_refused(self) -> None:
        refusal = self._refused(_plan_document(summary="ding\x07"))
        self.assertEqual(refusal.reason, "schema-mismatch")
        self.assertIn("U+0007", str(refusal))

    def test_a_terminal_escape_in_a_string_is_refused(self) -> None:
        """The next reader of that string may be a terminal."""
        refusal = self._refused(_plan_document(summary="\x1b[31mred"))
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_output_beyond_the_byte_ceiling_is_refused_before_parsing(self) -> None:
        refusal = self._refused(None, text="x" * (MAX_STRUCTURED_BYTES + 1))
        self.assertEqual(refusal.reason, "oversized")

    def test_a_depth_bomb_in_schema_free_arguments_is_refused(self) -> None:
        """Arguments are schema-free, not bound-free."""
        bomb: Any = "core"
        for _ in range(12):
            bomb = [bomb]
        document = _plan_document()
        document["operations"][0]["arguments"] = {"payload": bomb}
        refusal = self._refused(document)
        self.assertEqual(refusal.reason, "schema-mismatch")
        self.assertIn("depth", str(refusal))

    def test_an_arguments_object_with_too_many_keys_is_refused(self) -> None:
        document = _plan_document()
        document["operations"][0]["arguments"] = {
            f"key{index}": index for index in range(129)
        }
        refusal = self._refused(document)
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_an_integer_where_a_string_belongs_is_refused_not_converted(self) -> None:
        refusal = self._refused(_plan_document(summary=5))
        self.assertEqual(refusal.reason, "schema-mismatch")

    def test_the_refusal_carries_the_digest_of_the_rejected_text(self) -> None:
        """The record can name what was rejected without storing it."""
        text = json.dumps(_plan_document(summary=5))
        with self.assertRaises(StructuredOutputInvalid) as caught:
            parse_structured(text, PLAN_SCHEMA_REFERENCE)
        self.assertEqual(
            caught.exception.digest,
            hashlib.sha256(text.encode("utf-8")).hexdigest())


class RepairPath(unittest.TestCase):
    """The model is asked again with the failure named — never handed an answer."""

    def test_the_repair_instruction_names_the_failure_and_supplies_no_output(self) -> None:
        reason = "required field 'summary' is absent"
        instruction = repair_instruction(PLAN_SCHEMA_REFERENCE, reason)
        self.assertIn(PLAN_SCHEMA_REFERENCE, instruction)
        self.assertIn(reason, instruction)
        # No corrected JSON rides along: supplying one would be this module
        # doing the reinterpreting it exists to refuse.
        self.assertNotIn("{", instruction)
        self.assertNotIn("}", instruction)

    def test_the_repair_record_serializes_camel_case(self) -> None:
        record = RepairRecord(attempt=1, original_digest="abc123", reason="invalid-json")
        self.assertEqual(record.to_json(), {
            "attempt": 1,
            "originalDigest": "abc123",
            "reason": "invalid-json",
        })


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
