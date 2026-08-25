#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything the Public Alpha gates need to know, asked from inside the guest.

This runs **in a booted Bunny OS virtual machine**, not on a build host, and it
is injected by ``vm-alpha-story.sh`` rather than installed by the image. That
distinction is the point: it is a measuring instrument, and an instrument that
shipped in the artifact would be part of what it measures.

It writes one JSON document to standard output, framed by two markers so the
harness can lift it out of a serial console that also carries the kernel log.
Everything is best-effort: a probe that raised would take the whole record with
it, and a record with one section missing is worth more than no record.

What it answers, section by section:

``identity``       §39 — what this system says it is
``boot``           §4  — the timestamps, from systemd's own accounting
``units``          §12 — the dependency graph, as it actually resolved
``session``        §11 — whether the companion started once, in a real session
``provenance``     §6  — which files the running code was imported from
``capability``     §20 — hardware, and separately what works
``surveys``        §8/§9/§10 — providers, speech, audio
``network``        §13/§28 — every socket, and every outbound destination
``story``          §30 — the product path, as far as a headless VM can take it
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

BEGIN = "---BUNNY-ALPHA-JSON-BEGIN---"
END = "---BUNNY-ALPHA-JSON-END---"

#: Characters of base64 per console line. Short enough that a torn line loses
#: one chunk rather than a large fraction of the record, long enough that a
#: 130 kB record is a few hundred lines rather than a few thousand.
CHUNK = 512

INSTALLED_ROOT = Path("/usr/lib/bunny-os/python")

#: §6's list, verbatim. Every one of these must be imported from the installed
#: tree, and the record says which file each came from so that a bind-mounted
#: checkout cannot pass as an image.
SUBSYSTEMS = (
    ("companion runtime", "companion.runtime"),
    ("presentation", "companion.presentation"),
    ("2D renderer", "companion.character.animated_renderer"),
    ("3D renderer", "companion.character.three_d.renderer"),
    ("voice", "companion.voice.service"),
    ("speech input", "companion.speech.service"),
    ("agents", "companion.agents.service"),
    ("desktop actions", "companion.desktop.broker"),
    ("capability runtime", "capability.runtime"),
    ("ToolBroker", "companion.tools"),
)

#: The units the Alpha session is made of, in the order §12 declares them.
SYSTEM_UNITS = (
    "graphical.target", "gdm.service", "systemd-logind.service",
    "bunny-health-check.service", "bunny-system-broker.socket",
)
USER_UNITS = (
    "bunny-config-dir.service", "bunny-first-boot.service",
    "bunny-companion.service", "bunny-companion-window.service",
    "bunny-first-run.service",
)

TARGET_USER = os.environ.get("BUNNY_PROBE_USER", "bunny")


def run(argv: list[str], *, timeout: float = 60.0, user: str = "") -> dict:
    """Run a command and record what happened, never raising."""
    if user:
        argv = ["/usr/bin/systemd-run", "--quiet", "--pipe", "--wait",
                f"--machine={user}@", "--user", "--collect", "--", *argv]
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"argv": argv, "error": str(error), "returncode": -1, "stdout": "", "stderr": ""}
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-4000:],
    }


def _user_id() -> str:
    result = run(["/usr/bin/id", "-u", TARGET_USER], timeout=15)
    value = (result.get("stdout") or "").strip()
    return value if value.isdigit() else "1000"


