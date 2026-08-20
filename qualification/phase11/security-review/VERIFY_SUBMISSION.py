#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate a security-review submission against the committed contract.

Run this before submitting::

    python3 VERIFY_SUBMISSION.py record.json

Exit 0 means the record satisfies ``SUBMISSION_SCHEMA.json`` plus the
cross-field rules the schema documents but cannot express (alias equality,
digest membership in ``ARTIFACT_IDENTITY.json``, exact calendar dates and
review ordering, finding-ID uniqueness, attachment-digest shape, and the
release-authority overlap needing a recorded policy).
Exit 2 lists every problem found. The checks are read from the schema file
itself — required lists, enums, patterns, ``x-aliases`` — so this validator
and the schema cannot drift apart.

Two things this tool is honest about:

* It verifies that an independence declaration *exists*, never that it is
  true; credibility is a human judgment recorded in triage.
* Passing here is not acceptance. The only door into the record is the
  Phase 9 intake (``qualification/phase9/tools/intake.py register``), which
  runs its own validation and seals what it ingests. This tool exists so a
  reviewer learns about a contract problem before submitting rather than
  after, and so triage can re-check a registered record mechanically.

A record carrying ``fixtureClass: TEST_FIXTURE_ONLY`` is synthetic dry-run
material and is refused outright: a fixture is never evidence.

Determinism: no clock is read; dates are compared with each other, never
with "now".
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "SUBMISSION_SCHEMA.json"
IDENTITY_PATH = HERE / "ARTIFACT_IDENTITY.json"

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: Digest keys of the subject artifact, in ARTIFACT_IDENTITY.json order.
IDENTITY_DIGEST_KEYS = (
    "imageDigest", "isoSha256", "qcow2Sha256", "ociTarSha256", "rawSha256",
)

