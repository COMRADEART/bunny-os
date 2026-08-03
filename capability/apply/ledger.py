# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The resource reservation ledger.

A budget says how much may be spent. A ledger says how much has been *promised*,
which is a different and more urgent number: between deciding to start a service
and that service actually occupying memory there is a window, and two
transitions that both consult free memory during that window will both conclude
they fit. Reserving first closes the window.

The invariant this module exists to hold is one line:

    committed + reserved <= capacity - protected reserve

It is checked after every mutation rather than before every read, because a
ledger that can be temporarily wrong is a ledger whose readers must all remember
to re-check, and one of them eventually will not.

**Reservations are two-phase.** ``reserve`` takes memory out of the available
pool without claiming the service is running; ``commit`` records that the
service actually started; ``release`` gives it back. A start that fails halfway
therefore returns exactly what it took, and a crash between the two phases
leaves a reservation that is visibly uncommitted rather than a leak that looks
like a running service.

**Expiry is the backstop for the process that never comes back.** Every
reservation carries a deadline. A reservation past its deadline that was never
committed is an orphan by definition — nothing that started successfully would
have left one — and it is reclaimed with the reason recorded.

Durability is a single JSON file written atomically. §18 requires this to work
on very constrained nodes, and a resident database on a 64 MB board would cost
more than the thing it is accounting for. The file is small, bounded by the
number of services, and written only when the ledger changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Mapping

from . import RUNTIME_STATE_SCHEMA_VERSION

__all__ = [
    "DEFAULT_RESERVATION_TTL_SECONDS",
    "InMemoryLedger",
    "JsonFileLedger",
    "LedgerError",
    "LedgerInvariantError",
    "RESERVATION_STATES",
    "RESOURCE_TYPES",
    "Reservation",
]

#: Resource types the ledger accounts for. Memory is the one that can be
#: exhausted irrecoverably, so it is the one with a hard invariant; CPU share is
#: tracked for reporting because a machine that has promised 400% of its cores
#: is worth being able to say so about, but oversubscribing CPU degrades rather
#: than kills and is therefore not refused here.
RESOURCE_TYPES = ("memory_bytes", "cpu_percent")

RESERVATION_STATES = ("reserved", "committed", "released", "expired")

#: How long a reservation may stand uncommitted. Longer than any startup
#: timeout, so a slow start is never reclaimed out from under itself.
DEFAULT_RESERVATION_TTL_SECONDS = 120.0


class LedgerError(RuntimeError):
    """A reservation that cannot be granted or a release that makes no sense."""


class LedgerInvariantError(LedgerError):
    """The ledger's own arithmetic no longer holds. Always a bug in this file."""


