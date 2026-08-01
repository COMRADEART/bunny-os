#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Analyze a QEMU filter-dump pcap against an expected-traffic fixture.

The claim under qualification is "the installed system talks only to the
destinations we can name and justify". That claim is only as strong as the
analysis of the capture, so this analyzer is deliberately pure-stdlib: the
pcap record layout, ethernet/SLL framing, IPv4/IPv6 and TCP/UDP headers are
parsed by hand, and the DNS question section is decoded with a compact QNAME
walker. No scapy/dpkt means it runs on any builder that has python3, and the
byte-level layout it accepts is written down here rather than delegated.

The adversarial rule this file exists to enforce: a capture that never
started must not read as "no traffic". An *empty but well-formed* pcap (valid
global header, zero packet records) is a legitimate observation of silence
and evaluates normally. A missing file, an unrecognised magic, or a record
that runs off the end of the file is BLOCKED (exit 2) — corrupt evidence is
not evidence of anything, least of all of quietness.

Fixture format (--expected): a JSON list — or an object whose ``entries``
key holds the list — of ``{"kind": "dns"|"tcp"|"udp", "pattern": ...,
"reason": ...}``. ``pattern`` is an fnmatch glob matched against the query
name for ``dns`` and against ``ip:port`` for ``tcp``/``udp``. Every entry
must carry a non-empty reason: an allowance nobody can justify is not an
allowance. Anything observed that matches no entry is UNEXPECTED and fails
the corresponding assertion. IP traffic that is neither TCP nor UDP (ICMP,
unhandled IPv6 extension chains, ...) has no fixture kind that can allow it,
so it is always unexpected — fail closed and force a human to look.
Non-IP frames (ARP and friends) are tallied but not flagged: they are
link-local housekeeping inside the emulated 10.0.2.x segment and name no
destination host beyond it.

Exit codes: 0 all assertions PASS, 1 unexpected traffic observed, 2 BLOCKED.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any


class CaptureError(RuntimeError):
    """The capture file cannot be trusted enough to analyze."""


#: pcap global-header magic -> struct byte order of everything that follows.
#: Both the microsecond (a1b2c3d4) and nanosecond (a1b23c4d) variants appear,
#: each in either byte order depending on the writing host.
_MAGICS = {
    b"\xd4\xc3\xb2\xa1": "<",
    b"\x4d\x3c\xb2\xa1": "<",
    b"\xa1\xb2\xc3\xd4": ">",
    b"\xa1\xb2\x3c\x4d": ">",
}

LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101
LINKTYPE_SLL = 113
LINKTYPE_SLL2 = 276

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_IPV6 = 0x86DD
ETHERTYPE_VLAN = 0x8100

PROTO_TCP = 6
PROTO_UDP = 17


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "big")


def _u32le(data: bytes, offset: int, order: str) -> int:
    return int.from_bytes(data[offset:offset + 4], "little" if order == "<" else "big")


def _ipv4_address(raw: bytes) -> str:
    return ".".join(str(octet) for octet in raw)


def _ipv6_address(raw: bytes) -> str:
    # Uncompressed form is fine for an inventory; readability beats RFC 5952.
    return ":".join(f"{_u16(raw, index):x}" for index in range(0, 16, 2))


def parse_dns_queries(payload: bytes) -> list[str]:
    """Extract question names from a DNS message.

    Only the question section is walked. A compression pointer inside a
    question would be unusual for a query; rather than guess at an offset we
    stop, which under-reports names but never invents one. Under-reporting
    is acceptable here because the *destination* (port 53 somewhere) is
    still inventoried and still needs a fixture entry.
    """
    if len(payload) < 12:
        return []
    qdcount = _u16(payload, 4)
    names: list[str] = []
    offset = 12
    for _ in range(qdcount):
        labels: list[str] = []
        while True:
            if offset >= len(payload):
                return names
            length = payload[offset]
            if length == 0:
                offset += 1
                break
            if length & 0xC0:
                return names
            labels.append(payload[offset + 1:offset + 1 + length].decode("ascii", "replace"))
            offset += 1 + length
        names.append(".".join(labels))
        offset += 4  # QTYPE + QCLASS
    return names


def _layer3(linktype: int, frame: bytes) -> tuple[int | None, bytes]:
    """Strip the link-layer header; return (ethertype, network payload).

    Returns (None, b"") for a frame too short to carry its own link header —
    the caller counts it as undecoded rather than silently dropping it.
    """
    if linktype == LINKTYPE_ETHERNET:
        if len(frame) < 14:
            return None, b""
        ethertype = _u16(frame, 12)
        offset = 14
        if ethertype == ETHERTYPE_VLAN and len(frame) >= 18:
            ethertype = _u16(frame, 16)
            offset = 18
        return ethertype, frame[offset:]
    if linktype == LINKTYPE_SLL:
        if len(frame) < 16:
            return None, b""
        return _u16(frame, 14), frame[16:]
    if linktype == LINKTYPE_SLL2:
        if len(frame) < 20:
            return None, b""
        return _u16(frame, 0), frame[20:]
    if linktype == LINKTYPE_RAW:
        if not frame:
            return None, b""
        version = frame[0] >> 4
        return {4: ETHERTYPE_IPV4, 6: ETHERTYPE_IPV6}.get(version), frame
    raise CaptureError(f"unsupported pcap linktype {linktype}; the analyzer "
                       "knows ethernet (1), raw (101), SLL (113) and SLL2 (276)")


