# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Files: companion-aware file flows. Trust for opens. Not a chatbot.

Host twin of ``lib/bunnyFiles.js``. Nautilus remains the file browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import unquote

from .command_surface import route_command_answer
from .trust_copy import (
    ALLOW_ONCE_LABEL,
    DONT_ALLOW_LABEL,
    FILE_NOT_UPLOADED,
    FILE_OPEN_BUBBLE,
    FILE_OPEN_HEADLINE,
    NETWORK_ALLOWLIST_NOTE,
)

FILE_ACTIONS = ("ask", "summarise", "workspace", "provenance", "checkpoint", "open")
FILE_ACTION_LABELS = {
    "ask": "Ask Bunny about this file",
    "summarise": "Summarise with Bunny",
    "workspace": "Open in Bunny workspace",
    "provenance": "Show provenance",
    "checkpoint": "Create checkpoint before changes",
    "open": "Open",
}
_BUBBLE_ACTIONS = frozenset({"ask", "provenance"})
_TASK_ACTIONS = frozenset({"summarise", "workspace", "checkpoint"})


def _file_name(path: str) -> str:
    raw = str(path or "").replace("file://", "").strip()
    if not raw:
        return ""
    parts = [part for part in raw.split("/") if part]
    return parts[-1] if parts else raw


def parse_files_uri(uri: str) -> dict[str, Any]:
    text = str(uri or "").strip()
    prefix = "bunny://files/"
    if not text.lower().startswith(prefix):
        return {"valid": False, "action": "", "paths": [], "companionRequired": False}
    rest = text[len(prefix) :]
    action, _, query = rest.partition("?")
    action = action.strip().casefold()
    selection = ""
    if query.startswith("selection="):
        selection = query[len("selection=") :]
    try:
        decoded = unquote(selection)
    except Exception:  # noqa: BLE001 - malformed escape stays empty
        decoded = selection
    paths = [item.strip() for item in decoded.split("\n") if item.strip()]
    valid = action in FILE_ACTIONS
    return {
        "valid": valid,
        "action": action if valid else "",
        "paths": paths,
        "companionRequired": False,
        "chatbot": False,
    }


def file_open_needs_trust(*, action: str = "open", approved_location: bool = False) -> bool:
    if action == "open":
        return True
    if action == "checkpoint":
        return True
    return (not approved_location) and action == "workspace"


def build_file_open_trust(
    *,
    path: str = "",
    application: str = "an application",
    request_id: str = "file-open",
    cloud_context: str = "none",
    offering_remote_dispatch: bool = False,
    network: str = "Off",
) -> dict[str, Any]:
    name = _file_name(path) or "this file"
    heading = f"Bunny wants to open {name} in {application}" if application else FILE_OPEN_HEADLINE
    return {
        "kind": "TrustPrompt",
        "source": "files",
        "requestId": request_id,
        "heading": heading,
        "category": "files",
        "resource": str(path or name),
        "focusSafeAnswer": True,
        "allowLabel": ALLOW_ONCE_LABEL,
        "denyLabel": DONT_ALLOW_LABEL,
        "bubbleText": FILE_OPEN_BUBBLE,
        "note": FILE_NOT_UPLOADED,
        "network": network,
        "networkHonesty": NETWORK_ALLOWLIST_NOTE,
        "cloudContext": cloud_context,
        "offeringRemoteDispatch": bool(offering_remote_dispatch),
        "chatbot": False,
        "transcript": False,
        "companionRequired": False,
    }


def _caption(action: str, paths: Sequence[str]) -> str:
    count = len(paths)
    first = _file_name(paths[0]) if paths else "this file"
    if action == "ask":
        if count > 1:
            return f"Ask Bunny about {count} files. Nothing is uploaded."
        return f"Ask Bunny about {first}. Nothing is uploaded."
    if action == "summarise":
        return f"Summarise {first} here. Longer notes open a task card."
    if action == "workspace":
        return f"Attach {first} to a Bunny workspace. Files stay on this computer."
    if action == "provenance":
        return f"Provenance for {first}."
    if action == "checkpoint":
        return f"Checkpoint before changing {first}."
    return f"Open {first}. Review the request."


@dataclass(frozen=True)
class FilesRoute:
    action: str
    paths: tuple[str, ...]
    surface: str
    needs_trust: bool
    bubble_text: str
    transcript: bool = False
    chatbot: bool = False
    companion_required: bool = False
    uploaded: bool = False


def route_files_action(
    *,
    action: str = "ask",
    paths: Sequence[str] | None = None,
    application: str = "",
    approved_location: bool = True,
    cloud_context: str = "none",
    offering_remote_dispatch: bool = False,
) -> dict[str, Any]:
    resolved = action if action in FILE_ACTIONS else "ask"
    listed = tuple(str(item) for item in (paths or ()) if str(item).strip())
    needs_trust = file_open_needs_trust(action=resolved, approved_location=approved_location)
    caption = _caption(resolved, listed)
    routed = route_command_answer(caption, working=resolved in _TASK_ACTIONS, title=FILE_ACTION_LABELS[resolved])
    surface = "trust" if needs_trust else ("bubble" if resolved in _BUBBLE_ACTIONS else routed.surface)
    return {
        "action": resolved,
        "paths": list(listed),
        "surface": surface,
        "needsTrust": needs_trust,
        "bubbleText": FILE_OPEN_BUBBLE if needs_trust else caption,
        "trust": build_file_open_trust(
            path=listed[0] if listed else "",
            application=application,
            cloud_context=cloud_context,
            offering_remote_dispatch=offering_remote_dispatch,
        )
        if needs_trust
        else None,
        "transcript": False,
        "chatbot": False,
        "companionRequired": False,
        "uploaded": False,
        "note": FILE_NOT_UPLOADED,
    }


def build_bunny_files(
    *,
    locations: Sequence[Mapping[str, Any] | str] | None = None,
    entries: Sequence[Mapping[str, Any] | str] | None = None,
    query: str = "",
    reduced_motion: bool = False,
) -> dict[str, Any]:
    rows = []
    for index, entry in enumerate(list(entries or ())[:40]):
        item = dict(entry) if isinstance(entry, Mapping) else {"path": entry}
        path = str(item.get("path") or item.get("uri") or "")
        rows.append({
            "id": f"file-{index}",
            "title": str(item.get("name") or _file_name(path) or path),
            "subtitle": path,
            "kind": str(item.get("kind") or "file"),
            "path": path,
            "canFocus": True,
        })
    places = []
    for item in locations or ():
        rec = dict(item) if isinstance(item, Mapping) else {"path": item}
        places.append({"path": str(rec.get("path") or ""), "enabled": rec.get("enabled", True) is not False})
    return {
        "kind": "BunnyFiles",
        "title": "Bunny Files",
        "summary": "Approved folders and companion actions. Nautilus still browses. Opens need Trust.",
        "query": str(query or ""),
        "locations": places,
        "rows": rows,
        "actions": list(FILE_ACTIONS),
        "companionRequired": False,
        "chatbot": False,
        "transcript": False,
        "nautilusIsBrowser": True,
        "uploaded": False,
        "note": FILE_NOT_UPLOADED,
        "networkHonesty": NETWORK_ALLOWLIST_NOTE,
        "reducedMotion": bool(reduced_motion),
        "motionMs": 0 if reduced_motion else 220,
        "accessibleName": "Bunny Files",
        "canFocus": True,
    }
