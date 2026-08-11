#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The image task, asked for from inside a real Bunny graphical session.

This runs *as the logged-in user*, inside the session, against the Companion
service that the session started — the same socket the window talks to, the same
runtime, the same broker, the same capsule support. Nothing here constructs a
runtime, a plan or an approval; it asks and it answers, which is what a person
does.

What it establishes that the capsule qualification cannot:

* the Companion **service** — not a test fixture — resolved the file from the
  words of a request;
* the task reached ``waiting_for_approval`` and the approval it raised named
  the real application and the real file;
* answering it drove a real capsule launch inside a real graphical session,
  under the session's own systemd user manager;
* the result landed in the user's own directory and the original did not change;
* and, in the denial run, that answering "no" produced no grant, no launch and
  no output.

Two runs, one program. ``--decision allow`` is §15; ``--decision deny`` is §17.
They share every line above the answer so that a difference between them is a
difference in the answer and not in the harness.

The record is JSON on stdout between two markers, so the serial console can
carry it out of a machine with no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BEGIN = "BUNNY-JOURNEY-BEGIN"
END = "BUNNY-JOURNEY-END"

REQUEST = "Resize this to 100 pixels wide."
SOURCE_WIDTH, SOURCE_HEIGHT, TARGET_WIDTH = 400, 200, 100

#: How long to let the whole journey take. A capsule task is ~200 ms; this is
#: generous enough that a slow first launch is not a failure and short enough
#: that a hang is not a hang for ever.
JOURNEY_SECONDS = 180.0

#: The binding fields ``resolve_approval`` declares. Repeated back exactly as
#: received: the runtime compares every one against the request it recorded, and
#: a client that answered "this is not the question that was asked" by trying
#: again with different values would be doing the thing that check exists to
#: prevent.
BINDING_KEYS = (
    "requestId", "sessionId", "taskId", "planId", "transitionId", "action",
    "destination", "providerId", "dataClassification", "estimatedCostUnits",
    "destinationFingerprint",
)

#: Which answer this copy of the probe gives. The harness rewrites this line
#: when it stages the file, because the injected unit runs the probe with no
#: arguments and there is no channel into the guest before the session exists.
#: An anchor rather than an environment variable: a `sed` that matched nothing
#: would leave the denial run silently answering "allow", and a line that must
#: be rewritten is one whose absence the driver can check for.
DECISION_DEFAULT = "granted"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


def write_png(path: Path, width: int, height: int, colour: int) -> bool:
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except Exception:  # noqa: BLE001
        return False
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(path), "png", [], [])
    return path.is_file()


def measure_png(path: Path):
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    except Exception:  # noqa: BLE001
        return None
    return [pixbuf.get_width(), pixbuf.get_height()]


