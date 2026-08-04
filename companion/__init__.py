# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Companion runtime contracts and provider-neutral coordination."""

from __future__ import annotations

COMPANION_STATE_SCHEMA_VERSION = 1
TASK_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
CHARACTER_PACKAGE_SCHEMA_VERSION = 1
PROTOCOL_SCHEMA_VERSION = 1

__all__ = [
    "CHARACTER_PACKAGE_SCHEMA_VERSION",
    "COMPANION_STATE_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "PROTOCOL_SCHEMA_VERSION",
    "TASK_SCHEMA_VERSION",
]
