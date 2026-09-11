# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny / AI / Privacy Control Center modules.

Device panels still deep-link to GNOME. These three are Bunny-owned. Voice
stays off until wanted; AI is local-first; cloud_context is named honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .trust_copy import (
    CLOUD_MEMORY_STAYS_OFF,
    NETWORK_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET,
    NETWORK_OFF,
)

CONTROL_CENTER_MODULES = ("bunny", "ai", "privacy")

CLOUD_CONTEXT_LABELS = {
    "none": "Off — saved memory stays on this computer",
    "minimized": "Minimized — only current-request fields may go online after Allow once",
}


@dataclass(frozen=True)
class ControlRow:
    id: str
    label: str
    value: str
    hint: str = ""
    control: str = "label"


@dataclass(frozen=True)
class ControlModule:
    id: str
    title: str
    summary: str
    rows: tuple[ControlRow, ...]
    warnings: tuple[str, ...] = ()
    companion_required: bool = False


def bunny_module(values: Mapping[str, Any] | None = None, *, companion_hidden: bool = False) -> ControlModule:
    settings = values or {}
    return ControlModule(
        id="bunny",
        title="Bunny",
        summary="The companion is optional. Keyboard, dock, and Search still run the OS.",
        rows=(
            ControlRow(
                "launchBunnyAtLogin",
                "Open Bunny at login",
                "On" if settings.get("launchBunnyAtLogin") else "Off",
                control="toggle",
            ),
            ControlRow("theme", "Appearance", str(settings.get("theme", "system")), control="choice"),
            ControlRow(
                "companion",
                "Companion",
                "Hidden" if companion_hidden else "Visible",
                hint="Hiding the figure does not hide Search, Settings, or Trust.",
                control="toggle",
            ),
        ),
    )


def ai_module(values: Mapping[str, Any] | None = None) -> ControlModule:
    settings = values or {}
    local_only = bool(settings.get("localOnlyMode"))
    return ControlModule(
        id="ai",
        title="AI",
        summary="Answers start on this computer. Online generate is a separate Allow once.",
        rows=(
            ControlRow(
                "localAiEnabled",
                "Local AI",
                "On" if settings.get("localAiEnabled", True) else "Off",
                hint="Models on this machine. Nothing leaves until you allow a hop.",
                control="toggle",
            ),
            ControlRow(
                "localOnlyMode",
                "Local-only",
                "On" if local_only else "Off",
                hint="Refuses cloud failover. Local voice and local models stay available.",
                control="toggle",
            ),
            ControlRow(
                "voiceListening",
                "Voice listening",
                "Off until you ask",
                hint="Push-to-talk is Super+Alt+Space. Typed Search always works.",
            ),
            ControlRow(
                "voiceEnabled",
                "Spoken replies",
                "Available" if settings.get("voiceEnabled", True) else "Off",
                control="toggle",
            ),
            ControlRow(
                "microphoneEnabled",
                "Microphone permission",
                "Allowed when you talk" if settings.get("microphoneEnabled", True) else "Blocked",
                control="toggle",
            ),
        ),
        warnings=("Local-only is on. Bunny will not fail over to an online model.",) if local_only else (),
    )


def privacy_module(
    values: Mapping[str, Any] | None = None, *, cloud_context: str = "none"
) -> ControlModule:
    settings = values or {}
    cloud = cloud_context if cloud_context in CLOUD_CONTEXT_LABELS else "none"
    return ControlModule(
        id="privacy",
        title="Privacy",
        summary="Cloud memory and a one-time online answer are two different consents.",
        rows=(
            ControlRow(
                "cloudContext",
                "Cloud memory",
                CLOUD_CONTEXT_LABELS[cloud],
                hint=CLOUD_MEMORY_STAYS_OFF if cloud == "none" else (
                    "Minimized still cannot send saved memory, session memory, or a conversation summary."
                ),
            ),
            ControlRow(
                "network",
                "Application network",
                f"{NETWORK_OFF} or {NETWORK_FULL_INTERNET}",
                hint=NETWORK_ALLOWLIST_NOTE,
            ),
            ControlRow(
                "pluginNetworkDefault",
                "Plugin network",
                "Deny until asked" if settings.get("pluginNetworkDefault", "deny") == "deny" else "Ask",
                control="choice",
            ),
            ControlRow(
                "telemetryEnabled",
                "Telemetry",
                "On" if settings.get("telemetryEnabled") else "Off",
                hint="Off by default. Bunny does not phone home for analytics.",
            ),
            ControlRow(
                "clipboardHistory",
                "Clipboard history",
                "On" if settings.get("clipboardHistory") else "Off",
                hint="Off by default. There is no cloud clipboard.",
            ),
        ),
        warnings=(NETWORK_ALLOWLIST_NOTE, CLOUD_MEMORY_STAYS_OFF) if cloud == "none" else (NETWORK_ALLOWLIST_NOTE,),
    )


def control_center(
    values: Mapping[str, Any] | None = None,
    *,
    cloud_context: str = "none",
    companion_hidden: bool = False,
) -> dict[str, ControlModule]:
    settings = values or {}
    return {
        "bunny": bunny_module(settings, companion_hidden=companion_hidden),
        "ai": ai_module(settings),
        "privacy": privacy_module(settings, cloud_context=cloud_context),
    }
