# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What happened, in enough detail to answer for it and not enough to be a leak.

§21 asks for a structured record of every security-sensitive operation: who
asked, for what, when, what the user decided, at what scope, about which
resource, and how it turned out. §21 also says *do not record unnecessary private
content*, and those two requirements pull against each other in exactly one
place — the resource. A path is user content. ``/home/x/divorce/draft.odt``
discloses something to anybody who reads the log whether or not the permission
was granted, and a log is read by support tooling, diagnostics exports and
whoever has the disk.

So a record carries the resource's **digest** and its **display string**, and
never its identifier. The digest makes "was this the same file as last time" and
"which decision authorised this" answerable; the display string is the short,
root-relative form a person already saw on their own screen. The identifier —
the canonical absolute path — stays in the grant store, which is
owner-readable-only and is not part of a diagnostic export.

Three kinds of record, deliberately distinct:

``decision``
    a permission was asked for and answered. Every decision, including the ones
    nobody was asked about: a catalogue default and a fail-closed denial are both
    things the system did on the user's behalf, and a log holding only the
    prompted ones would understate that.
``use``
    a permission that was already held got used. This is what makes the activity
    view honest — "Camera used by Video Call — 3:14 PM" is a *use*, not a
    decision, and a system that only logged decisions would show a camera
    permission granted once in March and nothing since.
``revocation``
    a permission was withdrawn, and how soon it stops mattering.

The file is append-only JSON lines, fsynced per record, opened ``O_NOFOLLOW``.
Reading refuses to skip a damaged line: an audit reader that silently dropped
what it could not parse would report a shorter history than happened, and the
missing entries would be the ones something had damaged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Mapping

from .decision import Decision
from .errors import TrustStoreUnreadable
from .persistence import PersistenceError, append_jsonl, read_jsonl
from .resources import Resource

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "RECORD_KINDS",
    "ActivityEntry",
    "TrustAudit",
    "default_audit_path",
]

AUDIT_SCHEMA_VERSION = 1

RECORD_KINDS = ("decision", "use", "revocation")

_ENVIRONMENT_ROOT = "BUNNY_TRUST_ROOT"


def default_audit_path(root: Path | None = None) -> Path:
    if root is not None:
        base = Path(root)
    elif os.environ.get(_ENVIRONMENT_ROOT):
        base = Path(os.environ[_ENVIRONMENT_ROOT])
    else:
        state_home = os.environ.get("XDG_STATE_HOME")
        base = Path(state_home) if state_home else Path.home() / ".local" / "state"
        base = base / "bunny" / "trust"
    return base / "activity.jsonl"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ActivityEntry:
    """One line of the user-facing activity view.

    ``sentence`` is built by :mod:`trust.explain` for a decision and here for a
    use, so that the activity list and the prompt speak with one voice. ``at`` is
    ISO-8601; the surface formats it for the locale, because "3:14 PM" is a
    presentation decision and does not belong in a record.
    """

    kind: str
    at: str
    application_id: str
    application_name: str
    category: str
    category_title: str
    resource_display: str
    verdict: str | None
    sentence: str

    def as_record(self) -> Mapping[str, Any]:
        return {
            "kind": self.kind,
            "at": self.at,
            "applicationId": self.application_id,
            "applicationName": self.application_name,
            "category": self.category,
            "categoryTitle": self.category_title,
            "resource": self.resource_display,
            "verdict": self.verdict,
            "sentence": self.sentence,
        }


