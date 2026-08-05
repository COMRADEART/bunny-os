#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record what this machine actually is, and where the code actually came from.

Two questions decide whether any later result means anything, and both are easy
to answer wrongly by assumption:

**What is this machine?** A validation run on a nested compositor inside a
utility VM is a real Linux run and a useful one, but it is not a GNOME session
and it is not physical hardware. This program classifies the execution surface
from evidence rather than from the operator's intent, keeps the raw evidence
beside the classification so a reader can disagree with it, and never emits the
word GNOME unless a GNOME session is actually present.

**Where did the code come from?** ``import companion`` succeeds from a
repository checkout, a bind mount, a stray ``PYTHONPATH``, the current working
directory and a user site-packages directory, and in every one of those cases it
is testing something other than the installed artifact. The provenance section
records ``__file__`` for the canonical runtime, the presentation layer and the
renderer, classifies each one, and with ``--require-installed`` exits 2 rather
than let a developer tree be mistaken for a product.

Exit status: 0 report written, 2 a required condition failed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import site
import socket
import subprocess
import sys
from typing import Any

#: The one directory an installed Bunny OS imports the companion from.
INSTALLED_ROOT = Path("/usr/lib/bunny-os/python")

#: Provenance classes that mean "this is not the installed artifact". §2's list.
REJECTED_PROVENANCE = {
    "repository-checkout",
    "bind-mount",
    "developer-pythonpath",
    "working-directory",
    "user-site-packages",
}

#: The modules whose provenance §2 requires on the record, by role.
PROVENANCE_MODULES = {
    "canonicalRuntime": "companion.runtime",
    "presentationLayer": "companion.presentation",
    "renderer": "companion.character.surface",
}


def _run(command: list[str]) -> str | None:
    """Return a command's trimmed stdout, or ``None`` if it cannot be run.

    ``None`` and not ``""``: a missing ``systemd-detect-virt`` and a
    ``systemd-detect-virt`` that printed nothing are different facts, and the
    classifier below treats them differently.
    """
    executable = shutil.which(command[0])
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = completed.stdout.strip()
    # systemd-detect-virt exits non-zero for "none", which is an answer.
    return output or None


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# -- the machine -----------------------------------------------------------


def operating_system() -> dict[str, Any]:
    """Identity from ``/etc/os-release``, plus kernel and architecture."""
    fields: dict[str, str] = {}
    text = _read("/etc/os-release") or ""
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip().strip('"')
    uname = platform.uname()
    return {
        "id": fields.get("ID"),
        "versionId": fields.get("VERSION_ID"),
        "prettyName": fields.get("PRETTY_NAME"),
        "variantId": fields.get("VARIANT_ID"),
        "kernelName": uname.system,
        "kernelRelease": uname.release,
        "kernelVersion": uname.version,
        "architecture": uname.machine,
    }


def execution_surface() -> dict[str, Any]:
    """Classify the execution surface, and keep the evidence beside the verdict.

    The classes are deliberately not interchangeable. A container shares the
    host kernel; a VM does not; WSL2 is a VM with a vendor kernel and a
    partially synthetic userspace; physical hardware is the only one that
    exercises real firmware and real drivers. A claim proved on one is not
    proved on the others, so the record names which one it was.
    """
    virtualisation = _run(["systemd-detect-virt", "--vm"])
    containerisation = _run(["systemd-detect-virt", "--container"])
    osrelease = (_read("/proc/sys/kernel/osrelease") or "").strip()
    # WSL2 advertises itself in the kernel release string; both spellings have
    # shipped, so match either rather than pin to one vendor's formatting.
    is_wsl = bool(re.search(r"(microsoft|wsl)", osrelease, re.IGNORECASE)) or bool(
        os.environ.get("WSL_DISTRO_NAME")
    )

    # WSL is tested before the container branch on purpose. ``systemd-detect-virt
    # --container`` answers "wsl", which is true in systemd's taxonomy and
    # actively misleading in §3's: an nspawn container shares the host kernel,
    # whereas WSL2 boots its own (here a Microsoft kernel, reported by
    # ``--vm`` as "microsoft"). Filing it under "container" would put it in the
    # same bucket as nspawn, which is the confusion the classification exists to
    # prevent, so it gets a surface of its own and both detector answers stay in
    # the evidence for a reader who wants to re-derive the call.
    if is_wsl:
        surface = "wsl2"
        detail = "hyper-v utility vm with a vendor kernel and a partly synthetic userspace"
    elif containerisation and containerisation != "none":
        surface = "container"
        detail = containerisation
    elif virtualisation and virtualisation != "none":
        surface = "virtual-machine"
        detail = virtualisation
    elif virtualisation == "none" or virtualisation is None:
        surface = "physical-hardware" if virtualisation == "none" else "unknown"
        detail = virtualisation or "systemd-detect-virt unavailable"
    else:  # pragma: no cover - defensive
        surface = "unknown"
        detail = virtualisation

    return {
        "surface": surface,
        "detail": detail,
        "isPhysicalHardware": surface == "physical-hardware",
        "isNspawnContainer": containerisation == "systemd-nspawn",
        "sharesHostKernel": surface == "container",
        "note": (
            "Surfaces are not interchangeable. A container shares the host kernel, a "
            "virtual machine and WSL2 do not, and only physical hardware exercises "
            "real firmware and drivers. A result proved here is proved for this "
            f"surface ({surface}) and no other."
        ),
        "evidence": {
            "systemdDetectVirtVm": virtualisation,
            "systemdDetectVirtContainer": containerisation,
            "procOsRelease": osrelease or None,
            "wslDistroName": os.environ.get("WSL_DISTRO_NAME"),
        },
    }


