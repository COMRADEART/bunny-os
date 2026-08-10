# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where standing permissions live, and every way one stops standing.

The store holds :class:`~trust.decision.Grant` records and nothing else. It does
not decide; :mod:`trust.policy` reads it and decides. That split is what makes
"the policy engine cannot invent a grant" checkable by reading one file.

**A store that cannot be read denies everything.** Not "returns no grants" —
raises. An empty result and a corrupt file are different facts and only one of
them means nobody granted anything. :meth:`TrustStore.load` raises
:class:`~trust.errors.TrustStoreUnreadable` on damage, and the policy turns that
into a denial carrying ``failure="store-unreadable"``, which the surface renders
as *Bunny could not check this, so it said no* rather than as *you said no*.

**Session grants do not survive the session.** They are written to disk — a
crash of the companion must not silently escalate a session grant into nothing,
nor into an always grant — but they carry the session id they were made in, and
:meth:`TrustStore.load` drops every one whose session is not the current session.
A login that has ended cannot be reasoned about; the honest move is to forget.

**Revocation is durable before it is reported.** ``revoke`` writes and fsyncs
before returning, so a person told a permission is gone can rely on that across
a power cut. And revoking is *removal of an allow*, not the writing of a deny:
those are different user intentions ("stop letting it" versus "never let it") and
Settings offers both separately.

**Nothing here uses the wall clock to decide anything.** ``decided_at`` is an ISO
timestamp for display. Whether a grant still stands is answered by scope and
session identity, both of which are facts about the machine's current state
rather than about how much time somebody's clock thinks has passed. A machine
whose clock jumps backwards must not resurrect a grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, Sequence

from .decision import Grant
from .errors import TrustSchemaError, TrustStoreUnreadable
from .persistence import PersistenceError, atomic_write_json, read_json
from .request import PermissionRequest

__all__ = [
    "STORE_SCHEMA_VERSION",
    "TrustStore",
    "default_store_path",
    "utc_now",
]

#: Bumped when the on-disk shape changes. A store written by a newer version is
#: refused rather than guessed at, which denies rather than mis-granting.
STORE_SCHEMA_VERSION = 1

_ENVIRONMENT_ROOT = "BUNNY_TRUST_ROOT"