@dataclass
class TrustAudit:
    """The append-only record, and the projection Settings shows.

    ``names`` maps application ids to display names. It is supplied by the
    caller — the catalogue holds the names — rather than looked up here, so that
    an audit write cannot fail because a catalogue entry was removed. An unknown
    id is recorded and displayed as itself, which is worse to read and better
    than losing the record.
    """

    path: Path
    names: Mapping[str, str]

    def __init__(self, path: Path | str, *, names: Mapping[str, str] | None = None) -> None:
        self.path = Path(path)
        self.names = dict(names or {})

    def _name(self, application_id: str) -> str:
        return self.names.get(application_id, application_id)

    def _append(self, record: Mapping[str, Any]) -> None:
        try:
            append_jsonl(self.path, record)
        except PersistenceError as exc:
            raise TrustStoreUnreadable(f"the activity record could not be written: {exc}") from exc

    # -- writing ---------------------------------------------------------

    def record_decision(self, decision: Decision, *, failure: str | None = None) -> None:
        """Record one settled permission decision.

        ``failure`` is carried separately from ``reasonCode`` because it is the
        *diagnostic* half — an exception name, a store path that would not open —
        and it is the field a diagnostic export redacts. The reason code alone is
        enough to render the user-facing sentence.
        """
        record = {
            "schemaVersion": AUDIT_SCHEMA_VERSION,
            "kind": "decision",
            "at": decision.decided_at,
            **{key: value for key, value in decision.as_record().items() if key != "resource"},
            "resource": dict(decision.resource.as_record()),
            "applicationName": self._name(decision.application_id),
        }
        if failure:
            record["failure"] = failure
        self._append(record)

    def record_use(
        self,
        *,
        application_id: str,
        category: str,
        resource: Resource,
        grant_id: str | None,
        task_id: str | None = None,
        at: str | None = None,
    ) -> None:
        """Record that a permission already held was actually exercised."""
        self._append(
            {
                "schemaVersion": AUDIT_SCHEMA_VERSION,
                "kind": "use",
                "at": at or _timestamp(),
                "applicationId": application_id,
                "applicationName": self._name(application_id),
                "category": category,
                "resource": dict(resource.as_record()),
                "grantId": grant_id,
                "taskId": task_id,
            }
        )

    def record_revocation(
        self,
        *,
        application_id: str,
        category: str,
        resource: Resource,
        revocation: str,
        at: str | None = None,
    ) -> None:
        self._append(
            {
                "schemaVersion": AUDIT_SCHEMA_VERSION,
                "kind": "revocation",
                "at": at or _timestamp(),
                "applicationId": application_id,
                "applicationName": self._name(application_id),
                "category": category,
                "resource": dict(resource.as_record()),
                "revocation": revocation,
            }
        )

    # -- reading ---------------------------------------------------------

    def records(self, *, limit: int | None = None) -> list[Mapping[str, Any]]:
        try:
            return [record for record in read_jsonl(self.path, limit=limit) if isinstance(record, Mapping)]
        except PersistenceError as exc:
            raise TrustStoreUnreadable(f"the activity record could not be read: {exc}") from exc

    def activity(self, *, limit: int = 50, application_id: str | None = None) -> tuple[ActivityEntry, ...]:
        """The user-facing view: newest first, one sentence each.

        Deliberately built from the records rather than kept as a second
        structure. A projection that was maintained alongside the log would be a
        second account of what happened, and the two would eventually disagree
        about whether a camera was used.
        """
        from .categories import CATEGORIES  # local import: avoids a cycle at module load
        from .explain import decision_sentence
        from .decision import Decision as _Decision

        entries: list[ActivityEntry] = []
        for record in reversed(self.records()):
            if application_id is not None and record.get("applicationId") != application_id:
                continue
            kind = record.get("kind")
            if kind not in RECORD_KINDS:
                continue
            category = str(record.get("category", ""))
            title = CATEGORIES[category].title if category in CATEGORIES else category
            name = str(record.get("applicationName") or record.get("applicationId") or "an app")
            resource = str((record.get("resource") or {}).get("display", ""))
            if kind == "decision":
                verdict = str(record.get("verdict", ""))
                try:
                    sentence = decision_sentence(
                        _Decision(
                            request_id=str(record.get("requestId", "r")),
                            application_id=str(record.get("applicationId", "app")),
                            category=category,
                            resource=Resource(
                                kind=str((record.get("resource") or {}).get("kind", "none")),
                                identifier="",
                                display=resource,
                                digest=str((record.get("resource") or {}).get("digest", "")),
                            ),
                            purpose=str(record.get("purpose", "use")),
                            verdict=verdict or "deny",
                            scope=str(record.get("scope", "once")),
                            source=str(record.get("source", "policy")),
                            reason_code=str(record.get("reasonCode", "user-denied")),
                            decided_at=str(record.get("at", "")),
                            session_id=str(record.get("sessionId", "s")),
                        ),
                        application_name=name,
                    )
                except Exception:  # noqa: BLE001 - a damaged record still gets a line
                    sentence = f"{name}: {title}"
            elif kind == "use":
                verdict = "allow"
                sentence = f"{title} used by {name}" + (f" — {resource}" if resource else "")
            else:
                verdict = None
                sentence = f"{title} withdrawn from {name}" + (f" — {resource}" if resource else "")
            entries.append(
                ActivityEntry(
                    kind=str(kind),
                    at=str(record.get("at", "")),
                    application_id=str(record.get("applicationId", "")),
                    application_name=name,
                    category=category,
                    category_title=title,
                    resource_display=resource,
                    verdict=verdict,
                    sentence=sentence,
                )
            )
            if len(entries) >= limit:
                break
        return tuple(entries)
