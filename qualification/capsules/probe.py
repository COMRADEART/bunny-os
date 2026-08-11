#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A deterministic application that reports what it can reach, and nothing else.

This is the fixture the runtime qualification launches — once *inside* an App
Capsule and once outside it as the negative control. It is a real program: it
runs as the user, makes real syscalls, and writes a real file. What makes it
useful is that it is exhaustively boring — every check is a single attempt with
a fixed timeout, and the result is a value rather than an exit code.

Four rules it follows, and each exists because of a way this kind of probe lies.

**Standard library only, no repository imports.** It has to run inside a sandbox
where the only thing bound is ``/usr``, so it cannot import :mod:`trust` or
:mod:`capsules` even to describe itself. That constraint is also the point: a
probe that needed the repository on its path would be a probe that could not run
in the environment being tested.

**A failure to reach something is not the same as being denied it.** ``DENIED``
means the operating system refused; ``ABSENT`` means the thing was not there to
reach. A probe that reported ``ABSENT`` as ``DENIED`` would score a host with no
camera as a working camera restriction, which is exactly the false pass the
negative control exists to catch — so the distinction is made here as well, and
the two are compared.

**Every check is bounded.** A connect() to an unroutable address blocks for the
kernel's own timeout, so every network check carries an explicit one. A probe
that hung would be recorded as a crash.

**It writes its result to its own private storage rather than to stdout.** The
capsule's stdout goes to /dev/null, as any application's does; the result file
lands in the capsule's ``data`` directory, which the harness reads from the host
side afterwards. That makes "an application can write its own private data" a
measured result rather than an assumption, and it means the probe works
unchanged in both environments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

#: Where the probe writes its answer. Inside a capsule this is the bind target of
#: the capsule's own ``data`` directory; outside, the harness passes an ordinary
#: path so that the negative control writes somewhere comparable.
DEFAULT_OUTPUT = "/run/bunny/app/data/probe-result.json"

#: Every network attempt is bounded. Two seconds is far longer than a working
#: connection needs and far shorter than a kernel's own retry.
NETWORK_TIMEOUT = 2.0

#: What a check may report.
#:
#: ``AVAILABLE``  the probe did the thing.
#: ``DENIED``     the operating system refused. This is the isolation working.
#: ``ABSENT``     there was nothing there to reach; says nothing about isolation.
#: ``ERROR``      the check itself failed in a way that is neither.
RESULTS = ("AVAILABLE", "DENIED", "ABSENT", "ERROR")

_DENIED_ERRNOS = {1, 13, 30}  # EPERM, EACCES, EROFS


def _check(name: str, category: str, function) -> dict:
    """Run one check and record it.

    A check may return two values or three. The third is *structured* data —
    counts, key lists, mount points — and it is kept in its own field rather
    than stuffed into ``detail``, because ``detail`` is truncated for a human
    reader and a truncated JSON string silently parses as nothing. That is not
    hypothetical: it happened, the harness read ``None`` for the mount and
    environment counts, and the section skipped the comparison and reported PASS
    with the numbers missing from its own summary.
    """
    started = time.monotonic()
    data: dict | None = None
    try:
        outcome = function()
        if len(outcome) == 3:
            result, detail, data = outcome
        else:
            result, detail = outcome
    except PermissionError as error:
        result, detail = "DENIED", f"{type(error).__name__}: {error.strerror or error}"
    except FileNotFoundError as error:
        result, detail = "ABSENT", f"{type(error).__name__}: {error.strerror or error}"
    except OSError as error:
        if error.errno in _DENIED_ERRNOS:
            result, detail = "DENIED", f"errno {error.errno}: {error.strerror}"
        else:
            result, detail = "ABSENT", f"errno {error.errno}: {error.strerror}"
    except Exception as error:  # noqa: BLE001 - a probe must never abort the run
        result, detail = "ERROR", f"{type(error).__name__}: {error}"
    record = {
        "check": name,
        "category": category,
        "result": result,
        "detail": str(detail)[:400],
        "ms": round((time.monotonic() - started) * 1000, 2),
    }
    if data is not None:
        record["data"] = data
    return record


# -- individual checks ---------------------------------------------------


