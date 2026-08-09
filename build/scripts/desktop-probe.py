#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Ask a booted Bunny OS what its desktop is actually doing.

Injected into a copy of the disk by ``desktop-inject.sh`` and run once, after
the graphical target has settled. It is not shipped: a measuring instrument
inside the artifact would be part of what it measures.

The screenshot the harness takes says what the desktop *looks* like. This says
what it *is* — which session GDM chose, whether the extension is enabled or
merely installed, whether GNOME Shell threw while enabling it, and which of the
thirty-five modules reached the read-only root. Those are the questions a
picture cannot answer, and three of them have a failure mode that produces a
perfectly ordinary-looking GNOME desktop: an extension that failed to enable
leaves the session running and the desktop absent.

Everything is reported as measured. There is no field here that is computed
from another field, and no check that reports success because its input was
missing — the pattern PUBLIC_ALPHA_INTEGRATION_REPORT.md names as the reason
four separate checks passed while looking at the wrong thing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop_interaction  # noqa: E402

EXTENSION_UUID = "bunny-shell@bunny-os.org"
EXTENSION_ROOT = Path("/usr/share/gnome-shell/extensions") / EXTENSION_UUID
RECORD = Path("/var/log/bunny-desktop-record.json")
MARKER_BEGIN = "BUNNY-DESKTOP-RECORD-BEGIN"
MARKER_END = "BUNNY-DESKTOP-RECORD-END"


def run(argv: list[str], *, user: str | None = None, timeout: int = 30) -> dict:
    """Run a command and record what happened, including when it did not run."""
    if user:
        argv = ["/usr/bin/sudo", "-u", user, "-H", *argv]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "ran": False, "error": str(exc)}
    return {
        "argv": argv,
        "ran": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[:4000],
        "stderr": completed.stderr.strip()[:2000],
    }


def session_user() -> str:
    return os.environ.get("BUNNY_PROBE_USER", "bunny")


def user_bus_environment(user: str) -> list[str]:
    """The two variables a user-bus client needs, as a sudo prefix.

    loginctl gives the uid; the bus address is derived from it rather than read
    from the session, because a probe that could not find the session would
    otherwise silently query the *system* bus and report that GNOME Shell is not
    running on a machine where it is.
    """
    uid = run(["/usr/bin/id", "-u", user])
    value = uid.get("stdout", "").strip()
    if not value.isdigit():
        return []
    return [
        f"XDG_RUNTIME_DIR=/run/user/{value}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{value}/bus",
    ]


def shell_dbus(user: str, environment: list[str], method: str, body: str) -> dict:
    """Call a method on org.gnome.Shell as the session user.

    An empty `body` is dropped rather than passed. `ListExtensions` takes no
    arguments, and handing gdbus an empty argv element is handing it one
    argument — so the call was refused as "too many arguments" on every run, and
    `wait_for_shell` reported a shell that was answering every other question as
    not responding.
    """
    if not environment:
        return {"ran": False, "error": "no user runtime directory; the session was not found"}
    argv = ["/usr/bin/env", *environment, "/usr/bin/gdbus", "call", "--session",
            "--dest", "org.gnome.Shell",
            "--object-path", "/org/gnome/Shell",
            "--method", method]
    if body:
        argv.append(body)
    return run(argv, user=user)


def wait_for_shell(user: str, environment: list[str], *, seconds: int = 420) -> dict:
    """Poll until GNOME Shell answers, and say how long it took.

    A fixed sleep would either be too short on a cold llvmpipe boot or waste two
    minutes on a fast one, and — worse — a probe that ran too early would report
    a desktop that had not started yet as a desktop that failed.

    The budget was 180 seconds and that was exactly the failure it was written
    to avoid: a run reported `shellResponded: false after 180s` on a session
    whose shell answered every later question in the same run. The poll returns
    the moment the shell answers, so a larger budget costs a fast boot nothing
    and stops a slow one being reported as a broken one.
    """
    started = time.monotonic()
    attempts = 0
    while time.monotonic() - started < seconds:
        attempts += 1
        answer = shell_dbus(user, environment, "org.gnome.Shell.Extensions.ListExtensions", "")
        if answer.get("returncode") == 0:
            return {
                "responded": True,
                "afterSeconds": round(time.monotonic() - started, 1),
                "attempts": attempts,
            }
        time.sleep(5)
    return {"responded": False, "afterSeconds": seconds, "attempts": attempts}


