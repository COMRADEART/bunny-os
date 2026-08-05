# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Failure classification, retry policy and circuit breaking.

The single most useful thing a supervisor can do is tell apart the failures
worth trying again from the ones that will fail identically forever. A start
that timed out because the disk was busy deserves another attempt; a start that
failed because the unit does not exist will fail the same way a thousand times,
and a supervisor that keeps trying turns a missing file into a busy loop that
also drains a battery.

So every failure here carries a class, every class states whether it is
retryable, and the retry policy reads the class rather than the message. That
ordering matters: a policy that parsed error text would silently start retrying
permanent failures the day somebody rewrote a diagnostic string.

**Backoff is deterministic.** Exponential with jitter, but the jitter is derived
from a hash of the transition identity rather than from a random source. Two
services that fail in the same second still get different delays — which is the
only property jitter exists to provide — while a test can assert the exact
sequence of delays, and a restart of the applicator process recomputes the same
schedule rather than starting the backoff over from zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from typing import Any, Mapping

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerState",
    "FAILURE_CLASSES",
    "FailureClass",
    "RETRYABLE",
    "RetryJournal",
    "RetryPolicy",
    "RetryRecord",
    "classify_exception",
    "is_retryable",
]


@dataclass(frozen=True)
class FailureClass:
    """One way a transition can fail, and what may be done about it."""

    name: str
    retryable: bool
    #: Whether this failure means the plan itself is wrong, rather than the act.
    #: These trigger a reevaluation request instead of a retry: trying the same
    #: transition again against a plan that no longer fits would fail again for
    #: the same reason.
    needs_reevaluation: bool
    description: str


#: The complete taxonomy. Anything not in here is ``unexpected_internal_error``,
#: which is retried once and then reported — an unclassified failure is a bug in
#: this table, and treating it as permanently fatal would hide the bug while
#: treating it as freely retryable would spin on it.
FAILURE_CLASSES: Mapping[str, FailureClass] = {
    item.name: item for item in (
        FailureClass("invalid_plan", False, True,
                     "the plan is malformed or declares a schema this applicator cannot apply"),
        FailureClass("stale_plan", False, True,
                     "the plan was decided against a machine that has since changed"),
        FailureClass("superseded_plan", False, False,
                     "a newer plan is in force; this one will never be applied"),
        FailureClass("insufficient_resources", False, True,
                     "the budget cannot fund this transition now; the engine must decide again"),
        FailureClass("protected_reserve_violation", False, True,
                     "applying this would draw memory from the reserve, which nothing may do"),
        FailureClass("dependency_unavailable", True, False,
                     "a required service is not up yet; it may come up on its own"),
        FailureClass("permission_denied", False, False,
                     "the applicator is not authorised to operate this unit"),
        FailureClass("unit_not_authorized", False, False,
                     "the unit name is not one Bunny OS is permitted to control"),
        FailureClass("backend_unavailable", True, False,
                     "the service manager could not be reached; it may return"),
        FailureClass("startup_timeout", True, False,
                     "the service did not reach a running state inside its deadline"),
        FailureClass("shutdown_timeout", True, False,
                     "the service did not stop inside its deadline"),
        FailureClass("health_check_failure", True, False,
                     "the service started but did not report itself healthy"),
        FailureClass("configuration_error", False, False,
                     "the service refused its own configuration; retrying changes nothing"),
        FailureClass("remote_provider_failure", True, False,
                     "the remote provider rejected or dropped the work"),
        FailureClass("network_unavailable", True, False,
                     "there is no route to the provider"),
        FailureClass("approval_missing", False, False,
                     "a person has not approved this action; waiting is correct, retrying is not"),
        FailureClass("permanent_incompatibility", False, False,
                     "this machine cannot ever run this implementation"),
        FailureClass("cgroup_unavailable", False, False,
                     "resource limits could not be enforced; the service was not started unconstrained"),
        FailureClass("unexpected_internal_error", True, False,
                     "an unclassified error; retried once so a transient bug does not strand a service"),
    )
}

RETRYABLE = frozenset(name for name, item in FAILURE_CLASSES.items() if item.retryable)

#: Failures whose right response is a fresh decision rather than another attempt.
NEEDS_REEVALUATION = frozenset(name for name, item in FAILURE_CLASSES.items() if item.needs_reevaluation)


def is_retryable(failure_class: str | None) -> bool:
    if failure_class is None:
        return False
    entry = FAILURE_CLASSES.get(failure_class)
    return entry.retryable if entry is not None else False


def needs_reevaluation(failure_class: str | None) -> bool:
    if failure_class is None:
        return False
    entry = FAILURE_CLASSES.get(failure_class)
    return entry.needs_reevaluation if entry is not None else False


def classify_exception(error: BaseException) -> str:
    """Map a Python exception to a failure class.

    Only the exception *type* is consulted. Matching on message text would make
    the classification depend on a string that no test pins and that any
    dependency may reword.
    """
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, TimeoutError):
        return "startup_timeout"
    if isinstance(error, FileNotFoundError):
        return "backend_unavailable"
    if isinstance(error, (ConnectionError, OSError)):
        return "backend_unavailable"
    return "unexpected_internal_error"


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #


