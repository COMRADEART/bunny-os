# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every way the companion runtime refuses, named.

A refusal that arrives as a bare :class:`ValueError` cannot be handled
differently from a bug, and a caller that cannot tell "this task may not run
here" from "this code is wrong" ends up treating both as retryable. So each
refusal in this package has a type, and each type says which layer decided.

The hierarchy is shallow on purpose. Callers catch :class:`CompanionError` to
mean "the runtime declined and said why"; the specific classes exist so the CLI
can map them to exit codes and so tests can assert on the reason rather than on
the wording of a message, which is allowed to improve.
"""

from __future__ import annotations

__all__ = [
    "ApprovalDenied",
    "ApprovalExpired",
    "ApprovalError",
    "ApprovalMismatch",
    "ApprovalReplayed",
    "CancellationError",
    "CapabilityRefused",
    "CompanionError",
    "CoordinationLimitExceeded",
    "ExecutorError",
    "ExecutorUnavailable",
    "IntegrityError",
    "InvalidTransition",
    "MalformedOutput",
    "PayloadTooLarge",
    "RecoveryError",
    "ReviewerError",
    "ReviewerViolation",
    "SchemaError",
    "StoreError",
    "UnknownEventType",
]


class CompanionError(Exception):
    """Base class: the runtime declined to do something, and can say why."""


# -- state machine ---------------------------------------------------------


class InvalidTransition(CompanionError):
    """A task was asked to move between two states that do not connect.

    Raised rather than corrected. A runtime that quietly routed an illegal
    transition through a legal one would produce an event stream that describes
    a journey the task did not take.
    """


# -- events and schema -----------------------------------------------------


class SchemaError(CompanionError):
    """A record does not match the schema of its declared version."""


class UnknownEventType(SchemaError):
    """An event names a type this build does not implement."""


class PayloadTooLarge(SchemaError):
    """An event payload exceeds the bound the store will accept.

    Bounded rather than truncated: a silently shortened payload is a record that
    reads as complete and is not.
    """


class IntegrityError(CompanionError):
    """The event chain does not verify — a gap, a reorder, or a rewrite."""


# -- persistence -----------------------------------------------------------


class StoreError(CompanionError):
    """The durable store could not be read, locked or written."""


# -- capability ------------------------------------------------------------


class CapabilityRefused(CompanionError):
    """No executor is eligible under the capability plan and the policy.

    Carries the structured reasons so the blocked task can explain itself
    without the explanation being reconstructed from prose later.
    """

    def __init__(self, message: str, *, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reasons = reasons


# -- executors and reviewers -----------------------------------------------


class ExecutorError(CompanionError):
    """An executor failed in a way the runtime must record and stop on."""


class ExecutorUnavailable(ExecutorError):
    """The selected executor reports it cannot accept work right now."""


class MalformedOutput(ExecutorError):
    """An executor or reviewer returned something that is not its contract."""


class ReviewerError(CompanionError):
    """A reviewer failed. Never fatal to the task; always recorded."""


class ReviewerViolation(ReviewerError):
    """A reviewer attempted something reviewers may not do.

    This is a security event, not a bug report. Reviewers are observation-only,
    and an attempt to execute a tool, write a file or resolve an approval means
    either a defective reviewer or a hostile one. Either way the runtime refuses
    and the attempt is recorded against the reviewer's identity.
    """


# -- coordination ----------------------------------------------------------


class CoordinationLimitExceeded(CompanionError):
    """A ceiling in :mod:`companion.coordination` was reached."""

    def __init__(self, message: str, *, limit: str = "", measured: object = None, allowed: object = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.measured = measured
        self.allowed = allowed


# -- approvals -------------------------------------------------------------


class ApprovalError(CompanionError):
    """An approval could not be used for this act at this moment."""


class ApprovalExpired(ApprovalError):
    """The approval's time ran out. Consent to act now is not consent later."""


class ApprovalReplayed(ApprovalError):
    """An already-resolved approval was presented a second time."""


class ApprovalMismatch(ApprovalError):
    """The approval does not belong to this task, transition, plan or destination."""


class ApprovalDenied(ApprovalError):
    """A person said no, or nobody answered and the safe default applied."""


# -- cancellation and recovery ---------------------------------------------


class CancellationError(CompanionError):
    """Cancellation could not be completed cleanly; partial state recorded."""


class RecoveryError(CompanionError):
    """Recovery could not reach a safe decision about a task."""
