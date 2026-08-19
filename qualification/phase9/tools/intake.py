#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 9 external-evidence intake: the approved append mechanism.

Evidence enters ``qualification/phase9/intake/LEDGER.json`` through
``register`` and no other way. Each registration assigns the next intake ID,
ingests the submission's bytes under ``intake/<source>/<ID>/``, pins every
ingested file by size and sha256, answers the six validation questions
(identity, artifact binding, timestamp, completeness, integrity, scope), and
appends a sealed entry — the seal is the sha256 of the canonical JSON of the
entry without its seal field. Entries are immutable afterwards: SUPERSEDED
is derived from a later revision's existence, never written back.

``verify`` recomputes every seal and every pin, and walks the intake tree
for orphans; it exits 2 on any issue so a broken tree fails closed. The
guard test (``tests/release/test_phase9_intake.py``) calls the same
functions and executes the failure branches against constructed trees on
every run.

Determinism: this tool never reads the clock. ``--received-on`` is stated
by the operator; the timestamps inside a record are the evidence's own
claims; the commit is the tamper-evident time.

Honesty boundary: validation here is mechanical. The tool can check that a
reviewer is named, not that the name is real or independent — identity and
authority verification stays a human judgment, recorded in triage, never
manufactured by automation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INTAKE_ROOT = ROOT / "qualification" / "phase9" / "intake"
LEDGER_PATH = INTAKE_ROOT / "LEDGER.json"
LEDGER_PREFIX = "qualification/phase9/intake/"

SOURCES = (
    "security-review", "hardware", "signing", "second-approval", "alpha-feedback",
)

#: The six stored statuses. SUPERSEDED is in the vocabulary because reports
#: derive it for any entry with a later revision; ``register`` never stores it.
STATUSES = (
    "ACCEPTED", "REJECTED", "INCOMPLETE",
    "ARTIFACT_MISMATCH", "UNVERIFIABLE", "SUPERSEDED",
)

REVIEW_OUTCOMES = (
    "APPROVED", "APPROVED_WITH_CONDITIONS", "BLOCKED", "MORE_EVIDENCE_REQUIRED",
)

HARDWARE_STATUSES = ("PASS", "FAIL", "NOT_RUN", "NOT_SUPPORTED")

#: The eighteen dimensions of qualification/phase8/hardware-matrix.json.
HARDWARE_DIMENSIONS = (
    "boot-installation-media", "installation", "encrypted-boot", "login",
    "bunny-desktop", "companion-prerendered", "companion-2d",
    "companion-3d-native", "companion-3d-fallback", "voice-microphone",
    "voice-recognition", "voice-response", "trust-allow-verified",
    "trust-deny-verified", "reboot-persistence", "wifi", "audio-output",
    "display",
)

HARDWARE_IDENTITY_FIELDS = (
    "manufacturer", "model", "cpu", "ram", "gpu", "storage",
    "firmwareMode", "secureBootState",
)

ALPHA_CATEGORIES = (
    "SECURITY", "PRIVACY", "DATA_LOSS", "RELEASE_BLOCKER", "ACCESSIBILITY",
    "FUNCTIONAL", "PERFORMANCE", "UX", "HARDWARE", "HARNESS", "ENVIRONMENT",
)
ALPHA_CONFIDENCE = ("CONFIRMED", "LIKELY", "REPORTED", "UNREPRODUCED")
ALPHA_JOURNEYS = ("A", "B", "C", "D", "E", "exploratory")

