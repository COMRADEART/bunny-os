# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The recovery grader, replayed over journeys that must not pass.

Same discipline as the rollback grader: the verdict is a pure function of
recorded evidence, and this file executes its failure branches on every run —
including the control case the definition names explicitly: a "broken" disk
that boots anyway fails the whole journey.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "phase7_recovery_verdict",
    _ROOT / "qualification" / "phase7" / "recovery" / "verdict.py",
)
verdict = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verdict)

REAL = "d" * 64
BOGUS = "0" * 61 + "bad"
DEPLOY = "e" * 64

BREAKAGE = {"realChecksumDir": REAL, "bogusChecksumDir": BOGUS}

BROKEN_LOG = "error: file `/boot/ostree/%s/vmlinuz` not found\n" % BOGUS

HEALTHY = "[  OK  ] Reached target Multi-User System.\n"


def session_log(
    *,
    inspected: bool = True,
    before_dir: str = BOGUS,
    derived: str = f"default-{REAL}",
    after_dir: str = REAL,
    repaired: bool = True,
) -> str:
    lines = ["BUNNY-P7R: BEGIN recovery driver", HEALTHY.strip()]
    if inspected:
        lines += [
            f"BUNNY-P7R: deployment={DEPLOY}.0",
            "BUNNY-P7R: origin=container-image-reference=ostree-unverified-registry:localhost/bunny-os-beta:e906a48793d7",
            'BUNNY-P7R: os-release=PRETTY_NAME="Bunny OS 0.1.0"',
        ]
    lines += [
        f"BUNNY-P7R: entry-before-linux=linux /boot/ostree/default-{before_dir}/vmlinuz-7.1.5",
        f"BUNNY-P7R: derived-dir={derived}",
        f"BUNNY-P7R: entry-after-linux=linux /boot/ostree/default-{after_dir}/vmlinuz-7.1.5",
        f"BUNNY-P7R: entry-after-initrd=initrd /boot/ostree/default-{after_dir}/initramfs-7.1.5.img",
    ]
    if repaired:
        lines.append("BUNNY-P7R: REPAIRED")
    lines.append("BUNNY-P7R: END recovery driver")
    return "\n".join(lines) + "\n"


def repaired_log(csum: str = REAL, healthy: bool = True) -> str:
    text = f"... ostree=/ostree/boot.1/default/{csum}/0\n"
    if healthy:
        text += HEALTHY
    return text


class RecoveryVerdict(unittest.TestCase):
    def test_the_nominal_journey_passes(self) -> None:
        result = verdict.grade(BREAKAGE, BROKEN_LOG, session_log(), repaired_log())
        self.assertEqual(result["verdict"], "PASS", result["reasons"])
        self.assertEqual(result["steps"]["installationInspected"], [DEPLOY])

    def test_a_broken_disk_that_boots_anyway_fails_the_journey(self) -> None:
        result = verdict.grade(BREAKAGE, BROKEN_LOG + HEALTHY, session_log(), repaired_log())
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("breakage control" in r for r in result["reasons"]))

    def test_a_recovery_environment_that_never_started_is_not_run(self) -> None:
        result = verdict.grade(BREAKAGE, BROKEN_LOG, "no markers here\n", repaired_log())
        self.assertEqual(result["verdict"], "NOT_RUN")

    def test_no_inspection_is_fail(self) -> None:
        result = verdict.grade(BREAKAGE, BROKEN_LOG, session_log(inspected=False), repaired_log())
        self.assertEqual(result["verdict"], "FAIL")

    def test_an_unchanged_entry_is_fail(self) -> None:
        unchanged = session_log(before_dir=REAL, after_dir=REAL)
        result = verdict.grade(BREAKAGE, BROKEN_LOG, unchanged, repaired_log())
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("nothing was repaired" in r for r in result["reasons"]))

    def test_a_repair_naming_the_wrong_directory_is_fail(self) -> None:
        wrong = session_log(after_dir="f" * 64, derived=f"default-{'f' * 64}")
        result = verdict.grade(BREAKAGE, BROKEN_LOG, wrong, repaired_log())
        self.assertEqual(result["verdict"], "FAIL")

    def test_an_unverified_outcome_is_not_run(self) -> None:
        result = verdict.grade(BREAKAGE, BROKEN_LOG, session_log(), None)
        self.assertEqual(result["verdict"], "NOT_RUN")

    def test_a_repaired_disk_that_does_not_boot_is_fail(self) -> None:
        result = verdict.grade(
            BREAKAGE, BROKEN_LOG, session_log(), repaired_log(healthy=False)
        )
        self.assertEqual(result["verdict"], "FAIL")

    def test_a_repaired_disk_on_the_wrong_deployment_is_fail(self) -> None:
        result = verdict.grade(
            BREAKAGE, BROKEN_LOG, session_log(), repaired_log(csum="9" * 64)
        )
        self.assertEqual(result["verdict"], "FAIL")

    def test_missing_breakage_is_not_run(self) -> None:
        result = verdict.grade(None, None, session_log(), repaired_log())
        self.assertEqual(result["verdict"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