def init_system() -> dict[str, Any]:
    """Which init is PID 1, its version, and which cgroup hierarchy is live."""
    comm = (_read("/proc/1/comm") or "").strip() or None
    version_line = _run(["systemctl", "--version"])
    version = None
    if version_line:
        first = version_line.splitlines()[0].split()
        if len(first) >= 2:
            version = first[1]
    if Path("/sys/fs/cgroup/cgroup.controllers").exists():
        cgroup = "v2"
    elif Path("/sys/fs/cgroup").is_dir():
        cgroup = "v1-or-hybrid"
    else:
        cgroup = "none"
    return {
        "pid1": comm,
        "isSystemd": comm == "systemd",
        "systemdVersion": version,
        "cgroupHierarchy": cgroup,
    }


def _gnome_session_evidence() -> dict[str, Any]:
    """Look for a real GNOME session, and be hard to convince.

    §9's rule is that GNOME-specific claims require a real GNOME session. The
    cheap check — ``XDG_CURRENT_DESKTOP`` — is an environment variable that any
    script can export, so it is recorded as evidence but never sufficient on its
    own. A running ``gnome-shell`` owned by this user is the thing that actually
    means GNOME.
    """
    current_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    shell_running = False
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            comm = _read(entry / "comm")
            if comm and comm.strip() == "gnome-shell":
                shell_running = True
                break
    except OSError:
        pass
    return {
        "xdgCurrentDesktop": current_desktop or None,
        "gnomeShellProcessPresent": shell_running,
        # Both, not either. The variable alone is an assertion; the process is
        # the fact, and a claim wants the fact.
        "isGnomeSession": shell_running and "GNOME" in current_desktop.upper(),
    }


def display_surface() -> dict[str, Any]:
    """Classify the display stack without promoting it to a desktop session.

    WSLg is the case this exists for. It supplies a genuine Wayland socket
    served by a compositor running outside this distribution and composited by
    Windows, which makes it a real Wayland target for a GTK client and, at the
    same time, not a session compositor, not GNOME, and not evidence about a
    Bunny OS desktop. The record says all of that rather than the word
    "Wayland" on its own.
    """
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    x_display = os.environ.get("DISPLAY")
    session_type = os.environ.get("XDG_SESSION_TYPE")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    socket_path = None
    if wayland_display and runtime_dir:
        candidate = Path(wayland_display)
        socket_path = candidate if candidate.is_absolute() else Path(runtime_dir) / wayland_display

    if wayland_display:
        protocol = "wayland"
        # WSLg mounts its sockets from the host distribution; the giveaway is
        # /mnt/wslg, which no ordinary session has.
        if Path("/mnt/wslg").exists():
            compositor = "wslg-remoted"
            note = (
                "Wayland is served by the WSLg system distribution and composited by "
                "the Windows host. Sufficient to run and observe a real GTK client; "
                "not a session compositor and not a desktop-session claim."
            )
        else:
            compositor = "unclassified"
            note = "A Wayland socket is present; its compositor was not identified."
    elif x_display:
        protocol = "x11"
        compositor = "unclassified"
        note = "An X display is present; its server was not identified."
    else:
        protocol = "none"
        compositor = "none"
        note = "No display is available; only headless execution can be claimed."

    return {
        "protocol": protocol,
        "compositor": compositor,
        "note": note,
        "isSessionCompositor": False if compositor in {"wslg-remoted", "none"} else None,
        "socketPresent": bool(socket_path and socket_path.exists()),
        "evidence": {
            "waylandDisplay": wayland_display,
            "display": x_display,
            "xdgSessionType": session_type,
            "wslgPresent": Path("/mnt/wslg").exists(),
        },
        "gnome": _gnome_session_evidence(),
    }


