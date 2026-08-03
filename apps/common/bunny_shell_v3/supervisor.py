"""Session supervisor for the experimental Bunny Wayland shell.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The restart policy is a pure function of the observed outcomes so that the
"no infinite crash loop" property can be tested without starting a compositor.
The bound is absolute: at most ``max_total_restarts`` restarts for the lifetime
of a session, whatever the timing of the crashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import signal as signal_module
import subprocess
import sys
import time


NOTICE = (
    "BUNNY WAYLAND SHELL EXPERIMENT\n"
    "NOT RELEASE QUALIFIED\n"
    "DO NOT USE AS THE DEFAULT SESSION"
)


class Decision(str, Enum):
    """What the supervisor does after the compositor has exited."""

    STOP = "stop"
    """The session ended normally. Do not restart."""

    RESTART = "restart"
    """A bounded restart is still available."""

    RECOVER = "recover"
    """The restart budget is exhausted. Offer a safe return to GDM/GNOME."""


@dataclass(frozen=True)
class Outcome:
    """One observed compositor exit."""

    exit_code: int
    signal: int | None
    uptime_seconds: float

    @property
    def clean(self) -> bool:
        return self.signal is None and self.exit_code == 0

    def describe(self) -> str:
        if self.signal is not None:
            try:
                name = signal_module.Signals(self.signal).name
            except ValueError:
                name = f"signal {self.signal}"
            return f"terminated by {name}"
        return f"exited with status {self.exit_code}"


@dataclass
class RestartPolicy:
    """Bounded restart policy.

    ``max_consecutive_restarts`` limits a crash *storm* — the shell dying again
    almost immediately after a restart. ``max_total_restarts`` is the hard
    ceiling that makes an endless loop impossible regardless of timing: a shell
    that stays up for an hour and then crashes still consumes budget.
    """

    max_consecutive_restarts: int = 1
    max_total_restarts: int = 3
    healthy_uptime_seconds: float = 60.0
    consecutive_restarts: int = 0
    total_restarts: int = 0

    def decide(self, outcome: Outcome) -> Decision:
        if outcome.clean:
            return Decision.STOP
        if self.total_restarts >= self.max_total_restarts:
            return Decision.RECOVER
        if outcome.uptime_seconds >= self.healthy_uptime_seconds:
            # The shell had a healthy run before this crash, so this is not a
            # storm. The consecutive counter resets; the total budget does not.
            self.consecutive_restarts = 0
        if self.consecutive_restarts >= self.max_consecutive_restarts:
            return Decision.RECOVER
        self.consecutive_restarts += 1
        self.total_restarts += 1
        return Decision.RESTART

    def remaining(self) -> int:
        return max(0, self.max_total_restarts - self.total_restarts)


# Environment variables that must never be copied into a crash record. The
# compositor never sees a password, but a supervisor that dumped the
# environment could still capture an authentication token from an unrelated
# service, so the record is built from an allow list instead of a deny list.
_RECORD_ENVIRONMENT_ALLOW_LIST = (
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "BUNNY_SHELL_SESSION_KIND",
    "BUNNY_SHELL_MODE",
)


@dataclass
class Supervisor:
    """Starts the compositor and applies the restart policy to each exit."""

    command: list[str]
    state_dir: Path
    policy: RestartPolicy = field(default_factory=RestartPolicy)
    clock: object = time
    crash_records: list[dict] = field(default_factory=list)

    def crash_directory(self) -> Path:
        return self.state_dir / "crashes"

    def record_crash(self, outcome: Outcome, decision: Decision, *, index: int) -> dict:
        record = {
            "schemaVersion": 1,
            "notice": NOTICE.splitlines(),
            "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "attempt": index,
            "exitCode": outcome.exit_code,
            "signal": outcome.signal,
            "description": outcome.describe(),
            "uptimeSeconds": round(outcome.uptime_seconds, 3),
            "decision": decision.value,
            "restartsUsed": self.policy.total_restarts,
            "restartsRemaining": self.policy.remaining(),
            "clientsPreserved": False,
            "clientsPreservedReason": (
                "Wayland clients are connected to the compositor socket; when the "
                "compositor process exits the connection is lost and the clients "
                "terminate. Preserving them requires a socket-handover design that "
                "Smithay does not provide and that V3 did not attempt."
            ),
            "environment": {
                name: os.environ[name]
                for name in _RECORD_ENVIRONMENT_ALLOW_LIST
                if name in os.environ
            },
        }
        directory = self.crash_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"crash-{index:03d}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        self.crash_records.append(record)
        return record

    def write_recovery_marker(self, reason: str) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        marker = self.state_dir / "recovery.json"
        marker.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "notice": NOTICE.splitlines(),
                    "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "reason": reason,
                    "restartsUsed": self.policy.total_restarts,
                    "automaticRestartStopped": True,
                    "fallbackSession": "gnome",
                    "characterModeRequired": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return marker

    def run_once(self) -> Outcome:
        started = time.monotonic()
        completed = subprocess.run(self.command, check=False)
        uptime = time.monotonic() - started
        returncode = completed.returncode
        if returncode < 0:
            return Outcome(exit_code=128 - returncode, signal=-returncode, uptime_seconds=uptime)
        return Outcome(exit_code=returncode, signal=None, uptime_seconds=uptime)

    def run(self) -> int:
        attempt = 0
        while True:
            attempt += 1
            outcome = self.run_once()
            if outcome.clean:
                return 0
            decision = self.policy.decide(outcome)
            self.record_crash(outcome, decision, index=attempt)
            print(
                f"bunny-shell-supervisor: compositor {outcome.describe()} "
                f"after {outcome.uptime_seconds:.1f}s; decision={decision.value}",
                file=sys.stderr,
            )
            if decision is Decision.RESTART:
                print(
                    "bunny-shell-supervisor: restarting once "
                    f"({self.policy.remaining()} restart(s) left in this session)",
                    file=sys.stderr,
                )
                continue
            reason = f"compositor {outcome.describe()}; automatic restart budget exhausted"
            self.write_recovery_marker(reason)
            print_recovery_guidance(reason)
            return 3


def print_recovery_guidance(reason: str, stream=sys.stderr) -> None:
    """Plain-text recovery guidance.

    Deliberately text only: the recovery path must stay usable when Character
    Mode is off, when the compositor cannot start at all, and when nothing but
    a virtual terminal is available.
    """

    for line in NOTICE.splitlines():
        print(line, file=stream)
    print("", file=stream)
    print("The experimental Bunny shell stopped and will not restart automatically.", file=stream)
    print(f"Reason: {reason}", file=stream)
    print("", file=stream)
    print("Your session is safe. Nothing was changed on the system.", file=stream)
    print("", file=stream)
    print("What to do next:", file=stream)
    print("  1. You are being returned to the login screen.", file=stream)
    print("  2. Choose the GNOME session. GNOME is the supported session.", file=stream)
    print("  3. Crash records are in $XDG_STATE_HOME/bunny-shell/crashes/.", file=stream)
    print("", file=stream)
    print("The experimental shell is not required for anything on this system.", file=stream)
