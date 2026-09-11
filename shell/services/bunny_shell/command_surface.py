# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Universal command surface: Super+Space, character click, search entry.

Short answers stay in the companion bubble. Longer work opens a task card.
This module is the GTK/host twin of ``lib/commandSurface.js``.
"""

from __future__ import annotations

from dataclasses import dataclass

COMMAND_TRIGGERS = ("super-space", "character-click", "search-entry")
COMMAND_ACCELERATOR = "<Super>space"
_BUBBLE_CHAR_LIMIT = 220


def _sentence_count(value: str) -> int:
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return 0
    parts: list[str] = []
    buf = []
    for char in raw:
        buf.append(char)
        if char in ".!?":
            parts.append("".join(buf).strip())
            buf = []
    if buf and "".join(buf).strip():
        parts.append("".join(buf).strip())
    return len(parts)


def _limit_bubble(value: str, max_sentences: int = 3) -> str:
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return ""
    parts: list[str] = []
    buf: list[str] = []
    for char in raw:
        buf.append(char)
        if char in ".!?":
            parts.append("".join(buf).strip())
            buf = []
    if buf and "".join(buf).strip():
        parts.append("".join(buf).strip())
    if len(parts) <= max_sentences:
        return raw
    return " ".join(parts[:max_sentences])


@dataclass(frozen=True)
class CommandRoute:
    surface: str
    bubble_text: str
    task_title: str | None
    transcript: bool = False
    companion_required: bool = False


def route_command_answer(
    text: str,
    *,
    working: bool = False,
    stages: tuple[str, ...] = (),
    title: str = "",
) -> CommandRoute:
    original = " ".join(str(text or "").split()).strip()
    bubble = _limit_bubble(original)
    named = tuple(item for item in stages if str(item).strip())
    long = bool(working) or bool(named) or _sentence_count(original) > 3 or len(original) > _BUBBLE_CHAR_LIMIT
    return CommandRoute(
        surface="task-card" if long else "bubble",
        bubble_text=bubble or original,
        task_title=(title or "Working") if long else None,
        transcript=False,
        companion_required=False,
    )


@dataclass(frozen=True)
class CommandSurface:
    trigger: str
    query: str
    accelerator: str = COMMAND_ACCELERATOR
    companion_required: bool = False
    transcript: bool = False
    chatbot: bool = False
    accessible_name: str = "Search or ask Bunny"


def build_command_surface(*, trigger: str = "search-entry", query: str = "") -> CommandSurface:
    resolved = trigger if trigger in COMMAND_TRIGGERS else "search-entry"
    return CommandSurface(trigger=resolved, query=str(query or ""))