def _linger_state(username: str) -> bool | None:
    output = _run(["loginctl", "show-user", username, "--property=Linger"])
    if not output:
        return None
    return output.strip().endswith("=yes")


def user_context() -> dict[str, Any]:
    """Who is running this, and is the user session infrastructure usable."""
    uid = os.getuid()
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:  # pragma: no cover - a uid with no passwd entry
        username = None
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    runtime_detail: dict[str, Any] = {"path": runtime_dir}
    if runtime_dir:
        path = Path(runtime_dir)
        try:
            stat = path.stat()
            runtime_detail.update(
                {
                    "exists": True,
                    "mode": oct(stat.st_mode & 0o7777),
                    "ownerUid": stat.st_uid,
                    "ownedByUser": stat.st_uid == uid,
                }
            )
        except OSError:
            runtime_detail.update({"exists": False})
    return {
        "uid": uid,
        "gid": os.getgid(),
        "username": username,
        "isRoot": uid == 0,
        "xdgRuntimeDir": runtime_detail,
        "lingerEnabled": _linger_state(username) if username else None,
        "systemdUserManagerReachable": _run(["systemctl", "--user", "is-system-running"])
        is not None,
    }


def _mount_for(path: Path) -> dict[str, Any] | None:
    """Find the mountinfo entry backing ``path``.

    Returns the mount's filesystem type and its *root within that filesystem* —
    which is how a bind mount gives itself away: a bind of a subdirectory has a
    root that is not ``/``.
    """
    text = _read("/proc/self/mountinfo")
    if text is None:
        return None
    best: dict[str, Any] | None = None
    best_length = -1
    resolved = str(path.resolve())
    for line in text.splitlines():
        # 0:id 1:parent 2:dev 3:root 4:mountpoint ... - fstype source options
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError:
            continue
        if len(fields) < separator + 3:
            continue
        mount_root, mount_point = fields[3], fields[4]
        if resolved == mount_point or resolved.startswith(mount_point.rstrip("/") + "/"):
            if len(mount_point) > best_length:
                best_length = len(mount_point)
                best = {
                    "mountPoint": mount_point,
                    "rootWithinFilesystem": mount_root,
                    "filesystemType": fields[separator + 1],
                    "source": fields[separator + 2],
                    "isBindMount": mount_root != "/",
                }
    return best


def hardware() -> dict[str, Any]:
    """CPU and memory totals, for scaling later measurements — not for claims."""
    total_kib = None
    text = _read("/proc/meminfo") or ""
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                total_kib = int(parts[1])
            break
    return {
        "cpuCount": os.cpu_count(),
        "memTotalBytes": total_kib * 1024 if total_kib is not None else None,
        "note": (
            "Host capacity only. It bounds what a measurement can mean; it is not "
            "a Bunny OS target-hardware figure."
        ),
    }


# -- the code --------------------------------------------------------------


def classify_provenance(module_file: str | None) -> dict[str, Any]:
    """Say where a module was loaded from, in §2's vocabulary."""
    if module_file is None:
        return {"class": "unknown", "reason": "module has no __file__"}
    path = Path(module_file).resolve()

    if INSTALLED_ROOT.exists() and path.is_relative_to(INSTALLED_ROOT):
        classification, reason = "installed", f"below {INSTALLED_ROOT}"
    else:
        classification = reason = ""
        # Order matters: a repository checkout that also happens to be the
        # working directory should be reported as the checkout, which is the
        # more specific and more misleading of the two.
        for parent in [path, *path.parents]:
            if (parent / ".git").exists():
                classification = "repository-checkout"
                reason = f"a .git directory exists at {parent}"
                break
        if not classification:
            user_site = site.getusersitepackages()
            sites = [user_site] if isinstance(user_site, str) else list(user_site or [])
            if any(sites and path.is_relative_to(Path(entry)) for entry in sites):
                classification = "user-site-packages"
                reason = "below the per-user site-packages directory"
        if not classification:
            for entry in filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)):
                try:
                    if path.is_relative_to(Path(entry).resolve()):
                        classification = "developer-pythonpath"
                        reason = f"reachable because PYTHONPATH contains {entry}"
                        break
                except OSError:
                    continue
        if not classification:
            try:
                if path.is_relative_to(Path.cwd().resolve()):
                    classification = "working-directory"
                    reason = "below the current working directory"
            except OSError:
                pass
        if not classification:
            classification = "other"
            reason = "not the installed tree, and not a recognised developer source"

    mount = _mount_for(path)
    if mount and mount.get("isBindMount"):
        # A bind mount can make any of the above look like the installed tree,
        # so it overrides whatever was concluded from the path alone.
        classification = "bind-mount"
        reason = (
            f"the backing mount at {mount['mountPoint']} has root "
            f"{mount['rootWithinFilesystem']}, which makes it a bind mount"
        )

    return {
        "class": classification,
        "reason": reason,
        "accepted": classification == "installed",
        "mount": mount,
    }