def _read_own_data() -> tuple[str, str]:
    marker = Path(os.environ.get("XDG_DATA_HOME", "/run/bunny/app/data")) / "own-marker.txt"
    if not marker.exists():
        return "ABSENT", f"{marker} does not exist"
    return "AVAILABLE", marker.read_text(encoding="utf-8").strip()[:120]


def _write_own_data() -> tuple[str, str]:
    target = Path(os.environ.get("XDG_DATA_HOME", "/run/bunny/app/data")) / "probe-wrote-this.txt"
    target.write_text("probe was here\n", encoding="utf-8")
    return "AVAILABLE", str(target)


def _read_home(home: str) -> tuple[str, str]:
    entries = sorted(os.listdir(home))
    return "AVAILABLE", f"{len(entries)} entries: {entries[:8]}"


def _read_path(path: str) -> tuple[str, str]:
    target = Path(path)
    if target.is_dir():
        return "AVAILABLE", f"{len(sorted(os.listdir(target)))} entries"
    data = target.read_bytes()
    return "AVAILABLE", f"{len(data)} bytes"


def _enumerate_capsules(root: str) -> tuple[str, str]:
    entries = sorted(os.listdir(root))
    return "AVAILABLE", f"{len(entries)} capsule directories: {entries[:6]}"


def _environment() -> tuple[str, str]:
    dangerous = sorted(
        key for key in os.environ
        if key in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "GIO_MODULE_DIR", "GTK_MODULES")
        or key.lower().endswith(("_token", "_secret", "_key", "_password"))
        or key.lower() in ("http_proxy", "https_proxy")
    )
    return (
        "AVAILABLE",
        f"{len(os.environ)} variables, {len(dangerous)} of concern",
        {"count": len(os.environ), "keys": sorted(os.environ)[:60], "dangerous": dangerous},
    )


def _mounts() -> tuple[str, str]:
    text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    points = [line.split()[4] for line in lines if len(line.split()) > 4]
    return (
        "AVAILABLE",
        f"{len(lines)} mounts",
        {"count": len(lines), "points": sorted(set(points))[:40]},
    )


def _tmp() -> tuple[str, str]:
    entries = sorted(os.listdir("/tmp"))
    target = Path("/tmp/bunny-probe-write.txt")
    target.write_text("x", encoding="utf-8")
    target.unlink()
    return "AVAILABLE", f"{len(entries)} entries, writable, sample {entries[:5]}"


def _device(path: str) -> tuple[str, str]:
    if not os.path.exists(path):
        return "ABSENT", f"{path} is not present"
    with open(path, "rb") as handle:
        handle.read(0)
    return "AVAILABLE", f"{path} opened"


def _device_glob(prefix: str) -> tuple[str, str]:
    directory, _, stem = prefix.rpartition("/")
    if not os.path.isdir(directory):
        return "ABSENT", f"{directory} is not present"
    found = sorted(name for name in os.listdir(directory) if name.startswith(stem))
    if not found:
        return "ABSENT", f"no {prefix}* nodes"
    with open(f"{directory}/{found[0]}", "rb") as handle:
        handle.read(0)
    return "AVAILABLE", f"opened {directory}/{found[0]}"


def _connect(host: str, port: int, label: str) -> tuple[str, str]:
    try:
        with socket.create_connection((host, port), timeout=NETWORK_TIMEOUT):
            return "AVAILABLE", f"connected to {label}"
    except (socket.gaierror,) as error:
        return "DENIED", f"name resolution failed: {error}"
    except (TimeoutError, socket.timeout):
        return "DENIED", f"timed out after {NETWORK_TIMEOUT}s"
    except ConnectionRefusedError as error:
        # Something answered the syscall. Reachability, not permission.
        return "ABSENT", f"refused: {error}"
    except OSError as error:
        if error.errno in (101, 100, 13, 1):  # ENETUNREACH, ENETDOWN, EACCES, EPERM
            return "DENIED", f"errno {error.errno}: {error.strerror}"
        return "ABSENT", f"errno {error.errno}: {error.strerror}"


