# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every way the agent-provider subsystem refuses, named.

The taxonomy mirrors :mod:`companion.errors` for the same reason that module
gives: a refusal that arrives as a bare exception cannot be told from a bug.
The split that matters here is between *this request cannot be represented*
(:class:`AgentSchemaError` and its children — raised at construction, before a
provider is contacted) and *this generation did not produce a usable result*
(which is **not** an exception at all: adapters return a structured
:class:`~companion.agents.adapter.GenerationOutcome`, because a provider that
raised through the worker would take the worker down with it, and §17 needs
failure to be data it can count).

Two children deserve their own note:

:class:`ContextOverflow`
    Raised when the built context would exceed the provider's declared window.
    The alternative — silently dropping the oldest items — was rejected in
    §6's terms: the oldest items include the system policy, and a context that
    sheds its policy under pressure is exactly the prompt-injection amplifier
    the policy exists to prevent. Refusal is the only honest answer.

:class:`StreamViolation`
    A provider stream broke its ordering contract — a duplicate sequence, a
    regression, a delta after the terminal event, an oversized delta. The
    stream is closed and the generation fails; the finalized deltas received
    so far are kept as *provisional* history only, never presented as the
    result, because a stream that lies about ordering may be lying about
    content.
"""

from __future__ import annotations

from ..errors import CompanionError

__all__ = [
    "AgentProviderError",
    "AgentSchemaError",
    "ContextOverflow",
    "CredentialRefused",
    "GenerationBudgetExceeded",
    "ProviderConfigurationError",
    "StreamViolation",
    "StructuredOutputInvalid",
]


class AgentProviderError(CompanionError):
    """Base class: the agent-provider subsystem declined and can say why."""


class AgentSchemaError(AgentProviderError):
    """A request, descriptor or configuration does not match its schema.

    Raised at construction so an invalid request is not representable. Nothing
    that fails here ever reaches an adapter, a socket or a subprocess.
    """


class ContextOverflow(AgentSchemaError):
    """The built context exceeds the declared window.

    Refused rather than trimmed: the items most likely to be trimmed by any
    "drop the oldest" rule are the system policy and the privacy instructions,
    and a context that quietly sheds them is worse than no generation at all.
    """


class CredentialRefused(AgentProviderError):
    """A credential source exists but may not be used.

    World-readable file, symlink, unexpected owner, unapproved location — each
    is named in the message. The credential's *value* is never part of this
    error, its message, or anything derived from it.
    """


class ProviderConfigurationError(AgentSchemaError):
    """A provider configuration entry cannot be accepted as written."""


class StreamViolation(AgentProviderError):
    """A provider stream broke the ordering or bounding contract."""


class StructuredOutputInvalid(AgentProviderError):
    """Provider output failed local schema validation and repair is exhausted.

    Carries the digest of the invalid output so the record can name what was
    rejected without storing it.
    """

    def __init__(self, message: str, *, digest: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.digest = digest
        self.reason = reason


class GenerationBudgetExceeded(AgentProviderError):
    """A cost, token or loop ceiling would be crossed by starting this generation.

    Checked *before* the generation begins: a ceiling that is only noticed
    afterwards has already been spent through.
    """

    def __init__(self, message: str, *, limit: str = "", measured: object = None, allowed: object = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.measured = measured
        self.allowed = allowed
