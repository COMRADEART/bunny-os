# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminal, Software, and Updates chrome. Twin of ``lib/appChrome.js``."""

from __future__ import annotations

from typing import Any

from .trust_copy import NETWORK_ALLOWLIST_NOTE

IN_TREE_APPS = ("terminal", "software", "updates")


def _chrome(
    *,
    app_id: str,
    title: str,
    summary: str,
    next_step: str,
    rows: tuple[dict[str, str], ...] = (),
    warnings: tuple[str, ...] = (),
    reduced_motion: bool = False,
) -> dict[str, Any]:
    return {
        "kind": "AppChrome",
        "id": app_id,
        "title": title,
        "summary": summary,
        "next": next_step,
        "rows": list(rows),
        "warnings": list(warnings),
        "companionRequired": False,
        "chatbot": False,
        "transcript": False,
        "reducedMotion": bool(reduced_motion),
        "motionMs": 0 if reduced_motion else 220,
        "accessibleName": title,
        "canFocus": True,
    }


def build_terminal_chrome(
    *, command: str = "", classification: str = "read_only", reduced_motion: bool = False
) -> dict[str, Any]:
    risk = str(classification or "read_only")
    needs_trust = risk != "read_only"
    return _chrome(
        app_id="terminal",
        title="Terminal",
        summary="A command field with Bunny classification. The companion is not required.",
        next_step=(
            "This command needs Trust. Allow once or Don't allow. Don't allow is focused."
            if needs_trust
            else "Read-only. Run, or type another command."
        ),
        rows=(
            {"id": "command", "label": "Command", "value": str(command or "")},
            {"id": "classification", "label": "Classification", "value": risk.replace("_", " ")},
            {"id": "trust", "label": "Trust", "value": "Required" if needs_trust else "Not required"},
        ),
        warnings=(
            ("Non-read-only commands go through Trust. Bunny does not run them itself.",)
            if needs_trust
            else ()
        ),
        reduced_motion=reduced_motion,
    )


def build_software_chrome(*, installed: bool = False, reduced_motion: bool = False) -> dict[str, Any]:
    return _chrome(
        app_id="software",
        title="Software",
        summary=(
            "Opens GNOME Software. Bunny does not vendor a second store."
            if installed
            else "The software store is not installed on this system."
        ),
        next_step=(
            "Install or remove applications in GNOME Software. Bunny permissions stay in Trust."
            if installed
            else "Install GNOME Software, or use the package tools this image already has."
        ),
        rows=(
            {"id": "backend", "label": "Store", "value": "GNOME Software" if installed else "Not installed"},
            {"id": "bunnyOwned", "label": "Bunny-owned store", "value": "No"},
        ),
        warnings=(
            "Application network still needs Trust. Site allowlists are not available.",
            NETWORK_ALLOWLIST_NOTE,
        ),
        reduced_motion=reduced_motion,
    )


def build_updates_chrome(
    *, os_status: str = "Not measured", bunny_status: str = "Not measured", reduced_motion: bool = False
) -> dict[str, Any]:
    return _chrome(
        app_id="updates",
        title="Updates",
        summary="OS image updates stay separate from Bunny application updates.",
        next_step="Inspect status. Applying an OS image needs broker authorization. Not a boot claim.",
        rows=(
            {"id": "os", "label": "OS image", "value": str(os_status or "Not measured")},
            {"id": "bunny", "label": "Bunny applications", "value": str(bunny_status or "Not measured")},
            {"id": "broker", "label": "Broker", "value": "Required for OS image apply"},
        ),
        warnings=(
            "This chrome does not claim IMAGE, BOOT, or PASS.",
            "Status strings are host-visible copy, not a booted measurement.",
        ),
        reduced_motion=reduced_motion,
    )


def build_app_chrome(app_id: str, **options: Any) -> dict[str, Any]:
    if app_id == "terminal":
        return build_terminal_chrome(
            command=str(options.get("command") or ""),
            classification=str(options.get("classification") or "read_only"),
            reduced_motion=bool(options.get("reduced_motion") or options.get("reducedMotion")),
        )
    if app_id == "software":
        return build_software_chrome(
            installed=bool(options.get("installed")),
            reduced_motion=bool(options.get("reduced_motion") or options.get("reducedMotion")),
        )
    return build_updates_chrome(
        os_status=str(options.get("os_status") or options.get("osStatus") or "Not measured"),
        bunny_status=str(options.get("bunny_status") or options.get("bunnyStatus") or "Not measured"),
        reduced_motion=bool(options.get("reduced_motion") or options.get("reducedMotion")),
    )