def user_shell(command: str, *, timeout: float = 120.0) -> dict:
    """Run a shell command as the desktop user, inside their session bus.

    The environment is what makes this work, and getting it wrong is silent:
    ``systemctl --user`` with no ``XDG_RUNTIME_DIR`` and no
    ``DBUS_SESSION_BUS_ADDRESS`` does not fail, it answers ``unknown`` for
    every property. A whole section of this record read as "the companion did
    not start" for that reason on the first run.

    ``machinectl shell`` would set it for us and is the obvious tool. It is not
    installed: ``systemd-container`` is not part of a bootc desktop image, and
    the first run of this probe reported ``/usr/bin/machinectl: No such file or
    directory`` for every user query. So the environment is set by hand, which
    needs no package that the image does not already have.
    """
    uid = _user_id()
    runner = "/usr/sbin/runuser" if Path("/usr/sbin/runuser").exists() else "/usr/bin/runuser"
    if not Path(runner).exists():
        runner = "/usr/bin/su"
        argv = [runner, "-", TARGET_USER, "-c"]
    else:
        argv = [runner, "-u", TARGET_USER, "--"]
    environment = (
        f"XDG_RUNTIME_DIR=/run/user/{uid} "
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus "
        f"XDG_STATE_HOME=/var/home/{TARGET_USER}/.local/state "
        f"HOME=/var/home/{TARGET_USER} "
        "PATH=/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin "
    )
    if argv[-1] == "-c":
        return run([*argv, f"env {environment} bash -lc {command!r}"], timeout=timeout)
    return run([*argv, "env", *environment.split(), "bash", "-lc", command], timeout=timeout)


def section_identity() -> dict:
    record: dict = {}
    for name, path in (
        ("release", "/usr/lib/bunny-os/release.json"),
    ):
        try:
            record[name] = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as error:
            record[name] = {"error": str(error)}
    try:
        record["osRelease"] = {
            key: value.strip('"')
            for key, _, value in (
                line.partition("=") for line in
                Path("/usr/lib/os-release").read_text(encoding="utf-8").splitlines()
            ) if key
        }
    except Exception as error:
        record["osRelease"] = {"error": str(error)}
    record["companionIdentity"] = json.loads(
        run(["/usr/bin/bunny-os", "--json", "companion", "identity"]).get("stdout") or "{}"
    ) if _json_capable() else {}
    return record


def _json_capable() -> bool:
    result = run(["/usr/bin/bunny-os", "--json", "companion", "identity"], timeout=90)
    if result["returncode"] != 0:
        return False
    try:
        json.loads(result["stdout"])
    except Exception:
        return False
    return True


def section_boot() -> dict:
    """§4's timestamps, taken from systemd rather than from a stopwatch.

    ``systemd-analyze`` reports firmware, loader, kernel and userspace as
    intervals; the per-unit activation timestamps give the rest. Nothing here is
    measured by this script, which is deliberate — a probe that timed the boot
    would be timing itself.
    """
    record = {
        "analyze": run(["/usr/bin/systemd-analyze", "time"]).get("stdout", "").strip(),
        "blame": "\n".join(
            run(["/usr/bin/systemd-analyze", "blame"]).get("stdout", "").splitlines()[:15]
        ),
        "virtualisation": run(["/usr/bin/systemd-detect-virt"]).get("stdout", "").strip(),
    }
    stamps: dict[str, str] = {}
    for unit in ("systemd-journald.service", "sysinit.target", "basic.target",
                 "multi-user.target", "graphical.target", "gdm.service"):
        output = run([
            "/usr/bin/systemctl", "show", unit,
            "--property=ActiveEnterTimestampMonotonic",
            "--property=ActiveEnterTimestamp",
        ]).get("stdout", "")
        for line in output.splitlines():
            key, _, value = line.partition("=")
            if key and value:
                stamps[f"{unit}:{key}"] = value.strip()
    record["unitTimestamps"] = stamps
    record["kernel"] = run(["/usr/bin/uname", "-r"]).get("stdout", "").strip()
    return record


def section_units() -> dict:
    record: dict = {"system": {}, "user": {}}
    for unit in SYSTEM_UNITS:
        record["system"][unit] = _unit_properties(["/usr/bin/systemctl", "show", unit])
    listing = user_shell(
        "systemctl --user list-units --all --no-legend --no-pager 'bunny-*' | cat",
    )
    record["userListing"] = listing.get("stdout", "")
    for unit in USER_UNITS:
        result = user_shell(
            f"systemctl --user show {unit} "
            "--property=LoadState --property=ActiveState --property=SubState "
            "--property=Result --property=NRestarts --property=After --property=Wants "
            "--property=Requires --property=PartOf --property=ActiveEnterTimestampMonotonic | cat",
        )
        record["user"][unit] = _parse_properties(result.get("stdout", ""))
    record["userPreset"] = user_shell(
        "systemctl --user is-enabled bunny-companion.service bunny-companion-window.service 2>&1 | cat",
    ).get("stdout", "")
    return record


