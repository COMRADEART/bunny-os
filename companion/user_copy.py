# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Human copy for errors, offline, voice, and disconnects.

A status line that only names a phase ("error", "offline") leaves a person
to invent the rest. Every message here answers three questions, in that
order:

* what happened
* what to do
* whether anything on the computer changed

Every *screen* additionally answers the design-system trio exported as
:data:`SCREEN_QUESTIONS`: what am I doing, what is Bunny doing, what can I
do next.

The runtime still decides. This module only phrases. It does not grant
permissions, start tools, or invent a recovery that did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

__all__ = [
    "SCREEN_QUESTIONS",
    "UserMessage",
    "CLOUD_MEMORY_IS_OFF",
    "CLOUD_MEMORY_STAYS_OFF",
    "NETWORK_ALLOWLIST_NOTE",
    "NETWORK_FULL_INTERNET",
    "NETWORK_OFF",
    "ALLOWLISTED_CEILING_NOTE",
    "CLIPBOARD_BLUETOOTH_NOTE",
    "disconnected_message",
    "error_message",
    "offline_message",
    "voice_listening_message",
]

SCREEN_QUESTIONS = (
    "What am I doing?",
    "What is Bunny doing?",
    "What can I do next?",
)

#: Security #47 — fail-closed network chrome. Never a per-domain allowlist.
NETWORK_OFF = "Off"
NETWORK_FULL_INTERNET = "On (full internet)"
NETWORK_ALLOWLIST_NOTE = (
    "Site allowlists aren’t available yet — Full internet or Off."
)
ALLOWLISTED_CEILING_NOTE = (
    "No network until a real filter ships, or you allow the full internet. "
    "Bunny is not waiting for a site list."
)
CLIPBOARD_BLUETOOTH_NOTE = (
    "Clipboard and Bluetooth are not mediated in this build. Requests are denied "
    "before a prompt — Bunny cannot watch the clipboard or pair devices for an app."
)

#: Privacy cloud_context=none. Distinct from the remote_dispatch TrustPrompt line.
CLOUD_MEMORY_IS_OFF = (
    "Cloud memory is off. Bunny won’t send saved memory, session memory, "
    "or a conversation summary online."
)

#: Security #52 — remote_dispatch is not cloud_context.
CLOUD_MEMORY_STAYS_OFF = (
    "Cloud memory stays off. Allowing this sends only what you asked this time "
    "to an online service — not your saved memory, session memory, or a conversation summary."
)


@dataclass(frozen=True)
class UserMessage:
    """One human-readable status, with the three facts a person needs."""

    headline: str
    happened: str
    next_step: str
    changed: str
    kind: str = "info"

    def as_paragraph(self) -> str:
        return f"{self.headline} {self.happened} {self.next_step} {self.changed}"

    def sentence(self) -> str:
        """The three facts as one caption line."""
        return self.as_paragraph()

    def to_json(self) -> dict[str, str]:
        return {
            "headline": self.headline,
            "happened": self.happened,
            "nextStep": self.next_step,
            "changed": self.changed,
            "kind": self.kind,
        }


_ERROR_KINDS: Mapping[str, UserMessage] = {
    "failed": UserMessage(
        "That didn't work.",
        "Bunny stopped this step.",
        "You can try again, or ask for something else.",
        "Nothing else on this computer was changed.",
        "error",
    ),
    "blocked": UserMessage(
        "Bunny needs something to change first.",
        "This cannot go further with the permission or machine as it is.",
        "Answer the question if there is one, or try a smaller request.",
        "Nothing was changed.",
        "warning",
    ),
    "denied": UserMessage(
        "You said no.",
        "Bunny recorded the refusal and stopped.",
        "If that was a mistake, ask again and choose Allow once.",
        "Nothing was changed.",
        "info",
    ),
    "expired": UserMessage(
        "The question timed out.",
        "Bunny treated silence as no, which is the safe default.",
        "Ask again if you still want this done.",
        "Nothing was changed.",
        "warning",
    ),
}


def error_message(*, kind: str = "failed", detail: str = "") -> UserMessage:
    """A failure the person can act on. ``detail`` is already display-safe."""
    base = _ERROR_KINDS.get(kind, _ERROR_KINDS["failed"])
    extra = str(detail or "").strip()
    happened = f"{base.happened} {extra}".strip() if extra else base.happened
    return UserMessage(base.headline, happened, base.next_step, base.changed, base.kind)


def offline_message(*, intentional: bool = True) -> UserMessage:
    """Intentional offline, not a network outage dressed as a feature."""
    if intentional:
        return UserMessage(
            "You're offline on purpose.",
            "Bunny will only use this computer.",
            "Connect when you want a lookup that needs the internet.",
            "Nothing left this machine.",
            "info",
        )
    return UserMessage(
        "The network isn't available.",
        "Bunny cannot reach anything off this computer right now.",
        "Work that only needs this machine can still run. Try again when you're back online for the rest.",
        "Nothing left this machine.",
        "warning",
    )


def disconnected_message() -> UserMessage:
    return UserMessage(
        "This window cannot reach the companion runtime.",
        "The picture stopped updating.",
        "Keep using the desktop. Bunny will catch up when the connection returns.",
        "Anything already running is unaffected.",
        "warning",
    )


def voice_listening_message() -> UserMessage:
    return UserMessage(
        "Listening.",
        "The microphone is on, only while you hold talk.",
        "Speak, or press Stop if you didn't mean to.",
        "Audio is used for this request and is not kept.",
        "info",
    )
