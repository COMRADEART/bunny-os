#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate an Alpha tester report against the committed contract.

Run this before submitting::

    python3 VERIFY_TESTER_REPORT.py my-report.json

Exit 0 means the record satisfies ``TESTER_REPORT_SCHEMA.json`` plus the
cross-field rules the schema documents but cannot express: the intake-alias
pairs are equal; the artifact identity claim is coherent with the digest
you actually observed (``ARTIFACT_VERIFICATION.md``); and the observed
digest is never silently replaced by the published one. The checks are
read from the schema file itself — required lists, enums, patterns,
``x-aliases`` — so this validator and the schema cannot drift apart.

It also runs a courtesy scan for likely credential material (passwords,
tokens, keys) using the same class table as the intake boundary
(``qualification/phase9/tools/intake.py SECRET_CLASS_PATTERNS`` — the
guard suite asserts the two copies are identical). The intake rejects a
credential-bearing submission with nothing ingested; failing here first
costs you nothing.

Passing is not acceptance: the only door into the record is the Phase 9
intake, operated by the program. This tool exists so you learn about a
problem before submitting rather than after.

A record carrying ``fixtureClass: TEST_FIXTURE_ONLY`` is synthetic dry-run
material and is refused outright: a fixture is never evidence.

Determinism: no clock is read; dates are recorded, never judged against
"now".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "TESTER_REPORT_SCHEMA.json"
IDENTITY_PATH = HERE / "ARTIFACT_IDENTITY.json"

FIXTURE_MARKER = "TEST_FIXTURE_ONLY"

#: Must byte-match qualification/phase9/tools/intake.py
#: SECRET_CLASS_PATTERNS — asserted by the guard suite, so the courtesy
#: pre-check and the boundary cannot disagree about what a likely
#: credential is.
SECRET_CLASS_PATTERNS = (
    (r"-----BEGIN[^\n]{0,40}PRIVATE KEY", "private key material"),
    (r"[Bb]earer\s+[A-Za-z0-9._+/=-]{20,}", "bearer token"),
    (r"AKIA[0-9A-Z]{16}", "cloud access key id"),
    (r"(?i)(api[_-]?key|apikey|secret[_-]?key|access[_-]?token"
     r"|auth[_-]?token|session[_-]?token|client[_-]?secret"
     r"|session[_-]?cookie)[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9._+/=-]{16,}",
     "api or session token assignment"),
    (r"(?i)(password|passwd|passphrase)[\"']?\s*[=:]\s*[\"']?\S{8,}",
     "password assignment"),
    (r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}", "json web token"),
    (r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}", "code-forge token"),
)

_SECRET_RES = tuple(
    (re.compile(pattern.encode("utf-8")), label)
    for pattern, label in SECRET_CLASS_PATTERNS
)

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


def secret_classes(raw: bytes) -> list[str]:
    return sorted({label for pattern, label in _SECRET_RES
                   if pattern.search(raw)})


# ------------------------------------------------------------ schema checks

def _type_ok(value, declared) -> bool:
    names = declared if isinstance(declared, list) else [declared]
    for name in names:
        expected = _TYPES.get(name)
        if expected is None:
            continue
        if isinstance(value, expected):
            return True
    return False


def check_against(schema: dict, value, where: str) -> list[str]:
    """The subset of JSON Schema this contract uses: type, required, enum,
    const, pattern, minLength, properties, items. The guard suite refuses
    a schema keyword outside this subset, so nothing declared here is
    silently unenforced."""
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
        if alias == "artifactDigest":
            continue  # conditional; handled with the identity states below
        if alias in record and canonical in record \
                and record[alias] != record[canonical]:
            problems.append(
                "%s must equal %s (the intake boundary reads the former, "
                "this contract the latter; a report saying two things is "
                "saying nothing)" % (alias, canonical))

    subject = subject_digests(identity)
    observed = record.get("artifact_digest_observed")
    status = record.get("artifact_identity_status")
    verified = record.get("artifact_digest_verified")

    if isinstance(observed, str) and observed.strip():
        in_subject = normalize_digest(observed) in subject
        alias_value = record.get("artifactDigest")
        if alias_value is None:
            problems.append(
                "artifactDigest (intake alias) is missing while a digest "
                "was observed; the intake binds on it — set it to the "
                "digest you observed")
        elif alias_value != observed:
            problems.append(
                "artifactDigest must equal artifact_digest_observed — the "
                "report records what you observed, never a substituted "
                "expected digest")
        if in_subject and status == "MISMATCH":
            problems.append(
                "artifact_identity_status says MISMATCH but the observed "
                "digest IS the subject artifact")
        if not in_subject and status != "MISMATCH":
            problems.append(
                "the observed digest %s is not any of the subject "
                "artifact's digests; the honest identity status is "
                "MISMATCH — stop testing and report it"
                % normalize_digest(observed)[:12])
        if status == "MISSING":
            problems.append(
                "artifact_identity_status says MISSING but a digest was "
                "observed")
        if status == "VERIFIED" and verified is not True:
            problems.append(
                "VERIFIED requires artifact_digest_verified true — you "
                "compared it yourself")
        if status == "OBSERVED_UNVERIFIED" and verified is True:
            problems.append(
                "artifact_digest_verified true with OBSERVED_UNVERIFIED "
                "is incoherent; if you verified it, say VERIFIED")
    else:
        if status not in (None, "MISSING"):
            problems.append(
                "no digest was observed, so artifact_identity_status can "
                "only be MISSING — the report stays honest, unbound user "
                "evidence until a revision binds it")
        if verified is True:
            problems.append(
                "artifact_digest_verified true with no observed digest is "
                "incoherent")
        if record.get("artifactDigest"):
            problems.append(
                "artifactDigest (intake alias) is present but no digest "
                "was observed — never substitute the expected digest for "
                "an observation")

    for name, digest in (record.get("attachmentDigests") or {}).items():
        if not re.fullmatch(r"[0-9a-f]{64}", normalize_digest(str(digest))):
            problems.append(
                "attachmentDigests[%s]: not a sha256 hex digest" % name)

    found = secret_classes(
        json.dumps(record, sort_keys=True).encode("utf-8"))
    for label in found:
        problems.append(
            "likely credential material (%s) in the record; the intake "
            "will reject this submission with nothing ingested — remove "
            "or mask the value and re-check (the value is not repeated "
            "here)" % label)

    return problems


# ---------------------------------------------------------------- validate

def validate_report(record, schema: dict | None = None,
                    identity: dict | None = None) -> list[str]:
    """Every problem with one tester report; empty means valid."""
    if not isinstance(record, dict):
        return ["the record must be a JSON object"]
    if record.get("fixtureClass") == FIXTURE_MARKER:
        return ["the record declares fixtureClass %s; a fixture is never "
                "evidence and never a report" % FIXTURE_MARKER]
    schema = schema if schema is not None else load_schema()
    identity = identity if identity is not None else load_identity()
    problems = check_against(schema, record, "record")
    problems += cross_field_problems(record, schema, identity)
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: VERIFY_TESTER_REPORT.py report.json")
        return 2
    path = Path(argv[0])
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print("unreadable report: %s" % error)
        return 2
    problems = validate_report(record)
    if problems:
        for problem in problems:
            print(problem)
        print("%d problem(s); this report does not satisfy the contract"
              % len(problems))
        return 2
    print("report satisfies the contract; hand it to the program operator "
          "(Phase 9 intake) — passing here is not acceptance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