def utc_now() -> str:
    """An ISO-8601 UTC timestamp, for display only."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_store_path(root: Path | None = None) -> Path:
    """Where the grant database lives.

    ``$BUNNY_TRUST_ROOT`` exists so the tests, the vertical slice and a demo can
    each have their own, and is read only when no explicit root is passed. The
    installed system uses the XDG data directory of the logged-in user: permission
    grants are per-user state, not system state, and a second account on the same
    machine shares none of them.
    """
    if root is not None:
        base = Path(root)
    elif os.environ.get(_ENVIRONMENT_ROOT):
        base = Path(os.environ[_ENVIRONMENT_ROOT])
    else:
        data_home = os.environ.get("XDG_DATA_HOME")
        base = Path(data_home) if data_home else Path.home() / ".local" / "share"
        base = base / "bunny" / "trust"
    return base / "grants.json"


@dataclass
class TrustStore:
    """The set of standing grants for one user, on disk.

    Held in memory after :meth:`load` and written whole on every change. The
    document is small — a few hundred grants at most, one per application per
    category per resource — and writing it whole means there is no partial-update
    path in which a revocation lands and the grant it should have replaced does
    not.
    """

    path: Path
    session_id: str
    _grants: dict[str, Grant]
    _loaded: bool = False
    #: Grants dropped by the last load because their session has ended. Kept so
    #: that the vertical slice and the tests can assert the drop happened rather
    #: than inferring it from an absence.
    _dropped_sessions: int = 0

    def __init__(self, path: Path | str, *, session_id: str) -> None:
        self.path = Path(path)
        self.session_id = session_id
        self._grants = {}
        self._loaded = False
        self._dropped_sessions = 0

    # -- reading ---------------------------------------------------------

    def load(self) -> "TrustStore":
        """Read the store, dropping grants that belong to a finished session.

        Raises :class:`~trust.errors.TrustStoreUnreadable` when the file exists
        and is not a store this build understands. Callers must not turn that
        into an empty store.
        """
        try:
            document = read_json(self.path, default=None)
        except PersistenceError as exc:
            raise TrustStoreUnreadable(str(exc)) from exc
        self._grants = {}
        self._dropped_sessions = 0
        if document is None:
            self._loaded = True
            return self
        if not isinstance(document, Mapping):
            raise TrustStoreUnreadable(f"{self.path} does not contain a permission store")
        version = document.get("schemaVersion")
        if version != STORE_SCHEMA_VERSION:
            raise TrustStoreUnreadable(
                f"{self.path} is schema version {version!r}; this build understands {STORE_SCHEMA_VERSION}"
            )
        records = document.get("grants")
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise TrustStoreUnreadable(f"{self.path} has no grant list")
        for record in records:
            if not isinstance(record, Mapping):
                raise TrustStoreUnreadable(f"{self.path} holds a grant that is not a record")
            try:
                grant = Grant.from_record(record)
            except TrustSchemaError as exc:
                raise TrustStoreUnreadable(f"{self.path}: {exc}") from exc
            if grant.scope == "session" and grant.session_id != self.session_id:
                self._dropped_sessions += 1
                continue
            self._grants[grant.grant_id] = grant
        self._loaded = True
        return self

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise TrustStoreUnreadable("the permission store has not been loaded")

    @property
    def dropped_session_grants(self) -> int:
        """How many grants the last load discarded as belonging to a past session."""
        return self._dropped_sessions

    def __iter__(self) -> Iterator[Grant]:
        self._require_loaded()
        return iter(sorted(self._grants.values(), key=lambda grant: grant.grant_id))

    def for_application(self, application_id: str) -> tuple[Grant, ...]:
        """Every standing grant for one application, for the Settings surface."""
        self._require_loaded()
        return tuple(
            grant
            for grant in sorted(self._grants.values(), key=lambda g: (g.category, g.resource.display, g.grant_id))
            if grant.application_id == application_id
        )

    def matching(self, request: PermissionRequest) -> tuple[Grant, ...]:
        """Grants that answer ``request``, denials first.

        Denials sort first because a denial wins. An application holding both an
        old allow on a folder and a later deny on one file inside it must be
        refused that file, and ordering here is what makes the policy's
        first-match rule correct rather than merely usually correct.
        """
        self._require_loaded()
        matches = [grant for grant in self._grants.values() if grant.matches(request, session_id=self.session_id)]
        matches.sort(key=lambda grant: (grant.verdict != "deny", _specificity(grant), grant.grant_id))
        return tuple(matches)

    # -- writing ---------------------------------------------------------

    def put(self, grant: Grant) -> Grant:
        """Record a grant, replacing any it supersedes, and persist.

        A new grant *supersedes* an older one for the same application, category
        and exact resource: a person who changes their mind from "always" to
        "only while using" must not leave the wider grant behind. Superseding is
        by exact digest rather than by coverage, because removing every grant a
        new one happens to cover would silently discard decisions about other
        files.
        """
        self._require_loaded()
        superseded = [
            existing.grant_id
            for existing in self._grants.values()
            if existing.application_id == grant.application_id
            and existing.category == grant.category
            and existing.resource.digest == grant.resource.digest
            and existing.purpose == grant.purpose
        ]
        for grant_id in superseded:
            del self._grants[grant_id]
        self._grants[grant.grant_id] = grant
        self._flush()
        return grant

    def revoke(self, grant_id: str) -> bool:
        """Remove one grant. Returns whether it was there."""
        self._require_loaded()
        if grant_id not in self._grants:
            return False
        del self._grants[grant_id]
        self._flush()
        return True

    def revoke_application(self, application_id: str) -> int:
        """Remove every grant held by one application. Returns how many."""
        self._require_loaded()
        doomed = [gid for gid, grant in self._grants.items() if grant.application_id == application_id]
        for grant_id in doomed:
            del self._grants[grant_id]
        if doomed:
            self._flush()
        return len(doomed)

    def revoke_category(self, application_id: str, category: str) -> int:
        """Remove every grant one application holds in one category."""
        self._require_loaded()
        doomed = [
            gid
            for gid, grant in self._grants.items()
            if grant.application_id == application_id and grant.category == category
        ]
        for grant_id in doomed:
            del self._grants[grant_id]
        if doomed:
            self._flush()
        return len(doomed)

    def end_session(self) -> int:
        """Drop the current session's grants. Returns how many.

        Called when the session ends and when a capsule stops, because §11's
        ``session`` scope means "while you are using it" and a capsule that has
        exited is not being used.
        """
        self._require_loaded()
        doomed = [gid for gid, grant in self._grants.items() if grant.scope == "session"]
        for grant_id in doomed:
            del self._grants[grant_id]
        if doomed:
            self._flush()
        return len(doomed)

    def _flush(self) -> None:
        document = {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "writtenAt": utc_now(),
            "grants": [dict(grant.as_record()) for grant in sorted(self._grants.values(), key=lambda g: g.grant_id)],
        }
        try:
            atomic_write_json(self.path, document)
        except PersistenceError as exc:
            raise TrustStoreUnreadable(str(exc)) from exc


def _specificity(grant: Grant) -> int:
    """Lower sorts first. An exact resource beats a widening one.

    Only paths widen in a way that produces overlapping allow grants, so this is
    a two-value ranking rather than a metric: a directory grant is less specific
    than a file grant, and among two allows the more specific one is the one that
    was more deliberately given.
    """
    identifier = grant.resource.identifier
    if grant.resource.kind == "path" and (identifier.endswith("/") or identifier.endswith(os.sep)):
        return 1
    return 0
