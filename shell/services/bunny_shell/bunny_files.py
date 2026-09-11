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
    FILE_OPEN_DENIED,
    FILE_OPEN_DRIFT,
    FILE_OPEN_EXPIRED,
    FILE_OPEN_FAILED,
    FILE_OPEN_GRANTED,
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


def granted_file_path(path: str) -> str:
    """The exact file Trust granted. Not a folder walk, not Pictures."""
    raw = str(path or "").strip()
    if not raw or "\n" in raw or "\0" in raw:
        return ""
    if any(token in raw for token in (";", "|", "`", "$(")):
        return ""
    if raw.casefold().startswith("file://"):
        rest = raw[7:]
        try:
            rest = unquote(rest)
        except Exception:  # noqa: BLE001 - malformed escape is not a grant
            return ""
        if not rest:
            return ""
        raw = rest if rest.startswith("/") else f"/{rest}"
    if not raw.startswith("/"):
        return ""
    return raw


_ONCE_GRANTS = frozenset({"allow", "allow-once", "allow once", "once", "granted"})
_DENY_VERDICTS = frozenset({
    "deny", "denied", "don't allow", "dont-allow", "dont allow",
    "close", "closed", "escape", "dismiss", "cancel",
})
_EXPIRED_VERDICTS = frozenset({"timeout", "expired"})
_BROADEN_VERDICTS = frozenset({
    "always", "session", "allow-session", "allow while using", "allow-while-using",
})
_DEFAULT_APP = frozenset({"", "an application", "application", "default"})


def _is_once_grant(decision: str) -> bool:
    return str(decision or "").strip().casefold() in _ONCE_GRANTS


def _normalize_application(application: str) -> str:
    token = str(application or "").strip()
    if token.casefold() in _DEFAULT_APP:
        return ""
    return token


def resolve_file_open_after_trust(
    *,
    decision: str = "deny",
    path: str = "",
    approved_path: str = "",
    application: str = "",
    approved_application: str = "",
    action: str = "open",
    extra_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Plan the open. Deny-by-default. One file + app. Nothing uploaded."""
    del extra_paths  # never widened — Pictures and siblings stay closed
    offered = granted_file_path(path)
    approved = granted_file_path(approved_path or path)
    offered_app = _normalize_application(application)
    approved_app = _normalize_application(approved_application or application)
    token = str(decision or "").strip().casefold()
    once = token in _ONCE_GRANTS
    closed = {
        "shouldOpen": False,
        "uploaded": False,
        "path": "",
        "application": "",
        "command": None,
        "companionRequired": False,
        "chatbot": False,
        "note": FILE_NOT_UPLOADED,
    }
    if str(action or "open") != "open":
        return {
            **closed,
            "message": FILE_OPEN_DENIED if not once else "Allow once is recorded for this request.",
        }
    if token in _EXPIRED_VERDICTS:
        return {**closed, "message": FILE_OPEN_EXPIRED}
    if token in _DENY_VERDICTS or token in _BROADEN_VERDICTS or not once:
        return {**closed, "message": FILE_OPEN_DENIED}
    if not offered or not approved or offered != approved or offered_app != approved_app:
        return {**closed, "message": FILE_OPEN_DRIFT if (approved or approved_app) else FILE_OPEN_FAILED}
    return {
        "shouldOpen": True,
        "uploaded": False,
        "path": approved,
        "application": approved_app,
        "command": ["gio", "open", approved],
        "companionRequired": False,
        "chatbot": False,
        "note": FILE_NOT_UPLOADED,
        "message": FILE_OPEN_GRANTED,
    }


def apply_file_open_after_trust(
    *,
    decision: str = "deny",
    path: str = "",
    approved_path: str = "",
    application: str = "",
    approved_application: str = "",
    action: str = "open",
    extra_paths: Sequence[str] | None = None,
    opener: Any = None,
) -> dict[str, Any]:
    """Grant opens that file + app. Deny / close / timeout open nothing."""
    plan = resolve_file_open_after_trust(
        decision=decision,
        path=path,
        approved_path=approved_path,
        application=application,
        approved_application=approved_application,
        action=action,
        extra_paths=extra_paths,
    )
    if not plan["shouldOpen"]:
        return {**plan, "launched": False, "paths": []}
    launched = False
    if callable(opener):
        try:
            launched = opener(plan["command"], plan["path"], plan["application"]) is True
        except TypeError:
            try:
                launched = opener(plan["command"], plan["path"]) is True
            except Exception:  # noqa: BLE001 - a failed handler is a failed open
                launched = False
        except Exception:  # noqa: BLE001 - a failed handler is a failed open
            launched = False
    return {
        **plan,
        "launched": launched,
        "paths": [plan["path"]] if launched else [],
        "message": FILE_OPEN_GRANTED if launched else FILE_OPEN_FAILED,
    }


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
        "application": application,
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
        "application": application,
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
