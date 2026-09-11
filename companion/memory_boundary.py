# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""OS-level memory under user control; cloud gets only authorised context.

Four scopes, deny-by-default for anything that outlives the current task or
leaves the machine:

* ``working`` — the current request. Always on. It is RAM for the task, not
  a memory the OS keeps.
* ``session`` — until logout. Local. Off until the person allows it.
* ``durable`` — across reboots. Local. Off until the person allows it.
* ``cloud`` — off. When allowed, only a minimised, classified slice may
  leave, and only at or below the privacy ceiling.

Nothing here grants shell access, and nothing here can raise
:attr:`companion.settings.PrivacySettings.remote_transfer_ceiling`. A
cloud share that would exceed the ceiling is refused, not truncated into
a quiet leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from companion.privacy import (
    AUDIENCE_CEILING,
    DATA_CLASSES,
    project,
    rank,
    router_privacy,
)

__all__ = [
    "CLOUD_MODES",
    "MEMORY_SCOPE_TITLES",
    "MEMORY_SCOPES",
    "REMOTE_GENERATE_ALLOWED_FIELDS",
    "MemoryDecision",
    "MemoryPolicy",
    "authorize_cloud_context",
    "authorize_remote_generate",
    "may_store",
]

MEMORY_SCOPES = ("working", "session", "durable", "cloud")
CLOUD_MODES = ("none", "minimized")

#: What a person should read for each scope. The machine names stay in
#: :data:`MEMORY_SCOPES`; these are the labels Settings draws.
MEMORY_SCOPE_TITLES: Mapping[str, str] = {
    "working": "This task only",
    "session": "Until you log out",
    "durable": "Saved on this computer",
    "cloud": "Shared with a cloud you allowed",
}

#: What each scope may hold at most when the person has allowed it.
_SCOPE_CEILING: Mapping[str, str] = {
    "working": "secret",
    "session": "sensitive",
    "durable": "personal",
    "cloud": "internal",
}


@dataclass(frozen=True)
class MemoryPolicy:
    """The person's memory controls. Defaults deny everything but working."""

    session: bool = False
    durable: bool = False
    cloud_context: str = "none"

    def __post_init__(self) -> None:
        if self.cloud_context not in CLOUD_MODES:
            raise ValueError("cloud_context is 'none' or 'minimized'")

    @classmethod
    def from_settings(cls, privacy: object) -> "MemoryPolicy":
        """Read from :class:`companion.settings.PrivacySettings`."""
        session = bool(getattr(privacy, "local_session_memory", False))
        durable = bool(getattr(privacy, "local_durable_memory", False))
        cloud = str(getattr(privacy, "cloud_context", "none") or "none")
        if cloud not in CLOUD_MODES:
            cloud = "none"
        return cls(session=session, durable=durable, cloud_context=cloud)

    def to_json(self) -> dict[str, object]:
        return {
            "working": True,
            "session": self.session,
            "durable": self.durable,
            "cloudContext": self.cloud_context,
            "denyByDefault": True,
        }


@dataclass(frozen=True)
class MemoryDecision:
    """Whether one write or one cloud share may happen, and why."""

    allowed: bool
    scope: str
    reason: str
    classification: str
    released: Mapping[str, object] | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "scope": self.scope,
            "reason": self.reason,
            "classification": self.classification,
            "released": dict(self.released) if self.released is not None else None,
        }


def _scope_enabled(policy: MemoryPolicy, scope: str) -> bool:
    if scope == "working":
        return True
    if scope == "session":
        return policy.session
    if scope == "durable":
        return policy.durable
    if scope == "cloud":
        return policy.cloud_context == "minimized"
    return False


def may_store(
    classification: str,
    scope: str,
    policy: MemoryPolicy | None = None,
) -> MemoryDecision:
    """May this classified fact be kept in ``scope``?"""
    if classification not in DATA_CLASSES:
        raise ValueError(f"unknown classification: {classification!r}")
    if scope not in MEMORY_SCOPES:
        raise ValueError(f"unknown memory scope: {scope!r}")
    resolved = policy or MemoryPolicy()
    if not _scope_enabled(resolved, scope):
        return MemoryDecision(
            False, scope,
            f"{scope} memory is off until you turn it on",
            classification,
        )
    ceiling = _SCOPE_CEILING[scope]
    if rank(classification) > rank(ceiling):
        return MemoryDecision(
            False, scope,
            f"{scope} memory will not keep {classification} facts "
            f"(ceiling is {ceiling})",
            classification,
        )
    return MemoryDecision(
        True, scope,
        f"{scope} memory may keep this {classification} fact on this computer"
        if scope != "cloud" else "cloud context is authorised and minimised",
        classification,
    )


