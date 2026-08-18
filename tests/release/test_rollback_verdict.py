# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The rollback grader, replayed over journeys that must not pass.

The Phase 5 finding was not that rollback failed — it was that the harness
grading it could not fail: three runs reported a selected deployment nobody
selected. The Phase 7 grader is therefore a pure function of (expectation,
logs), and this file replays it over constructed journeys: the nominal one,
and the ones that must come out FAIL or NOT_RUN. A healthy machine on the
wrong deployment is the load-bearing case, because that is the exact shape
that passed three times.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "phase7_rollback_verdict",
    _ROOT / "qualification" / "phase7" / "rollback" / "verdict.py",
)
verdict = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verdict)

# Two constructed deployments: A is the before-update Alpha RC, B the staged
# update target — the same shape as the real staged disk.
COMMIT_A = "a" * 64
BOOT_A = "1" * 64
COMMIT_B = "b" * 64
BOOT_B = "2" * 64

MARKER = "/var/home/p7-user-data.txt"
MARKER_SHA = hashlib.sha256(b"user data\n").hexdigest()

EXPECTATION = {
    "deployments": [
        {
            "blsEntry": "ostree-2.conf", "blsVersion": 2, "title": "Bunny OS Alpha 0.1",
            "bootChecksum": BOOT_A, "deployCommit": COMMIT_A,
            "originImage": "ostree-unverified-image:oci-archive:/x/bunny-os-beta-e906a48793d7.tar",
        },
        {
            "blsEntry": "ostree-1.conf", "blsVersion": 1, "title": "Bunny OS 0.1.0 (development)",
            "bootChecksum": BOOT_B, "deployCommit": COMMIT_B,
            "originImage": "ostree-unverified-image:oci-archive:/x/bunny-os-beta-e501218f2fe0.tar",
        },
    ],
    "rules": {"preservedByteIdentical": {MARKER: MARKER_SHA}},
}


def make_log(
    *,
    step: str,
    bootcsum: str,
    etc_identity: str,
    bootc_commit: str,
    rollback_exit: int | None = None,
    ostree_after: str | None = None,
    marker_sha: str | None = MARKER_SHA,
    healthy: bool = True,
    hostname: str = "ABSENT",
    locale: str = 'LANG="C.UTF-8"',
) -> str:
    lines = [
        f"BUNNY-P7: BEGIN step={step}",
        f"BUNNY-P7: cmdline=BOOT_IMAGE=/vmlinuz root=UUID=x rw ostree=/ostree/boot.0/default/{bootcsum}/0",
        f"BUNNY-P7: etc-identity={etc_identity}",
        f"BUNNY-P7: hostname-file={hostname}",
        "BUNNY-P7: hostname-transient=localhost",
        f"BUNNY-P7: locale={locale}",
    ]
    bootc = {"status": {"booted": {"ostree": {"checksum": bootc_commit},
                                   "image": {"image": {"image": "oci"}}}}}
    lines += [f"BUNNY-P7-BOOTC: {line}" for line in json.dumps(bootc, indent=1).splitlines()]
    if marker_sha is not None:
        lines.append(f"BUNNY-P7-SHA: {marker_sha}  {MARKER}")
    else:
        lines.append(f"BUNNY-P7-SHA: ABSENT  {MARKER}")
    if rollback_exit is not None:
        lines.append("BUNNY-P7: running bootc rollback")
        lines.append(f"BUNNY-P7: rollback exit={rollback_exit}")
    if ostree_after is not None:
        lines.append(f"BUNNY-P7-OSTREE-AFTER: * default {ostree_after}.0")
    if healthy:
        lines.append("[  OK  ] Reached target Multi-User System.")
    lines.append(f"BUNNY-P7: END step={step}")
    return "\n".join(lines) + "\n"


def nominal_restage_log() -> str:
    # The staged disk boots the before-update deployment by default (the
    # measured fact); the restage boot flips the default to the target.
    return make_log(
        step="restage", bootcsum=BOOT_A, etc_identity=COMMIT_A,
        bootc_commit=COMMIT_A, ostree_after=COMMIT_B,
    )


def nominal_rollback_log() -> str:
    return make_log(
        step="rollback", bootcsum=BOOT_B, etc_identity=COMMIT_B,
        bootc_commit=COMMIT_B, rollback_exit=0, ostree_after=COMMIT_A,
    )


def nominal_verify_log() -> str:
    return make_log(
        step="verify", bootcsum=BOOT_A, etc_identity=COMMIT_A,
        bootc_commit=COMMIT_A,
    )