def _unit_properties(argv: list[str]) -> dict:
    return _parse_properties(run([
        *argv, "--property=LoadState", "--property=ActiveState",
        "--property=SubState", "--property=Result", "--property=NRestarts",
    ]).get("stdout", ""))


def _parse_properties(text: str) -> dict:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key.strip()] = value.strip()
    return values


def section_session() -> dict:
    """§11: one runtime, one window, no terminal, and what the timeline says."""
    record: dict = {
        "loginctl": run(["/usr/bin/loginctl", "list-sessions", "--no-legend"]).get("stdout", ""),
        "seat": run(["/usr/bin/loginctl", "show-seat", "seat0", "--property=ActiveSession"]).get("stdout", ""),
    }
    # Counted as *processes in the unit's cgroup*, which is the question §11
    # asks: is there one runtime and one window, or two of either.
    #
    # Two wrong answers were measured before this one. ``pgrep -f
    # bunny-companion-window`` matches its own command line, the shell that
    # invoked it and the runuser that invoked that — three of each, on a system
    # where neither unit was enabled. ``TasksCurrent`` counts *threads*: 8 for
    # the runtime and 22 for a GTK window are normal and say nothing about
    # duplication.
    #
    # ``cgroup.procs`` holds exactly the processes systemd started for the unit.
    record["processCounts"] = _parse_properties(user_shell(
        "count() { "
        "  p=$(systemctl --user show \"$1\" --property=ControlGroup --value 2>/dev/null); "
        "  f=/sys/fs/cgroup${p}/cgroup.procs; "
        "  if [ -n \"$p\" ] && [ -r \"$f\" ]; then wc -l <\"$f\"; else echo 0; fi; }; "
        "printf 'runtime=%s\\nwindow=%s\\nterminals=%s\\n' "
        "\"$(count bunny-companion.service)\" "
        "\"$(count bunny-companion-window.service)\" "
        "\"$(pgrep -c -x gnome-terminal-server 2>/dev/null || echo 0)\"",
    ).get("stdout", ""))
    record["mainPids"] = user_shell(
        "systemctl --user show bunny-companion.service bunny-companion-window.service "
        "--property=Id --property=MainPID --property=NRestarts | cat",
    ).get("stdout", "")
    record["timeline"] = user_shell(
        "cat ${XDG_STATE_HOME:-$HOME/.local/state}/bunny-os/companion/session-timeline.json "
        "2>/dev/null || cat /var/lib/systemd/linger 2>/dev/null || true",
    ).get("stdout", "")
    record["socket"] = user_shell(
        "ls -la ${XDG_RUNTIME_DIR}/bunny-companion/ 2>&1 | cat",
    ).get("stdout", "")
    record["journal"] = user_shell(
        "journalctl --user -u bunny-companion.service -u bunny-companion-window.service "
        "-n 60 --no-pager -o cat 2>&1 | cat",
    ).get("stdout", "")
    return record