def _jitter_fraction(seed: str) -> float:
    """A stable pseudo-random number in [0, 1) derived from ``seed``.

    Deterministic on purpose. The property jitter provides is that two services
    failing simultaneously do not retry simultaneously, and a hash of the
    transition identity provides that just as well as a random source while
    remaining reproducible across processes and assertable in a test.
    """
    raw = hashlib.sha256(seed.encode("utf-8")).digest()[:4]
    return int.from_bytes(raw, "big") / float(1 << 32)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff with deterministic jitter."""

    maximum_attempts: int = 3
    initial_delay_seconds: float = 2.0
    multiplier: float = 3.0
    maximum_delay_seconds: float = 120.0
    #: Fraction of the computed delay that jitter may add. 0 disables it.
    jitter_fraction: float = 0.25

    def should_retry(self, failure_class: str | None, attempt: int) -> bool:
        """Whether attempt ``attempt`` (1-based) may be followed by another."""
        if not is_retryable(failure_class):
            return False
        return attempt < self.maximum_attempts

    def delay_seconds(self, attempt: int, *, seed: str = "") -> float:
        """How long to wait before attempt ``attempt + 1``.

        Capped before jitter is added, so the cap is a real ceiling rather than
        a value the jitter can push past.
        """
        if attempt < 1:
            attempt = 1
        base = min(
            self.maximum_delay_seconds,
            self.initial_delay_seconds * (self.multiplier ** (attempt - 1)),
        )
        if self.jitter_fraction <= 0:
            return base
        return base + base * self.jitter_fraction * _jitter_fraction(f"{seed}:{attempt}")

    def to_json(self) -> dict[str, Any]:
        return {
            "maximumAttempts": self.maximum_attempts,
            "initialDelaySeconds": self.initial_delay_seconds,
            "multiplier": self.multiplier,
            "maximumDelaySeconds": self.maximum_delay_seconds,
            "jitterFraction": self.jitter_fraction,
        }


@dataclass(frozen=True)
class RetryRecord:
    """What has already been tried for one service, and when the next try is due."""

    service_id: str
    attempt: int = 0
    last_failure_class: str | None = None
    last_failure_at_monotonic: float = 0.0
    next_attempt_at_monotonic: float = 0.0
    exhausted: bool = False

    def due(self, now: float) -> bool:
        return not self.exhausted and now >= self.next_attempt_at_monotonic

    def to_json(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "attempt": self.attempt,
            "lastFailureClass": self.last_failure_class,
            "lastFailureAtMonotonic": self.last_failure_at_monotonic,
            "nextAttemptAtMonotonic": self.next_attempt_at_monotonic,
            "exhausted": self.exhausted,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "RetryRecord":
        if not isinstance(document, Mapping):
            raise ValueError("a retry record must be an object")
        service_id = document.get("serviceId")
        if not isinstance(service_id, str) or not service_id:
            raise ValueError("a retry record needs a serviceId")
        attempt = document.get("attempt", 0)
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
            raise ValueError("a retry record's attempt must be a non-negative integer")

        def number(key: str) -> float:
            value = document.get(key, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"retry record field {key!r} must be a number")
            return float(value)

        failure = document.get("lastFailureClass")
        return cls(
            service_id=service_id,
            attempt=attempt,
            last_failure_class=failure if isinstance(failure, str) else None,
            last_failure_at_monotonic=number("lastFailureAtMonotonic"),
            next_attempt_at_monotonic=number("nextAttemptAtMonotonic"),
            exhausted=bool(document.get("exhausted", False)),
        )


@dataclass
class RetryJournal:
    """Retry state that survives the applicator process.

    §11 requires that restarting the applicator must not restart the retries.
    Without this, a service that fails at boot is retried three times, the
    supervisor restarts the applicator, and the count begins again — which is a
    restart loop assembled out of two components that each believed they were
    bounded.

    Times are monotonic, so a journal restored after a reboot has deadlines in
    the past and every service is immediately due. That is the correct behaviour:
    a reboot genuinely is a fresh chance for a service to start, and the attempt
    count is what stops it looping. Carrying a wall-clock deadline across a
    reboot would instead leave a service refusing to start for a window that no
    longer means anything.
    """

    policy: RetryPolicy = field(default_factory=RetryPolicy)
    records: dict[str, RetryRecord] = field(default_factory=dict)
    path: Any = None

    def record_of(self, service_id: str) -> RetryRecord:
        return self.records.get(service_id, RetryRecord(service_id))

    def not_before(self) -> dict[str, float]:
        """The map reconciliation consults to hold a service inside its backoff."""
        return {
            key: item.next_attempt_at_monotonic
            for key, item in self.records.items()
            if not item.exhausted and item.next_attempt_at_monotonic > 0
        }

    def exhausted_services(self) -> tuple[str, ...]:
        return tuple(sorted(key for key, item in self.records.items() if item.exhausted))

    def record_failure(self, service_id: str, failure_class: str | None, now: float) -> RetryRecord:
        """Note a failure and compute when, if ever, to try again."""
        previous = self.record_of(service_id)
        attempt = previous.attempt + 1
        retryable = self.policy.should_retry(failure_class, attempt)
        delay = self.policy.delay_seconds(attempt, seed=service_id) if retryable else 0.0
        updated = RetryRecord(
            service_id=service_id,
            attempt=attempt,
            last_failure_class=failure_class,
            last_failure_at_monotonic=now,
            next_attempt_at_monotonic=now + delay if retryable else 0.0,
            exhausted=not retryable,
        )
        self.records[service_id] = updated
        self._persist()
        return updated

    def record_success(self, service_id: str) -> None:
        if self.records.pop(service_id, None) is not None:
            self._persist()

    def load(self) -> tuple[str, ...]:
        """Restore the journal. Damage is discarded, never repaired by guessing."""
        if self.path is None or not self.path.is_file():
            return ()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return (f"{self.path} could not be read ({exc}); retry history starts empty",)
        entries = document.get("records") if isinstance(document, Mapping) else None
        if not isinstance(entries, list):
            return (f"{self.path} has no records array; retry history starts empty",)
        warnings: list[str] = []
        restored: dict[str, RetryRecord] = {}
        for raw in entries:
            try:
                entry = RetryRecord.from_json(raw)
            except ValueError as exc:
                warnings.append(f"discarded an unreadable retry record: {exc}")
                continue
            restored[entry.service_id] = entry
        self.records = restored
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
            try:
                temporary.unlink()
            except OSError:
                pass

    def to_json(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_json(),
            "records": [self.records[key].to_json() for key in sorted(self.records)],
        }


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #

#: How long an open circuit stays open before one probe is allowed through.
DEFAULT_RECOVERY_SECONDS = 300.0


@dataclass(frozen=True)
class CircuitBreakerState:
    """One service's failure history, as far as the breaker is concerned."""

    service_id: str
    consecutive_failures: int = 0
    state: str = "closed"            # "closed" | "open" | "half_open"
    opened_at_monotonic: float | None = None
    last_failure_class: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "state": self.state,
            "consecutiveFailures": self.consecutive_failures,
            "openedAtMonotonic": self.opened_at_monotonic,
            "lastFailureClass": self.last_failure_class,
        }


