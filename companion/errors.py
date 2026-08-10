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
    """An approval could not be used for this act at this moment.

    Every subclass names the terminal state it puts the approval into, and the
    caller records *that* rather than a single word for all of them. Collapsing
    them was a real defect: a question withdrawn because the user paused the
    task was written into the record as ``denied``, which says the person
    refused. They did not; they pressed pause. Only :class:`ApprovalDenied`
    means somebody declined.
    """

    #: The value written to ``approval_resolved``'s ``decision`` field.
    terminal_state = "invalidated"


class ApprovalExpired(ApprovalError):
    """The approval's time ran out. Consent to act now is not consent later."""

    terminal_state = "expired"


class ApprovalReplayed(ApprovalError):
    """An already-resolved approval was presented a second time."""

    terminal_state = "superseded"


class ApprovalMismatch(ApprovalError):
    """The approval does not belong to this task, transition, plan or destination."""

    terminal_state = "superseded"


class ApprovalDenied(ApprovalError):
    """A person said no, or nobody answered and the safe default applied."""

    terminal_state = "denied-by-user"


class ApprovalInvalidated(ApprovalError):
    """The question was withdrawn because the task stopped.

    Raised where a pause or a cancellation has already recorded the withdrawal,
    so that the worker which arrives afterwards records the same thing the
    withdrawal did rather than the safe default for an unanswered question.

    The terminal state is per-instance because the reasons differ and the
    difference is user-visible: "the task was paused" and "the task was
    cancelled" are not the same sentence to read next to a question you were
    about to answer.
    """

    def __init__(self, message: str, *, terminal_state: str = "invalidated") -> None:
        super().__init__(message)
        self.terminal_state = terminal_state


# -- cancellation and recovery ---------------------------------------------


class CancellationError(CompanionError):
    """Cancellation could not be completed cleanly; partial state recorded."""


class RecoveryError(CompanionError):
    """Recovery could not reach a safe decision about a task."""