def extension_state(user: str, environment: list[str]) -> dict:
    """Installed, enabled, and — the one that matters — whether it errored.

    GNOME Shell's extension state is an enum: 1 ENABLED, 2 DISABLED, 3 ERROR,
    4 OUT_OF_DATE, 6 INITIALIZED. An extension whose enable() threw is state 3
    with the exception in `error`, and the session looks entirely normal.
    """
    call = shell_dbus(
        user, environment, "org.gnome.Shell.Extensions.GetExtensionInfo",
        f'"{EXTENSION_UUID}"')
    state = {"call": call, "state": None, "stateName": "unknown", "error": None}
    if call.get("returncode") != 0:
        return state
    text = call.get("stdout", "")
    matched = re.search(r"'state':\s*<(\d+(?:\.\d+)?)>", text)
    if matched:
        value = int(float(matched.group(1)))
        state["state"] = value
        state["stateName"] = {
            1: "ENABLED", 2: "DISABLED", 3: "ERROR", 4: "OUT_OF_DATE",
            5: "DOWNLOADING", 6: "INITIALIZED", 7: "DISABLING", 8: "ENABLING",
        }.get(value, f"unknown({value})")
    error = re.search(r"'error':\s*<'([^']*)'>", text)
    if error and error.group(1):
        state["error"] = error.group(1)
    return state


def installed_modules() -> dict:
    if not EXTENSION_ROOT.is_dir():
        return {"present": False, "root": str(EXTENSION_ROOT), "modules": []}
    modules = sorted(
        str(path.relative_to(EXTENSION_ROOT))
        for path in EXTENSION_ROOT.rglob("*.js")
    )
    return {
        "present": True,
        "root": str(EXTENSION_ROOT),
        "moduleCount": len(modules),
        "modules": modules,
        "hasCompiledSchema": (EXTENSION_ROOT / "schemas/gschemas.compiled").is_file(),
        "stylesheetBytes": (EXTENSION_ROOT / "stylesheet.css").stat().st_size
        if (EXTENSION_ROOT / "stylesheet.css").is_file() else None,
    }


def desktop_journal(user: str) -> dict:
    """The desktop's own log lines, and GNOME Shell's complaints about it.

    Two separate reads. The first is what the desktop chose to say — the
    renderer probe, the layout decision, any dropped card. The second is what
    the compositor said about it, which is where an exception during enable()
    appears.
    """
    ours = run(["/usr/bin/journalctl", "--no-pager", "--since", "-30min",
                "--grep", "bunny-desktop", "-o", "cat"])
    shell = run(["/usr/bin/journalctl", "--no-pager", "--since", "-30min",
                 "-t", "gnome-shell", "-p", "warning", "-o", "cat"])
    return {
        "desktopLines": [line for line in ours.get("stdout", "").splitlines() if line.strip()],
        "shellWarnings": [line for line in shell.get("stdout", "").splitlines() if line.strip()][-40:],
    }


def session_identity(user: str, environment: list[str]) -> dict:
    """Which session GDM actually started.

    The whole harness is pointless if GDM picked plain GNOME: the extension
    would be installed, enabled and inert, because extension.js returns early
    unless BUNNY_SHELL_MODE is "normal".
    """
    loginctl = run(["/usr/bin/loginctl", "list-sessions", "--no-legend"])
    detail = {}
    for line in loginctl.get("stdout", "").splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[2] == user:
            detail = run(["/usr/bin/loginctl", "show-session", fields[0],
                          "-p", "Type", "-p", "Desktop", "-p", "State", "-p", "Active"])
            break
    environment_dump = run(
        ["/usr/bin/systemctl", "--user", "show-environment"], user=user) if environment else {}
    return {
        "sessions": loginctl,
        "session": detail,
        "userEnvironment": environment_dump,
    }


def background_setting(user: str, environment: list[str]) -> dict:
    if not environment:
        return {"ran": False, "error": "no user session"}
    result = run(["/usr/bin/env", *environment, "/usr/bin/gsettings", "get",
                  "org.gnome.desktop.background", "picture-uri-dark"], user=user)
    uri = result.get("stdout", "").strip().strip("'")
    path = uri[len("file://"):] if uri.startswith("file://") else None
    return {
        "call": result,
        "uri": uri,
        # The setting naming a file is not the same as the file existing, and
        # the difference is a black desktop.
        "fileExists": Path(path).is_file() if path else False,
        "fileBytes": Path(path).stat().st_size if path and Path(path).is_file() else None,
    }


def assistant_bridge(user: str) -> dict:
    """The bridge is a shipped program; run it and record what it says.

    As the session user, not as the probe. The companion runtime's socket lives
    under the *user's* state directory, so asking as root produces
    ``/root/.local/state/.../runtime.sock: No such file or directory`` — a
    correct answer to a question about the wrong account, and one that reads
    exactly like a runtime that is not running.
    """
    result = run(["/usr/bin/bunny-shell-assistant", "health"], user=user)
    document = None
    if result.get("returncode") == 0:
        for line in result.get("stdout", "").splitlines():
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"call": result, "health": document}


