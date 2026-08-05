# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral, data-only character presentation for Bunny Companion.

The package consumes the runtime core's task and event projections.  It does
not execute tasks, choose providers, grant approvals, or probe hardware.
"""

from __future__ import annotations

CHARACTER_PACKAGE_SCHEMA_VERSION = 1
CHARACTER_RENDERER_API_VERSION = "1.0"
MINIMUM_BUNNY_OS_VERSION = "0.1.0"

__all__ = [
    "CHARACTER_PACKAGE_SCHEMA_VERSION",
    "CHARACTER_RENDERER_API_VERSION",
    "MINIMUM_BUNNY_OS_VERSION",
]