_TYPES = {
    "object": dict, "array": list, "string": str,
    "boolean": bool, "null": type(None),
}


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_identity(path: Path = IDENTITY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_digest(value: str) -> str:
    value = str(value).strip().lower()
    return value[7:] if value.startswith("sha256:") else value


def subject_digests(identity: dict) -> set[str]:
    artifact = identity["subjectArtifact"]
    return {
        normalize_digest(artifact[key])
        for key in IDENTITY_DIGEST_KEYS if artifact.get(key)
    }


# ------------------------------------------------------------ schema checks

def _type_ok(value, declared) -> bool:
    names = declared if isinstance(declared, list) else [declared]
    for name in names:
        expected = _TYPES.get(name)
        if expected is None:
            continue
        # bool is an int subclass; there is no integer in this contract, so
        # the plain isinstance check is exact for every type used.
        if isinstance(value, expected):
            return True
    return False


def check_against(schema: dict, value, where: str) -> list[str]:
    """The subset of JSON Schema this contract uses: type, required, enum,
    const, pattern, minLength, properties, items. Anything the schema file
    declares outside this subset would be silently unenforced, so the
    guard test asserts the schema uses only these keywords."""
    problems: list[str] = []
    declared_type = schema.get("type")
    if declared_type is not None and not _type_ok(value, declared_type):
        return ["%s: expected %s" % (where, declared_type)]
    if "const" in schema and value != schema["const"]:
        problems.append("%s: must be %r" % (where, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        problems.append("%s: %r is not one of %s"
                        % (where, value, "/".join(map(str, schema["enum"]))))
    if "pattern" in schema and isinstance(value, str) \
            and not re.search(schema["pattern"], value):
        problems.append("%s: %r does not match %s"
                        % (where, value, schema["pattern"]))
    if "minLength" in schema and isinstance(value, str) \
            and len(value.strip()) < schema["minLength"]:
        problems.append("%s: must be non-empty" % where)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                problems.append("%s: required field %r is missing" % (where, name))
        for name, subschema in schema.get("properties", {}).items():
            if name in value:
                problems.extend(check_against(
                    subschema, value[name], "%s.%s" % (where, name)))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems.extend(check_against(
                schema["items"], item, "%s[%d]" % (where, index)))
    return problems


# ------------------------------------------------------- cross-field checks

def cross_field_problems(record: dict, schema: dict, identity: dict) -> list[str]:
    problems: list[str] = []

    for alias, canonical in schema.get("x-aliases", []):
        if alias in record and canonical in record \
                and record[alias] != record[canonical]:
            problems.append(
                "%s must equal %s (the intake boundary reads the former, "
                "this contract the latter; a submission saying two things "
                "is saying nothing)" % (alias, canonical))

    subject = subject_digests(identity)
    for field in ("artifact_digest", "independently_computed_digest"):
        value = record.get(field)
        if isinstance(value, str) and value.strip() \
                and normalize_digest(value) not in subject:
            problems.append(
                "%s: %s is not any of the subject artifact's five digests — "
                "you are holding different bytes; stop and report that "
                "(blocking condition 6)" % (field, normalize_digest(value)))

    parsed_dates: dict[str, datetime.date] = {}
    for field in ("review_start", "review_end", "date"):
        value = record.get(field)
        if not isinstance(value, str):
            continue
        try:
            # These contract fields are dates, not timestamps. Exact parsing
            # rejects impossible calendar dates and suffixes that merely begin
            # like a date; neither is a usable evidence boundary.
            parsed_dates[field] = datetime.date.fromisoformat(value)
        except ValueError:
            problems.append(
                "%s: %r is not an exact ISO 8601 calendar date" %
                (field, value))
    start, end = (parsed_dates.get("review_start"),
                  parsed_dates.get("review_end"))
    if start is not None and end is not None and start > end:
        problems.append("review_start %s postdates review_end %s" %
                        (start.isoformat(), end.isoformat()))

    independence = record.get("independence")
    if isinstance(independence, dict) \
            and independence.get("is_release_decision_authority") is True \
            and not str(independence.get("policy_exception") or "").strip():
        problems.append(
            "independence: the reviewer declares themselves the release "
            "decision authority; that overlap requires a recorded policy in "
            "policy_exception, and no such policy currently exists")

    seen: set[str] = set()
    for index, finding in enumerate(record.get("findings") or []):
        if not isinstance(finding, dict):
            continue
        fid = finding.get("reviewer_finding_id")
        if isinstance(fid, str):
            if fid in seen:
                problems.append(
                    "findings[%d]: reviewer_finding_id %r is duplicated"
                    % (index, fid))
            seen.add(fid)

    for name, digest in (record.get("attachmentDigests") or {}).items():
        if not re.fullmatch(r"[0-9a-f]{64}", normalize_digest(str(digest))):
            problems.append(
                "attachmentDigests[%s]: not a sha256 hex digest" % name)

    return problems


# ---------------------------------------------------------------- validate

def validate_submission(record, schema: dict | None = None,
                        identity: dict | None = None) -> list[str]:
    """Every problem with one submission record; empty means valid."""
    if not isinstance(record, dict):
        return ["the record must be a JSON object"]
    if record.get("fixtureClass") == FIXTURE_MARKER:
        return ["the record declares fixtureClass %s; a fixture is never "
                "evidence and never a submission" % FIXTURE_MARKER]
    schema = schema if schema is not None else load_schema()
    identity = identity if identity is not None else load_identity()
    problems = check_against(schema, record, "record")
    problems += cross_field_problems(record, schema, identity)
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: VERIFY_SUBMISSION.py record.json")
        return 2
    path = Path(argv[0])
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable record: %s" % error)
        return 2
    problems = validate_submission(record)
    if problems:
        for problem in problems:
            print(problem)
        print("%d problem(s); this record does not satisfy the contract"
              % len(problems))
        return 2
    print("record satisfies the submission contract; submit it through the "
          "project operator (Phase 9 intake) — passing here is not acceptance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