@dataclass
class CircuitBreaker:
    """Stops the applicator from retrying a service that keeps failing.

    Essential services are **never** broken. A breaker exists to stop wasted
    work on something optional; opening one on the control plane would mean the
    machine stops trying to bring up the service that reports why it cannot,
    which converts a recoverable fault into a silent one. Essential-service
    failures are recorded, reported and reevaluated instead.
    """

    threshold: int = 3
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS
    states: dict[str, CircuitBreakerState] = field(default_factory=dict)
    #: Service ids exempt from breaking, normally every essential service.
    protected: frozenset[str] = frozenset()

    def state_of(self, service_id: str) -> CircuitBreakerState:
        return self.states.get(service_id, CircuitBreakerState(service_id))

    def allows(self, service_id: str, now: float) -> bool:
        """Whether a transition for this service may be attempted now."""
        if service_id in self.protected:
            return True
        entry = self.state_of(service_id)
        if entry.state == "closed":
            return True
        if entry.state == "half_open":
            return True
        elapsed = now - (entry.opened_at_monotonic or 0.0)
        if elapsed >= self.recovery_seconds:
            # One probe is let through. It is recorded as half-open so that a
            # second failure re-opens immediately rather than spending another
            # full recovery window discovering the same thing.
            self.states[service_id] = replace(entry, state="half_open")
            return True
        return False

    def record_success(self, service_id: str) -> None:
        self.states.pop(service_id, None)

    def record_failure(self, service_id: str, failure_class: str | None, now: float) -> CircuitBreakerState:
        entry = self.state_of(service_id)
        failures = entry.consecutive_failures + 1
        if service_id in self.protected:
            updated = replace(
                entry, consecutive_failures=failures, state="closed",
                last_failure_class=failure_class,
            )
        elif entry.state == "half_open" or failures >= self.threshold:
            updated = replace(
                entry, consecutive_failures=failures, state="open",
                opened_at_monotonic=now, last_failure_class=failure_class,
            )
        else:
            updated = replace(
                entry, consecutive_failures=failures, state="closed",
                last_failure_class=failure_class,
            )
        self.states[service_id] = updated
        return updated

    def open_services(self) -> tuple[str, ...]:
        return tuple(sorted(key for key, item in self.states.items() if item.state == "open"))

    def to_json(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "recoverySeconds": self.recovery_seconds,
            "protected": sorted(self.protected),
            "services": [self.states[key].to_json() for key in sorted(self.states)],
        }
