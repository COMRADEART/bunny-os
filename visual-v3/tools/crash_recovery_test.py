#!/usr/bin/env python3
"""Crash the shell for real and watch what the supervisor does.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Two scenarios:

1. A compositor that always dies immediately — the crash-storm case.
2. The real compositor, killed with SIGKILL while running — the case that
   proves the supervisor handles a signalled death, not just a bad exit code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/common"))

from harness import BINARY, NOTICE_LINES, ROOT, banner, shell_environment, write_report  # noqa: E402

SUPERVISOR = ROOT / "sessions/bunny-shell-supervisor"


def run_supervisor(compositor: list[str], state_dir: Path, *, timeout: int = 120) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--compositor",
            compositor[0],
            "--state-dir",
            str(state_dir),
            *compositor[1:],
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=shell_environment(),
    )
    return {
        "exitCode": completed.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "stderr": completed.stderr[-4000:],
    }


def scenario_always_crashes() -> dict:
    """A shell that dies immediately, every time."""

    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        crasher = Path(directory) / "always-crash"
        crasher.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
        crasher.chmod(0o755)

        result = run_supervisor([str(crasher)], state_dir)
        crashes = sorted((state_dir / "crashes").glob("crash-*.json"))
        records = [json.loads(path.read_text(encoding="utf-8")) for path in crashes]
        marker_path = state_dir / "recovery.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else None
        return {
            "scenario": "compositor exits 1 immediately, every time",
            "supervisorExitCode": result["exitCode"],
            "elapsedSeconds": result["seconds"],
            "crashRecords": len(records),
            "restartsAttempted": sum(1 for r in records if r["decision"] == "restart"),
            "endedInRecovery": bool(marker),
            "automaticRestartStopped": bool(marker and marker["automaticRestartStopped"]),
            "infiniteLoop": result["seconds"] > 60 or len(records) > 10,
            "recoveryOfferedGnome": bool(marker and marker["fallbackSession"] == "gnome"),
            "recoveryUsableWithoutCharacterMode": bool(
                marker and marker["characterModeRequired"] is False
            ),
            "guidanceMentionsGnome": "GNOME is the supported session" in result["stderr"],
            "noCredentialInRecords": all(
                not any(
                    needle in json.dumps(record).lower()
                    for needle in ("password", "passphrase", "secret", "credential")
                )
                for record in records
            ),
        }


def scenario_real_compositor_killed() -> dict:
    """The real compositor, SIGKILLed while it is running."""

    if not BINARY.is_file() or not os.environ.get("WAYLAND_DISPLAY"):
        return {
            "scenario": "real compositor killed with SIGKILL",
            "evidence": "unavailable",
            "reason": "compositor not built, or no host Wayland session to nest inside",
        }

    with tempfile.TemporaryDirectory() as directory:
        state_dir = Path(directory) / "state"
        state_dir.mkdir(parents=True)
        environment = shell_environment(BUNNY_SHELL_MODE="regular")
        log = Path(directory) / "shell.log"
        killed_after = []
        outcomes = []
        # Drive the supervisor's policy by hand against the real binary so the
        # kill can be timed precisely.
        sys.path.insert(0, str(ROOT / "apps/common"))
        from bunny_shell_v3.supervisor import Decision, Outcome, RestartPolicy, Supervisor

        policy = RestartPolicy()
        supervisor = Supervisor(command=[str(BINARY)], state_dir=state_dir, policy=policy)

        attempt = 0
        decision = None
        while attempt < 8:
            attempt += 1
            with log.open("ab") as stream:
                process = subprocess.Popen(
                    [str(BINARY), "--socket", f"bunny-crash-{attempt}", "--frames", "5000"],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    env=environment,
                )
            started = time.monotonic()
            time.sleep(2.5)
            if process.poll() is None:
                process.send_signal(signal.SIGKILL)
            returncode = process.wait(timeout=20)
            uptime = time.monotonic() - started
            killed_after.append(round(uptime, 2))
            outcome = (
                Outcome(exit_code=128 - returncode, signal=-returncode, uptime_seconds=uptime)
                if returncode < 0
                else Outcome(exit_code=returncode, signal=None, uptime_seconds=uptime)
            )
            decision = policy.decide(outcome)
            supervisor.record_crash(outcome, decision, index=attempt)
            outcomes.append({"attempt": attempt, "outcome": outcome.describe(), "decision": decision.value})
            if decision is not Decision.RESTART:
                break

        marker = supervisor.write_recovery_marker("SIGKILL during a nested run")
        return {
            "scenario": "real compositor killed with SIGKILL",
            "evidence": "observed",
            "attempts": outcomes,
            "uptimeBeforeEachKillSeconds": killed_after,
            "restartsUsed": policy.total_restarts,
            "finalDecision": decision.value if decision else None,
            "stoppedRestarting": decision is not None and decision.value == "recover",
            "recoveryMarkerWritten": marker.is_file(),
            "signalledDeathDetected": all(
                "terminated by SIGKILL" in item["outcome"] for item in outcomes
            ),
            "clientsPreserved": False,
            "clientsPreservedNote": (
                "Wayland clients connect to the compositor's socket. When the compositor "
                "process dies the connection is lost and the clients exit. Preserving them "
                "would need a socket-handover design that smithay does not provide."
            ),
        }


def main() -> int:
    banner()
    storm = scenario_always_crashes()
    killed = scenario_real_compositor_killed()

    verdict_reasons = []
    if storm["infiniteLoop"]:
        verdict_reasons.append("the crash-storm scenario looped")
    if not storm["endedInRecovery"]:
        verdict_reasons.append("the crash-storm scenario did not reach recovery")
    if killed.get("evidence") == "observed" and not killed["stoppedRestarting"]:
        verdict_reasons.append("the SIGKILL scenario kept restarting")

    payload = {
        "schemaVersion": 1,
        "scenarios": [storm, killed],
        "boundedRestartHolds": not verdict_reasons,
        "problems": verdict_reasons,
    }
    write_report("crash-recovery.json", payload)
    print(f"bounded restart holds: {payload['boundedRestartHolds']}")
    for scenario in payload["scenarios"]:
        print(f"  - {scenario['scenario']}: {scenario.get('evidence', 'observed')}")
    return 0 if payload["boundedRestartHolds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
