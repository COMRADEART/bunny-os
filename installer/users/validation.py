# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate a conventional least-privilege Linux user plan."""

from __future__ import annotations

import re
from typing import Mapping


USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SECRET_REFERENCE = re.compile(r"^(fd:[3-9][0-9]*|installer-secret:[A-Za-z0-9_-]{16,64})$")
RESERVED = frozenset({"root", "bin", "daemon", "nobody", "bunny", "bunny-live"})


def validate_user_plan(value: Mapping[str, object]) -> tuple[str, ...]:
    errors: list[str] = []
    username = value.get("username")
    display = value.get("displayName")
    reference = value.get("passwordSecretRef")
    if not isinstance(username, str) or not USERNAME.fullmatch(username) or username in RESERVED:
        errors.append("invalid or reserved username")
    if not isinstance(display, str) or not display.strip() or len(display) > 128 or any(ord(character) < 32 for character in display):
        errors.append("invalid display name")
    if not isinstance(reference, str) or not SECRET_REFERENCE.fullmatch(reference):
        errors.append("protected password secret reference is required")
    if value.get("administrator") is not True:
        errors.append("the first user requires conventional administrative elevation")
    if value.get("autologin") is not False:
        errors.append("automatic login is off by default")
    forbidden_groups = value.get("groups", [])
    if forbidden_groups not in ([], ()):
        errors.append("extra groups are not accepted in the installer plan")
    return tuple(errors)

