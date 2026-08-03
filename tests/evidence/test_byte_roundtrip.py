# SPDX-License-Identifier: GPL-3.0-or-later
"""Byte-attested evidence must round-trip git exactly.

``release/evidence.py`` verifies a record by hashing the file named in its
``evidenceReference`` and comparing the result against the recorded
``contentDigest``. That check is only meaningful if the bytes on disk are the
bytes that were committed. Any checkout-time content filter — EOL normalisation
being the one that actually bites — changes them, and a record generated on one
platform then stops verifying on another.

These tests discover the attested files from the evidence documents rather than
from a hand-maintained list, so a newly attested file is covered the moment it is
referenced, and fails until ``.gitattributes`` is updated to protect it.

None of this makes stale evidence current. A file whose bytes round-trip
correctly can still carry a digest measured against an older version of itself;
that is a different defect with a different fix, and it is checked elsewhere.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Documents that bind a repository path to a digest of its bytes.
EVIDENCE_DOCUMENTS = ("operations/data/release-evidence.json",)

# Records whose recorded digest matches the file's CRLF bytes rather than its
# committed bytes. Each one was generated on a Windows checkout before
# .gitattributes protected these paths, and verifies only on such a checkout.
#
# The fix is to RE-MEASURE the evidence, not to recompute the digest against the
# committed bytes. Re-hashing would bind a record to bytes it was never measured
# from, which is exactly the substitution the digest check exists to catch.
#
# This set exists so a *new* occurrence fails the suite. Removing an entry is
# correct once that evidence has been re-measured.
KNOWN_CRLF_BOUND_RECORDS = frozenset({"operations/data/hardware-evidence.json"})


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def attested_paths() -> dict[str, set[str]]:
    """Every repository path bound to a digest, mapped to the digests claimed."""
    found: dict[str, set[str]] = {}
    for name in EVIDENCE_DOCUMENTS:
        document = json.loads((ROOT / name).read_text(encoding="utf-8"))
        for record in document.get("records", []):
            reference = record.get("evidenceReference")
            digest = record.get("contentDigest")
            if reference and digest:
                found.setdefault(reference, set()).add(digest)
    return found


def committed_bytes(path: str) -> bytes:
    return git("show", f"HEAD:{path}")


def filtering_disabled(path: str) -> bool:
    """True when git applies no content filter to this path on checkout.

    ``-text`` reports as ``text: unset``. Anything else — ``set``, ``auto``, or
    an unspecified attribute inheriting the core.autocrlf default — means the
    bytes may be rewritten.
    """
    out = git("check-attr", "text", "--", path).decode().strip()
    return out.rsplit(": ", 1)[-1] == "unset"


class DiscoveryTests(unittest.TestCase):
    def test_the_evidence_documents_exist(self):
        for name in EVIDENCE_DOCUMENTS:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_attested_paths_are_found(self):
        paths = attested_paths()
        self.assertGreaterEqual(len(paths), 7, "discovery found suspiciously few attested paths")

    def test_every_attested_path_exists_in_the_tree(self):
        for path in attested_paths():
            self.assertTrue((ROOT / path).is_file(), f"{path} is attested but absent")


class FilterProtectionTests(unittest.TestCase):
    """Requirement: every byte-attested file bypasses content filtering."""

    def test_every_attested_file_has_content_filtering_disabled(self):
        unprotected = sorted(p for p in attested_paths() if not filtering_disabled(p))
        self.assertEqual(
            unprotected,
            [],
            "these files are attested by digest but git may rewrite their bytes on "
            "checkout; add a '-text' rule for each in .gitattributes",
        )

    def test_the_detector_notices_an_unprotected_path(self):
        """Mutation test: a guard nobody has broken is a guard nobody has checked."""
        # A path that is deliberately not listed in .gitattributes.
        self.assertFalse(
            filtering_disabled("README.md"),
            "README.md is expected to be unprotected; if it gained a -text rule, "
            "choose a different control path for this test",
        )


class ByteRoundTripTests(unittest.TestCase):
    """Requirement: working-tree bytes equal committed bytes.

    On Linux this passes trivially. On a Windows checkout with
    core.autocrlf=true it is the test that actually proves the protection works,
    and it failed for all seven files before .gitattributes was corrected.
    """

    def test_working_tree_sha256_equals_committed_sha256(self):
        differing = []
        for path in sorted(attested_paths()):
            working = sha256((ROOT / path).read_bytes()).hexdigest()
            committed = sha256(committed_bytes(path)).hexdigest()
            if working != committed:
                differing.append(f"{path}: working {working[:12]} != committed {committed[:12]}")
        self.assertEqual(differing, [], "attested bytes do not round-trip this checkout")

    def test_no_attested_file_has_crlf_baked_into_history(self):
        """A filter that ran before the fix would have committed CRLF bytes."""
        contaminated = [
            path for path in sorted(attested_paths()) if b"\r\n" in committed_bytes(path)
        ]
        self.assertEqual(contaminated, [], "committed bytes contain CRLF")


class RecordedDigestOriginTests(unittest.TestCase):
    """Which byte sequence each recorded digest was actually measured from.

    A digest can match the committed bytes (correct), match the CRLF bytes (the
    record was generated on a Windows checkout and is platform-bound), or match
    neither (the record is stale because the file changed after measurement).
    Only the middle case is this file's concern.
    """

    def classify(self) -> dict[str, str]:
        verdicts = {}
        for path, digests in attested_paths().items():
            committed = sha256(committed_bytes(path)).hexdigest()
            crlf = sha256(committed_bytes(path).replace(b"\n", b"\r\n")).hexdigest()
            for digest in digests:
                if digest == committed:
                    verdicts[path] = "committed"
                elif digest == crlf:
                    verdicts[path] = "crlf-bound"
                else:
                    verdicts.setdefault(path, "stale")
        return verdicts

    def test_no_new_record_is_bound_to_crlf_bytes(self):
        crlf_bound = {p for p, v in self.classify().items() if v == "crlf-bound"}
        new = crlf_bound - KNOWN_CRLF_BOUND_RECORDS
        self.assertEqual(
            new,
            set(),
            "a record was generated on a checkout that rewrote line endings; "
            "re-measure the evidence rather than recomputing its digest",
        )

    def test_the_known_crlf_bound_record_is_still_detected(self):
        """If this fails because the set is empty, the evidence was re-measured.

        That is the correct outcome, and the fix is to remove the entry from
        KNOWN_CRLF_BOUND_RECORDS deliberately — not to delete this test.
        """
        crlf_bound = {p for p, v in self.classify().items() if v == "crlf-bound"}
        for path in KNOWN_CRLF_BOUND_RECORDS:
            if path not in crlf_bound:
                self.skipTest(
                    f"{path} is no longer CRLF-bound; remove it from "
                    "KNOWN_CRLF_BOUND_RECORDS to close this out"
                )
        self.assertTrue(crlf_bound)

    def test_protection_does_not_make_stale_evidence_current(self):
        """The point of the accompanying documentation, asserted.

        qualification-matrices.json round-trips correctly and its record is
        still stale, because the file changed after the record was measured.
        Byte protection and evidence freshness are independent properties.
        """
        verdicts = self.classify()
        self.assertEqual(
            verdicts.get("operations/data/qualification-matrices.json"),
            "stale",
            "this record must remain stale; PR #18 deliberately left it blocking",
        )


if __name__ == "__main__":
    unittest.main()
