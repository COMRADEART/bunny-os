"""Shared library for the experimental Bunny Wayland shell (Visual Phase V3).

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.
"""

from __future__ import annotations

NOTICE_LINES = (
    "BUNNY WAYLAND SHELL EXPERIMENT",
    "NOT RELEASE QUALIFIED",
    "DO NOT USE AS THE DEFAULT SESSION",
)

NOTICE = "\n".join(NOTICE_LINES)

__all__ = ["NOTICE", "NOTICE_LINES"]
