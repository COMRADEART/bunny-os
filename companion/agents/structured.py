# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured output: validated locally, against schemas only this build names.

Two decisions carry this module.

**Schemas are named, never transported.** A generation request carries a
*reference* into :data:`SCHEMAS`; there is no path by which a provider — or
anything downstream of one — supplies a schema object. A provider that could
describe its own output's shape could describe a shape with room for what §12
forbids, which is the "untrusted model descriptor" case in §20's list.

**Validation never coerces.** A string where an integer belongs is a refusal,
not a conversion; an unknown field is a refusal (every schema here closes with
``additionalProperties: false``); a string carrying ESC or C0 control bytes is
a refusal, because the next reader of that string may be a terminal. When
repair is allowed the *model* is asked again with the failure named —
:func:`repair_instruction` — and the original invalid output survives as a
digest in the :class:`RepairRecord`. Nothing edits the output into validity,
because edited output is output nobody produced.

The validator is a deliberate subset of JSON Schema: ``type``, ``properties``,
``required``, ``additionalProperties``, ``enum``, ``maxLength``, ``maxItems``,
``minimum``, ``maximum``, ``items``, plus the private ``identifier`` keyword
(:func:`companion.ids.valid_id`). Nothing here compiles a pattern from a
schema, because the schemas are ours and the day one needs a regex is the day
the validator grows one deliberately.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..ids import valid_id
from .errors import StructuredOutputInvalid

__all__ = [
    "MAX_REPAIR_ATTEMPTS",
    "MAX_STRUCTURED_BYTES",
    "PLAN_SCHEMA_REFERENCE",
    "OBSERVATIONS_SCHEMA_REFERENCE",
    "RepairRecord",
    "SCHEMAS",
    "parse_structured",
    "repair_instruction",
    "schema_for",
]

MAX_STRUCTURED_BYTES = 64 * 1024
MAX_REPAIR_ATTEMPTS = 1
_MAX_DEPTH = 8
_DEFAULT_MAX_ITEMS = 128
_DEFAULT_MAX_LENGTH = 4096

PLAN_SCHEMA_REFERENCE = "agent-plan/1"
OBSERVATIONS_SCHEMA_REFERENCE = "agent-observations/1"

#: Severities and categories mirror ``companion.reviewer``; a test asserts the
#: agreement, because this package may not import that module.
_OBSERVATION_SEVERITIES = ("info", "low", "medium", "high", "blocking")
_OBSERVATION_CATEGORIES = ("correctness", "security", "privacy", "improvement", "policy")

SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    PLAN_SCHEMA_REFERENCE: {
        "type": "object",
        "required": ("summary", "operations"),
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 240},
            "operations": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "required": ("name", "tool", "arguments"),
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "maxLength": 64, "identifier": True},
                        "tool": {"type": "string", "maxLength": 128},
                        "arguments": {"type": "object"},
                        "rationale": {"type": "string", "maxLength": 240},
                        "expectedEffect": {"type": "string", "maxLength": 240},
                    },
                },
            },
        },
    },
    OBSERVATIONS_SCHEMA_REFERENCE: {
        "type": "object",
        "required": ("observations",),
        "additionalProperties": False,
        "properties": {
            "observations": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "required": ("severity", "category", "summary"),
                    "additionalProperties": False,
                    "properties": {
                        "severity": {"type": "string", "enum": _OBSERVATION_SEVERITIES},
                        "category": {"type": "string", "enum": _OBSERVATION_CATEGORIES},
                        "summary": {"type": "string", "maxLength": 240},
                        "suggestedAction": {"type": "string", "maxLength": 240},
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class RepairRecord:
    """One bounded repair attempt, with the invalid original pinned by digest."""

    attempt: int
    original_digest: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"attempt": self.attempt, "originalDigest": self.original_digest, "reason": self.reason}


def schema_for(reference: str) -> Mapping[str, Any]:
    schema = SCHEMAS.get(reference)
    if schema is None:
        raise StructuredOutputInvalid(
            f"schema reference {reference!r} names nothing this build validates against",
            reason="unknown-schema-reference",
        )
    return schema


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _clean_string(value: str, path: str) -> None:
    for character in value:
        code = ord(character)
        if code == 0x1B:
            raise ValueError(f"{path}: contains a terminal escape byte")
        if code < 0x20 and character not in ("\n", "\t"):
            raise ValueError(f"{path}: contains control character U+{code:04X}")


def _validate(value: Any, schema: Mapping[str, Any], path: str, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError(f"{path}: exceeds depth {_MAX_DEPTH}")
    declared = schema.get("type")
    if declared == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected object, found {type(value).__name__}")
        if len(value) > _DEFAULT_MAX_ITEMS:
            raise ValueError(f"{path}: more than {_DEFAULT_MAX_ITEMS} fields")
        properties: Mapping[str, Any] = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in value:
                raise ValueError(f"{path}: required field {name!r} is absent")
        for name, item in value.items():
            if not isinstance(name, str):
                raise ValueError(f"{path}: non-string field name")
            _clean_string(name, f"{path}.{name}")
            if name in properties:
                _validate(item, properties[name], f"{path}.{name}", depth + 1)
            elif schema.get("additionalProperties", True) is False:
                raise ValueError(f"{path}: field {name!r} is not in the schema")
            else:
                _validate_free(item, f"{path}.{name}", depth + 1)
    elif declared == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected array, found {type(value).__name__}")
        limit = int(schema.get("maxItems", _DEFAULT_MAX_ITEMS))
        if len(value) > limit:
            raise ValueError(f"{path}: more than {limit} items")
        item_schema = schema.get("items")
        for index, item in enumerate(value):
            if item_schema is not None:
                _validate(item, item_schema, f"{path}[{index}]", depth + 1)
            else:
                _validate_free(item, f"{path}[{index}]", depth + 1)
    elif declared == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected string, found {type(value).__name__}")
        limit = int(schema.get("maxLength", _DEFAULT_MAX_LENGTH))
        if len(value) > limit:
            raise ValueError(f"{path}: longer than {limit}")
        _clean_string(value, path)
        if schema.get("identifier") and not valid_id(value):
            raise ValueError(f"{path}: {value!r} is not a valid identifier")
        allowed = schema.get("enum")
        if allowed is not None and value not in allowed:
            raise ValueError(f"{path}: {value!r} is not one of {tuple(allowed)}")
    elif declared == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path}: expected integer, found {type(value).__name__}")
        _check_range(value, schema, path)
    elif declared == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{path}: expected number, found {type(value).__name__}")
        _check_range(value, schema, path)
    elif declared == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected boolean, found {type(value).__name__}")
    else:
        raise ValueError(f"{path}: schema declares unsupported type {declared!r}")


def _check_range(value: Any, schema: Mapping[str, Any], path: str) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and value < minimum:
        raise ValueError(f"{path}: {value} is below {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{path}: {value} is above {maximum}")


def _validate_free(value: Any, path: str, depth: int) -> None:
    """Bounds for schema-free regions (tool arguments): size, depth, cleanliness.

    Argument *meaning* is the tool declaration's business, checked where the
    proposal meets the broker; here the concern is only that the region cannot
    smuggle unbounded or unprintable content past the size checks.
    """
    if depth > _MAX_DEPTH:
        raise ValueError(f"{path}: exceeds depth {_MAX_DEPTH}")
    if isinstance(value, dict):
        if len(value) > _DEFAULT_MAX_ITEMS:
            raise ValueError(f"{path}: more than {_DEFAULT_MAX_ITEMS} fields")
        for name, item in value.items():
            if not isinstance(name, str):
                raise ValueError(f"{path}: non-string field name")
            _clean_string(name, f"{path}.{name}")
            _validate_free(item, f"{path}.{name}", depth + 1)
    elif isinstance(value, list):
        if len(value) > _DEFAULT_MAX_ITEMS:
            raise ValueError(f"{path}: more than {_DEFAULT_MAX_ITEMS} items")
        for index, item in enumerate(value):
            _validate_free(item, f"{path}[{index}]", depth + 1)
    elif isinstance(value, str):
        if len(value) > _DEFAULT_MAX_LENGTH:
            raise ValueError(f"{path}: longer than {_DEFAULT_MAX_LENGTH}")
        _clean_string(value, path)
    elif isinstance(value, bool) or value is None:
        pass
    elif isinstance(value, (int, float)):
        pass
    else:
        raise ValueError(f"{path}: {type(value).__name__} is not JSON data")


def parse_structured(text: str, reference: str) -> tuple[Any, str]:
    """Parse and validate, or refuse with the original pinned by digest.

    Returns ``(value, digest)``. The digest is of the *text as received*, so
    the record can name what was accepted or rejected without storing it.
    """
    digest = _digest(text)
    schema = schema_for(reference)
    if len(text.encode("utf-8", errors="replace")) > MAX_STRUCTURED_BYTES:
        raise StructuredOutputInvalid(
            f"structured output exceeds {MAX_STRUCTURED_BYTES} bytes",
            digest=digest, reason="oversized",
        )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise StructuredOutputInvalid(
            f"structured output is not JSON: {error.msg} at position {error.pos}",
            digest=digest, reason="invalid-json",
        ) from None
    try:
        _validate(value, schema, "$", 0)
    except ValueError as error:
        raise StructuredOutputInvalid(
            f"structured output does not match {reference}: {error}",
            digest=digest, reason="schema-mismatch",
        ) from None
    return value, digest


def repair_instruction(reference: str, reason: str) -> str:
    """What the model is told on the bounded repair attempt.

    The instruction names the failure; it never includes a corrected version
    of the output, because supplying one would be this module doing the
    reinterpreting it exists to refuse.
    """
    return (
        f"The previous output was rejected by local validation against {reference}: "
        f"{reason}. Emit the corrected JSON only, matching the schema exactly, "
        "with no surrounding prose."
    )
