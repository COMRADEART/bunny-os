# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only system facts and a closed MPRIS control surface.

These are ordinary ToolBroker tools, not shortcuts around the assistant.  The
planner can name one of three metrics or one of three media commands; the tool
validates that enum again and performs no shell execution.  Metric answers are
measured locally at invocation time, so a model can never supply or guess the
number shown to the user.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping

from .tools import ToolDeclaration, ToolOutcome

__all__ = [
    "GET_SYSTEM_METRIC",
    "LOCAL_SYSTEM_TOOLS",
    "MEDIA_CONTROL",
    "MprisController",
    "get_system_metric",
    "media_control",
]

SYSTEM_METRICS = ("memory", "storage", "wifi")
MEDIA_COMMANDS: Mapping[str, str] = {
    "pause": "Pause",
    "play": "Play",
    "next": "Next",
}


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for suffix in ("bytes", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or suffix == "TiB":
            if suffix == "bytes":
                return f"{int(amount)} {suffix}"
            return f"{amount:.1f} {suffix}"
        amount /= 1024.0
    return f"{amount:.1f} TiB"


def _memory_metric(meminfo: Path = Path("/proc/meminfo")) -> tuple[bool, str, str]:
    try:
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="ascii", errors="strict").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            fields = raw.strip().split()
            if not fields or not fields[0].isdigit():
                continue
            multiplier = 1024 if len(fields) > 1 and fields[1].casefold() == "kb" else 1
            values[key] = int(fields[0]) * multiplier
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        if total <= 0 or not 0 <= available <= total:
            return False, "", "the kernel did not report usable memory totals"
        used = total - available
        percent = round(used / total * 100)
        return True, f"You are using {_format_bytes(used)} of {_format_bytes(total)} of memory ({percent}%).", ""
    except OSError as exc:
        return False, "", f"memory telemetry is unavailable: {exc.strerror or exc}"


def _storage_metric(home: Path | None = None) -> tuple[bool, str, str]:
    # HOME is the authoritative per-session location on Linux. Consulting it
    # explicitly also keeps the metric usable in constrained test/session
    # environments where platform-specific home discovery points outside the
    # process's readable namespace.
    target = home or Path(os.environ.get("HOME") or Path.home())
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return False, "", f"storage telemetry is unavailable: {exc.strerror or exc}"
    used = usage.total - usage.free
    percent = round(used / usage.total * 100) if usage.total else 0
    return True, (
        f"Your home storage has {_format_bytes(usage.free)} free of "
        f"{_format_bytes(usage.total)} ({percent}% used)."
    ), ""


def _wifi_metric(network_root: Path = Path("/sys/class/net")) -> tuple[bool, str, str]:
    try:
        interfaces = sorted(network_root.iterdir())
    except OSError as exc:
        return False, "", f"network telemetry is unavailable: {exc.strerror or exc}"
    wireless: list[tuple[str, str]] = []
    for interface in interfaces:
        if not (interface / "wireless").exists():
            continue
        try:
            state = (interface / "operstate").read_text(encoding="ascii").strip().casefold()
        except OSError:
            state = "unknown"
        wireless.append((interface.name, state))
    if not wireless:
        return True, "This machine does not currently expose a Wi-Fi interface.", ""
    connected = [name for name, state in wireless if state == "up"]
    if connected:
        return True, f"Wi-Fi is connected through {connected[0]}.", ""
    if any(state == "unknown" for _name, state in wireless):
        return True, "A Wi-Fi interface is present, but its connection state is unavailable.", ""
    return True, "Wi-Fi is not connected.", ""


def get_system_metric(
    arguments: Mapping[str, Any],
    *,
    memory_reader: Callable[[], tuple[bool, str, str]] = _memory_metric,
    storage_reader: Callable[[], tuple[bool, str, str]] = _storage_metric,
    wifi_reader: Callable[[], tuple[bool, str, str]] = _wifi_metric,
) -> ToolOutcome:
    metric = arguments.get("metric", "")
    if not isinstance(metric, str) or metric not in SYSTEM_METRICS:
        return ToolOutcome("system.get_metric", False, detail="that system metric is not permitted")
    readers = {"memory": memory_reader, "storage": storage_reader, "wifi": wifi_reader}
    ok, sentence, detail = readers[metric]()
    return ToolOutcome("system.get_metric", ok, value=sentence if ok else None, detail=detail)


class MprisController:
    """Select and control one session MPRIS player through fixed D-Bus calls."""

    PREFIX = "org.mpris.MediaPlayer2."
    OBJECT = "/org/mpris/MediaPlayer2"
    PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

    @staticmethod
    def _gio() -> Any:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # type: ignore

        return Gio

    def control(self, command: str) -> tuple[bool, str]:
        method = MEDIA_COMMANDS.get(command)
        if method is None:
            return False, "that media command is not permitted"
        try:
            Gio = self._gio()
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            reply = connection.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "ListNames", None, None,
                Gio.DBusCallFlags.NONE, 2_000, None,
            )
            names = sorted(
                name for name in reply.unpack()[0]
                if isinstance(name, str) and name.startswith(self.PREFIX)
            )
            if not names:
                return False, "there is no active MPRIS media player"

            ranked: list[tuple[int, str]] = []
            for name in names:
                try:
                    status_reply = connection.call_sync(
                        name, self.OBJECT, "org.freedesktop.DBus.Properties", "Get",
                        self._variant("(ss)", (self.PLAYER_IFACE, "PlaybackStatus")),
                        None, Gio.DBusCallFlags.NONE, 1_000, None,
                    )
                    unpacked = status_reply.unpack()[0]
                    status = str(unpacked.unpack() if hasattr(unpacked, "unpack") else unpacked)
                except Exception:  # noqa: BLE001 - one broken player does not hide another
                    status = "Stopped"
                rank = 0 if status == "Playing" else 1 if status == "Paused" else 2
                ranked.append((rank, name))
            _rank, selected = min(ranked)
            connection.call_sync(
                selected, self.OBJECT, self.PLAYER_IFACE, method,
                None, None, Gio.DBusCallFlags.NONE, 2_000, None,
            )
            return True, ""
        except Exception as exc:  # noqa: BLE001 - session bus/player absence is normal
            return False, str(exc)

    def _variant(self, signature: str, value: Any) -> Any:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib  # type: ignore

        return GLib.Variant(signature, value)


def media_control(
    arguments: Mapping[str, Any],
    *,
    controller: MprisController | None = None,
) -> ToolOutcome:
    command = arguments.get("command", "")
    if not isinstance(command, str) or command not in MEDIA_COMMANDS:
        return ToolOutcome("media.control", False, detail="that media command is not permitted")
    ok, detail = (controller or MprisController()).control(command)
    sentence = {
        "pause": "Media is paused.",
        "play": "Media is playing.",
        "next": "I skipped to the next track.",
    }[command]
    return ToolOutcome("media.control", ok, value=sentence if ok else None, detail=detail)


GET_SYSTEM_METRIC = ToolDeclaration(
    "system.get_metric",
    "Read a current local memory, storage or Wi-Fi metric",
)

MEDIA_CONTROL = ToolDeclaration(
    "media.control",
    "Send play, pause or next to the active MPRIS player",
    interrupts_user=True,
)

LOCAL_SYSTEM_TOOLS: Mapping[str, tuple[ToolDeclaration, Callable[..., ToolOutcome]]] = {
    "system.get_metric": (GET_SYSTEM_METRIC, get_system_metric),
    "media.control": (MEDIA_CONTROL, media_control),
}
