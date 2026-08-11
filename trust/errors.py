# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every way a trust decision is refused, named separately.

The separation is not taxonomy. Each name leads to a different sentence in front
of a person and a different next move for the caller:

``TrustSchemaError``
    the request itself is malformed — an unknown category, a missing resource, a
    path that is not a string. Nobody can answer a question that is not a
    question, and the answer is denial.
``TrustRefused``
    the request was well formed and policy declined it. This is the ordinary
    security refusal and it is always audited.
``TrustNotDeclared``
    the application is asking for something its catalogue entry never said it
    would need. Separate from a plain refusal because it is evidence about the
    *application*, not about the user's preferences, and it is the one refusal
    that should survive into a report.
``TrustStoreUnreadable``
    the grant database could not be read or is corrupt. §22 requires this to
    fail closed, so it is an error rather than an empty result — an empty result
    is indistinguishable from "nothing was ever granted", and code that treats
    the two alike will re-prompt where it should refuse.
``TrustSurfaceUnavailable``
    there is nowhere to ask. A permission that needs a person and has no surface
    to reach one is denied; §22 says the privileged operation must not proceed
    when the permission UI is not working.
``TrustExpired`` / ``TrustReplayed``
    a decision that has stopped counting, and a decision presented twice. Both
    exist because a grant is consent *at a time*, and the remedy differs: the
    first asks again, the second is evidence of a defect or an attack.

Everything derives from :class:`TrustError`, so a caller that only wants "the
trust layer said no, and here is why" keeps working when a new case is added.
"""

from __future__ import annotations

__all__ = [
    "TrustError",
    "TrustExpired",
    "TrustNotDeclared",
    "TrustRefused",
    "TrustReplayed",
    "TrustSchemaError",
    "TrustStoreUnreadable",
    "TrustSurfaceUnavailable",
]


class TrustError(Exception):
    """Base for every refusal produced by the trust layer."""

    #: Stable machine-readable code. Audit records carry this rather than the
    #: message, because a message is written for a person and may be reworded.
    code = "trust-error"


class TrustSchemaError(TrustError):
    """The request could not be understood well enough to be answered."""

    code = "malformed-request"


class TrustRefused(TrustError):
    """Policy declined a well-formed request."""

    code = "refused"


class TrustNotDeclared(TrustRefused):
    """The application asked for a permission it never declared it would need."""

    code = "not-declared"


class TrustStoreUnreadable(TrustError):
    """The grant record could not be read; every decision therefore denies."""

    code = "store-unreadable"


class TrustSurfaceUnavailable(TrustError):
    """No surface exists to put the question to a person."""

    code = "no-surface"


class TrustExpired(TrustRefused):
    """A grant that once stood has stopped standing."""

    code = "expired"


class TrustReplayed(TrustRefused):
    """A decision was presented a second time."""

    code = "replayed"