def serve_interaction(user: str, environment: list[str]) -> dict:
    """Answer the host's requests until it says the interaction is finished.

    The protocol is four verbs and it is deliberately dumb — the host holds the
    script, and this end only measures. Anything else would mean two programs
    that both believe they know what the test is.

      controls      every named control the shell exposes, with its rectangle
      state <name>  the four signals for `files` or `terminal`
      shell         is GNOME Shell answering, is the extension still enabled
      done          stop serving; the run is over

    A missing control channel is recorded and is not fatal. The rest of the
    probe's answers are still worth having, and a harness that failed the whole
    run because one virtio device did not appear would be reporting a defect in
    itself as a defect in the product.
    """
    channel = desktop_interaction.ControlChannel()
    transcript: list[dict] = []
    result: dict = {
        "channel": {"path": str(desktop_interaction.CONTROL_PORT),
                    "available": channel.available, "error": channel.error},
        "transcript": transcript,
    }
    if not channel.available:
        print("interaction: no control port; the pointer test cannot run", flush=True)
        return result

    # Wait to be asked, rather than announcing.
    #
    # A virtio-serial chardev with `wait=off` discards everything the guest
    # writes while no host client is attached, and the host attaches after it
    # has finished taking its timed screenshots — a minute or more after this
    # probe is ready. Announcing first therefore writes the targets into a void
    # and then blocks forever waiting for a reply to a message nobody received.
    # The handshake removes the race instead of tuning the delays either side
    # of it.
    print("interaction: waiting for the host to open the control channel", flush=True)
    hello = channel.receive(timeout=780)
    if hello is None:
        result["channel"]["error"] = "the host never opened the control channel"
        print("interaction: the host never said hello", flush=True)
        channel.close()
        return result
    result["hello"] = hello

    result["accessibility"] = desktop_interaction.enable_accessibility(user, environment)
    controls = desktop_interaction.locate_controls(user, environment)
    result["controls"] = controls
    targets = {}
    for logical, label in (("files", "Files"), ("terminal", "Terminal"),
                           ("assistant", "AI Assistant"), ("home", "Home")):
        found = desktop_interaction.find_control(controls, label)
        if found is not None:
            targets[logical] = found
    result["targets"] = targets

    # The host is waiting for this before it touches the pointer.
    channel.send({"event": "ready", "targets": targets,
                  "controlCount": len(controls.get("controls", []))})

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        request = channel.receive(timeout=deadline - time.monotonic())
        if request is None:
            transcript.append({"note": "the host stopped talking"})
            break
        verb = request.get("command")
        label = request.get("label", "")
        answer: dict = {"command": verb, "label": label}
        if verb == "controls":
            fresh = desktop_interaction.locate_controls(user, environment)
            answer["controls"] = fresh
        elif verb == "state":
            name = request.get("application")
            if name in desktop_interaction.APPLICATIONS:
                answer["state"] = desktop_interaction.application_state(name, user, environment)
            else:
                answer["error"] = f"unknown application {name!r}"
        elif verb == "shell":
            answer["shell"] = desktop_interaction.shell_alive(user, environment)
        elif verb == "done":
            transcript.append(answer)
            channel.send({"reply": answer})
            break
        else:
            answer["error"] = f"unknown command {verb!r}"
        transcript.append(answer)
        channel.send({"reply": answer})

    channel.close()
    return result


def main() -> int:
    user = session_user()
    environment = user_bus_environment(user)

    record: dict = {
        "schemaVersion": 1,
        "probe": "bunny-desktop-probe",
        "user": user,
        "bootId": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip(),
        "osRelease": dict(
            line.split("=", 1) for line in
            Path("/usr/lib/os-release").read_text(encoding="utf-8").splitlines()
            if "=" in line
        ),
        "userBusEnvironment": environment,
    }

    # Before anything is measured: stop the machine locking itself. A session
    # that idles into the lock screen disables every extension, including this
    # desktop, and a probe that waited a few minutes too long would then report
    # a working desktop as absent. See keep_the_session_awake.
    record["sessionAwake"] = desktop_interaction.keep_the_session_awake(user, environment)

    record["shellResponded"] = wait_for_shell(user, environment)
    record["sessionIdentity"] = session_identity(user, environment)
    record["extension"] = extension_state(user, environment)
    record["installedModules"] = installed_modules()
    record["background"] = background_setting(user, environment)
    record["assistantBridge"] = assistant_bridge(user)

    # The pointer test. Everything above is a question this probe asks itself;
    # this is the one thing it cannot do alone, because the pointer lives in
    # QEMU. The guest finds the controls and reports what happened; the host
    # presses them. See desktop_interaction.ControlChannel.
    record["interaction"] = serve_interaction(user, environment)

    record["journal"] = desktop_journal(user)

    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    # Also on the console, framed, so a run whose disk cannot be read afterwards
    # still produced something.
    print(MARKER_BEGIN, flush=True)
    print(json.dumps(record, sort_keys=True), flush=True)
    print(MARKER_END, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
