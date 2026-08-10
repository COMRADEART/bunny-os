# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sentence-aware text chunks shared by local neural speech providers.

The canonical caption remains one bounded string.  Neural synthesis gets a
second, smaller bound because feeding several paragraphs to a model in one call
raises latency and makes cancellation unnecessarily coarse.  This module never
changes the words or invents punctuation; it only chooses boundaries.
"""

from __future__ import annotations

import re

__all__ = ["MAX_CHUNK_CHARACTERS", "MIN_CHUNK_CHARACTERS", "sentence_chunks"]


MIN_CHUNK_CHARACTERS = 24
MAX_CHUNK_CHARACTERS = 280

_BOUNDARY = re.compile(r"(?<=[.!?;])\s+")
_SOFT_BOUNDARY = re.compile(r"(?<=[,:])\s+")
_ABBREVIATIONS = frozenset({
    "dr.", "e.g.", "etc.", "i.e.", "jr.", "mr.", "mrs.", "ms.", "prof.",
    "sr.", "st.", "vs.",
})


def _ends_in_abbreviation(text: str) -> bool:
    tail = text.casefold().rsplit(" ", 1)[-1]
    if tail in _ABBREVIATIONS:
        return True
    # Initials and decimal numbers are not sentence endings.
    return bool(re.search(r"(?:\b[A-Za-z]|\d)\.$", text) and not re.search(r"[!?]$", text))


def _hard_split(text: str, maximum: int) -> list[str]:
    """Split one overlong sentence at words, preferring a soft boundary."""
    pieces: list[str] = []
    rest = text.strip()
    while len(rest) > maximum:
        window = rest[: maximum + 1]
        candidates = [match.end() for match in _SOFT_BOUNDARY.finditer(window)]
        boundary = candidates[-1] if candidates else window.rfind(" ")
        if boundary <= 0:
            boundary = maximum
        pieces.append(rest[:boundary].strip())
        rest = rest[boundary:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def sentence_chunks(
    text: str,
    *,
    minimum: int = MIN_CHUNK_CHARACTERS,
    maximum: int = MAX_CHUNK_CHARACTERS,
) -> tuple[str, ...]:
    """Return stable, sentence-aware chunks without altering the caption.

    Short adjacent sentences are coalesced until ``minimum`` is reached.  A
    sentence over ``maximum`` is split at comma/colon boundaries where possible,
    then at a word boundary.  Abbreviations and decimal-like endings are kept
    with the following text when practical.
    """
    if not isinstance(text, str):
        raise TypeError("speech text must be a string")
    if minimum < 1 or maximum < minimum:
        raise ValueError("chunk bounds must satisfy 1 <= minimum <= maximum")
    body = " ".join(text.split())
    if not body:
        return ()

    raw = _BOUNDARY.split(body)
    sentences: list[str] = []
    for part in raw:
        item = part.strip()
        if not item:
            continue
        if sentences and _ends_in_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {item}"
        else:
            sentences.append(item)

    bounded: list[str] = []
    for sentence in sentences:
        bounded.extend(_hard_split(sentence, maximum))

    chunks: list[str] = []
    pending = ""
    for item in bounded:
        combined = f"{pending} {item}".strip() if pending else item
        if pending and len(combined) > maximum:
            chunks.append(pending)
            pending = item
        else:
            pending = combined
        if len(pending) >= minimum and pending[-1:] in ".!?;":
            chunks.append(pending)
            pending = ""
    if pending:
        if chunks and len(pending) < minimum and len(chunks[-1]) + 1 + len(pending) <= maximum:
            chunks[-1] = f"{chunks[-1]} {pending}"
        else:
            chunks.append(pending)
    return tuple(chunks)
