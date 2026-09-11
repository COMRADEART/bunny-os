# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Trust chrome copy shared by Settings, Control Center, and TrustPrompt.

JavaScript in ``lib/trustPrompt.js`` is the drawable source. These strings
must stay byte-identical; ``tests/shell/test_ux_phase2.py`` compares them.
"""

from __future__ import annotations

NETWORK_OFF = "Off"
NETWORK_FULL_INTERNET = "Full internet"
NETWORK_ALLOWLIST_NOTE = (
    "Site allowlists aren’t available yet — Full internet or Off."
)
CLOUD_MEMORY_STAYS_OFF = (
    "Cloud memory stays off. Allowing this sends only what you asked this time "
    "to an online service — not your saved memory, session memory, or a conversation summary."
)
ALLOW_ONCE_LABEL = "Allow once"
DONT_ALLOW_LABEL = "Don't allow"


def network_facing_label(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lower = text.casefold()
    if lower in {"off", "none", "blocked", "nothing on the network"}:
        return NETWORK_OFF
    return NETWORK_FULL_INTERNET


def remote_dispatch_disclosure(
    *, cloud_context: str = "none", offering_remote_dispatch: bool = False
) -> str:
    if not offering_remote_dispatch:
        return ""
    cloud = str(cloud_context or "none").strip().casefold() or "none"
    if cloud == "none":
        return CLOUD_MEMORY_STAYS_OFF
    return ""
