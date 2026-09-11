# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Trust chrome copy shared by Settings, Control Center, and TrustPrompt.

JavaScript in ``lib/trustPrompt.js`` is the drawable source. These strings
must stay byte-identical; ``tests/shell/test_ux_phase2.py`` compares them.
"""

from __future__ import annotations

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
CLOUD_MEMORY_IS_OFF = (
    "Cloud memory is off. Bunny won’t send saved memory, session memory, "
    "or a conversation summary online."
)
CLOUD_MEMORY_STAYS_OFF = (
    "Cloud memory stays off. Allowing this sends only what you asked this time "
    "to that online service — not your saved memory, session memory, or a conversation summary."
)
NO_ONLINE_MODELS_IS_LOCAL_ONLY = (
    "No online models ever is Local only — not Cloud memory off."
)
ALLOW_ONCE_LABEL = "Allow once"
DONT_ALLOW_LABEL = "Don't allow"
ALLOW_ACCESSIBLE_NAME = "Allow this Bunny action"
DENY_ACCESSIBLE_NAME = "Deny this Bunny action"
FILE_OPEN_HEADLINE = "Bunny wants to open this file"
FILE_OPEN_BUBBLE = "Review this open request."
FILE_NOT_UPLOADED = "No file is uploaded automatically."

_EXPLICIT_OFF = {"off", "none", "blocked", "nothing on the network"}
_EXPLICIT_ON = {
    "on", "internet", "full internet", "on (full internet)", "the internet", "granted",
}


def network_is_declared_only(value: str | None) -> bool:
    lower = str(value or "").strip().casefold()
    if not lower:
        return False
    if lower in _EXPLICIT_OFF or lower in _EXPLICIT_ON:
        return False
    return True


def network_facing_label(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lower = text.casefold()
    if lower in _EXPLICIT_ON:
        return NETWORK_FULL_INTERNET
    return NETWORK_OFF


def remote_dispatch_disclosure(
    *, cloud_context: str = "none", offering_remote_dispatch: bool = False
) -> str:
    if not offering_remote_dispatch:
        return ""
    cloud = str(cloud_context or "none").strip().casefold() or "none"
    if cloud == "none":
        return CLOUD_MEMORY_STAYS_OFF
    return ""


def is_unbounded_grant(option: dict | None) -> bool:
    if not isinstance(option, dict):
        return True
    scope = str(option.get("scope") or "").casefold()
    label = str(option.get("label") or "").casefold()
    if scope in {"*", "everything", "unbounded"}:
        return True
    return "everything" in label or "unbounded" in label or "always allow all" in label


def bounded_allow_options(options: list | tuple | None, category: str = "") -> list[dict]:
    cat = str(category or "").casefold()
    kept: list[dict] = []
    for option in options or ():
        if not isinstance(option, dict) or is_unbounded_grant(option):
            continue
        if cat == "network" and str(option.get("scope") or "").casefold() == "always":
            continue
        kept.append(option)
    return kept
