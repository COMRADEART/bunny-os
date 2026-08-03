#!/usr/bin/env python3
"""Adversarial security harness for the experimental Bunny shell.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Runs the twenty rejection requirements as a single reportable set. Each entry
records which suite proves it and whether the proof is a unit test or an
observation of a running shell.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import ROOT, banner, write_report  # noqa: E402


#: The twenty rejections, each mapped to what actually proves it.
REJECTIONS = [
    (1, "Experimental shell becoming the default session", "tests/security_v3", "unit"),
    (2, "GNOME session being removed", "tests/security_v3", "unit"),
    (3, "Arbitrary text reaching /bin/sh", "tests/shell_ui_v3 + cargo security::tests", "unit"),
    (4, "Character surfaces receiving keyboard focus", "tests/shell_ui_v3 + cargo focus::tests", "unit"),
    (5, "Two character assets displayed simultaneously", "tests/shell_ui_v3", "unit"),
    (6, "Completed pose shown before backend completion", "tests/shell_ui_v3", "unit"),
    (7, "Approval accepted without explicit input", "tests/shell_ui_v3 + cargo security::tests", "unit"),
    (8, "Critical approval with a default affirmative button", "tests/shell_ui_v3", "unit"),
    (9, "Lock-screen crash exposing the desktop", "tests/security_v3 + cargo session::tests", "unit"),
    (10, "Password content written to logs", "tests/security_v3", "unit"),
    (11, "Screen capture without portal authorization", "tests/security_v3", "unit"),
    (12, "Missing privacy indicator during capture", "tests/security_v3", "unit"),
    (13, "Clipboard content persisted to disk", "tests/security_v3", "unit"),
    (14, "XWayland silently required for shell startup", "compositor tests/start_gates.rs", "process"),
    (15, "Output hotplug leaving an uncovered lock-screen area", "tests/security_v3 + cargo session::tests", "unit"),
    (16, "Shell crash causing an infinite restart loop", "visual-v3/tools/crash_recovery_test.py", "observed"),
    (17, "Unsupported protocol reported as supported", "visual-v3/tools/protocol_test.py", "observed"),
    (18, "Mock backend state packaged as real state", "tests/shell_ui_v3 + package gate", "unit"),
    (19, "Experimental files modifying qualification evidence", "tests/security_v3 (git diff)", "observed"),
    (20, "Visual prototype presented as release-qualified", "tests/security_v3", "unit"),
]


def run_suite(directory: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", directory, "-t", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tail = completed.stderr.strip().splitlines()
    ran = next((line for line in tail if line.startswith("Ran ")), "")
    return {
        "suite": directory,
        "passed": completed.returncode == 0,
        "summary": ran,
        "failureOutput": "" if completed.returncode == 0 else completed.stderr[-3000:],
    }


def mutation_check() -> dict:
    """Mutation-test the highest-risk checks.

    Each entry disables one guard and asserts the outcome *changes*. A guard
    whose removal changes nothing was never load-bearing, and the guarantee it
    appears to provide is decoration. A mutant is "killed" when the behaviour
    flips; a surviving mutant is a finding.
    """

    sys.path.insert(0, str(ROOT / "apps/common"))
    from bunny_shell_v3 import character, notifications, portals
    from bunny_shell_v3.supervisor import Decision, Outcome, RestartPolicy

    results = []

    def record(name: str, guarantee: str, before, after) -> None:
        results.append(
            {
                "mutation": name,
                "guarantee": guarantee,
                "unmutatedOutcome": str(before),
                "mutatedOutcome": str(after),
                "killed": before != after,
            }
        )

    # 1. Remove the bounded restart budget.
    def restarts(policy: RestartPolicy) -> int:
        return [
            policy.decide(Outcome(exit_code=1, signal=None, uptime_seconds=0.1))
            for _ in range(50)
        ].count(Decision.RESTART)

    record(
        "restart budget raised to 10000",
        "a crashing shell stops restarting",
        restarts(RestartPolicy()),
        restarts(RestartPolicy(max_consecutive_restarts=10_000, max_total_restarts=10_000)),
    )

    # 2. Remove the success-state guard on the guide character.
    def completed_pose() -> str:
        layer = character.CharacterLayer(ROOT, character_mode=True)
        return type(layer.show("task-summary", character.GuideState.COMPLETED)).__name__

    original_success = character.SUCCESS_STATES
    before = completed_pose()
    character.SUCCESS_STATES = frozenset()
    try:
        after = completed_pose()
    finally:
        character.SUCCESS_STATES = original_success
    record("SUCCESS_STATES emptied", "success poses require an observed success", before, after)

    # 3. Allow the character onto a forbidden surface.
    def lock_screen_character() -> str:
        layer = character.CharacterLayer(ROOT, character_mode=True)
        return str(layer.show("lock-screen", character.GuideState.READY))

    original_forbidden = character.FORBIDDEN_CONTAINERS
    original_approved = character.APPROVED_CONTAINERS
    before = lock_screen_character()
    character.FORBIDDEN_CONTAINERS = frozenset()
    character.APPROVED_CONTAINERS = original_approved | {"lock-screen"}
    try:
        after = lock_screen_character()
    finally:
        character.FORBIDDEN_CONTAINERS = original_forbidden
        character.APPROVED_CONTAINERS = original_approved
    record(
        "forbidden container list emptied",
        "the character never appears on an authentication surface",
        before,
        after,
    )

    # 4. Allow a Bunny action to complete without backend confirmation.
    def complete_without_confirmation() -> str:
        notification = notifications.Notification(
            app_id="bunny", summary="x", category=notifications.Category.BUNNY_ACTION
        )
        notification.advance(notifications.ActionState.WAITING_FOR_APPROVAL)
        notification.advance(notifications.ActionState.RUNNING)
        try:
            notification.advance(notifications.ActionState.COMPLETED)
            return "completed"
        except notifications.TransitionRefused:
            return "refused"

    before = complete_without_confirmation()
    original_advance = notifications.Notification.advance

    def unguarded(self, target, *, backend_confirmed=False):
        return original_advance(self, target, backend_confirmed=True)

    notifications.Notification.advance = unguarded
    try:
        after = complete_without_confirmation()
    finally:
        notifications.Notification.advance = original_advance
    record(
        "backend-confirmation requirement bypassed",
        "completed requires backend confirmation",
        before,
        after,
    )

    # 5. Capture without a showable privacy indicator.
    request = portals.CaptureRequest(
        app_id="a", source=portals.CaptureSource.OUTPUT, portal_token="t", user_selected_source=True
    )
    record(
        "privacy indicator reported available when it is not",
        "capture requires a showable indicator",
        type(portals.authorise_capture(request, indicator_available=False)).__name__,
        type(portals.authorise_capture(request, indicator_available=True)).__name__,
    )

    # 6. Drop the portal token requirement.
    without_token = portals.CaptureRequest(
        app_id="a", source=portals.CaptureSource.OUTPUT, portal_token=None, user_selected_source=True
    )
    record(
        "portal token removed",
        "capture requires portal authorisation",
        type(portals.authorise_capture(request, indicator_available=True)).__name__,
        type(portals.authorise_capture(without_token, indicator_available=True)).__name__,
    )

    survivors = [item["mutation"] for item in results if not item["killed"]]
    return {"mutations": results, "allKilled": not survivors, "survivors": survivors}


def main() -> int:
    banner()
    suites = [run_suite(directory) for directory in ("tests/security_v3", "tests/shell_ui_v3")]
    mutations = mutation_check()
    payload = {
        "schemaVersion": 1,
        "suites": suites,
        "mutationTesting": mutations,
        "rejections": [
            {"id": number, "requirement": text, "provenBy": suite, "proofKind": kind}
            for number, text, suite, kind in REJECTIONS
        ],
        "allSuitesPassed": all(suite["passed"] for suite in suites),
    }
    write_report("security.json", payload)
    for suite in suites:
        print(f"{suite['suite']}: {'PASS' if suite['passed'] else 'FAIL'} {suite['summary']}")
    print(f"mutants killed: {mutations['allKilled']}" + ("" if mutations["allKilled"] else f" survivors={mutations['survivors']}"))
    return 0 if payload["allSuitesPassed"] and mutations["allKilled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
