"""Local-only/offline policy decisions consumed by Bunny Shell clients."""

from __future__ import annotations

from typing import Any

from .settings import SettingsStore


NETWORK_KINDS = {"cloud_provider", "remote_embedding", "remote_transcription", "external_model_api", "plugin_network", "os_update", "remote_integration"}


def evaluate(kind: str, *, destination: str | None = None, plugin_exempt: bool = False, settings: SettingsStore | None = None) -> dict[str, Any]:
    if kind not in NETWORK_KINDS | {"loopback", "local_model"}:
        return {"allowed": False, "reason": "unknown_action", "enforced": True}
    values = (settings or SettingsStore()).get_all()
    if kind in {"loopback", "local_model"}:
        return {"allowed": True, "reason": "local_resource", "enforced": True}
    if values["offlineMode"]:
        if kind == "plugin_network" and plugin_exempt:
            return {"allowed": True, "reason": "explicit_offline_plugin_exemption", "enforced": True}
        return {"allowed": False, "reason": "offline_mode", "enforced": True}
    if values["localOnlyMode"] and kind in {"cloud_provider", "remote_embedding", "remote_transcription", "external_model_api"}:
        return {"allowed": False, "reason": "local_only_mode", "enforced": True}
    if kind == "plugin_network" and values["pluginNetworkDefault"] == "deny" and not plugin_exempt:
        return {"allowed": False, "reason": "plugin_network_not_granted", "enforced": True}
    return {"allowed": True, "reason": "policy_allows", "enforced": True, "destination": destination}
