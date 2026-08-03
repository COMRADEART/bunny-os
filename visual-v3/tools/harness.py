"""Shared harness helpers for the V3 measurement tools.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Every harness records how it knew something. A value that could not be measured
is written as ``unavailable`` and never as an estimate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def _binary() -> Path:
    """Locate the compositor.

    BUNNY_SHELL_BINARY wins, because the Windows working tree and the Linux
    build directory are different filesystems: the sources live on /mnt/c and
    the cargo target directory does not.
    """

    override = os.environ.get("BUNNY_SHELL_BINARY")
    if override:
        return Path(override)
    return ROOT / "compositor/bunny-shell/target/release/bunny-shell"


BINARY = _binary()
REPORTS = ROOT / "visual-v3/reports"
NOTICE_LINES = [
    "BUNNY WAYLAND SHELL EXPERIMENT",
    "NOT RELEASE QUALIFIED",
    "DO NOT USE AS THE DEFAULT SESSION",
]

OBSERVED = "observed"
INFERRED = "inferred"
UNAVAILABLE = "unavailable"
UNSUPPORTED = "unsupported"


def banner() -> None:
    for line in NOTICE_LINES:
        print(line)


def write_report(name: str, payload: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {"notice": NOTICE_LINES, **payload}
    path = REPORTS / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {path.relative_to(ROOT)}")
    return path


def preconditions() -> list[str]:
    """Reasons the harness cannot measure anything here."""

    problems = []
    if not sys.platform.startswith("linux"):
        problems.append("not Linux")
    if not BINARY.is_file():
        problems.append("compositor not built; run `make bunny-shell-build`")
    if not os.environ.get("WAYLAND_DISPLAY"):
        problems.append("no host Wayland session to nest inside")
    return problems


def shell_environment(**overrides: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["BUNNY_SHELL_EXPERIMENTAL"] = "1"
    environment.setdefault("BUNNY_SHELL_ALLOW_MISSING_GNOME", "1")
    environment.update(overrides)
    return environment


class NestedShell:
    """Runs the compositor on its own socket and cleans up after itself."""

    def __init__(self, socket: str, *, frames: int = 900, mode: str = "regular", log: Path | None = None):
        self.socket = socket
        self.frames = frames
        self.mode = mode
        self.log = log or (REPORTS / f"{socket}.log")
        self.process: subprocess.Popen | None = None
        self.diagnostics_path = REPORTS / f"{socket}-diagnostics.json"
        self.started_at = 0.0
        self.socket_ready_seconds: float | None = None

    def runtime_dir(self) -> Path:
        return Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/0"))

    def socket_path(self) -> Path:
        return self.runtime_dir() / self.socket

    def __enter__(self) -> "NestedShell":
        REPORTS.mkdir(parents=True, exist_ok=True)
        for suffix in ("", ".lock"):
            candidate = Path(str(self.socket_path()) + suffix)
            if candidate.exists():
                candidate.unlink()
        self.started_at = time.monotonic()
        with self.log.open("wb") as stream:
            self.process = subprocess.Popen(
                [
                    str(BINARY),
                    "--socket",
                    self.socket,
                    "--frames",
                    str(self.frames),
                    "--diagnostics-output",
                    str(self.diagnostics_path),
                ],
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=shell_environment(BUNNY_SHELL_MODE=self.mode),
            )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.socket_path().exists():
                self.socket_ready_seconds = time.monotonic() - self.started_at
                return self
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        raise RuntimeError(f"compositor socket {self.socket} never appeared; see {self.log}")

    def __exit__(self, *_exception) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def client_environment(self, **overrides: str) -> dict[str, str]:
        return shell_environment(
            WAYLAND_DISPLAY=self.socket,
            GDK_BACKEND="wayland",
            BUNNY_SHELL_MODE=self.mode,
            PYTHONPATH=str(ROOT / "apps/common"),
            **overrides,
        )

    def run_client(self, argv: list[str], *, timeout: int = 25, **overrides: str):
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=self.client_environment(**overrides),
        )

    def spawn_client(self, argv: list[str], **overrides: str) -> subprocess.Popen:
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self.client_environment(**overrides),
        )

    def diagnostics(self) -> dict:
        if self.diagnostics_path.is_file():
            return json.loads(self.diagnostics_path.read_text(encoding="utf-8"))
        return {}

    def log_text(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace") if self.log.is_file() else ""


def component_command(component: str) -> list[str]:
    return [sys.executable, str(ROOT / "shell-ui" / component / f"bunny-{component}")]


def which(name: str) -> str | None:
    return shutil.which(name)
