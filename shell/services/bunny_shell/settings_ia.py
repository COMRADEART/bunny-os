# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Calm Settings information architecture.

Progressive disclosure: You (Bunny-owned) is always visible; This computer
deep-links to GNOME and starts collapsed; System is last. Not a macOS clone
and not a chatbot wall.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control_center import CONTROL_CENTER_MODULES

SETTINGS_IA_GROUPS = ("you", "device", "system")

GROUP_TITLES = {
    "you": "You",
    "device": "This computer",
    "system": "System",
}

GROUP_BLURBS = {
    "you": "Bunny, AI, privacy, and how this computer talks to you.",
    "device": "Stable device panels. Bunny opens GNOME Settings for these.",
    "system": "Updates, recovery, and what this image is.",
}


@dataclass(frozen=True)
class SidebarItem:
    id: str
    title: str
    group: str
    blurb: str
    disclosure: str = "primary"
    gnome_panel: str | None = None
    aliases: tuple[str, ...] = ()
    bunny_owned: bool = False


SIDEBAR_ITEMS: tuple[SidebarItem, ...] = (
    SidebarItem(
        "bunny", "Bunny", "you",
        "Character, voice, personality, motion, place on screen, and how much Bunny offers.",
        bunny_owned=True,
    ),
    SidebarItem(
        "ai-models", "AI & Models", "you",
        "Automatic, Local only, or Online enhanced. Advanced facts stay collapsed.",
        aliases=("Voice & AI", "Local Models", "AI"),
        bunny_owned=True,
    ),
    SidebarItem(
        "privacy", "Privacy", "you",
        "Cloud memory and a one-time online answer are two different consents.",
        aliases=("Memory",),
        bunny_owned=True,
    ),
    SidebarItem(
        "accessibility", "Accessibility", "you",
        "Motion, contrast, text size, captions. The companion is never required.",
        gnome_panel="universal-access",
        bunny_owned=True,
    ),
    SidebarItem(
        "network", "Network", "device",
        "Wi-Fi and wired. Application network is Off or On (full internet).",
        disclosure="nested", gnome_panel="network",
    ),
    SidebarItem(
        "bluetooth", "Bluetooth", "device",
        "Device Bluetooth. App Bluetooth is not mediated in this build.",
        disclosure="nested", gnome_panel="bluetooth",
    ),
    SidebarItem(
        "displays", "Displays", "device", "Arrangement, scale, and night light.",
        disclosure="nested", gnome_panel="display",
    ),
    SidebarItem(
        "sound", "Sound", "device", "Input, output, and volume.",
        disclosure="nested", gnome_panel="sound",
    ),
    SidebarItem(
        "power", "Power", "device", "Sleep and battery.",
        disclosure="nested", gnome_panel="power",
    ),
    SidebarItem(
        "keyboard", "Keyboard", "device", "Layout and shortcuts.",
        disclosure="nested", gnome_panel="keyboard",
    ),
    SidebarItem(
        "mouse", "Mouse and Touchpad", "device", "Pointer speed and tap-to-click.",
        disclosure="nested", gnome_panel="mouse", aliases=("Mouse", "Touchpad"),
    ),
    SidebarItem(
        "appearance", "Appearance", "device", "Wallpaper and GNOME appearance.",
        disclosure="nested", gnome_panel="background",
    ),
    SidebarItem(
        "applications", "Applications", "device", "Installed applications.",
        disclosure="nested", gnome_panel="applications", aliases=("Apps",),
    ),
    SidebarItem(
        "notifications", "Notifications", "device",
        "Quiet Bunny notices. GNOME still owns the session daemon.",
        disclosure="nested", gnome_panel="notifications", bunny_owned=True,
    ),
    SidebarItem(
        "users", "Users", "device", "People who can sign in.",
        disclosure="nested", gnome_panel="user-accounts",
    ),
    SidebarItem(
        "datetime", "Date and Time", "device", "Clock and timezone.",
        disclosure="nested", gnome_panel="datetime", aliases=("Timezone",),
    ),
    SidebarItem(
        "storage", "Storage", "device", "Disks and free space.",
        disclosure="nested", gnome_panel="info-overview",
    ),
    SidebarItem(
        "updates", "Updates", "system",
        "OS image updates stay separate from Bunny application updates.",
        disclosure="nested", bunny_owned=True,
    ),
    SidebarItem(
        "recovery", "Recovery", "system",
        "Previous deployments, safe graphics, and diagnostics without Bunny Core.",
        disclosure="nested", bunny_owned=True,
    ),
    SidebarItem(
        "plugins", "Plugins", "system", "Signed extensions. Network denied until asked.",
        disclosure="nested", bunny_owned=True,
    ),
    SidebarItem(
        "permissions", "Permissions", "system",
        "Allow once or Don't allow. There is no Always allow everything.",
        disclosure="nested", bunny_owned=True,
    ),
    SidebarItem(
        "system-information", "System Information", "system",
        "What this computer is. Not a claim about a booted image.",
        disclosure="nested", gnome_panel="info-overview", aliases=("About",),
    ),
)

_BY_ID = {item.id: item for item in SIDEBAR_ITEMS}

#: Visible sidebar titles in reading order. Deep-link aliases are not listed.
SIDEBAR_SECTION_TITLES: tuple[str, ...] = tuple(item.title for item in SIDEBAR_ITEMS)


def resolve_section(name: str | None) -> SidebarItem:
    """Match a sidebar id, title, or alias. Unknown names become Bunny."""
    token = str(name or "bunny").strip()
    if not token:
        return _BY_ID["bunny"]
    folded = token.casefold().replace("_", " ").replace("-", " ")
    for item in SIDEBAR_ITEMS:
        candidates = (item.id, item.title, *item.aliases)
        for candidate in candidates:
            if candidate.casefold().replace("_", " ").replace("-", " ") == folded:
                return item
    return _BY_ID["bunny"]


def sidebar_groups(*, device_collapsed: bool = True) -> tuple[dict[str, Any], ...]:
    groups = []
    for group_id in SETTINGS_IA_GROUPS:
        items = [item for item in SIDEBAR_ITEMS if item.group == group_id]
        groups.append({
            "id": group_id,
            "title": GROUP_TITLES[group_id],
            "blurb": GROUP_BLURBS[group_id],
            "collapsed": bool(device_collapsed) if group_id != "you" else False,
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "blurb": item.blurb,
                    "disclosure": item.disclosure,
                    "gnomePanel": item.gnome_panel,
                    "bunnyOwned": item.bunny_owned,
                    "accessibleName": item.title,
                    "canFocus": True,
                }
                for item in items
            ],
        })
    return tuple(groups)


def build_settings_ia(
    *,
    selected: str = "bunny",
    companion_hidden: bool = False,
    device_collapsed: bool = True,
) -> dict[str, Any]:
    current = resolve_section(selected)
    return {
        "kind": "SettingsIA",
        "title": "Settings",
        "summary": "A calm sidebar. Bunny is optional. Device panels stay in GNOME.",
        "groups": sidebar_groups(device_collapsed=device_collapsed),
        "selected": current.id,
        "selectedTitle": current.title,
        "companionRequired": False,
        "companionHidden": bool(companion_hidden),
        "controlCenterModules": list(CONTROL_CENTER_MODULES),
        "styleClass": "bunny-sidebar",
        "canFocus": True,
        "questions": (
            "What am I doing?",
            "What is Bunny doing?",
            "What can I do next?",
        ),
        "accessibleName": "Bunny Settings",
        "chatbot": False,
    }


def gnome_panel_for(name: str | None) -> str | None:
    return resolve_section(name).gnome_panel