def authorize_cloud_context(
    payload: Mapping[str, object],
    *,
    classification: str,
    policy: MemoryPolicy,
    remote_transfer_ceiling: str,
    allowed_fields: Sequence[str] = (),
) -> MemoryDecision:
    """Release a minimised payload, or nothing.

    ``allowed_fields`` is the allow-list of keys that may leave. Anything
    else is dropped. The result is then projected at the ``remote``
    audience, and refused entirely if the classification is above the
    person's remote-transfer ceiling.
    """
    store = may_store(classification, "cloud", policy)
    if not store.allowed:
        return store
    if rank(classification) > rank(remote_transfer_ceiling):
        return MemoryDecision(
            False, "cloud",
            f"cloud context cannot carry {classification} when the transfer "
            f"ceiling is {remote_transfer_ceiling}",
            classification,
        )
    if rank(router_privacy(classification)) > rank(AUDIENCE_CEILING["remote"]):
        return MemoryDecision(
            False, "cloud",
            "the remote audience ceiling forbids this classification",
            classification,
        )
    allow = {str(name) for name in allowed_fields}
    if not allow:
        return MemoryDecision(
            False, "cloud",
            "cloud context needs an explicit field allow-list; none was given",
            classification,
        )
    trimmed = {key: value for key, value in payload.items() if str(key) in allow}
    released = project(trimmed, audience="remote", classification=classification)
    return MemoryDecision(
        True, "cloud",
        "only the authorised, minimised fields would leave this computer",
        classification,
        released=released if isinstance(released, Mapping) else {"value": released},
    )


#: Keys a remote generate may carry. Current interaction only — never session
#: or durable memory, never a conversation-summary slot.
REMOTE_GENERATE_ALLOWED_FIELDS = (
    "user_request",
    "instruction",
    "system_policy_reference",
    "classification",
    "task_id",
    "purpose",
)

_FORBIDDEN_REMOTE_MARKERS = (
    "conversation-summary",
    "conversation_summary",
    "summary_text",
    "durable",
    "session_memory",
    "memory_record",
    "memory_records",
    "memory_body",
    "memory_hits",
    "recall",
)


def authorize_remote_generate(
    payload: Mapping[str, object],
    *,
    classification: str,
    remote_transfer_ceiling: str,
    remote_dispatch_granted: bool,
    policy: MemoryPolicy | None = None,
) -> MemoryDecision:
    """Gate one remote generate: current request only, never durable memory.

    Two consents, not one:

    * ``PrivacySettings.cloud_context`` gates **memory / cloud-context egress**
      (durable, session, conversation-summary). ``none`` keeps that off.
    * ``remote_dispatch`` gates **this-interaction online generate** of
      current-request allow-listed fields only.

    They must not be conflated. ``cloud_context=none`` does not silently
    block an already-granted ``remote_dispatch`` current-request hop.
    Session and durable stay off on the effective policy regardless.
    Forbidden keys (``summary_text``, conversation-summary, durable records,
    ``memory_records``) refuse the whole payload rather than being stripped
    into a quiet leak. Conversation-summary stays unwired.

    ``authorize_cloud_context`` still runs so the field allow-list and remote
    audience projection are on the generation wire. Alpha CODE accept:
    ``docs/SECURITY_ALPHA_ACCEPT_REMOTE_DISPATCH_CLOUD_CONTEXT.md``.
    """
    if not remote_dispatch_granted:
        return MemoryDecision(
            False, "cloud",
            "remote generate requires a granted remote_dispatch approval",
            classification,
        )
    for key in payload:
        lowered = str(key).lower().replace(" ", "-")
        for marker in _FORBIDDEN_REMOTE_MARKERS:
            if marker in lowered:
                return MemoryDecision(
                    False, "cloud",
                    f"remote generate refuses {key!r}; persistent or summary "
                    "context must not leave this computer",
                    classification,
                )
    # Working-scope current request only. Session/durable never ride along,
    # even if the person later enables those scopes for local storage.
    effective = MemoryPolicy(
        session=False,
        durable=False,
        cloud_context="minimized",
    )
    if policy is not None and policy.cloud_context == "none":
        # SECURITY CO-SIGN HOOK — ACCEPTED for Alpha at CODE (2026-09-11).
        # Owner: Bunny OS Security Engineer.
        # cloud_context gates memory/cloud-context egress (durable / session /
        # summary). remote_dispatch gates this-interaction online generate of
        # current-request allow-listed fields only. Therefore cloud_context=none
        # MUST NOT silently block an already-granted remote_dispatch
        # current-request hop. Do not reverse this `pass` into a refuse.
        # Session/durable stay off on ``effective``; forbidden keys still
        # refuse the whole payload. Conversation-summary stays unwired.
        # Revisit before wiring conversation-summary or expanding the online
        # path. See docs/SECURITY_ALPHA_ACCEPT_REMOTE_DISPATCH_CLOUD_CONTEXT.md.
        pass
    return authorize_cloud_context(
        payload,
        classification=classification,
        policy=effective,
        remote_transfer_ceiling=remote_transfer_ceiling,
        allowed_fields=REMOTE_GENERATE_ALLOWED_FIELDS,
    )
