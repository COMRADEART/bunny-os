# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quiet notification center with optional Bunny summary.

GNOME remains the freedesktop daemon. This is Bunny's own history: collapse
repeats, summarize Bunny chatter, keep lock-screen redaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

QUIET_DEFAULTS = {
    "quiet": True,
    "max_visible_toasts": 3,
    "max_history": 50,
    "collapse_window_ms": 8000,
    "bunny_summary": True,
    "sensitive_default": True,
}


@dataclass(frozen=True)
class FoldedNotice:
    source: str
    title: str
    body: str
    severity: str
    at: int
    count: int
    sensitive: bool


def _key(source: str, title: str) -> str:
    return f"{source}\n{title}"


def fold_notifications(
    items: Sequence[Mapping[str, Any]] | None,
    *,
    quiet: bool = True,
    bunny_summary: bool = True,
    now: int = 0,
) -> tuple[FoldedNotice, ...]:
    kept: list[FoldedNotice] = []
    seen: dict[str, int] = {}
    for raw in items or ():
        if not isinstance(raw, Mapping):
            continue
        severity = str(raw.get("severity") or "info")
        source = str(raw.get("source") or "Bunny")
        title = str(raw.get("title") or raw.get("body") or "Notification")
        body = str(raw.get("body") or "")
        stamp = int(raw.get("at") or now or 0)
        key = _key(source, title)
        if quiet and severity == "info":
            previous = seen.get(key)
            if previous is not None and stamp - previous <= QUIET_DEFAULTS["collapse_window_ms"] and kept:
                last = kept[-1]
                if _key(last.source, last.title.split(" (")[0]) == key or _key(last.source, last.title) == key:
                    count = last.count + 1
                    kept[-1] = FoldedNotice(
                        source=last.source,
                        title=f"{title} ({count})",
                        body=f"{title} ({count})" if bunny_summary and source == "Bunny" else last.body,
                        severity=last.severity,
                        at=last.at,
                        count=count,
                        sensitive=last.sensitive,
                    )
                    continue
            seen[key] = stamp
        kept.append(
            FoldedNotice(
                source=source,
                title=title,
                body=body,
                severity=severity,
                at=stamp,
                count=1,
                sensitive=raw.get("sensitive", True) is not False,
            )
        )
    return tuple(kept[-QUIET_DEFAULTS["max_history"]:])


def summarize_bunny(items: Sequence[FoldedNotice]) -> str | None:
    bunny = [item for item in items if item.source == "Bunny"]
    if not bunny:
        return None
    if len(bunny) == 1:
        return bunny[0].title
    errors = sum(1 for item in bunny if item.severity == "error")
    if errors:
        return f"Bunny: {len(bunny)} updates, {errors} need attention"
    return f"Bunny: {len(bunny)} updates"


def build_notification_center(
    items: Sequence[Mapping[str, Any]] | None = None,
    *,
    quiet: bool = True,
    bunny_summary: bool = True,
    do_not_disturb: bool = False,
) -> dict[str, Any]:
    folded = () if do_not_disturb else fold_notifications(
        items, quiet=quiet, bunny_summary=bunny_summary
    )
    return {
        "kind": "NotificationCenter",
        "quiet": quiet,
        "bunnySummary": bunny_summary,
        "doNotDisturb": do_not_disturb,
        "maxVisibleToasts": QUIET_DEFAULTS["max_visible_toasts"],
        "summary": summarize_bunny(folded) if bunny_summary else None,
        "items": [
            {"title": item.title, "body": item.body, "severity": item.severity, "source": item.source}
            for item in folded
        ],
        "emptyCopy": (
            "Do Not Disturb is on. Bunny is not showing notices."
            if do_not_disturb
            else "No notices. Bunny stays quiet unless something needs you."
        ),
        "spam": False,
        "companionRequired": False,
        "accessibleName": "Notification center",
    }


def should_toast(
    level: str,
    message: str,
    recent: Sequence[Mapping[str, Any]] | None = None,
    *,
    quiet: bool = True,
    now: int = 0,
) -> bool:
    if not quiet:
        return True
    if level in {"error", "warning"}:
        return True
    text = str(message or "")
    window = QUIET_DEFAULTS["collapse_window_ms"]
    for entry in recent or ():
        if (
            entry.get("level") == "info"
            and entry.get("message") == text
            and now - int(entry.get("at") or 0) < window
        ):
            return False
    return True
