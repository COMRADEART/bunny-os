"""Adversarial tests for the V3 non-release safeguards.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

These cover the phase's rejection requirements 1, 2, 14, 19 and 20.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests.support import ROOT


V3 = ROOT / "visual-v3"
SESSIONS = ROOT / "sessions"
NOTICE_LINES = (
    "BUNNY WAYLAND SHELL EXPERIMENT",
    "NOT RELEASE QUALIFIED",
    "DO NOT USE AS THE DEFAULT SESSION",
)


class BranchPolicyTests(unittest.TestCase):
    def test_branch_policy_is_explicitly_non_release(self) -> None:
        policy = json.loads((V3 / "branch-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["branch"], "visual/bunny-wayland-shell-v3")
        for flag in (
            "defaultSessionChanged",
            "gnomeSessionRemoved",
            "qualificationTargetsChanged",
            "releaseGatesChanged",
            "qualifiedImageChanged",
            "productionKeysAllowed",
            "publishableImage",
            "mergeableIntoMain",
        ):
            self.assertFalse(policy[flag], f"{flag} must be false on an experimental branch")
        self.assertTrue(policy["gnomeRemainsSupportedFallback"])
        self.assertTrue(policy["requiresExplicitExperimentalMode"])
        self.assertEqual(policy["status"], list(NOTICE_LINES))

    def test_the_prototype_is_never_presented_as_release_qualified(self) -> None:
        """Rejection 20: a visual prototype presented as release-qualified."""
        for document in sorted(V3.glob("*.md")):
            text = document.read_text(encoding="utf-8")
            self.assertIn(
                "NOT RELEASE QUALIFIED",
                text,
                f"{document.name} must carry the experiment notice",
            )
            self.assertNotIn("release qualified", text.replace("NOT RELEASE QUALIFIED", ""))


class SessionIsolationTests(unittest.TestCase):
    def test_the_experimental_session_is_never_the_default(self) -> None:
        """Rejection 1: the experimental shell becoming the default session."""
        desktop = (SESSIONS / "bunny-shell-experimental.desktop").read_text(encoding="utf-8")
        self.assertIn("Name=Bunny Shell Experimental", desktop)
        self.assertIn("X-Bunny-Default-Session=false", desktop)
        self.assertIn("X-Bunny-Release-Qualified=false", desktop)
        self.assertNotIn("X-GDM-BypassXsession", desktop)

    def test_no_gnome_session_file_is_created_or_replaced(self) -> None:
        """Rejection 2: the GNOME session being removed."""
        for name in ("gnome.desktop", "gnome-wayland.desktop", "gnome-xorg.desktop", "gnome.session"):
            self.assertFalse((SESSIONS / name).exists(), f"V3 must not ship {name}")

    def test_the_launcher_refuses_without_explicit_experimental_mode(self) -> None:
        launcher = (SESSIONS / "bunny-shell-experimental-session").read_text(encoding="utf-8")
        self.assertIn('"${BUNNY_SHELL_EXPERIMENTAL:-}" != "1"', launcher)
        self.assertIn("refusing to start", launcher)
        for line in NOTICE_LINES:
            self.assertIn(line, launcher)

    def test_the_launcher_refuses_when_gnome_stops_being_selectable(self) -> None:
        launcher = (SESSIONS / "bunny-shell-experimental-session").read_text(encoding="utf-8")
        self.assertIn("GNOME must remain the supported fallback", launcher)

    def test_the_experimental_units_stay_out_of_the_qualified_image(self) -> None:
        """Rejection 19: experimental files modifying qualification evidence.

        build/scripts/install-root.py copies systemd/ and systemd/user/ into the
        image wholesale. Anything placed there ships in the qualified image, so
        the experimental units live under sessions/ instead.
        """
        for unit in ("bunny-shell-session.service", "bunny-shell-recovery.service", "bunny-shell-experimental.target"):
            self.assertTrue((SESSIONS / unit).is_file(), f"{unit} must exist under sessions/")
            self.assertFalse((ROOT / "systemd" / unit).exists(), f"{unit} must not be in systemd/")
            self.assertFalse((ROOT / "systemd/user" / unit).exists(), f"{unit} must not be in systemd/user/")

    def test_the_session_target_is_not_wanted_by_graphical_session(self) -> None:
        target = (SESSIONS / "bunny-shell-experimental.target").read_text(encoding="utf-8")
        self.assertNotIn("WantedBy=graphical-session.target", target)
        service = (SESSIONS / "bunny-shell-session.service").read_text(encoding="utf-8")
        self.assertNotIn("WantedBy=graphical-session.target", service)
        self.assertIn("WantedBy=bunny-shell-experimental.target", service)


class QualificationIsolationTests(unittest.TestCase):
    def test_v3_touches_no_qualification_evidence(self) -> None:
        """Rejection 19, checked against the working tree rather than a claim."""
        changed = subprocess.run(
            ["git", "diff", "--name-only", "visual/bunny-desktop-v2-dual-mode...HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if changed.returncode != 0:
            self.skipTest("git range unavailable in this checkout")
        forbidden_prefixes = (
            "qualification/",
            "evidence/",
            "release/",
            "security/keys",
            "build/out/",
        )
        offenders = [
            path
            for path in changed.stdout.splitlines()
            if path and path.startswith(forbidden_prefixes)
        ]
        self.assertEqual(offenders, [], f"V3 must not modify qualification or release evidence: {offenders}")

    def test_no_release_gate_is_altered(self) -> None:
        changed = subprocess.run(
            ["git", "diff", "--name-only", "visual/bunny-desktop-v2-dual-mode...HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if changed.returncode != 0:
            self.skipTest("git range unavailable in this checkout")
        gate_paths = [
            path
            for path in changed.stdout.splitlines()
            if path.startswith("scripts/gate") or "gate" in Path(path).name.lower() and path.startswith("scripts/")
        ]
        self.assertEqual(gate_paths, [], f"V3 must not alter qualification gates: {gate_paths}")


class SupervisorPolicyTests(unittest.TestCase):
    """Rejection 16: a shell crash causing an infinite restart loop."""

    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT / "apps/common"))
        from bunny_shell_v3 import supervisor

        self.supervisor = supervisor

    def test_a_permanently_crashing_shell_stops_restarting(self) -> None:
        policy = self.supervisor.RestartPolicy()
        decisions = []
        for _ in range(50):
            outcome = self.supervisor.Outcome(exit_code=1, signal=None, uptime_seconds=0.2)
            decisions.append(policy.decide(outcome))
        self.assertLessEqual(
            decisions.count(self.supervisor.Decision.RESTART),
            policy.max_total_restarts,
            "the restart budget must be absolute",
        )
        self.assertEqual(decisions[-1], self.supervisor.Decision.RECOVER)

    def test_a_long_healthy_run_does_not_grant_unlimited_restarts(self) -> None:
        policy = self.supervisor.RestartPolicy()
        restarts = 0
        for _ in range(50):
            # Every crash follows an hour of healthy uptime, which resets the
            # consecutive counter but must not reset the total budget.
            outcome = self.supervisor.Outcome(exit_code=1, signal=None, uptime_seconds=3600.0)
            if policy.decide(outcome) is self.supervisor.Decision.RESTART:
                restarts += 1
        self.assertEqual(restarts, policy.max_total_restarts)

    def test_a_clean_exit_is_not_a_crash(self) -> None:
        policy = self.supervisor.RestartPolicy()
        outcome = self.supervisor.Outcome(exit_code=0, signal=None, uptime_seconds=5.0)
        self.assertEqual(policy.decide(outcome), self.supervisor.Decision.STOP)
        self.assertEqual(policy.total_restarts, 0)

    def test_a_signalled_exit_is_a_crash(self) -> None:
        policy = self.supervisor.RestartPolicy()
        outcome = self.supervisor.Outcome(exit_code=139, signal=11, uptime_seconds=0.5)
        self.assertFalse(outcome.clean)
        self.assertEqual(policy.decide(outcome), self.supervisor.Decision.RESTART)

    def test_crash_records_carry_no_credential_material(self) -> None:
        """Rejection 10: password content written to logs."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            runner = self.supervisor.Supervisor(command=["/bin/true"], state_dir=Path(directory))
            outcome = self.supervisor.Outcome(exit_code=1, signal=None, uptime_seconds=0.1)
            record = runner.record_crash(outcome, self.supervisor.Decision.RECOVER, index=1)
            serialised = json.dumps(record).lower()
            for forbidden in ("password", "passphrase", "secret", "token", "credential"):
                self.assertNotIn(forbidden, serialised)
            # The allow list is what keeps it that way.
            self.assertLessEqual(set(record["environment"]), set(self.supervisor._RECORD_ENVIRONMENT_ALLOW_LIST))

    def test_recovery_guidance_does_not_require_character_mode(self) -> None:
        import io

        stream = io.StringIO()
        self.supervisor.print_recovery_guidance("test reason", stream=stream)
        text = stream.getvalue()
        self.assertIn("GNOME is the supported session", text)
        self.assertNotIn("character", text.lower())


if __name__ == "__main__":
    unittest.main()
