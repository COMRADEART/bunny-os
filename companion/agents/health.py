# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider health: counted failures, a three-state circuit, and no tight loops.

§17's list of things to monitor is :data:`FAILURE_KINDS`, and every failure an
adapter reports is one of them — a failure that cannot be named cannot be
counted, and a failure that is not counted keeps a paid provider being
retried. The circuit is the standard three states with two deliberate
asymmetries:

* **Authentication failures do not close on a timer.** A wrong key at 09:00
  is a wrong key at 09:05, and a breaker that half-opens every thirty seconds
  turns one misconfiguration into a login-attempt pattern the provider's own
  abuse systems will notice. An ``authentication`` failure opens the circuit
  for :data:`AUTH_OPEN_SECONDS` and marks it ``requires_intervention``; the
  honest fix is a configuration change, and the status surface says so.

* **Rate limiting opens wide immediately.** One 429 is the provider saying
  "stop"; counting to the threshold first would be continuing after being
  told to stop. The open window honours the provider's retry hint where one
  was given, bounded by :data:`MAX_RETRY_HINT_SECONDS` so a hostile header
  cannot park a provider for a week.

Half-open admits exactly one probe. Its success closes the circuit; its
failure re-opens the full window. Everything is driven by the caller's
monotonic clock — this module never reads time itself, for the same reason
nothing in this runtime does.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .errors import AgentSchemaError

__all__ = [
    "AUTH_OPEN_SECONDS",
    "CIRCUIT_STATES",
    "CircuitBreaker",
    "FAILURE_KINDS",
    "FAILURE_THRESHOLD",
    "MAX_RETRY_HINT_SECONDS",
    "OPEN_SECONDS",
    "ProviderHealthMonitor",
]

FAILURE_KINDS = (
    "connection",
    "authentication",
    "rate-limit",
    "timeout",
    "invalid-response",
    "malformed-output",
    "cancellation-failure",
    "context-limit",
    "model-unavailable",
)

CIRCUIT_STATES = ("closed", "open", "half-open")

FAILURE_THRESHOLD = 3
OPEN_SECONDS = 30.0
AUTH_OPEN_SECONDS = 900.0
MAX_RETRY_HINT_SECONDS = 300.0


@dataclass
class CircuitBreaker:
    """One provider's circuit. Not shared; the monitor holds one per provider."""

    failure_threshold: int = FAILURE_THRESHOLD
    open_seconds: float = OPEN_SECONDS
    auth_open_seconds: float = AUTH_OPEN_SECONDS

    def __post_init__(self) -> None:
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._open_until = 0.0
        self._probe_outstanding = False
        self._requires_intervention = False
        self._last_kind = ""

    @property
    def state(self) -> str:
        return self._state

    @property
    def requires_intervention(self) -> bool:
        return self._requires_intervention

    def allows(self, monotonic: float) -> tuple[bool, str]:
        """Whether a generation may be attempted now, with the reason when not."""
        if self._state == "closed":
            return True, ""
        if self._state == "open":
            if monotonic >= self._open_until:
                self._state = "half-open"
                self._probe_outstanding = False
            else:
                remaining = self._open_until - monotonic
                why = (
                    f"circuit open after {self._last_kind or 'failure'}; "
                    f"{remaining:.0f}s until a probe is allowed"
                )
                if self._requires_intervention:
                    why += " (authentication failed; retrying will not fix a wrong credential)"
                return False, why
        if self._state == "half-open":
            if self._probe_outstanding:
                return False, "circuit half-open with a probe already in flight"
            self._probe_outstanding = True
            return True, ""
        return False, f"circuit in unexpected state {self._state!r}"  # pragma: no cover

    def record_success(self) -> None:
        self._state = "closed"
        self._consecutive_failures = 0
        self._probe_outstanding = False
        self._requires_intervention = False
        self._last_kind = ""

    def record_failure(self, kind: str, monotonic: float, *, retry_hint_seconds: float = 0.0) -> None:
        if kind not in FAILURE_KINDS:
            raise AgentSchemaError(f"failure kind {kind!r} is not one of {FAILURE_KINDS}")
        self._last_kind = kind
        self._probe_outstanding = False
        if kind == "authentication":
            self._open(monotonic, self.auth_open_seconds)
            self._requires_intervention = True
            return
        if kind == "rate-limit":
            window = self.open_seconds
            if retry_hint_seconds > 0:
                window = min(max(retry_hint_seconds, self.open_seconds), MAX_RETRY_HINT_SECONDS)
            self._open(monotonic, window)
            return
        if self._state == "half-open":
            # The probe failed; the full window starts again.
            self._open(monotonic, self.open_seconds)
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._open(monotonic, self.open_seconds)

    def _open(self, monotonic: float, window: float) -> None:
        self._state = "open"
        self._opened_at = monotonic
        self._open_until = monotonic + window
        self._consecutive_failures = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "consecutiveFailures": self._consecutive_failures,
            "openUntilMonotonic": self._open_until,
            "requiresIntervention": self._requires_intervention,
            "lastFailureKind": self._last_kind,
        }


class ProviderHealthMonitor:
    """Counts what §17 lists, per provider, and answers "may I try".

    Thread-safe: adapters record from the worker thread, the status operations
    read from the endpoint's.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._counters: dict[str, dict[str, int]] = {}
        self._last_detail: dict[str, str] = {}

    def _breaker(self, provider_id: str) -> CircuitBreaker:
        breaker = self._breakers.get(provider_id)
        if breaker is None:
            breaker = CircuitBreaker()
            self._breakers[provider_id] = breaker
        return breaker

    def allows(self, provider_id: str, monotonic: float) -> tuple[bool, str]:
        with self._guard:
            return self._breaker(provider_id).allows(monotonic)

    def record_success(self, provider_id: str) -> None:
        with self._guard:
            self._breaker(provider_id).record_success()
            self._last_detail[provider_id] = ""

    def record_failure(
        self, provider_id: str, kind: str, monotonic: float,
        *, detail: str = "", retry_hint_seconds: float = 0.0,
    ) -> None:
        with self._guard:
            self._breaker(provider_id).record_failure(
                kind, monotonic, retry_hint_seconds=retry_hint_seconds
            )
            counters = self._counters.setdefault(provider_id, {})
            counters[kind] = counters.get(kind, 0) + 1
            self._last_detail[provider_id] = detail[:400]

    def healthy(self, provider_id: str) -> bool:
        with self._guard:
            return self._breaker(provider_id).state == "closed"

    def report(self, provider_id: str) -> dict[str, Any]:
        with self._guard:
            return {
                "providerId": provider_id,
                "circuit": self._breaker(provider_id).to_json(),
                "failureCounts": dict(self._counters.get(provider_id, {})),
                "lastFailureDetail": self._last_detail.get(provider_id, ""),
            }

    def reports(self) -> dict[str, dict[str, Any]]:
        with self._guard:
            known = set(self._breakers) | set(self._counters)
        return {provider_id: self.report(provider_id) for provider_id in sorted(known)}