def _dbus(kind: str) -> tuple[str, str]:
    if kind == "session":
        address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        path = address.split("unix:path=", 1)[-1].split(",", 1)[0] if "unix:path=" in address else ""
        if not path:
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            path = f"{runtime}/bus" if runtime else ""
    else:
        path = "/run/dbus/system_bus_socket"
    if not path:
        return "ABSENT", "no bus address in the environment"
    if not os.path.exists(path):
        return "ABSENT", f"{path} is not present"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(NETWORK_TIMEOUT)
    try:
        sock.connect(path)
        return "AVAILABLE", f"connected to {path}"
    finally:
        sock.close()


def _subprocess() -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-c", "print('child ok')"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if result.returncode != 0:
        return "DENIED", f"exit {result.returncode}: {result.stderr.strip()[:200]}"
    return "AVAILABLE", result.stdout.strip()


def _traversal(target: str) -> tuple[str, str]:
    base = os.environ.get("XDG_DATA_HOME", "/run/bunny/app/data")
    candidate = os.path.join(base, "..", "..", "..", "..", target.lstrip("/"))
    data = Path(candidate).read_bytes()
    return "AVAILABLE", f"{len(data)} bytes via {candidate}"


def _symlink_escape(target: str) -> tuple[str, str]:
    base = Path(os.environ.get("XDG_DATA_HOME", "/run/bunny/app/data"))
    link = base / "escape-link"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        os.symlink(target, link)
    except OSError as error:
        return "ERROR", f"could not create the link: {error}"
    data = link.read_bytes()
    return "AVAILABLE", f"{len(data)} bytes through a symlink to {target}"


def _write_outside(path: str) -> tuple[str, str]:
    target = Path(path)
    target.write_text("probe wrote here\n", encoding="utf-8")
    return "AVAILABLE", f"wrote {target}"


def _process_visibility() -> tuple[str, str]:
    pids = sorted(int(name) for name in os.listdir("/proc") if name.isdigit())
    others = [pid for pid in pids if pid not in (os.getpid(), os.getppid(), 1)]
    return (
        "AVAILABLE",
        f"{len(pids)} processes visible, {len(others)} of them somebody else's",
        {"visible": len(pids), "others": len(others), "sample": pids[:12]},
    )