class RollbackVerdict(unittest.TestCase):
    def grade(self, rollback_log, verify_log, restage_log=None):
        if restage_log is None:
            restage_log = nominal_restage_log()
        return verdict.grade(EXPECTATION, restage_log, rollback_log, verify_log)

    def test_the_nominal_journey_passes_with_all_four_identities(self) -> None:
        result = self.grade(nominal_rollback_log(), nominal_verify_log())
        self.assertEqual(result["verdict"], "PASS", result["reasons"])
        identities = result["identities"]
        self.assertEqual(identities["beforeUpdateDeployment"], COMMIT_A)
        self.assertEqual(identities["updateTargetDeployment"], COMMIT_B)
        self.assertEqual(identities["bootedBeforeRollback"], COMMIT_B)
        self.assertEqual(identities["selectedRollbackTarget"], COMMIT_A)
        self.assertEqual(
            identities["actuallyBooted"],
            {"cmdline": COMMIT_A, "bootc": COMMIT_A, "etcIdentity": COMMIT_A},
        )

    def test_a_healthy_machine_on_the_wrong_deployment_is_fail(self) -> None:
        wrong = make_log(
            step="verify", bootcsum=BOOT_B, etc_identity=COMMIT_B,
            bootc_commit=COMMIT_B, healthy=True,
        )
        result = self.grade(nominal_rollback_log(), wrong)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(
            any("instead of the selected rollback target" in r and "healthy" in r
                for r in result["reasons"]),
            result["reasons"],
        )

    def test_disagreeing_identity_sources_are_fail(self) -> None:
        disagreeing = make_log(
            step="verify", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_B,
        )
        result = self.grade(nominal_rollback_log(), disagreeing)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("sources disagree" in r for r in result["reasons"]))

    def test_a_changed_user_state_marker_is_fail(self) -> None:
        tampered = make_log(
            step="verify", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_A, marker_sha="c" * 64,
        )
        result = self.grade(nominal_rollback_log(), tampered)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("marker changed" in r for r in result["reasons"]))

    def test_a_vanished_user_state_marker_is_fail(self) -> None:
        vanished = make_log(
            step="verify", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_A, marker_sha=None,
        )
        result = self.grade(nominal_rollback_log(), vanished)
        self.assertEqual(result["verdict"], "FAIL")

    def test_a_failed_rollback_command_is_fail(self) -> None:
        broken = make_log(
            step="rollback", bootcsum=BOOT_B, etc_identity=COMMIT_B,
            bootc_commit=COMMIT_B, rollback_exit=1, ostree_after=COMMIT_A,
        )
        result = self.grade(broken, nominal_verify_log())
        self.assertEqual(result["verdict"], "FAIL")

    def test_a_restage_selection_that_did_not_take_is_fail(self) -> None:
        # The restage selected the update target, and the rollback boot came
        # up on the before-update deployment anyway, healthy: the exact shape
        # the grubenv harness reported as PASS three times. FAIL.
        stubborn = make_log(
            step="rollback", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_A, rollback_exit=0, ostree_after=COMMIT_B,
        )
        result = self.grade(stubborn, nominal_verify_log())
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("selection did not take" in r for r in result["reasons"]))

    def test_a_restage_that_left_the_wrong_default_is_not_run(self) -> None:
        # The restage boot never selected the update target: no N+1 -> N
        # rollback existed to qualify, and nothing may be passed.
        inert = make_log(
            step="restage", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_A, ostree_after=COMMIT_A,
        )
        result = self.grade(nominal_rollback_log(), nominal_verify_log(), restage_log=inert)
        self.assertEqual(result["verdict"], "NOT_RUN")

    def test_missing_logs_are_not_run(self) -> None:
        self.assertEqual(self.grade(None, None)["verdict"], "NOT_RUN")
        self.assertEqual(self.grade(nominal_rollback_log(), None)["verdict"], "NOT_RUN")
        self.assertEqual(
            verdict.grade(EXPECTATION, None, nominal_rollback_log(), nominal_verify_log())["verdict"],
            "NOT_RUN",
        )

    def test_an_unhealthy_verify_boot_is_fail_even_on_the_right_deployment(self) -> None:
        unhealthy = make_log(
            step="verify", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_A, healthy=False,
        )
        result = self.grade(nominal_rollback_log(), unhealthy)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("healthy boot target" in r for r in result["reasons"]))

    def test_a_hostname_that_appears_is_fail(self) -> None:
        appeared = make_log(
            step="verify", bootcsum=BOOT_A, etc_identity=COMMIT_A,
            bootc_commit=COMMIT_A, hostname="intruder",
        )
        result = self.grade(nominal_rollback_log(), appeared)
        self.assertEqual(result["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
