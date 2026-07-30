# SPDX-License-Identifier: GPL-3.0-or-later
"""Flatpak-first application policy with honest enforcement labels."""

from __future__ import annotations

from typing import Iterable


PERMISSIONS = frozenset({"filesystem", "camera", "microphone", "location", "network", "devices", "background", "notifications", "screen_capture"})


def application_record(*, app_id: str, source: str, permissions: Iterable[str], verified_publisher: bool | None = None) -> dict[str, object]:
    if source not in {"bunny-system", "bunny-verified", "flatpak", "native", "developer", "web"}:
        raise ValueError("unknown application source")
    unique = sorted(set(permissions))
    unknown = sorted(set(unique) - PERMISSIONS)
    if unknown:
        raise ValueError("unknown permissions: " + ", ".join(unknown))
    enforceable = source == "flatpak"
    return {
        "schemaVersion": 1,
        "applicationId": app_id,
        "source": source,
        "verifiedPublisher": verified_publisher,
        "permissions": [{"name": name, "enforcement": "sandbox/portal" if enforceable else "Not enforced by this package format"} for name in unique],
        "broadFilesystemByDefault": False,
    }


def remote_plan(*, name: str, url: str, explicit_user_choice: bool, signatureConfigured: bool) -> dict[str, object]:
    if not url.startswith("https://"):
        raise ValueError("application remotes require HTTPS")
    if name.lower() == "flathub" and not explicit_user_choice:
        raise ValueError("Flathub requires explicit user choice")
    if not signatureConfigured:
        raise ValueError("remote signature trust is not configured")
    return {"name": name, "url": url, "scope": "user", "enabled": True, "explicitUserChoice": explicit_user_choice}


def developer_environment(*, project: str, privileged: bool = False) -> dict[str, object]:
    if privileged:
        raise ValueError("automatic privileged development containers are forbidden")
    return {"backend": "rootless-podman", "project": project, "privileged": False, "bunnyContainerSocketAccess": False, "storageQuotaRequired": True}