def section_provenance() -> dict:
    """§6: every subsystem's ``__file__``, digest, and the mount behind it.

    Run as the desktop user through their session so that the interpreter, the
    path and the environment are the ones the companion actually runs with. A
    provenance record taken as root with a different ``sys.path`` would be a
    record of a different program.
    """
    script = (
        "import hashlib, json, os, site, sys\n"
        "root = '/usr/lib/bunny-os/python'\n"
        "if root not in sys.path:\n"
        "    sys.path.insert(0, root)\n"
        "out = {'sysPath': sys.path, 'modules': {}, 'rejections': []}\n"
        f"pairs = {list(SUBSYSTEMS)!r}\n"
        "for label, name in pairs:\n"
        "    try:\n"
        "        module = __import__(name, fromlist=['*'])\n"
        "        path = getattr(module, '__file__', '') or ''\n"
        "        try:\n"
        "            digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()\n"
        "        except Exception as error:\n"
        "            digest = 'error: %s' % error\n"
        "        out['modules'][label] = {'module': name, 'file': path, 'sha256': digest,\n"
        "                                 'installed': bool(path) and path.startswith(root)}\n"
        "        if path and not path.startswith(root):\n"
        "            out['rejections'].append('%s imported from %s' % (label, path))\n"
        "    except Exception as error:\n"
        "        out['modules'][label] = {'module': name, 'error': str(error), 'installed': False}\n"
        "        out['rejections'].append('%s did not import: %s' % (label, error))\n"
        "out['pythonpath'] = os.environ.get('PYTHONPATH', '')\n"
        "if out['pythonpath']:\n"
        "    out['rejections'].append('PYTHONPATH is set: %s' % out['pythonpath'])\n"
        "out['userSite'] = site.getusersitepackages() if hasattr(site, 'getusersitepackages') else ''\n"
        "out['userSiteExists'] = os.path.isdir(out['userSite']) if out['userSite'] else False\n"
        "if out['userSiteExists']:\n"
        "    out['rejections'].append('a user site-packages directory exists: %s' % out['userSite'])\n"
        "print(json.dumps(out))\n"
    )
    # Written to a file rather than passed through the shell. The first version
    # hex-encoded it into a -c argument to avoid quoting, which worked and made
    # the failure unreadable: when the user shell itself was broken, what came
    # back was four kilobytes of hex in the error record.
    source = Path("/tmp/bunny-alpha-provenance.py")
    try:
        source.write_text(script, encoding="utf-8")
        source.chmod(0o644)
    except OSError as error:
        return {"error": f"the provenance script could not be written: {error}"}
    result = user_shell(f"python3 {source}", timeout=180)
    try:
        record = json.loads(result.get("stdout", "").strip().splitlines()[-1])
    except Exception as error:
        return {"error": str(error), "raw": result}
    record["mounts"] = run(["/usr/bin/findmnt", "-n", "-o", "TARGET,SOURCE,FSTYPE", "/usr"]).get("stdout", "")
    record["imageDigest"] = run(["/usr/bin/bootc", "status", "--json"]).get("stdout", "")[:4000]
    return record


def section_capability() -> dict:
    result = user_shell("bunny-os --json companion capability-record 2>&1 | cat", timeout=240)
    try:
        return json.loads(result.get("stdout", "").strip())
    except Exception as error:
        return {"error": str(error), "raw": result.get("stdout", "")[:4000]}


def section_surveys() -> dict:
    record: dict = {}
    for name, command in (
        ("onboarding", "bunny-os --json companion onboarding"),
        ("diagnose", "bunny-os --json companion diagnose"),
        ("characterPolicy", "bunny-os --json companion character-policy --dry-run"),
        ("settings", "bunny-os --json companion settings show"),
        ("firstRun", "bunny-first-run --describe"),
    ):
        result = user_shell(f"{command} 2>&1 | cat", timeout=240)
        try:
            record[name] = json.loads(result.get("stdout", "").strip())
        except Exception as error:
            record[name] = {"error": str(error), "raw": result.get("stdout", "")[:3000]}
    return record


def section_network() -> dict:
    """§13 and §28. Every socket, and specifically every non-loopback one.

    The assertion the gate makes is about ``established``: a listening socket on
    loopback is the companion's own, and an established connection to anything
    off this machine is the thing that must not exist.
    """
    listening = run(["/usr/sbin/ss", "-tulpn"]).get("stdout", "")
    established = run(["/usr/sbin/ss", "-tnp", "state", "established"]).get("stdout", "")
    outbound = [
        line for line in established.splitlines()[1:]
        if line.strip() and not any(
            local in line for local in ("127.0.0.1", "[::1]", "0.0.0.0")
        )
    ]
    return {
        "listening": listening,
        "established": established,
        "outboundConnections": outbound,
        "outboundCount": len(outbound),
        "resolvConf": _read("/etc/resolv.conf"),
        "defaultRoute": run(["/usr/sbin/ip", "route", "show", "default"]).get("stdout", "").strip(),
    }


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError as error:
        return f"error: {error}"


