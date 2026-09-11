# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny / AI / Privacy Control Center modules.

Device panels still deep-link to GNOME. These three are Bunny-owned. Voice
stays off until wanted; AI is one local-first control; cloud_context is named
honestly and is not remote_dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .trust_copy import (
    ALLOWLISTED_CEILING_NOTE,
    CLIPBOARD_BLUETOOTH_NOTE,
    CLOUD_MEMORY_IS_OFF,
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

AI_MODES = ("automatic", "local-only", "online-enhanced")
AI_MODE_LABELS = {
    "automatic": "Automatic",
    "local-only": "Local only",
    "online-enhanced": "Online enhanced",
}
AI_MODE_HINTS = {
    "automatic": (
        "Picks a local model from measured resources on this computer. "
        "Bunny does not go online because local is slower. An online answer still "
        "needs Allow once for this request."
    ),
    "local-only": (
        "Refuses hosted providers. Bunny will not show a Trust prompt to generate "
        "online. Typed Search still works."
    ),
    "online-enhanced": (
        "Still starts locally. Online generate is offered only when the router would "
        "escalate, and only after Allow once for this request — not always cloud."
    ),
}
_AI_WARNINGS = {
    "automatic": (
        "Automatic never goes online just because a local model is slower.",
    ),
    "local-only": (
        "Local only refuses hosted providers. Bunny will not ask to generate online.",
    ),
    "online-enhanced": (
        "Online enhanced is still local-first. Cloud generate needs Allow once "
        "for this request — not always cloud.",
    ),
}


def resolve_ai_mode(values: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
    settings = dict(values or {})
    settings.update(kwargs)
    if settings.get("localOnlyMode"):
        return "local-only"
    mode = str(settings.get("aiMode") or "automatic").strip().casefold()
    if mode in {"online-enhanced", "local-only"}:
        return mode
    return "automatic"


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
    mode = resolve_ai_mode(settings)
    return ControlModule(
        id="ai",
        title="AI",
        summary="One control. Automatic is the default. Answers start on this computer.",
        rows=(
            ControlRow(
                "aiMode",
                "AI mode",
                AI_MODE_LABELS[mode],
                hint=AI_MODE_HINTS[mode],
                control="choice",
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
        warnings=_AI_WARNINGS[mode],
    )


def privacy_module(
    values: Mapping[str, Any] | None = None, *, cloud_context: str = "none"
) -> ControlModule:
    settings = values or {}
    cloud = cloud_context if cloud_context in CLOUD_CONTEXT_LABELS else "none"
    warnings = [
        NETWORK_ALLOWLIST_NOTE,
        ALLOWLISTED_CEILING_NOTE,
        CLIPBOARD_BLUETOOTH_NOTE,
    ]
    if cloud == "none":
        warnings.append(CLOUD_MEMORY_IS_OFF)
    warnings.append(CLOUD_MEMORY_STAYS_OFF)
    return ControlModule(
        id="privacy",
        title="Privacy",
        summary="Cloud memory and a one-time online answer are two different consents.",
        rows=(
            ControlRow(
                "cloudContext",
                "Cloud memory",
                CLOUD_CONTEXT_LABELS[cloud],
                hint=CLOUD_MEMORY_IS_OFF if cloud == "none" else (
                    "Minimized still cannot send saved memory, session memory, or a conversation summary."
                ),
            ),
            ControlRow(
                "remoteDispatch",
                "Online for this request",
                "Allow once each time",
                hint=CLOUD_MEMORY_STAYS_OFF,
            ),
            ControlRow(
                "network",
                "Application network",
                f"{NETWORK_OFF} or {NETWORK_FULL_INTERNET}",
                hint=NETWORK_ALLOWLIST_NOTE,
            ),
            ControlRow(
                "appClipboard",
                "App clipboard",
                "Not mediated",
                hint=CLIPBOARD_BLUETOOTH_NOTE,
            ),
            ControlRow(
                "appBluetooth",
                "App Bluetooth",
                "Not mediated",
                hint=CLIPBOARD_BLUETOOTH_NOTE,
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
                hint="Off by default. There is no cloud clipboard. This is not application clipboard access.",
            ),
        ),
        warnings=tuple(warnings),
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
