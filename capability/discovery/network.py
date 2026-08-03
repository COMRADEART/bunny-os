# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interfaces, default route, connection type, metering and bounded reachability.

§1 of the brief and §17's performance requirement agree on one constraint that
shapes this whole module: **do not perform uncontrolled internet tests during
boot**. So the default pass is entirely local — sysfs and procfs — and answers
"is there a route at all" without emitting a packet.

Reachability is separate, opt-in, and bounded: a caller must pass explicit
endpoints, each gets one TCP connect with a short timeout, and nothing is sent
on the socket. No bandwidth measurement exists here at all, because an honest
one means moving real traffic and this subsystem has no mandate to spend a
user's metered allowance measuring itself.
"""

from __future__ import annotations

from pathlib import Path
import socket

from ..model import NetworkFacts, absent, measured, unknown
from .sources import Deadline, iter_directory, read_first_line, read_text, run, sanitize, which_allowed

__all__ = ["default_route_interface", "probe", "reachable"]

#: Interfaces that are never the answer to "is this machine on a network".
_IGNORED_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "podman", "cni", "flannel", "tailscale0")


def _interfaces() -> list[str]:
    return [
        entry.name for entry in iter_directory("/sys/class/net", limit=128)
        if not entry.name.startswith(_IGNORED_PREFIXES)
    ]


def default_route_interface() -> tuple[str | None, str]:
    """The interface carrying a default route, from procfs alone.

    ``/proc/net/route`` lists IPv4 routes with hex fields; a destination and
    mask of all zeros is the default route. IPv6 is checked separately because
    an IPv6-only machine is online and would otherwise be reported offline.
    """
    text = read_text("/proc/net/route", limit=64 * 1024)
    if text is not None:
        for line in text.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 8 and fields[1] == "00000000" and fields[7] == "00000000":
                return sanitize(fields[0], limit=32), "/proc/net/route"

    text = read_text("/proc/net/ipv6_route", limit=64 * 1024)
    if text is not None:
        for line in text.splitlines():
            fields = line.split()
            # destination network, prefix length, then the device in the last field
            if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00":
                return sanitize(fields[-1], limit=32), "/proc/net/ipv6_route"

    if text is None:
        return None, "/proc/net routing tables unreadable"
    return None, "no default route in the IPv4 or IPv6 routing table"


def _connection_type(interface: str) -> tuple[str | None, str]:
    base = Path("/sys/class/net") / interface
    if (base / "wireless").is_dir() or (base / "phy80211").exists():
        return "wireless", "sysfs phy80211"
    kind = read_first_line(base / "type")
    if kind == "1":
        return "wired", "sysfs type=1 (ethernet)"
    if kind is None:
        return None, "sysfs type unreadable"
    return None, f"unrecognised sysfs type {sanitize(kind, limit=8)}"


def _metered(deadline: Deadline) -> tuple[bool | None, str]:
    """Metering, from NetworkManager if it is present to be asked.

    There is no file-based source for this: metering is connection state that
    NetworkManager owns. ``nmcli`` is queried with a fixed, read-only,
    terse-output argument list. When NetworkManager is not installed the answer
    is ``unknown`` — and ``unknown`` must be treated as *possibly metered* by
    policy, which is what ``policy.metered_network_allowed`` does.
    """
    if which_allowed("/usr/bin/nmcli") is None:
        return None, "NetworkManager not installed; metering cannot be determined locally"
    result = run(["/usr/bin/nmcli", "-t", "-f", "GENERAL.METERED", "device", "show"], deadline=deadline, timeout=2.0)
    if not result.ok:
        return None, f"nmcli did not answer ({result.detail})"
    states = set()
    for line in result.stdout.splitlines()[:64]:
        _, _, value = line.partition(":")
        value = value.strip().lower()
        if value.startswith("yes"):
            states.add(True)
        elif value.startswith("no"):
            states.add(False)
    if True in states:
        return True, "nmcli reports at least one metered device"
    if False in states:
        return False, "nmcli reports no metered device"
    return None, "nmcli returned no metering state"


def reachable(endpoints: tuple[tuple[str, int], ...], *, timeout: float = 1.0) -> tuple[bool | None, float | None, str]:
    """One bounded TCP connect per endpoint. Nothing is sent.

    Returns ``(reachable, latency_ms, detail)``. This is never called unless a
    caller supplied endpoints, and callers are expected to supply endpoints the
    user has already configured — a provider they chose, a Bunny node they
    paired. It exists so that "a route exists" and "the thing we would offload
    to answers" stay separate facts, since a captive portal satisfies the first
    and fails the second.
    """
    if not endpoints:
        return None, None, "no endpoints configured; no probe was attempted"
    import time

    for host, port in endpoints[:4]:
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except (OSError, ValueError, socket.timeout):
            continue
        return True, round((time.monotonic() - start) * 1000, 1), f"connected to a configured endpoint on port {port}"
    return False, None, "no configured endpoint accepted a connection"


def probe(
    deadline: Deadline,
    *,
    endpoints: tuple[tuple[str, int], ...] = (),
    probe_reachability: bool = False,
) -> NetworkFacts:
    interfaces = _interfaces()
    if not Path("/sys/class/net").is_dir():
        interfaces_present = unknown("/sys/class/net", "not present")
        carrier = unknown("/sys/class/net")
    else:
        interfaces_present = measured(len(interfaces), "/sys/class/net")
        up = [
            name for name in interfaces
            if read_first_line(Path("/sys/class/net") / name / "carrier") == "1"
        ]
        carrier = measured(bool(up), "/sys/class/net carrier")

    interface, route_source = default_route_interface()
    if route_source.endswith("unreadable"):
        default_route = unknown("/proc/net", route_source)
    else:
        default_route = measured(interface is not None, route_source)

    if interface:
        kind, kind_source = _connection_type(interface)
        connection_type = measured(kind, "sysfs", kind_source) if kind else unknown("sysfs", kind_source)
    else:
        connection_type = absent("sysfs", "no default route, so no connection to classify")

    metered_value, metered_source = _metered(deadline)
    metered = (
        measured(metered_value, "nmcli", metered_source)
        if metered_value is not None
        else unknown("nmcli", metered_source)
    )

    if not probe_reachability:
        endpoint_reachable = unknown(
            "tcp connect",
            "reachability probing is opt-in and was not requested for this pass",
        )
        latency = unknown("tcp connect", "no probe was attempted")
    else:
        ok, latency_ms, detail = reachable(endpoints, timeout=min(1.0, deadline.remaining_seconds))
        if ok is None:
            endpoint_reachable = unknown("tcp connect", detail)
            latency = unknown("tcp connect", detail)
        else:
            endpoint_reachable = measured(ok, "tcp connect", detail)
            latency = measured(latency_ms, "tcp connect") if latency_ms is not None else unknown("tcp connect", detail)

    return NetworkFacts(
        interfaces_present=interfaces_present,
        carrier_up=carrier,
        default_route=default_route,
        connection_type=connection_type,
        metered=metered,
        endpoint_reachable=endpoint_reachable,
        latency_ms=latency,
        bandwidth_bits_per_second=unknown(
            "none",
            "no bandwidth probe exists: measuring it means moving real traffic, "
            "which this subsystem will not do on a user's connection",
        ),
    )