def section_story() -> dict:
    """§30, as far as a headless VM can take it.

    The steps that need a person looking at a screen — "the character appears",
    "the transcript appears" — are not attempted here and are not reported as
    passing. What is attempted is every step that has an observable effect:
    submitting a request, the provider selection that follows, the desktop
    action broker's view of what it may do, and the reversibility of a volume
    change.
    """
    steps: list[dict] = []

    def step(name: str, command: str, *, timeout: float = 240.0) -> dict:
        result = user_shell(f"{command} 2>&1 | cat", timeout=timeout)
        parsed: object
        try:
            parsed = json.loads(result.get("stdout", "").strip())
        except Exception:
            parsed = result.get("stdout", "")[:2000]
        record = {"step": name, "returncode": result.get("returncode"), "result": parsed}
        steps.append(record)
        return record

    step("no terminal is running", "pgrep -c -x gnome-terminal-server || echo 0")
    step("companion health", "bunny-os --json companion health")
    step("providers", "bunny-os --json companion agents-health")
    step("desktop actions available", "bunny-os --json companion diagnose")
    step("submit a typed request",
         "bunny-os --json companion task submit --request 'What can you do?' --run || true",
         timeout=300)
    step("task history survives", "bunny-os --json companion sessions")
    return {"steps": steps}


def main() -> int:
    record = {
        "schemaVersion": 1,
        "probe": "bunny-alpha-probe",
        "sections": {},
    }
    for name, function in (
        ("identity", section_identity),
        ("boot", section_boot),
        ("units", section_units),
        ("session", section_session),
        ("provenance", section_provenance),
        ("capability", section_capability),
        ("surveys", section_surveys),
        ("network", section_network),
        ("story", section_story),
    ):
        try:
            record["sections"][name] = function()
        except Exception as error:  # pragma: no cover - a probe never takes the record with it
            record["sections"][name] = {"error": f"{type(error).__name__}: {error}"}
    # The disk first, because the disk is authoritative.
    #
    # A serial console is a best-effort channel shared with the kernel, and on
    # the offline boots it demonstrably loses a line: `offline-001` lost chunk
    # 51 of 217 to interleaving even with the framing below. Writing the record
    # into the guest's own /var and reading it back out of the image afterwards
    # has no such channel — the harness mounts the disk and downloads a file.
    #
    # The console output is kept as the fallback, because it is the only channel
    # that works when the guest never finishes shutting down cleanly, and
    # because it is what makes a run watchable while it happens.
    #
    # Both candidates are under ``/var`` because ``/var`` is on the disk. The
    # fallback was ``/tmp`` and that is a tmpfs: it would have written
    # successfully, reported success, and left the harness — which looks at the
    # filesystem in the image — with nothing to find.
    serialised = json.dumps(record, sort_keys=True)
    for destination in ("/var/log/bunny-alpha-record.json", "/var/tmp/bunny-alpha-record.json"):
        try:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialised, encoding="utf-8")
            os.chmod(destination, 0o644)
            print(f"bunny-alpha-probe: wrote {destination}", flush=True)
            break
        except OSError as error:
            print(f"bunny-alpha-probe: {destination}: {error}", flush=True)

    # Base64, in numbered chunks, because a serial console interleaves.
    #
    # The first version printed the JSON as one line. It survives most boots and
    # it did not survive `offline-001`: a kernel message landed inside the
    # object at character 48312 and the record was lost — one story in five,
    # reported as a product failure when it was an instrument failure.
    #
    # A chunk line is `BUNNYB64 <index> <data>`. Anything the kernel writes
    # between two of them fails to match and is dropped; a chunk that is torn in
    # half fails to match and its *index* is missing, so the reassembly can say
    # which piece it lost instead of decoding something short and calling it
    # JSON. Base64 rather than raw, so the payload cannot contain a space, a
    # newline or a bracket that the framing depends on.
    payload = base64.b64encode(serialised.encode("utf-8")).decode("ascii")
    chunks = [payload[at:at + CHUNK] for at in range(0, len(payload), CHUNK)]
    print(BEGIN, flush=True)
    print(f"BUNNYB64-COUNT {len(chunks)}", flush=True)
    for index, chunk in enumerate(chunks):
        print(f"BUNNYB64 {index} {chunk}", flush=True)
    print(END, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