def analyze_capture(data: bytes) -> dict[str, Any]:
    """Parse pcap bytes into an observed-traffic inventory.

    Raises CaptureError for anything that undermines trust in the capture:
    short/unknown global header, a packet record header or body running off
    the end of the file. Zero packets after a valid header is a valid
    observation and returns an all-zero inventory.
    """
    if len(data) < 24:
        raise CaptureError(f"file is {len(data)} bytes; a pcap global header is 24")
    order = _MAGICS.get(data[:4])
    if order is None:
        raise CaptureError(f"unrecognised pcap magic {data[:4].hex()}")
    linktype = _u32le(data, 20, order) & 0x0FFFFFFF  # high nibbles: FCS metadata

    destinations: dict[tuple[str, str, int], dict[str, int]] = {}
    other_protocol: dict[tuple[int, str], int] = {}
    non_ip: dict[str, int] = {}
    dns_queries: set[str] = set()
    syn_destinations: set[str] = set()
    total_packets = 0
    total_bytes = 0
    undecoded = 0

    offset = 24
    while offset < len(data):
        if offset + 16 > len(data):
            raise CaptureError("packet record header is truncated")
        incl_len = _u32le(data, offset + 8, order)
        orig_len = _u32le(data, offset + 12, order)
        offset += 16
        if offset + incl_len > len(data):
            raise CaptureError("packet body runs past the end of the file")
        frame = data[offset:offset + incl_len]
        offset += incl_len
        total_packets += 1
        total_bytes += orig_len

        ethertype, network = _layer3(linktype, frame)
        if ethertype == ETHERTYPE_IPV4 and len(network) >= 20:
            header_length = (network[0] & 0x0F) * 4
            protocol = network[9]
            destination = _ipv4_address(network[16:20])
            transport = network[header_length:]
        elif ethertype == ETHERTYPE_IPV6 and len(network) >= 40:
            # Fixed header only; extension chains land in other_protocol
            # below, which is fail-closed (they can never match a fixture).
            protocol = network[6]
            destination = _ipv6_address(network[24:40])
            transport = network[40:]
        elif ethertype is None:
            undecoded += 1
            continue
        else:
            non_ip[f"0x{ethertype:04x}"] = non_ip.get(f"0x{ethertype:04x}", 0) + 1
            continue

        if protocol == PROTO_UDP and len(transport) >= 8:
            port = _u16(transport, 2)
            key = ("udp", destination, port)
            entry = destinations.setdefault(key, {"packets": 0, "bytes": 0})
            entry["packets"] += 1
            entry["bytes"] += orig_len
            if port == 53:
                dns_queries.update(parse_dns_queries(transport[8:]))
        elif protocol == PROTO_TCP and len(transport) >= 14:
            port = _u16(transport, 2)
            key = ("tcp", destination, port)
            entry = destinations.setdefault(key, {"packets": 0, "bytes": 0})
            entry["packets"] += 1
            entry["bytes"] += orig_len
            flags = transport[13]
            if flags & 0x02 and not flags & 0x10:  # SYN without ACK: an attempt
                syn_destinations.add(f"{destination}:{port}")
        else:
            other_protocol[(protocol, destination)] = \
                other_protocol.get((protocol, destination), 0) + 1

    return {
        "totalPackets": total_packets,
        "totalBytes": total_bytes,
        "linktype": linktype,
        "destinations": [
            {"protocol": protocol, "ip": ip, "port": port,
             "packets": tally["packets"], "bytes": tally["bytes"]}
            for (protocol, ip, port), tally in sorted(destinations.items())
        ],
        "dnsQueries": sorted(dns_queries),
        "tcpSynDestinations": sorted(syn_destinations),
        "otherProtocolDestinations": [
            {"ipProtocol": protocol, "ip": ip, "packets": count}
            for (protocol, ip), count in sorted(other_protocol.items())
        ],
        "nonIpFrames": dict(sorted(non_ip.items())),
        "undecodedPackets": undecoded,
    }


