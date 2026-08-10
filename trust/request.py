# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One question, and the provenance of every claim inside it.

The rule this module exists to enforce is §10's last line: *the Companion must
never fabricate why an application needs permission.* That is not achievable by
telling the model not to. It is achievable by making the reason a field with a
**source**, where every source is something that can be pointed at afterwards,
and where the source ``model`` does not exist.

:data:`REASON_SOURCES` is the whole of it:

``catalog``
    the curated catalogue entry declares this permission and says what it is
    for. Reviewed by whoever curates the catalogue, shown as "Bunny's catalogue
    says".
``application``
    the application supplied a reason at the moment it asked, through the
    portal. Shown as "The app says", quoted, and never trusted — an application
    that lies here has told a lie a person can see and disbelieve.
``task``
    the user asked Bunny to do something and the permission is a step in it.
    The reason is the user's own request, echoed back.
``unknown``
    nobody said. The prompt then says nobody said, which is information, and is
    the honest answer.

There is no fifth source, and in particular there is no source meaning "the
model inferred it". If a provider wants a permission for a reason it invented,
the reason is not carried; the request is ``unknown`` and reads as such.

A request also carries the *purpose class* — read, write, or use — because "open
this image" and "overwrite this image" are different consents and a category
alone does not distinguish them. §15 requires the original be preserved unless
modification was explicitly requested, and a write is exactly the thing that has
to have been explicitly requested.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any, Mapping

from .categories import descriptor
from .errors import TrustSchemaError
from .resources import Resource, resource_for

__all__ = [
    "MAX_REASON_LENGTH",
    "PURPOSES",
    "REASON_SOURCES",
    "PermissionRequest",
    "Reason",
]

#: Long enough to be a sentence, short enough that it cannot be a document. A
#: reason is shown verbatim to a person; an application that supplies four
#: kilobytes of text is trying to push the buttons off the screen.
MAX_REASON_LENGTH = 240

#: Where a stated reason came from. See the module docstring for why there are
#: exactly four and why none of them is the model.
REASON_SOURCES = ("catalog", "application", "task", "unknown")

#: What the permission is *for*. Distinguishing read from write is what lets §15
#: keep the original file intact by default: an export writes to a new path, and
#: overwriting the input requires a request that says ``write`` about the input.
PURPOSES = ("read", "write", "use")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
#: Every control character, newline and tab included. A reason is one sentence
#: on one line: an application that could put a newline in it could draw a second
#: line under the real one — "Allow always (recommended)" is a convincing forgery
#: when it appears in the same typeface directly below a genuine sentence. Tab is
#: refused for the same reason in a surface that renders monospaced.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _identifier(value: object, what: str) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise TrustSchemaError(f"not a valid {what}: {value!r}")
    return value


@dataclass(frozen=True)
class Reason:
    """Why the permission is being asked for, and who says so.

    ``text`` is ``None`` exactly when ``source`` is ``unknown``. The two are kept
    consistent at construction rather than by convention, because the failure —
    a reason with no source, or a source with no reason — renders as a confident
    sentence with nothing behind it, which is the thing this whole module is
    against.
    """

    source: str
    text: str | None = None

    def __post_init__(self) -> None:
        if self.source not in REASON_SOURCES:
            raise TrustSchemaError(f"unknown reason source: {self.source!r}")
        if self.source == "unknown":
            if self.text is not None:
                raise TrustSchemaError("an unknown reason cannot carry text")
            return
        if not isinstance(self.text, str) or not self.text.strip():
            raise TrustSchemaError(f"a {self.source} reason needs text")
        if len(self.text) > MAX_REASON_LENGTH:
            raise TrustSchemaError(f"a reason may not exceed {MAX_REASON_LENGTH} characters")
        if _CONTROL.search(self.text):
            raise TrustSchemaError("a reason may not contain control characters")

    @classmethod
    def unknown(cls) -> "Reason":
        return cls(source="unknown", text=None)

    def as_record(self) -> Mapping[str, Any]:
        return {"source": self.source, "text": self.text}


@dataclass(frozen=True)
class PermissionRequest:
    """A well-formed question about one capability, one application, one resource.

    Construction validates; it does not decide. Whether the answer is yes is
    :mod:`trust.policy`'s business, and keeping the two apart is what lets the
    tests enumerate malformed requests and assert that every one of them denies
    without any policy being configured at all.
    """

    request_id: str
    application_id: str
    category: str
    resource: Resource
    purpose: str
    reason: Reason
    session_id: str
    task_id: str | None = None
    #: Monotonic-clock reading at which the request was made, in seconds. Wall
    #: clock is deliberately not used for anything that expires; see
    #: :mod:`trust.store`.
    requested_at: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request id")
        _identifier(self.application_id, "application id")
        _identifier(self.session_id, "session id")
        if self.task_id is not None:
            _identifier(self.task_id, "task id")
        if self.purpose not in PURPOSES:
            raise TrustSchemaError(f"unknown purpose: {self.purpose!r}")
        # Raises for an unknown category, which is the deny-by-default path for
        # anything this build does not implement.
        descriptor(self.category)
        checked = resource_for(self.category, self.resource)
        if checked is not self.resource:
            object.__setattr__(self, "resource", checked)
        if not isinstance(self.requested_at, (int, float)):
            raise TrustSchemaError("requested_at must be a number")
        if self.purpose == "write" and self.resource.kind not in ("path", "peer", "none"):
            raise TrustSchemaError("only a path, a peer or a capability may be written to")

    @classmethod
    def build(
        cls,
        *,
        request_id: str,
        application_id: str,
        category: str,
        session_id: str,
        resource: Resource | None = None,
        purpose: str = "use",
        reason: Reason | None = None,
        task_id: str | None = None,
        requested_at: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> "PermissionRequest":
        """Construct with the sentinel resource filled in for resourceless categories."""
        return cls(
            request_id=request_id,
            application_id=application_id,
            category=category,
            resource=resource_for(category, resource),
            purpose=purpose,
            reason=reason or Reason.unknown(),
            session_id=session_id,
            task_id=task_id,
            requested_at=float(requested_at),
            metadata=dict(metadata or {}),
        )

    def with_reason(self, reason: Reason) -> "PermissionRequest":
        return replace(self, reason=reason)

    def as_record(self) -> Mapping[str, Any]:
        """The audit projection. Carries no resource identifier and no metadata.

        Metadata is caller-supplied and may hold anything; an audit record that
        copied it would be a channel through which user content reaches a log by
        accident. What survives is the shape of the request.
        """
        return {
            "requestId": self.request_id,
            "applicationId": self.application_id,
            "category": self.category,
            "purpose": self.purpose,
            "resource": dict(self.resource.as_record()),
            "reason": dict(self.reason.as_record()),
            "sessionId": self.session_id,
            "taskId": self.task_id,
        }
