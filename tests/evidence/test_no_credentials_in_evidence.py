# SPDX-License-Identifier: GPL-3.0-or-later
"""No credential material is written into the evidence tree.

Evidence in this project is immutable: a record that turns out to be wrong is
retained byte-for-byte and reclassified rather than edited (see
``test_invalidated_evidence``). That rule and a leaked secret compose badly —
a credential committed into ``qualification/`` cannot be scrubbed later without
breaking every digest that attests to the bytes around it. The only workable
discipline is that it must never arrive, so this is a gate rather than a
review.

What it scans: the text-bearing evidence. Disk images (``*.qcow2``), packet
captures, framebuffer dumps and screenshots are excluded — they are the
*products* of runs that used the declared fixture passphrase below, and a
regex over a 3 GB disk image would be theatre rather than a check. The scope
is stated here so the gap is a decision on the record and not an oversight.

One fixture credential is deliberately present and declared: the LUKS
passphrase the install journeys type into throwaway VM disks. It is a harness
constant, never a product default and never a real user's secret, and it
appears because the harness records its own command line. It is declared so
that it stays the *only* one — anything else matching a credential shape, and
any of the harness's account passwords, fails this gate.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "qualification"

# Suffixes carrying text a person or a tool wrote. Everything else is a binary
# artefact of a run; see the module docstring for why those are out of scope.
TEXT_SUFFIXES = frozenset(
    {
        ".log",
        ".json",
        ".jsonl",
        ".ndjson",
        ".txt",
        ".md",
        ".sh",
        ".py",
        ".sha256",
        ".lock",
        ".permall",
        "",
    }
)

# Shapes that are credential material wherever they appear. Each is anchored on
# a issuer-assigned prefix or an unmistakable envelope, so a match is a finding
# and not a guess.
CREDENTIAL_SHAPES = (
    ("github token", r"gh[pousr]_[A-Za-z0-9]{16,}"),
    ("github fine-grained token", r"github_pat_[A-Za-z0-9_]{20,}"),
    ("aws access key id", r"AKIA[0-9A-Z]{16}"),
    ("slack token", r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    ("private key block", r"-----BEGIN (?:[A-Z][A-Z ]* )?PRIVATE KEY-----"),
    (
        "authorization header carrying a value",
        r"[Aa]uthorization:\s*(?:Bearer|Basic|token)\s+[A-Za-z0-9._~+/=-]{8,}",
    ),
    ("credential embedded in a url", r"https?://[^/\s:@]+:[^/\s@]{3,}@"),
)

SCANNER = re.compile(
    "|".join(f"(?P<shape_{index}>{pattern})" for index, (_, pattern) in enumerate(CREDENTIAL_SHAPES))
)
SHAPE_NAMES = {f"shape_{index}": name for index, (name, _) in enumerate(CREDENTIAL_SHAPES)}

# The one fixture that is allowed to be here, and the reason it is.
DECLARED_FIXTURE_SECRETS = {
    "bunny-disk-passphrase": (
        "The LUKS passphrase the install journeys type into a throwaway VM disk. "
        "A harness constant, recorded because the harness logs its own argv."
    ),
}

# Passwords the login stories give to accounts they create. None of these is a
# shape the scanner would recognise, so they are named explicitly.
HARNESS_ACCOUNT_PASSWORDS = (
    "bunny-test-password",  # vm-login-story.sh's default, for the installed account
    "bunny-second-password",  # the second and third accounts the multi-user story creates
    "bunny-login-password",
)


def _evidence_text_files() -> list[Path]:
    return sorted(
        path
        for path in EVIDENCE.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
    )


def _scan(text: str) -> list[tuple[str, str]]:
    """Return (shape name, matched text) for every credential shape in *text*."""
    findings = []
    for match in SCANNER.finditer(text):
        name = SHAPE_NAMES[match.lastgroup]
        findings.append((name, match.group()))
    return findings


@dataclass(frozen=True)
class EvidenceScan:
    """Everything the three assertions need, from one walk of the tree.

    The tree is 200 MB of text; reading it once per assertion turns a cheap
    gate into one nobody wants to run.
    """

    fileCount: int
    credentialFindings: tuple[str, ...]
    passwordOffenders: tuple[str, ...]
    fixturesSeen: frozenset[str]


@lru_cache(maxsize=1)
def _scan_evidence() -> EvidenceScan:
    credentials: list[str] = []
    passwords: list[str] = []
    fixtures: set[str] = set()
    count = 0

    for path in _evidence_text_files():
        count += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        where = path.relative_to(ROOT).as_posix()
        for shape, matched in _scan(text):
            credentials.append(f"{where}: {shape} — {matched[:24]}…")
        for password in HARNESS_ACCOUNT_PASSWORDS:
            if password in text:
                passwords.append(f"{where}: {password}")
        for fixture in DECLARED_FIXTURE_SECRETS:
            if fixture in text:
                fixtures.add(fixture)

    return EvidenceScan(
        fileCount=count,
        credentialFindings=tuple(credentials),
        passwordOffenders=tuple(passwords),
        fixturesSeen=frozenset(fixtures),
    )


class EvidenceCredentialScanTests(unittest.TestCase):
    def setUp(self) -> None:
        if not EVIDENCE.is_dir():
            self.skipTest("no qualification tree in this checkout")

    def test_the_scanner_finds_a_planted_credential(self) -> None:
        """The negative control.

        A scan that reports nothing is only reassuring if it would have
        reported something. Each shape is exercised against a planted sample,
        because a scanner that silently matches nothing passes every other
        test in this file.
        """
        planted = {
            "github token": "ghp_0123456789abcdefghijABCDEFGHIJklmnop",
            "github fine-grained token": "github_pat_11ABCDEFG0abcdefghij_KLMNOPqrstuv",
            "aws access key id": "AKIAIOSFODNN7EXAMPLE",
            "slack token": "xoxb-123456789012-abcdefghijkl",
            "private key block": "-----BEGIN OPENSSH PRIVATE KEY-----",
            "authorization header carrying a value": "Authorization: Bearer abcdef0123456789",
            "credential embedded in a url": "https://someone:hunter2@example.invalid/x",
        }
        for expected_shape, sample in planted.items():
            with self.subTest(shape=expected_shape):
                found = _scan(f"noise before\n{sample}\nnoise after")
                self.assertTrue(
                    found, f"the scanner did not notice a planted {expected_shape}"
                )
                self.assertIn(expected_shape, [name for name, _ in found])

    def test_no_credential_material_in_the_evidence_tree(self) -> None:
        scan = _scan_evidence()
        self.assertGreater(scan.fileCount, 100, "the evidence tree did not enumerate")
        self.assertEqual(
            (),
            scan.credentialFindings,
            "credential material in the evidence tree:\n"
            + "\n".join(scan.credentialFindings[:20]),
        )

    def test_harness_account_passwords_are_not_written_into_evidence(self) -> None:
        """The passwords the stories give the accounts they create stay out.

        These are not a recognisable shape — they are ordinary strings — so the
        scanner above would never see them. A story that logged its own
        environment would put one here, which is the mistake this catches.
        """
        scan = _scan_evidence()
        self.assertEqual(
            (),
            scan.passwordOffenders,
            "account passwords in evidence:\n" + "\n".join(scan.passwordOffenders[:20]),
        )

    def test_the_declared_fixture_is_declared_because_it_is_really_there(self) -> None:
        """A declaration that no longer describes the tree is a lie in waiting.

        If the fixture stops appearing, the entry must go — otherwise it is a
        standing permission for a secret nobody is checking for any more.
        """
        scan = _scan_evidence()
        for fixture in DECLARED_FIXTURE_SECRETS:
            with self.subTest(fixture=fixture):
                self.assertIn(
                    fixture,
                    scan.fixturesSeen,
                    f"{fixture!r} is declared as present in the evidence tree but is not; "
                    "remove the declaration rather than keeping a permission nobody needs",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