def load_fixture(path: Path) -> list[dict[str, str]]:
    """Load and validate the expected-traffic fixture; malformed is BLOCKED.

    Validation is strict because a typo in a fixture entry ("knid", an empty
    pattern) would silently allow nothing or everything; refusing to run is
    cheaper than a wrong verdict either way.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError(f"expected-traffic fixture {path} is unreadable: {exc}") from exc
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise CaptureError(f"{path} must be a list of entries or {{'entries': [...]}}")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get("kind") not in {"dns", "tcp", "udp"} \
                or not isinstance(entry.get("pattern"), str) or not entry["pattern"] \
                or not isinstance(entry.get("reason"), str) or not entry["reason"]:
            raise CaptureError(
                f"{path} entry {index} must be "
                "{kind: dns|tcp|udp, pattern: <glob>, reason: <non-empty>}")
    return entries


def evaluate(observed: dict[str, Any],
             entries: list[dict[str, str]]) -> tuple[list[dict[str, str]], str]:
    """Compare the inventory against the fixture; return (assertions, result)."""

    def allowed(kind: str, subject: str) -> bool:
        return any(entry["kind"] == kind and fnmatch.fnmatchcase(subject, entry["pattern"])
                   for entry in entries)

    unexpected_destinations = [
        f'{item["protocol"]}://{item["ip"]}:{item["port"]}'
        for item in observed["destinations"]
        if not allowed(item["protocol"], f'{item["ip"]}:{item["port"]}')
    ]
    # No fixture kind can justify ICMP or an unparsed extension chain, and an
    # undecoded packet could be hiding anything: all of them fail closed.
    unexpected_destinations += [
        f'ipproto-{item["ipProtocol"]}://{item["ip"]}'
        for item in observed["otherProtocolDestinations"]
    ]
    if observed["undecodedPackets"]:
        unexpected_destinations.append(
            f'{observed["undecodedPackets"]} undecodable packet(s): cannot rule out '
            "unexpected traffic inside them")

    unexpected_dns = [name for name in observed["dnsQueries"] if not allowed("dns", name)]

    quiet = observed["totalPackets"] == 0
    assertions = [
        {
            "name": "no-unexpected-destinations",
            "expected": "every observed destination matches an expected-traffic fixture entry",
            "observed": ("no traffic observed (0 packets in a valid capture)" if quiet
                         else (f"unexpected: {', '.join(unexpected_destinations)}"
                               if unexpected_destinations else
                               f"all {len(observed['destinations'])} destination(s) expected")),
            "result": "PASS" if not unexpected_destinations else "FAIL",
        },
        {
            "name": "no-dns-beyond-expected",
            "expected": "every DNS query name matches an expected-traffic fixture entry",
            "observed": ("no traffic observed (0 packets in a valid capture)" if quiet
                         else (f"unexpected queries: {', '.join(unexpected_dns)}"
                               if unexpected_dns else
                               f"all {len(observed['dnsQueries'])} quer(ies) expected")),
            "result": "PASS" if not unexpected_dns else "FAIL",
        },
    ]
    result = "PASS" if all(a["result"] == "PASS" for a in assertions) else "FAIL"
    return assertions, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analyze_network_capture")
    parser.add_argument("capture", type=Path,
                        help="pcap written by QEMU's filter-dump")
    parser.add_argument("--expected", type=Path, default=None,
                        help="expected-traffic fixture JSON; omitting it means "
                             "NOTHING is expected and any traffic fails")
    parser.add_argument("--output", required=True, type=Path,
                        help="where to write the evidence record")
    args = parser.parse_args(argv)

    # Adversarial rule: a capture that never started must not read as "no
    # traffic". Existence and header validity are preconditions for any
    # verdict at all, including the quiet one.
    if not args.capture.is_file():
        print(f"BLOCKED: capture {args.capture} does not exist. A capture that "
              "never started is not evidence of silence.", file=sys.stderr)
        return 2
    try:
        observed = analyze_capture(args.capture.read_bytes())
        entries = load_fixture(args.expected) if args.expected is not None else []
    except CaptureError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    limitations = [
        "capture reflects the guest's emulated NIC under QEMU user-mode "
        "networking; traffic the hypervisor itself originates is out of scope",
        "IPv6 extension-header chains are not traversed; such packets are "
        "inventoried by IP protocol number and always count as unexpected",
        "DNS names are read from question sections of queries to port 53; "
        "DNS over TCP or non-53 resolvers appear only as destinations",
    ]
    if args.expected is None:
        limitations.append("no expected-traffic fixture was supplied; every "
                           "observed destination is treated as unexpected")

    assertions, result = evaluate(observed, entries)
    document = {
        "schemaVersion": 1,
        "collection": "network-capture-analysis",
        "capture": args.capture.name,
        "expectedFixture": args.expected.name if args.expected else None,
        "assertions": assertions,
        "observed": observed,
        "limitations": limitations,
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"network capture analysis: {result}")
    print(f"  packets: {observed['totalPackets']}  bytes: {observed['totalBytes']}")
    for item in observed["destinations"]:
        print(f"  dest {item['protocol']} {item['ip']}:{item['port']} "
              f"({item['packets']} pkt, {item['bytes']} B)")
    for name in observed["dnsQueries"]:
        print(f"  dns  {name}")
    for target in observed["tcpSynDestinations"]:
        print(f"  syn  {target}")
    for assertion in assertions:
        print(f"  {assertion['result']:4} {assertion['name']}: {assertion['observed'][:110]}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
