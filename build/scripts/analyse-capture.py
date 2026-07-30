#!/usr/bin/env python3
"""Summarise a quiet-boot packet capture.

Parses libpcap format directly rather than depending on tcpdump, which is not
guaranteed on the builder and would add an unpinned tool to an evidence path.
The format is simple enough that a dependency is not worth it: a 24-byte global
header, then per-packet a 16-byte header and the frame.

Only what is needed to answer the privacy question is decoded: Ethernet, IPv4
and IPv6 headers, and TCP/UDP destination ports. Payloads are never inspected —
this asks *whether* a device talked to anyone, not what it said.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import struct
from typing import Any, Iterator

PCAP_MAGIC_LE = 0xA1B2C3D4
PCAP_MAGIC_BE = 0xD4C3B2A1
PCAP_MAGIC_LE_NANO = 0xA1B23C4D
PCAP_MAGIC_BE_NANO = 0x4D3CB2A1

#: QEMU user-mode networking. The guest sees 10.0.2.15, the gateway is
#: 10.0.2.2 and the built-in DNS resolver is 10.0.2.3. Traffic to these is the
#: emulator itself, not the outside world.
SLIRP_NETWORK = ipaddress.ip_network("10.0.2.0/24")

WELL_KNOWN_PORTS = {
    53: "dns",
    67: "dhcp-server",
    68: "dhcp-client",
    80: "http",
    123: "ntp",
    443: "https",
    5353: "mdns",
}


def _frames(data: bytes) -> Iterator[bytes]:
    if len(data) < 24:
        return
    (magic,) = struct.unpack("<I", data[:4])
    if magic in (PCAP_MAGIC_LE, PCAP_MAGIC_LE_NANO):
        endian = "<"
    elif magic in (PCAP_MAGIC_BE, PCAP_MAGIC_BE_NANO):
        endian = ">"
    else:
        raise ValueError(f"not a libpcap capture (magic {magic:#x})")
    offset = 24
    while offset + 16 <= len(data):
        _, _, captured, _ = struct.unpack(endian + "IIII", data[offset : offset + 16])
        offset += 16
        if captured <= 0 or offset + captured > len(data):
            break
        yield data[offset : offset + captured]
        offset += captured


def _decode(frame: bytes) -> dict[str, Any] | None:
    if len(frame) < 14:
        return None
    ethertype = struct.unpack("!H", frame[12:14])[0]
    payload = frame[14:]
    if ethertype == 0x0800 and len(payload) >= 20:
        header_length = (payload[0] & 0x0F) * 4
        protocol = payload[9]
        source = str(ipaddress.IPv4Address(payload[12:16]))
        destination = str(ipaddress.IPv4Address(payload[16:20]))
        transport = payload[header_length:]
    elif ethertype == 0x86DD and len(payload) >= 40:
        protocol = payload[6]
        source = str(ipaddress.IPv6Address(payload[8:24]))
        destination = str(ipaddress.IPv6Address(payload[24:40]))
        transport = payload[40:]
    elif ethertype == 0x0806:
        return {"protocol": "arp", "source": None, "destination": None, "port": None}
    else:
        return None

    port = None
    if protocol in (6, 17) and len(transport) >= 4:
        port = struct.unpack("!H", transport[2:4])[0]
    name = {6: "tcp", 17: "udp", 1: "icmp", 58: "icmpv6"}.get(protocol, str(protocol))
    return {"protocol": name, "source": source, "destination": destination, "port": port}


def _is_local(address: str | None) -> bool:
    if not address:
        return True
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    if parsed.version == 4:
        return parsed in SLIRP_NETWORK or parsed.is_multicast or parsed.is_unspecified
    return parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified or parsed.is_loopback


def analyse(capture: Path) -> dict[str, Any]:
    data = capture.read_bytes()
    total = 0
    protocols: dict[str, int] = {}
    external: dict[str, dict[str, Any]] = {}
    local_ports: dict[str, int] = {}

    for frame in _frames(data):
        decoded = _decode(frame)
        if decoded is None:
            continue
        total += 1
        protocols[decoded["protocol"]] = protocols.get(decoded["protocol"], 0) + 1
        destination = decoded["destination"]
        port = decoded["port"]
        if port is not None:
            label = WELL_KNOWN_PORTS.get(port, str(port))
            local_ports[label] = local_ports.get(label, 0) + 1
        if not _is_local(destination):
            key = f"{destination}:{port}" if port else str(destination)
            entry = external.setdefault(
                key,
                {
                    "destination": destination,
                    "port": port,
                    "service": WELL_KNOWN_PORTS.get(port or -1),
                    "packets": 0,
                },
            )
            entry["packets"] += 1

    findings = sorted(external.values(), key=lambda item: -item["packets"])
    return {
        "schemaVersion": 1,
        "capture": capture.name,
        "captureBytes": len(data),
        "framesDecoded": total,
        "protocolCounts": dict(sorted(protocols.items())),
        "observedPorts": dict(sorted(local_ports.items())),
        "externalDestinations": findings,
        "externalDestinationCount": len(findings),
        "quiet": not findings,
        "note": (
            "Destinations inside QEMU's 10.0.2.0/24 user-mode range are the emulator's own "
            "gateway and DNS resolver, not the outside world. Payloads were never inspected: "
            "this records whether the device contacted anyone, not what it said."
        ),
        "limitation": (
            "An idle freshly booted image is a narrow case. It says nothing about an installed "
            "system doing real work over days, which is what the production evidence row needs."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    report = analyse(arguments.capture)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"frames decoded      : {report['framesDecoded']}")
    print(f"protocols           : {report['protocolCounts']}")
    print(f"observed ports      : {report['observedPorts']}")
    print(f"external destinations: {report['externalDestinationCount']}")
    for entry in report["externalDestinations"]:
        print(f"  {entry['destination']}:{entry['port']} ({entry['service'] or 'unknown'}) x{entry['packets']}")
    print(f"wrote {arguments.output}")
    return 0 if report["quiet"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