@dataclass(frozen=True)
class Reservation:
    """One promise of resources to one transition."""

    reservation_id: str
    plan_id: str
    transition_id: str
    service_id: str
    resource_type: str
    reserved_amount: int
    committed_amount: int = 0
    released_amount: int = 0
    state: str = "reserved"
    created_at_monotonic: float = 0.0
    expires_at_monotonic: float = 0.0
    #: Who holds it. ``applicator`` for normal work; recovery marks reclaimed
    #: entries so an audit can tell a reclaim from an ordinary release.
    owner: str = "applicator"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in RESERVATION_STATES:
            raise ValueError(f"unknown reservation state: {self.state!r}")
        if self.resource_type not in RESOURCE_TYPES:
            raise ValueError(f"unknown resource type: {self.resource_type!r}")
        if self.reserved_amount < 0:
            raise ValueError("a reservation cannot be for a negative amount")

    @property
    def outstanding(self) -> int:
        """What this reservation currently holds against the pool.

        A committed reservation still holds its committed amount — the service
        is running and using it. A released one holds nothing.
        """
        if self.state == "reserved":
            return self.reserved_amount
        if self.state == "committed":
            return self.committed_amount
        return 0

    def expired(self, now: float) -> bool:
        return self.state == "reserved" and self.expires_at_monotonic > 0 and now > self.expires_at_monotonic

    def to_json(self) -> dict[str, Any]:
        return {
            "reservationId": self.reservation_id,
            "planId": self.plan_id,
            "transitionId": self.transition_id,
            "serviceId": self.service_id,
            "resourceType": self.resource_type,
            "reservedAmount": self.reserved_amount,
            "committedAmount": self.committed_amount,
            "releasedAmount": self.released_amount,
            "outstanding": self.outstanding,
            "state": self.state,
            "createdAtMonotonic": self.created_at_monotonic,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "owner": self.owner,
            "detail": self.detail,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "Reservation":
        """Parse a persisted reservation. Untrusted structured input.

        A ledger file is on disk and can be edited, truncated or corrupted. Every
        field is checked, because a reservation with a negative amount would make
        the invariant pass while the pool was overdrawn.
        """
        if not isinstance(document, Mapping):
            raise LedgerError("a reservation must be an object")

        def integer(key: str, default: int = 0) -> int:
            value = document.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LedgerError(f"reservation field {key!r} must be a non-negative integer")
            return value

        def text(key: str) -> str:
            value = document.get(key)
            if not isinstance(value, str) or not value:
                raise LedgerError(f"reservation field {key!r} must be a non-empty string")
            return value

        def number(key: str) -> float:
            value = document.get(key, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LedgerError(f"reservation field {key!r} must be a number")
            return float(value)

        state = document.get("state", "reserved")
        if state not in RESERVATION_STATES:
            raise LedgerError(f"unknown reservation state {state!r}")
        resource = document.get("resourceType")
        if resource not in RESOURCE_TYPES:
            raise LedgerError(f"unknown resource type {resource!r}")

        return cls(
            reservation_id=text("reservationId"),
            plan_id=str(document.get("planId", "")),
            transition_id=str(document.get("transitionId", "")),
            service_id=text("serviceId"),
            resource_type=str(resource),
            reserved_amount=integer("reservedAmount"),
            committed_amount=integer("committedAmount"),
            released_amount=integer("releasedAmount"),
            state=str(state),
            created_at_monotonic=number("createdAtMonotonic"),
            expires_at_monotonic=number("expiresAtMonotonic"),
            owner=str(document.get("owner", "applicator")),
            detail=str(document.get("detail", "")),
        )


@dataclass
class InMemoryLedger:
    """A concurrency-safe reservation ledger held in memory.

    The lock is a plain :class:`threading.Lock` and it is held across the whole
    check-and-take in :meth:`reserve`. That is the entire point of this class:
    two threads asking "does 200 MiB fit" against the same 300 MiB must not both
    be told yes. A finer-grained scheme would be faster and would reintroduce
    exactly the race the ledger exists to close.
    """

    #: Total memory the applicator may promise, protected reserve already
    #: removed. Taken from the budget, never computed here — the ledger does not
    #: get a second opinion about what the reserve is.
    capacity_bytes: int = 0
    #: Recorded so the ledger can *report* the reserve it is protecting. It is
    #: not subtracted again; ``capacity_bytes`` already excludes it.
    protected_reserve_bytes: int = 0
    reservations: dict[str, Reservation] = field(default_factory=dict)
    default_ttl_seconds: float = DEFAULT_RESERVATION_TTL_SECONDS
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _counter: int = 0

    # ------------------------------------------------------------------ #
    # Accounting
    # ------------------------------------------------------------------ #

    def outstanding_bytes(self) -> int:
        return sum(
            item.outstanding for item in self.reservations.values()
            if item.resource_type == "memory_bytes"
        )

    def available_bytes(self) -> int:
        return max(0, self.capacity_bytes - self.outstanding_bytes())

    def committed_bytes(self) -> int:
        return sum(
            item.committed_amount for item in self.reservations.values()
            if item.resource_type == "memory_bytes" and item.state == "committed"
        )

    def _check_invariants(self) -> None:
        """Assert the ledger's arithmetic. Called after every mutation.

        Three things must hold, and each has a failure mode worth naming:
        the pool must not be overdrawn (an overdrawn ledger is one that has
        promised memory the machine does not have); no reservation may hold a
        negative amount (which would mask an overdraw); and a committed
        reservation may not have committed more than it reserved (which would
        let a service quietly grow past the plan's grant, breaking the decision
        boundary in the one place nobody would look for it).
        """
        outstanding = self.outstanding_bytes()
        if outstanding > self.capacity_bytes:
            raise LedgerInvariantError(
                f"ledger holds {outstanding} bytes against a {self.capacity_bytes} byte capacity; "
                "a reservation was granted that should have been refused"
            )
        for item in self.reservations.values():
            if item.outstanding < 0:
                raise LedgerInvariantError(f"reservation {item.reservation_id} holds a negative amount")
            if item.committed_amount > item.reserved_amount:
                raise LedgerInvariantError(
                    f"reservation {item.reservation_id} committed {item.committed_amount} bytes "
                    f"against {item.reserved_amount} reserved; a commit may never exceed its reservation"
                )

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def reserve(
        self,
        *,
        service_id: str,
        amount_bytes: int,
        plan_id: str = "",
        transition_id: str = "",
        now: float = 0.0,
        ttl_seconds: float | None = None,
        owner: str = "applicator",
    ) -> Reservation:
        """Take ``amount_bytes`` out of the pool, or refuse.

        Atomic: the availability check and the take happen under one lock, so a
        concurrent caller sees either the state before or the state after, never
        the state in between.
        """
        if amount_bytes < 0:
            raise LedgerError("cannot reserve a negative amount")
        with self._lock:
            self._expire_locked(now)
            available = self.available_bytes()
            if amount_bytes > available:
                raise LedgerError(
                    f"{service_id} requested {amount_bytes} bytes and {available} bytes remain "
                    f"of a {self.capacity_bytes} byte pool (protected reserve "
                    f"{self.protected_reserve_bytes} bytes is already excluded)"
                )
            self._counter += 1
            # Identity is derived from the transition where there is one, so a
            # recovering process reconstructs the same id rather than minting a
            # second reservation for work already in flight.
            identifier = (
                f"res-{transition_id}" if transition_id
                else f"res-{service_id}-{self._counter}"
            )
            ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
            entry = Reservation(
                reservation_id=identifier,
                plan_id=plan_id,
                transition_id=transition_id,
                service_id=service_id,
                resource_type="memory_bytes",
                reserved_amount=amount_bytes,
                created_at_monotonic=now,
                expires_at_monotonic=(now + ttl) if ttl > 0 else 0.0,
                owner=owner,
            )
            self.reservations[identifier] = entry
            self._check_invariants()
            self._persist()
            return entry

    def commit(self, reservation_id: str, *, amount_bytes: int | None = None) -> Reservation:
        """Record that the service actually started and is using the memory.

        ``amount_bytes`` may be *less* than reserved — a service that started
        smaller than expected returns the difference — but never more. Growing a
        commitment past its reservation would let a service exceed the plan's
        grant, which is the applicator overriding the engine, and it raises.
        """
        with self._lock:
            entry = self.reservations.get(reservation_id)
            if entry is None:
                raise LedgerError(f"no reservation {reservation_id!r} to commit")
            if entry.state == "committed":
                return entry
            if entry.state != "reserved":
                raise LedgerError(f"reservation {reservation_id!r} is {entry.state} and cannot be committed")
            committed = entry.reserved_amount if amount_bytes is None else amount_bytes
            if committed > entry.reserved_amount:
                raise LedgerError(
                    f"cannot commit {committed} bytes against a {entry.reserved_amount} byte reservation; "
                    "the applicator may never grant more than the plan reserved"
                )
            updated = replace(entry, state="committed", committed_amount=max(0, committed))
            self.reservations[reservation_id] = updated
            self._check_invariants()
            self._persist()
            return updated

    def release(self, reservation_id: str, *, detail: str = "") -> Reservation | None:
        """Give the resources back. Idempotent.

        Releasing an already-released reservation returns it unchanged rather
        than raising, and releasing one that does not exist returns ``None``.
        Both are deliberate: release is called from failure paths and from
        rollback, and a cleanup path that can itself fail is a cleanup path that
        leaks.
        """
        with self._lock:
            entry = self.reservations.get(reservation_id)
            if entry is None:
                return None
            if entry.state in ("released", "expired"):
                return entry
            updated = replace(
                entry,
                state="released",
                released_amount=entry.outstanding,
                detail=detail or entry.detail,
            )
            self.reservations[reservation_id] = updated
            self._check_invariants()
            self._persist()
            return updated

    def release_for_service(self, service_id: str, *, detail: str = "") -> tuple[Reservation, ...]:
        """Release everything held for one service."""
        identifiers = [
            key for key, item in self.reservations.items()
            if item.service_id == service_id and item.state in ("reserved", "committed")
        ]
        return tuple(
            result for key in sorted(identifiers)
            if (result := self.release(key, detail=detail)) is not None
        )

    # ------------------------------------------------------------------ #
    # Recovery
    # ------------------------------------------------------------------ #

    def expire(self, now: float) -> tuple[Reservation, ...]:
        """Reclaim reservations that were never committed inside their deadline."""
        with self._lock:
            expired = self._expire_locked(now)
            if expired:
                self._persist()
            return expired

    def _expire_locked(self, now: float) -> tuple[Reservation, ...]:
        expired: list[Reservation] = []
        for key in sorted(self.reservations):
            entry = self.reservations[key]
            if entry.expired(now):
                updated = replace(
                    entry, state="expired", released_amount=entry.reserved_amount,
                    detail="uncommitted past its deadline; the transition that took it never finished",
                )
                self.reservations[key] = updated
                expired.append(updated)
        if expired:
            self._check_invariants()
        return tuple(expired)

    def orphans(self, active_service_ids: Iterable[str]) -> tuple[Reservation, ...]:
        """Committed reservations for services that are not actually running.

        This is the reconciliation the ledger cannot do for itself. It holds
        promises; only the backend can say whether they were kept. A committed
        reservation for a service the machine says is stopped is memory the
        applicator believes is in use and nothing is using — the classic leak
        after an unclean shutdown.
        """
        active = set(active_service_ids)
        return tuple(
            self.reservations[key] for key in sorted(self.reservations)
            if self.reservations[key].state == "committed"
            and self.reservations[key].service_id not in active
        )

    def reconcile_with_actual(self, active_service_ids: Iterable[str]) -> tuple[Reservation, ...]:
        """Release every orphan and report what was reclaimed."""
        reclaimed: list[Reservation] = []
        for orphan in self.orphans(active_service_ids):
            result = self.release(
                orphan.reservation_id,
                detail="reclaimed: the service holding this reservation is not running",
            )
            if result is not None:
                reclaimed.append(replace(result, owner="recovery"))
                self.reservations[result.reservation_id] = reclaimed[-1]
        return tuple(reclaimed)

    def for_service(self, service_id: str) -> tuple[Reservation, ...]:
        return tuple(
            self.reservations[key] for key in sorted(self.reservations)
            if self.reservations[key].service_id == service_id
        )

    def active(self) -> tuple[Reservation, ...]:
        return tuple(
            self.reservations[key] for key in sorted(self.reservations)
            if self.reservations[key].state in ("reserved", "committed")
        )

    def _persist(self) -> None:
        """Hook for durable subclasses. In memory, nothing to do."""

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": RUNTIME_STATE_SCHEMA_VERSION,
            "capacityBytes": self.capacity_bytes,
            "protectedReserveBytes": self.protected_reserve_bytes,
            "outstandingBytes": self.outstanding_bytes(),
            "committedBytes": self.committed_bytes(),
            "availableBytes": self.available_bytes(),
            "reservations": [self.reservations[key].to_json() for key in sorted(self.reservations)],
        }


@dataclass
class JsonFileLedger(InMemoryLedger):
    """An :class:`InMemoryLedger` that survives the process.

    One JSON file, written atomically through a temporary file and a rename, so
    a crash mid-write leaves the previous ledger rather than a truncated one.
    No database: §18 requires this to be usable on a node where a resident
    database would cost more memory than the services it accounts for.

    The file is a **cache of promises, not a source of truth about the machine.**
    On load, every committed reservation is provisional until
    :meth:`reconcile_with_actual` has compared it against what the backend can
    actually see. A ledger that trusted its own file would, after an unclean
    shutdown, believe a machine full of services that are not running.
    """

    path: Path | None = None

    def load(self) -> tuple[str, ...]:
        """Read the persisted ledger. Returns warnings, never raises on damage.

        A corrupt ledger must not prevent the applicator from starting: the
        recovery path is to discard what cannot be parsed and reconcile against
        the machine, which is strictly better than refusing to run because a
        bookkeeping file is unreadable.
        """
        warnings: list[str] = []
        if self.path is None or not self.path.is_file():
            return ()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return (f"{self.path} could not be read ({exc}); starting from an empty ledger",)
        entries = document.get("reservations") if isinstance(document, Mapping) else None
        if not isinstance(entries, list):
            return (f"{self.path} has no reservations array; starting from an empty ledger",)
        recovered: dict[str, Reservation] = {}
        for raw in entries:
            try:
                entry = Reservation.from_json(raw)
            except LedgerError as exc:
                warnings.append(f"discarded an unreadable reservation: {exc}")
                continue
            if entry.state in ("reserved", "committed"):
                recovered[entry.reservation_id] = entry
        self.reservations = recovered
        try:
            self._check_invariants()
        except LedgerInvariantError as exc:
            # A persisted ledger that violates the invariant is not one to
            # repair by guessing which entry is wrong. Discard and reconcile.
            self.reservations = {}
            warnings.append(f"{self.path} violated the ledger invariant ({exc}); starting from an empty ledger")
        return tuple(warnings)

    def _persist(self) -> None:
        if self.path is None:
            return
        payload = json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n"
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            # A ledger that cannot be persisted is still a correct ledger for
            # this process. Losing durability is a degradation to report, not a
            # reason to fail the transition that was being accounted for; the
            # recovery path reconciles against the machine regardless.
            try:
                temporary.unlink()
            except OSError:
                pass