def _identity() -> dict:
    return {
        "pid": os.getpid(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "cwd": os.getcwd(),
        "executable": sys.executable,
        "hostname": socket.gethostname(),
        "in_userns": _userns_id(),
    }


def _userns_id() -> str:
    try:
        return os.readlink("/proc/self/ns/user")
    except OSError as error:
        return f"unreadable: {error}"


# -- the run -------------------------------------------------------------


def run(home: str) -> dict:
    checks = [
        _check("own_data_read", "capsule", _read_own_data),
        _check("own_data_write", "capsule", _write_own_data),
        _check("home_read", "user-files", lambda: _read_home(home)),
        _check("ssh_read", "credentials", lambda: _read_path(f"{home}/.ssh")),
        _check("ssh_key_read", "credentials", lambda: _read_path(f"{home}/.ssh/id_ed25519")),
        _check("gnupg_read", "credentials", lambda: _read_path(f"{home}/.gnupg")),
        _check("browser_profile_read", "credentials", lambda: _read_path(f"{home}/.mozilla")),
        _check("shadow_read", "credentials", lambda: _read_path("/etc/shadow")),
        _check("other_capsule_enumerate", "cross-app",
               lambda: _enumerate_capsules(os.environ.get("BUNNY_PROBE_CAPSULE_ROOT", f"{home}/.local/share/bunny/capsules"))),
        _check("other_capsule_secret_read", "cross-app",
               lambda: _read_path(os.environ.get("BUNNY_PROBE_PEER_SECRET", "/nonexistent"))),
        _check("granted_file_read", "file-grant",
               lambda: _read_path(os.environ.get("BUNNY_PROBE_GRANTED_FILE", "/nonexistent"))),
        _check("neighbour_file_read", "file-grant",
               lambda: _read_path(os.environ.get("BUNNY_PROBE_NEIGHBOUR_FILE", "/nonexistent"))),
        _check("environment", "environment", _environment),
        _check("mounts", "environment", _mounts),
        _check("tmp", "filesystem", _tmp),
        _check("camera", "devices", lambda: _device_glob("/dev/video")),
        _check("microphone", "devices", lambda: _device_glob("/dev/snd/")),
        _check("gpu", "devices", lambda: _device_glob("/dev/dri/")),
        _check("clipboard", "desktop", lambda: _clipboard()),
        _check("network_external", "network", lambda: _connect("1.1.1.1", 443, "1.1.1.1:443")),
        _check("network_dns", "network", lambda: _connect("example.com", 443, "example.com:443")),
        _check("network_localhost", "network",
               lambda: _connect("127.0.0.1", int(os.environ.get("BUNNY_PROBE_LOCALHOST_PORT", "22")),
                                "127.0.0.1:" + os.environ.get("BUNNY_PROBE_LOCALHOST_PORT", "22"))),
        _check("network_allowed_domain", "network",
               lambda: _connect(os.environ.get("BUNNY_PROBE_ALLOWED_DOMAIN", "example.com"), 443, "allowed domain")),
        _check("network_forbidden_domain", "network",
               lambda: _connect(os.environ.get("BUNNY_PROBE_FORBIDDEN_DOMAIN", "example.org"), 443, "unnamed domain")),
        _check("dbus_system", "ipc", lambda: _dbus("system")),
        _check("dbus_session", "ipc", lambda: _dbus("session")),
        _check("subprocess", "execution", _subprocess),
        _check("traversal_etc_passwd", "filesystem", lambda: _traversal("/etc/passwd")),
        _check("symlink_escape_home", "filesystem",
               lambda: _symlink_escape(os.environ.get("BUNNY_PROBE_SYMLINK_TARGET", home))),
        _check("write_outside_home", "filesystem", lambda: _write_outside(f"{home}/probe-escaped.txt")),
        _check("write_outside_tmp_root", "filesystem", lambda: _write_outside("/probe-escaped.txt")),
        _check("process_visibility", "process", _process_visibility),
    ]
    return {
        "schemaVersion": 1,
        "probeVersion": 1,
        "environment": os.environ.get("BUNNY_PROBE_ENVIRONMENT", "unknown"),
        "identity": _identity(),
        "checks": checks,
    }


def _clipboard() -> tuple[str, str]:
    """Wayland offers no clipboard read without a compositor connection.

    Reported by whether a Wayland socket is reachable at all, because that is the
    honest answer available to a program with no toolkit: a capsule that can open
    the compositor socket can, with a toolkit, read the selection.
    """
    display = os.environ.get("WAYLAND_DISPLAY")
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not display or not runtime:
        return "ABSENT", "no WAYLAND_DISPLAY or XDG_RUNTIME_DIR in the environment"
    path = os.path.join(runtime, display)
    if not os.path.exists(path):
        return "ABSENT", f"{path} is not present"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(NETWORK_TIMEOUT)
    try:
        sock.connect(path)
        return "AVAILABLE", f"compositor socket {path} is reachable"
    finally:
        sock.close()


def _load_configuration() -> None:
    """Read ``probe-config.json`` from beside this file into the environment.

    The probe is parameterised — which home to try, which peer secret, which
    granted file — and a capsule's environment is a fixed eight-key map that
    :mod:`capsules.isolation` builds rather than inherits. Adding a ninth key so
    a test fixture could be configured would weaken the property being tested, so
    the configuration arrives as a file in the capsule's own storage instead,
    which is a thing an ordinary application has and a thing the sandbox already
    permits.
    """
    beside = Path(__file__).resolve().parent / "probe-config.json"
    if not beside.exists():
        return
    try:
        document = json.loads(beside.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for key, value in document.items():
        if isinstance(key, str) and key.startswith("BUNNY_PROBE_") and isinstance(value, str):
            os.environ.setdefault(key, value)


def main() -> int:
    _load_configuration()
    home = os.environ.get("BUNNY_PROBE_HOME") or os.path.expanduser("~")
    output = Path(os.environ.get("BUNNY_PROBE_OUTPUT", DEFAULT_OUTPUT))
    document = run(home)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        # The one failure the probe cannot report through its own file. Falls back
        # to stdout so a harness that captures it still learns something.
        print(json.dumps({"error": f"could not write {output}: {error}", "document": document}))
        return 2
    print(json.dumps({"wrote": str(output), "checks": len(document["checks"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