INTAKE_ID = re.compile(r"^INTAKE-(\d{3})(?:-R([1-9]\d*))?$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
HW_ID = re.compile(r"^HW-\d{3}$")
TESTER_ID = re.compile(r"^T-\d{3}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_RESIDUE = ("__pycache__",)


# ---------------------------------------------------------------- ledger I/O

def load_ledger(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_ledger(path: Path, ledger: dict) -> None:
    path.write_text(
        json.dumps(ledger, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def seal_entry(entry: dict) -> str:
    """sha256 over canonical JSON (sorted keys, compact) minus the seal."""
    unsealed = {k: v for k, v in entry.items() if k != "seal"}
    canonical = json.dumps(unsealed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _digest_file(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def subject_digests(ledger: dict) -> set[str]:
    """The normalized digest set the subject artifact answers to."""
    artifact = ledger["subjectArtifact"]
    keys = ("imageDigest", "isoSha256", "qcow2Sha256", "ociTarSha256", "rawSha256")
    return {_normalize_digest(artifact[k]) for k in keys if artifact.get(k)}


def _normalize_digest(value: str) -> str:
    value = value.strip().lower()
    return value[7:] if value.startswith("sha256:") else value


# ---------------------------------------------------------------- key hygiene

def contains_private_key(raw: bytes) -> bool:
    """PEM/OpenSSH private key material, which must never be ingested."""
    return b"PRIVATE KEY" in raw and b"-----BEGIN" in raw


# ---------------------------------------------------------------- validation

def _missing(record: dict, fields: tuple[str, ...]) -> list[str]:
    out = []
    for field in fields:
        value = record.get(field)
        if value is None or value == "" or value == [] or value == {}:
            out.append(field)
    return out


def _record_digest(record: dict, *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            value = value.get("digest")
        if isinstance(value, str) and value.strip():
            return value
    return None


def validate_record(source: str, record: dict, subject: set[str]) -> dict:
    """Answer the six questions; resolve one stored status.

    Returns ``{"status", "statusReason", "usableIf", "binding",
    "gateEligible", "validation"}``. Precedence: REJECTED (never valid for
    this gate) > ARTIFACT_MISMATCH (binding is checked before the rest is
    trusted) > UNVERIFIABLE > INCOMPLETE > ACCEPTED.
    """
    rejected: list[str] = []
    missing: list[str] = []
    scope_notes: list[str] = []
    digests: list[str] = []
    identity = "MISSING"
    timestamp = record.get("date") or record.get("signingTimestamp") or ""

    if source == "security-review":
        missing += _missing(record, ("reviewer", "scope", "date", "disposition"))
        if "findings" not in record:
            missing.append("findings")
        identity = str(record.get("reviewer") or "MISSING")
        disposition = record.get("disposition")
        if disposition and disposition not in REVIEW_OUTCOMES:
            missing.append(
                "disposition must be one of %s" % "/".join(REVIEW_OUTCOMES)
            )
        digest = _record_digest(record, "artifact", "artifactDigest")
        if digest is None:
            missing.append("artifact digest")
        else:
            digests.append(digest)
        scope_notes.append("independent review of the subject artifact")

    elif source == "hardware":
        missing += _missing(record, ("hwId", "machine", "date", "results"))
        hw_id = record.get("hwId", "")
        identity = "%s / %s" % (record.get("operator", "MISSING"), hw_id or "MISSING")
        if hw_id and not HW_ID.match(hw_id):
            missing.append("hwId must match HW-NNN")
        machine = record.get("machine") or {}
        for field in HARDWARE_IDENTITY_FIELDS:
            if not machine.get(field):
                missing.append("machine.%s" % field)
        results = record.get("results") or {}
        for dimension, row in results.items():
            if dimension not in HARDWARE_DIMENSIONS:
                missing.append("unknown dimension %r" % dimension)
                continue
            status = row.get("status") if isinstance(row, dict) else row
            if status not in HARDWARE_STATUSES:
                missing.append("%s status must be one of %s"
                               % (dimension, "/".join(HARDWARE_STATUSES)))
            elif status == "PASS" and not (isinstance(row, dict) and row.get("evidence")):
                missing.append("%s: PASS requires an evidence reference" % dimension)
        digest = _record_digest(record, "artifactDigest")
        if digest is None:
            missing.append("artifactDigest (the ISO the machine booted)")
        else:
            digests.append(digest)
        scope_notes.append("per-dimension results; a machine PASS never "
                           "collapses into all-features PASS")

    elif source == "signing":
        category = record.get("category", "")
        if category == "SIGNING DRILL":
            rejected.append("a signing drill satisfies nothing in the "
                            "PRODUCTION ARTIFACT SIGNED category")
        missing += _missing(record, (
            "category", "signatureIdentifier", "signerIdentity",
            "signerAuthority", "signingTimestamp", "verificationResult",
            "verificationRunBy",
        ))
        if category and category not in ("SIGNING DRILL", "PRODUCTION ARTIFACT SIGNED"):
            missing.append('category must be "PRODUCTION ARTIFACT SIGNED"')
        identity = "%s (%s)" % (
            record.get("signerIdentity", "MISSING"),
            record.get("signerAuthority", "MISSING"),
        )
        digest = _record_digest(record, "artifactDigest")
        if digest is None:
            missing.append("artifactDigest")
        else:
            digests.append(digest)
        scope_notes.append("verification independent of the signing command; "
                           "the command's success message is insufficient")

    elif source == "second-approval":
        missing += _missing(record, ("scope",))
        first = record.get("firstApprover") or {}
        second = record.get("secondApprover") or {}
        for label, approver in (("firstApprover", first), ("secondApprover", second)):
            for field in ("name", "role", "date", "decision"):
                if not approver.get(field):
                    missing.append("%s.%s" % (label, field))
            if approver.get("decision") not in (None, "", "APPROVE", "REJECT"):
                missing.append("%s.decision must be APPROVE or REJECT" % label)
        if first.get("name") and first.get("name") == second.get("name"):
            rejected.append("one person approving twice is not a second approval")
        identity = "%s + %s" % (
            first.get("name", "MISSING"), second.get("name", "MISSING"),
        )
        timestamp = timestamp or first.get("date", "") or second.get("date", "")
        for label, approver in (("firstApprover", first), ("secondApprover", second)):
            digest = approver.get("recomputedDigest")
            if digest:
                digests.append(digest)
            else:
                missing.append("%s.recomputedDigest — each approver recomputes "
                               "the digest; neither inherits it" % label)
        if not digests and (record.get("commit") or record.get("branch")):
            missing.append("approval names a branch or commit but not the "
                           "artifact; approval of a branch is not approval of bytes")
        scope_notes.append("two people, independently naming the same bytes")

    elif source == "alpha-feedback":
        missing += _missing(record, ("testerId", "journey", "environment", "date"))
        if "steps" not in record:
            missing.append("steps")
        tester = record.get("testerId", "")
        identity = tester or "MISSING"
        if tester and not TESTER_ID.match(tester):
            missing.append("testerId must match T-NNN")
        if record.get("journey") not in (None, "") + ALPHA_JOURNEYS:
            missing.append("journey must be one of %s" % "/".join(ALPHA_JOURNEYS))
        for finding in record.get("findings") or []:
            if finding.get("category") not in ALPHA_CATEGORIES:
                missing.append("finding category must be one of the eleven")
            if finding.get("reproductionConfidence") not in ALPHA_CONFIDENCE:
                missing.append("finding reproductionConfidence must be one of the four")
        digest = _record_digest(record, "artifactDigest")
        if digest is not None:
            digests.append(digest)
        # No digest is not INCOMPLETE here: the report survives as
        # USER_EVIDENCE_UNBOUND per the intake governance.
        scope_notes.append("measured and user-reported evidence stay separate arrays")

    else:
        raise ValueError("unknown source %r" % source)

    # Binding.
    normalized = [_normalize_digest(d) for d in digests]
    foreign = [d for d in normalized if d not in subject]
    if not digests:
        binding = "USER_EVIDENCE_UNBOUND" if source == "alpha-feedback" else "MISSING"
    elif foreign:
        binding = "MISMATCH:%s" % ",".join(sorted(set(foreign)))
    else:
        binding = "BOUND"

    # Timestamp.
    stamp_ok = bool(timestamp) and bool(ISO_DATE.match(str(timestamp)))
    if not stamp_ok:
        missing.append("the record must date its own action (ISO 8601)")

    # Resolution.
    if rejected:
        status, reason = "REJECTED", "; ".join(rejected)
        usable = "resubmit evidence that is valid for this gate"
    elif foreign:
        status = "ARTIFACT_MISMATCH"
        reason = ("binds to %s, not the subject artifact; no transfer by "
                  "default" % ", ".join(sorted(set(foreign))))
        usable = ("establish an explicit, recorded artifact relationship, or "
                  "resubmit against the subject artifact")
    elif missing:
        status, reason = "INCOMPLETE", "missing: " + "; ".join(missing)
        usable = "supply the missing fields and resubmit as a revision"
    else:
        status, reason, usable = "ACCEPTED", "", ""

    return {
        "status": status,
        "statusReason": reason,
        "usableIf": usable,
        "binding": binding,
        "gateEligible": status == "ACCEPTED" and binding == "BOUND",
        "validation": {
            "identity": identity,
            "artifactBinding": binding,
            "timestamp": str(timestamp) if stamp_ok else "MISSING",
            "completeness": {"missing": missing},
            "integrity": "",  # filled in by register() from ingested bytes
            "scope": "; ".join(scope_notes),
        },
    }


# ---------------------------------------------------------------- register

def next_intake_id(entries: list[dict], revises: str | None) -> str:
    if revises is None:
        highest = 0
        for entry in entries:
            match = INTAKE_ID.match(entry["intakeId"])
            if match:
                highest = max(highest, int(match.group(1)))
        return "INTAKE-%03d" % (highest + 1)
    match = INTAKE_ID.match(revises)
    if not match:
        raise SystemExit("refusing: %r is not an intake ID" % revises)
    if not any(e["intakeId"] == revises for e in entries):
        raise SystemExit("refusing: %s is not in the ledger" % revises)
    root_id = "INTAKE-%s" % match.group(1)
    revision = 1 + sum(
        1 for e in entries
        if INTAKE_ID.match(e["intakeId"]) and
        INTAKE_ID.match(e["intakeId"]).group(1) == match.group(1) and
        INTAKE_ID.match(e["intakeId"]).group(2)
    )
    return "%s-R%d" % (root_id, revision)


def register(ledger_path: Path, source: str, record_path: Path,
             attachments: list[Path], received_on: str,
             submitted_by: str, revises: str | None = None) -> dict:
    """Ingest one submission; append one sealed entry; return it."""
    if source not in SOURCES:
        raise SystemExit("refusing: unknown source %r" % source)
    if not ISO_DATE.match(received_on):
        raise SystemExit("refusing: --received-on must be ISO 8601")
    ledger = load_ledger(ledger_path)
    broken = [e["intakeId"] for e in ledger["entries"] if seal_entry(e) != e["seal"]]
    if broken:
        raise SystemExit(
            "refusing to append to a tampered ledger; broken seals: %s"
            % ", ".join(broken)
        )
    intake_id = next_intake_id(ledger["entries"], revises)

    entry = {
        "intakeId": intake_id,
        "revises": revises,
        "source": source,
        "receivedOn": received_on,
        "submittedBy": submitted_by,
        "files": {},
    }

    # Key hygiene precedes ingestion: on a hit, nothing is copied.
    sources = [record_path, *attachments]
    tainted = [p.name for p in sources if contains_private_key(p.read_bytes())]
    if tainted:
        entry.update({
            "status": "REJECTED",
            "statusReason": "private key material in %s; nothing was ingested"
                            % ", ".join(sorted(tainted)),
            "usableIf": "resubmit without private key material; treat the "
                        "exposed key as compromised and record that event",
            "binding": "MISSING",
            "gateEligible": False,
            "validation": {
                "identity": "not examined", "artifactBinding": "not examined",
                "timestamp": "not examined",
                "completeness": {"missing": []},
                "integrity": "refused before ingestion",
                "scope": "key hygiene violation",
            },
        })
    else:
        intake_root = ledger_path.parent
        dest = intake_root / source / intake_id
        if dest.exists():
            raise SystemExit("refusing: %s already exists" % dest)
        dest.mkdir(parents=True)
        ingested: dict[str, Path] = {}
        for src, name in [(record_path, "record.json")] + [
            (p, p.name) for p in attachments
        ]:
            if name in ingested:
                raise SystemExit("refusing: duplicate attachment name %r" % name)
            target = dest / name
            target.write_bytes(src.read_bytes())
            ingested[name] = target
        for name, target in sorted(ingested.items()):
            size, digest = _digest_file(target)
            key = "%s%s/%s/%s" % (LEDGER_PREFIX, source, intake_id, name)
            entry["files"][key] = {"bytes": size, "sha256": digest}

        record = None
        parse_error: Exception | None = None
        try:
            record = json.loads(ingested["record.json"].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            parse_error = error
        if parse_error is not None:
            entry.update({
                "status": "UNVERIFIABLE",
                "statusReason": "record.json is not parseable JSON: %s" % parse_error,
                "usableIf": "resubmit a machine-readable record as a revision",
                "binding": "MISSING",
                "gateEligible": False,
                "validation": {
                    "identity": "unparseable", "artifactBinding": "unparseable",
                    "timestamp": "unparseable",
                    "completeness": {"missing": ["a parseable record"]},
                    "integrity": "bytes preserved verbatim",
                    "scope": "unparseable",
                },
            })
        elif isinstance(record, dict) and record.get("fixtureClass") == "TEST_FIXTURE_ONLY":
            # Synthetic dry-run material is distinguished structurally, not
            # by filename: a record declaring itself a fixture is never
            # evidence, whatever it is named or wherever it came from.
            entry.update({
                "status": "REJECTED",
                "statusReason": "the record declares fixtureClass "
                                "TEST_FIXTURE_ONLY; a fixture is never evidence",
                "usableIf": "real evidence carries no fixture marker",
                "binding": "MISSING",
                "gateEligible": False,
                "validation": {
                    "identity": "not examined", "artifactBinding": "not examined",
                    "timestamp": "not examined",
                    "completeness": {"missing": []},
                    "integrity": "bytes preserved verbatim",
                    "scope": "declared test fixture",
                },
            })
        else:
            verdict = validate_record(source, record, subject_digests(ledger))
            claimed = record.get("attachmentDigests") or {}
            mismatched = sorted(
                name for name, digest in claimed.items()
                if name in ingested
                and _digest_file(ingested[name])[1] != _normalize_digest(str(digest))
            )
            unattached = sorted(name for name in claimed if name not in ingested)
            if mismatched or unattached:
                problems = []
                if mismatched:
                    problems.append("claimed digests do not match ingested "
                                    "bytes: %s" % ", ".join(mismatched))
                if unattached:
                    problems.append("digests claimed for files not attached: %s"
                                    % ", ".join(unattached))
                verdict.update({
                    "status": "UNVERIFIABLE",
                    "statusReason": "; ".join(problems),
                    "usableIf": "resubmit with attachments matching their "
                                "claimed digests",
                    "gateEligible": False,
                })
                verdict["validation"]["integrity"] = "; ".join(problems)
            elif claimed:
                verdict["validation"]["integrity"] = (
                    "%d attachment digest(s) recomputed and matched" % len(claimed)
                )
            else:
                verdict["validation"]["integrity"] = "no attachment digests claimed"
            entry.update(verdict)

    entry["seal"] = seal_entry(entry)
    ledger["entries"].append(entry)
    dump_ledger(ledger_path, ledger)
    return entry


# ---------------------------------------------------------------- verify

def verify_intake(intake_root: Path, ledger: dict) -> dict[str, list[str]]:
    """Every seal, every pin, no orphans, well-formed IDs. Empty == clean."""
    issues: dict[str, list[str]] = {
        "sealBroken": [], "fileMissing": [], "fileChanged": [],
        "unregistered": [], "idMalformed": [], "idDuplicate": [],
        "revisionOrphan": [], "statusInvalid": [], "sourceInvalid": [],
        "pathOutsidePlace": [],
    }
    seen: dict[str, int] = {}
    pinned: set[str] = set()
    ids = {e["intakeId"] for e in ledger["entries"]}
    repo_root = intake_root.parents[2]

    for entry in ledger["entries"]:
        intake_id = entry.get("intakeId", "<missing>")
        if seal_entry(entry) != entry.get("seal"):
            issues["sealBroken"].append(intake_id)
        match = INTAKE_ID.match(intake_id)
        if not match:
            issues["idMalformed"].append(intake_id)
        seen[intake_id] = seen.get(intake_id, 0) + 1
        revises = entry.get("revises")
        if revises is not None and revises not in ids:
            issues["revisionOrphan"].append("%s revises %s" % (intake_id, revises))
        if entry.get("status") not in STATUSES or entry.get("status") == "SUPERSEDED":
            issues["statusInvalid"].append(
                "%s: %r" % (intake_id, entry.get("status")))
        if entry.get("source") not in SOURCES:
            issues["sourceInvalid"].append(
                "%s: %r" % (intake_id, entry.get("source")))
        place = "%s%s/%s/" % (LEDGER_PREFIX, entry.get("source"), intake_id)
        for name, expected in entry.get("files", {}).items():
            pinned.add(name)
            if not name.startswith(place):
                issues["pathOutsidePlace"].append(name)
            path = repo_root / name
            if not path.is_file():
                issues["fileMissing"].append(name)
                continue
            size, digest = _digest_file(path)
            if size != expected["bytes"] or digest != expected["sha256"]:
                issues["fileChanged"].append(name)

    issues["idDuplicate"] = sorted(i for i, n in seen.items() if n > 1)

    if intake_root.is_dir():
        for path in sorted(intake_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(repo_root).as_posix()
            if any(part in _RESIDUE for part in relative.split("/")):
                continue
            if path.name == "LEDGER.json" and path.parent == intake_root:
                continue
            if path.name == "README" and path.parent.parent == intake_root:
                continue
            if relative not in pinned:
                issues["unregistered"].append(relative)

    return {kind: sorted(found) for kind, found in issues.items() if found}


def effective_statuses(ledger: dict) -> dict[str, str]:
    """Stored status, except SUPERSEDED for any entry a revision points past.

    The stored records never change; supersession is a fact about the chain,
    derived here, reported by ``status``, and never written back.
    """
    superseded = {e["revises"] for e in ledger["entries"] if e.get("revises")}
    return {
        e["intakeId"]: "SUPERSEDED" if e["intakeId"] in superseded else e["status"]
        for e in ledger["entries"]
    }


# ---------------------------------------------------------------- decision

#: What AUTHORIZED minimally requires from this ledger: a gate-eligible
#: ACCEPTED intake in each of these sources. This is the mechanical floor —
#: authority itself is human and is not checkable here.
AUTHORIZATION_FLOOR_SOURCES = ("security-review", "signing", "second-approval")


def authorization_floor(decision: dict, ledger: dict) -> list[str]:
    """Violations that make an AUTHORIZED decision self-manufactured."""
    final = decision.get("final_decision")
    if final not in ("AUTHORIZED", "AUTHORIZED_WITH_LIMITATIONS"):
        return []
    effective = effective_statuses(ledger)
    violations = []
    for source in AUTHORIZATION_FLOOR_SOURCES:
        eligible = [
            e for e in ledger["entries"]
            if e["source"] == source and e.get("gateEligible")
            and effective[e["intakeId"]] == "ACCEPTED"
        ]
        if not eligible:
            violations.append(
                "%s: no gate-eligible ACCEPTED intake exists, so %r cannot "
                "have come from its owner" % (source, final)
            )
    return violations


# ---------------------------------------------------------------- CLI

def _cmd_register(args: argparse.Namespace) -> int:
    entry = register(
        LEDGER_PATH, args.source, Path(args.record),
        [Path(p) for p in args.attach], args.received_on,
        args.submitted_by, args.revises,
    )
    print("%s %s %s" % (entry["intakeId"], entry["status"],
                        entry.get("statusReason", "")))
    return 0


def _cmd_verify(_args: argparse.Namespace) -> int:
    issues = verify_intake(INTAKE_ROOT, load_ledger(LEDGER_PATH))
    if not issues:
        print("intake ledger verifies clean")
        return 0
    for kind, found in sorted(issues.items()):
        for item in found:
            print("%s: %s" % (kind, item))
    return 2


def _cmd_status(_args: argparse.Namespace) -> int:
    ledger = load_ledger(LEDGER_PATH)
    effective = effective_statuses(ledger)
    for source in SOURCES:
        entries = [e for e in ledger["entries"] if e["source"] == source]
        eligible = [
            e["intakeId"] for e in entries
            if e.get("gateEligible") and effective[e["intakeId"]] == "ACCEPTED"
        ]
        print("%-16s %d intake(s); gate-eligible: %s"
              % (source, len(entries), ", ".join(eligible) or "none"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    reg = commands.add_parser("register", help="append one submission")
    reg.add_argument("--source", required=True, choices=SOURCES)
    reg.add_argument("--record", required=True,
                     help="the machine-readable record (JSON)")
    reg.add_argument("--attach", action="append", default=[],
                     help="attachment file (repeatable)")
    reg.add_argument("--received-on", required=True,
                     help="ISO 8601 date, stated by the operator")
    reg.add_argument("--submitted-by", required=True,
                     help="claimed submitter identity, recorded verbatim")
    reg.add_argument("--revises", default=None,
                     help="intake ID this corrects (original is preserved)")
    reg.set_defaults(func=_cmd_register)

    ver = commands.add_parser("verify", help="seals, pins, orphans; exit 2 on any issue")
    ver.set_defaults(func=_cmd_verify)

    status = commands.add_parser("status", help="effective per-source summary")
    status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