def session_ready(wait: float) -> dict:
    """The installed readiness probe, run as it ships.

    Not reimplemented here. A harness with its own idea of readiness is a
    harness that can be ready when the product is not.
    """
    probe = Path("/usr/libexec/bunny-session-ready")
    if not probe.is_file():
        return {"ok": False, "reason": "the readiness probe is not installed"}
    completed = subprocess.run(
        [str(probe), "--wait", str(wait)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    document = {}
    try:
        document = json.loads(completed.stdout.split("BUNNY_SESSION_READY")[0].strip())
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": completed.returncode == 0,
        "markerSeen": any(
            line.strip() == "BUNNY_SESSION_READY" for line in completed.stdout.splitlines()
        ),
        "notReady": document.get("notReady", []),
        "checks": document.get("checks", {}),
    }


def run(decision: str) -> dict:
    sys.path.insert(0, "/usr/lib/bunny-os/python")
    from companion.protocol import CompanionClient, CompanionClientError

    record: dict = {"decision": decision, "request": REQUEST}
    record["readiness"] = session_ready(120.0)

    pictures = Path.home() / "Pictures"
    source = pictures / "holiday.png"
    neighbour = pictures / "private-neighbour.png"
    for path in (source, neighbour):
        if path.exists():
            path.unlink()
    for stale in pictures.glob("holiday-resized*.png"):
        stale.unlink()
    if not write_png(source, SOURCE_WIDTH, SOURCE_HEIGHT, 0x3366CCFF):
        record["fixture"] = {"ok": False, "reason": "no image library in the session"}
        return record
    write_png(neighbour, 32, 32, 0xFF0000FF)
    before = digest(source)
    neighbour_before = digest(neighbour)
    record["fixture"] = {"ok": True, "source": str(source), "digest": before}

    client = CompanionClient()
    try:
        session = client.create_session("Journey")
        session_id = str(session["session"]["sessionId"])
    except (CompanionClientError, KeyError) as error:
        record["submit"] = {"ok": False, "error": str(error)}
        return record

    started = time.monotonic()
    try:
        submitted = client.submit_task(session_id, REQUEST)
        task_id = str(submitted["task"]["taskId"])
    except (CompanionClientError, KeyError) as error:
        record["submit"] = {"ok": False, "error": str(error)}
        return record
    record["submit"] = {"ok": True, "taskId": task_id, "sessionId": session_id}

    # Watch the task. Every state it passes through is recorded, because §14
    # asks for the states to be exercised by the real task and a list of them is
    # the evidence for that.
    states: list[str] = []
    answered = False
    approval: dict = {}
    deadline = time.monotonic() + JOURNEY_SECONDS
    while time.monotonic() < deadline:
        try:
            view = client.get_task(task_id)["task"]
        except CompanionClientError:
            break
        state = str(view.get("state", ""))
        if not states or states[-1] != state:
            states.append(state)
        if state == "waiting_for_approval" and not answered:
            # The *presentation* state, which is where the window gets its
            # approvals. The task view carries only eight of the eleven binding
            # fields — no sessionId, no taskId, no destination — so answering
            # from it is refused with "requires sessionId". ApprovalPresentation
            # has a `binding` for exactly this, and the runtime compares every
            # field against the request it recorded.
            try:
                presented = client.get_presentation_state(task_id)
            except CompanionClientError as error:
                record["presentationError"] = str(error)
                break
            pending = (presented.get("state") or {}).get("approvals") or []
            if pending:
                raw = dict(pending[-1])
                binding = {key: raw.get(key) for key in BINDING_KEYS}
                approval = {
                    "action": raw.get("action"),
                    "reason": raw.get("reason"),
                    "destination": raw.get("destination"),
                    "destinationDetail": raw.get("destinationDetail"),
                    "requestId": raw.get("requestId"),
                    "dataClassification": raw.get("dataClassification"),
                    "keys": sorted(raw),
                    "missingFromBinding": sorted(
                        key for key in BINDING_KEYS if raw.get(key) in (None, "")
                    ),
                }
                try:
                    client.resolve_approval(binding, decision)
                    answered = True
                    record["answeredAt"] = round(time.monotonic() - started, 3)
                except CompanionClientError as error:
                    record["answerError"] = str(error)
                    break
        if state in ("completed", "failed", "cancelled", "blocked"):
            break
        time.sleep(0.25)

    record["states"] = states
    record["approval"] = approval
    record["elapsedSeconds"] = round(time.monotonic() - started, 3)
    try:
        final = client.get_task(task_id)["task"]
    except CompanionClientError:
        final = {}
    record["finalState"] = final.get("state")
    record["summary"] = str(final.get("summary") or final.get("displaySummary") or "")[:400]
    record["outputs"] = final.get("outputs") or []

    produced = sorted(item.name for item in pictures.glob("holiday-resized*.png"))
    record["result"] = {
        "files": produced,
        "pixels": measure_png(pictures / produced[0]) if produced else None,
    }
    record["original"] = {"unchanged": digest(source) == before, "exists": source.is_file()}
    record["neighbour"] = {
        "unchanged": neighbour.is_file() and digest(neighbour) == neighbour_before,
    }

    # The grant the answer produced, and whether it survived the task.
    try:
        from trust.store import TrustStore
        import trust

        store = TrustStore(trust.default_store_path(), session_id="journey-probe").load()
        grants = [
            dict(grant.as_record())
            for grant in store.for_application("art.comrade.BunnyImageTool")
        ]
        record["grantsAfter"] = grants
    except Exception as error:  # noqa: BLE001
        record["grantsAfter"] = {"error": f"{type(error).__name__}: {error}"}

    return record


def _reexec_as_user(user: str, argv: list[str]) -> int:
    """Run again as the logged-in user, inside their session.

    The harness injects this as a *system* unit, so it starts as root — and root
    is exactly who cannot do this. The Companion socket lives in the user's
    runtime directory, the capsule runtime asks the user's own systemd manager
    for a transient unit, and a grant belongs to a person. A probe that ran as
    root would be measuring a path the product does not have.

    The session's own environment is read from the user manager rather than
    guessed: `WAYLAND_DISPLAY` in particular is imported by gnome-session at a
    moment nothing here can predict, and a hard-coded `wayland-0` is right until
    it is not.
    """
    uid = subprocess.run(["id", "-u", user], capture_output=True, text=True,
                         check=False).stdout.strip()
    if not uid.isdigit():
        print(f"no such user: {user}", file=sys.stderr)
        return 3
    runtime = f"/run/user/{uid}"
    environment = {
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        "HOME": f"/home/{user}",
        "PATH": "/usr/bin:/bin",
    }
    shown = subprocess.run(
        ["runuser", "-u", user, "--", "env", f"XDG_RUNTIME_DIR={runtime}",
         f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
         "systemctl", "--user", "show-environment"],
        capture_output=True, text=True, check=False,
    ).stdout
    for line in shown.splitlines():
        key, _, value = line.partition("=")
        if key in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE", "XDG_DATA_DIRS"):
            environment[key] = value
    command = ["runuser", "-u", user, "--", "env"]
    command += [f"{key}={value}" for key, value in environment.items()]
    command += [sys.executable, os.path.abspath(__file__)] + argv
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capsule-journey-probe")
    parser.add_argument(
        "--decision", choices=("granted", "denied"), default=DECISION_DEFAULT
    )
    parser.add_argument("--as-user", default=os.environ.get("BUNNY_PROBE_USER", ""))
    arguments = parser.parse_args(argv)

    if arguments.as_user and os.geteuid() == 0:
        return _reexec_as_user(
            arguments.as_user, ["--decision", arguments.decision]
        )
    try:
        record = run(arguments.decision)
    except Exception as error:  # noqa: BLE001 - a probe that dies must still report
        import traceback

        record = {"probeError": f"{type(error).__name__}: {error}",
                  "traceback": traceback.format_exc()[-1500:]}
    body = json.dumps(record, indent=1, sort_keys=True)
    # A file first, and the console second.
    #
    # The console is shared with the kernel, and a kernel audit line landed in
    # the middle of a JSON *line* — not between lines, where a prefix strip
    # would have caught it. The record parsed as garbage and a completed run
    # read as no record at all. The file is extracted from the disk afterwards;
    # the console copy stays because it is the only channel a boot that never
    # reaches shutdown still has.
    try:
        target = Path("/var/log/bunny-journey.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    except OSError as error:
        print(f"could not write the record: {error}", file=sys.stderr)
    print(BEGIN, flush=True)
    print(body, flush=True)
    print(END, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
