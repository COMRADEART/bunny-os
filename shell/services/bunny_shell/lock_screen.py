# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Companion-aware login and lock chrome.

GDM remains the stock Fedora greeter. This module is the Bunny session lock
and a first-login overlay model: the figure may sit in the corner, and the
OS still unlocks if the figure is hidden or fails to draw.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core_state import notifications_for_lock_screen

LOCK_PASSWORD_NAME = "Password"
LOGIN_PASSWORD_NAME = "Password"
COMPANION_CORNER = "bottom-right"

LOCK_SUMMARY = "Unlock this computer. Bunny is optional."
LOGIN_SUMMARY = "Sign in. Bunny is optional. The desktop works without the figure."


def _companion_visible(*, hidden: bool, failed: bool) -> bool:
    return not hidden and not failed


def _redacted_notices(
    snapshot: Mapping[str, Any] | None = None,
    notices: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if snapshot is not None:
        try:
            return notifications_for_lock_screen(dict(snapshot))
        except (ValueError, TypeError, PermissionError):
            return []
    projected: list[dict[str, Any]] = []
    for item in notices or ():
        if not isinstance(item, Mapping):
            continue
        source = str(item.get("source") or "Application")[:80]
        if item.get("sensitive", True):
            projected.append({
                "source": source,
                "title": "Sensitive notification",
                "body": "",
                "actions": [],
            })
        else:
            projected.append({
                "source": source,
                "title": str(item.get("title") or "Notification")[:160],
                "body": "",
                "actions": [],
            })
    return projected


def build_lock_screen(
    *,
    user: str = "you",
    clock: str = "",
    companion_hidden: bool = False,
    companion_failed: bool = False,
    snapshot: Mapping[str, Any] | None = None,
    notices: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    visible = _companion_visible(hidden=companion_hidden, failed=companion_failed)
    return {
        "kind": "LockScreen",
        "title": "Locked",
        "summary": LOCK_SUMMARY,
        "user": str(user or "you"),
        "clock": str(clock or ""),
        "passwordAccessibleName": LOCK_PASSWORD_NAME,
        "companionVisible": visible,
        "companionAnchor": COMPANION_CORNER,
        "companionRequired": False,
        "companionFailed": bool(companion_failed),
        "unlockWithoutCompanion": True,
        "usableWithoutCompanion": True,
        "trustOnLock": False,
        "chatbot": False,
        "gdmBranding": False,
        "notifications": _redacted_notices(snapshot, notices),
        "initialFocus": "password",
        "canFocus": True,
        "styleClass": "bunny-lock-screen",
        "accessibleName": "Bunny lock screen",
        "questions": (
            "What am I doing?",
            "What is Bunny doing?",
            "What can I do next?",
        ),
        "next": "Type your password and press Return. Super+L locks again after you unlock.",
    }


def build_login_screen(
    *,
    user: str = "",
    companion_hidden: bool = False,
    companion_failed: bool = False,
) -> dict[str, Any]:
    visible = _companion_visible(hidden=companion_hidden, failed=companion_failed)
    return {
        "kind": "LoginScreen",
        "title": "Sign in",
        "summary": LOGIN_SUMMARY,
        "user": str(user or ""),
        "passwordAccessibleName": LOGIN_PASSWORD_NAME,
        "companionVisible": visible,
        "companionAnchor": COMPANION_CORNER,
        "companionRequired": False,
        "companionFailed": bool(companion_failed),
        "unlockWithoutCompanion": True,
        "usableWithoutCompanion": True,
        "trustOnLock": False,
        "chatbot": False,
        "gdmBranding": False,
        "stockGreeter": True,
        "initialFocus": "password",
        "canFocus": True,
        "styleClass": "bunny-login-screen",
        "accessibleName": "Bunny sign-in",
        "questions": (
            "What am I doing?",
            "What is Bunny doing?",
            "What can I do next?",
        ),
        "next": "Sign in with your account. Bunny waits in the corner after first-run, or stays hidden.",
    }