def import_provenance() -> dict[str, Any]:
    """Import the three modules §2 names, and record where each came from."""
    import importlib

    records: dict[str, Any] = {}
    for role, module_name in PROVENANCE_MODULES.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as error:  # noqa: BLE001 - the failure is the record
            records[role] = {
                "module": module_name,
                "imported": False,
                "error": f"{type(error).__name__}: {error}",
            }
            continue
        module_file = getattr(module, "__file__", None)
        records[role] = {
            "module": module_name,
            "imported": True,
            "file": module_file,
            "provenance": classify_provenance(module_file),
        }
    return records


def python_context() -> dict[str, Any]:
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "pythonPathEnvironment": os.environ.get("PYTHONPATH"),
        "userSiteEnabled": site.ENABLE_USER_SITE,
        "sysPathHead": sys.path[:6],
    }


# -- assembly --------------------------------------------------------------


def build_report(*, subject: Path | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "bunny-os/linux-environment-report/1",
        "hostname": socket.gethostname(),
        "operatingSystem": operating_system(),
        "executionSurface": execution_surface(),
        "initSystem": init_system(),
        "displaySurface": display_surface(),
        "userContext": user_context(),
        "hardware": hardware(),
        "python": python_context(),
        "importProvenance": import_provenance(),
    }
    if subject is not None:
        report["subject"] = {
            "path": str(subject),
            "mount": _mount_for(subject),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument(
        "--subject",
        type=Path,
        help="a directory under test, recorded with the mount that backs it",
    )
    parser.add_argument(
        "--require-installed",
        action="store_true",
        help="exit 2 unless every recorded module came from the installed tree",
    )
    parser.add_argument(
        "--require-systemd",
        action="store_true",
        help="exit 2 unless PID 1 is systemd",
    )
    arguments = parser.parse_args(argv)

    if arguments.require_installed:
        # Exactly what /usr/libexec/bunny-companion-service does, and nothing
        # else. Adding the source tree as well — which the development path
        # below does — would make the gate unable to fail: the import would
        # succeed from the checkout and the provenance check would then be
        # reporting on a fallback the installed service never uses.
        if INSTALLED_ROOT.is_dir() and str(INSTALLED_ROOT) not in sys.path:
            sys.path.insert(0, str(INSTALLED_ROOT))
    else:
        # Development runs are allowed to import from the checkout, and say so.
        for candidate in (INSTALLED_ROOT, Path(__file__).resolve().parents[1]):
            if candidate.is_dir() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))

    report = build_report(subject=arguments.subject)

    failures: list[str] = []
    if arguments.require_installed:
        for role, record in report["importProvenance"].items():
            if not record.get("imported"):
                failures.append(f"{role} ({record['module']}) could not be imported")
                continue
            provenance = record["provenance"]
            if not provenance["accepted"]:
                failures.append(
                    f"{role} ({record['module']}) came from {provenance['class']}: "
                    f"{provenance['reason']}"
                )
    if arguments.require_systemd and not report["initSystem"]["isSystemd"]:
        failures.append(f"PID 1 is {report['initSystem']['pid1']}, not systemd")

    report["gate"] = {
        "requireInstalled": arguments.require_installed,
        "requireSystemd": arguments.require_systemd,
        "failures": failures,
        "passed": not failures,
    }

    serialised = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialised + "\n", encoding="utf-8")
    print(serialised)

    for failure in failures:
        print(f"REFUSED: {failure}", file=sys.stderr)
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
