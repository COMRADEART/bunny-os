# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The pcap analyzer, exercised on hand-crafted captures.

Every capture here is built byte by byte from the pcap and protocol layouts,
not with a packet library: the analyzer's whole value is its independence
from third-party dissectors, so its tests must not smuggle one in either.
The two packets used throughout are the two shapes QEMU user-mode networking
actually produces for an installed guest: a UDP DNS query to the emulated
resolver 10.0.2.3:53, and an outbound TCP SYN toward a public address.

The BLOCKED contract matters most: a truncated or missing capture must exit
2 and leave no record behind, because a record saying "no traffic" about a
capture that never happened is exactly the false comfort the adversarial
rules forbid.
"""

from __future__ import annotations

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

# The scripts directory is not a package (its parents carry dashes), so the
# analyzer is imported the same way its runner would: by path.
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "qualification" / "installed-system" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze_network_capture as anc  # noqa: E402


# --- byte-level builders ---------------------------------------------------

def pcap(*frames: bytes) -> bytes:
    """A little-endian microsecond pcap: magic 0xa1b2c3d4, linktype ethernet."""
    header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    records = b"".join(
        struct.pack("<IIII", 0, 0, len(frame), len(frame)) + frame
        for frame in frames
    )
    return header + records


def ethernet(payload: bytes, ethertype: int = 0x0800) -> bytes:
    return (b"\x52\x54\x00\x12\x34\x56" + b"\x52\x54\x00\x12\x34\x57"
            + struct.pack(">H", ethertype) + payload)


def ipv4(source: str, destination: str, protocol: int, payload: bytes) -> bytes:
    def packed(address: str) -> bytes:
        return bytes(int(octet) for octet in address.split("."))
    header = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 0, 0,
                         64, protocol, 0, packed(source), packed(destination))
    return header + payload


def udp(source_port: int, destination_port: int, payload: bytes) -> bytes:
    return struct.pack(">HHHH", source_port, destination_port,
                       8 + len(payload), 0) + payload


def tcp_syn(source_port: int, destination_port: int) -> bytes:
    # Data offset 5, flags SYN only — a connection attempt, not a reply.
    return struct.pack(">HHIIBBHHH", source_port, destination_port,
                       0, 0, 0x50, 0x02, 64240, 0, 0)


def dns_query(name: str) -> bytes:
    qname = b"".join(
        bytes([len(label)]) + label.encode("ascii") for label in name.split(".")
    ) + b"\x00"
    return struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + qname \
        + struct.pack(">HH", 1, 1)  # QTYPE A, QCLASS IN


def dns_frame(name: str = "example.com") -> bytes:
    return ethernet(ipv4("10.0.2.15", "10.0.2.3", 17,
                         udp(51515, 53, dns_query(name))))


def syn_frame(destination: str = "1.2.3.4", port: int = 443) -> bytes:
    return ethernet(ipv4("10.0.2.15", destination, 6, tcp_syn(49152, port)))


#: Fixture that names and justifies exactly the traffic the two frames make.
MATCHING_FIXTURE = [
    {"kind": "dns", "pattern": "example.com", "reason": "test resolver lookup"},
    {"kind": "udp", "pattern": "10.0.2.3:53", "reason": "emulated slirp resolver"},
    {"kind": "tcp", "pattern": "1.2.3.4:443", "reason": "expected update endpoint"},
]


def run_main(directory: Path, capture: bytes | None,
             fixture: list | None) -> tuple[int, Path]:
    """Drive the analyzer through its CLI, the way the runner will."""
    capture_path = directory / "guest.pcap"
    if capture is not None:
        capture_path.write_bytes(capture)
    output = directory / "record.json"
    argv = [str(capture_path), "--output", str(output)]
    if fixture is not None:
        fixture_path = directory / "expected.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        argv += ["--expected", str(fixture_path)]
    with contextlib.redirect_stdout(io.StringIO()):
        code = anc.main(argv)
    return code, output


class ParsingTests(unittest.TestCase):
    def test_dns_query_name_is_extracted(self) -> None:
        observed = anc.analyze_capture(pcap(dns_frame("example.com")))
        self.assertEqual(observed["dnsQueries"], ["example.com"])
        self.assertEqual(observed["destinations"], [{
            "protocol": "udp", "ip": "10.0.2.3", "port": 53,
            "packets": 1, "bytes": len(dns_frame("example.com")),
        }])

    def test_tcp_syn_destination_is_recorded(self) -> None:
        observed = anc.analyze_capture(pcap(syn_frame("1.2.3.4", 443)))
        self.assertEqual(observed["tcpSynDestinations"], ["1.2.3.4:443"])
        self.assertEqual(observed["destinations"][0]["protocol"], "tcp")
        self.assertEqual(observed["destinations"][0]["ip"], "1.2.3.4")
        self.assertEqual(observed["destinations"][0]["port"], 443)

    def test_totals_count_every_packet(self) -> None:
        frames = [dns_frame(), syn_frame()]
        observed = anc.analyze_capture(pcap(*frames))
        self.assertEqual(observed["totalPackets"], 2)
        self.assertEqual(observed["totalBytes"], sum(len(f) for f in frames))


class FixtureComparisonTests(unittest.TestCase):
    def test_unexpected_destination_is_flagged_when_fixture_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch),
                                    pcap(dns_frame(), syn_frame()), fixture=[])
            self.assertEqual(code, 1)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["result"], "FAIL")
            by_name = {a["name"]: a for a in record["assertions"]}
            self.assertEqual(by_name["no-unexpected-destinations"]["result"], "FAIL")
            self.assertIn("1.2.3.4:443", by_name["no-unexpected-destinations"]["observed"])
            self.assertEqual(by_name["no-dns-beyond-expected"]["result"], "FAIL")
            self.assertIn("example.com", by_name["no-dns-beyond-expected"]["observed"])

    def test_expected_destination_is_not_flagged_when_fixture_matches(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch),
                                    pcap(dns_frame(), syn_frame()),
                                    fixture=MATCHING_FIXTURE)
            self.assertEqual(code, 0)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["result"], "PASS")
            self.assertTrue(all(a["result"] == "PASS" for a in record["assertions"]))
            # The inventory is embedded even when everything is expected:
            # the record must show what was seen, not just that it was fine.
            self.assertEqual(record["observed"]["dnsQueries"], ["example.com"])
            self.assertEqual(record["observed"]["tcpSynDestinations"], ["1.2.3.4:443"])

    def test_partial_fixture_still_flags_the_unlisted_destination(self) -> None:
        # Allowing DNS must not quietly allow the TCP connection too.
        fixture = [entry for entry in MATCHING_FIXTURE if entry["kind"] != "tcp"]
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch),
                                    pcap(dns_frame(), syn_frame()), fixture=fixture)
            self.assertEqual(code, 1)
            record = json.loads(output.read_text(encoding="utf-8"))
            by_name = {a["name"]: a for a in record["assertions"]}
            self.assertEqual(by_name["no-unexpected-destinations"]["result"], "FAIL")
            self.assertEqual(by_name["no-dns-beyond-expected"]["result"], "PASS")


class EmptyAndCorruptCaptureTests(unittest.TestCase):
    def test_empty_but_valid_pcap_is_a_passing_zero_traffic_result(self) -> None:
        # A well-formed header with zero records is a real observation of
        # silence and must produce a PASS record, not a BLOCKED refusal.
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch), pcap(), fixture=[])
            self.assertEqual(code, 0)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["result"], "PASS")
            self.assertEqual(record["observed"]["totalPackets"], 0)
            self.assertEqual(record["observed"]["destinations"], [])
            for assertion in record["assertions"]:
                self.assertEqual(assertion["result"], "PASS")
                self.assertIn("no traffic observed", assertion["observed"])

    def test_truncated_global_header_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch), pcap()[:10], fixture=[])
            self.assertEqual(code, 2)
            # BLOCKED must leave no record: a half-written verdict about a
            # corrupt capture would be indistinguishable from evidence.
            self.assertFalse(output.exists())

    def test_missing_capture_file_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch), capture=None, fixture=[])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_truncated_packet_record_is_blocked(self) -> None:
        whole = pcap(dns_frame())
        with self.assertRaises(anc.CaptureError):
            anc.analyze_capture(whole[:-5])

    def test_unknown_magic_is_blocked(self) -> None:
        bogus = b"\x00\x01\x02\x03" + pcap()[4:]
        with self.assertRaises(anc.CaptureError):
            anc.analyze_capture(bogus)


class FixtureValidationTests(unittest.TestCase):
    def test_malformed_fixture_entry_is_blocked(self) -> None:
        # A typo'd fixture must refuse to run, not allow nothing/everything.
        bad = [{"kind": "tcp", "pattern": "1.2.3.4:443"}]  # reason missing
        with tempfile.TemporaryDirectory() as scratch:
            code, output = run_main(Path(scratch), pcap(syn_frame()), fixture=bad)
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
