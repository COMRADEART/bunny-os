#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install Bunny OS-owned files into a bootc container filesystem.

Every copy this makes comes from ``build/scripts/install_routes.py``, which is
the same table ``build-input-closure.py`` reads to answer "is this change
build-affecting?". That is not tidiness: the two used to hold separate ideas of
the install set, the analyser modelled ``copy_tree`` and ``copy_file`` and not
``copy_python_package``, and the entire ``companion`` package — installed by the
call it did not model — was reported as not reaching the image.

Because the table is shared, the file selection here and the classification
there are literally the same function. There is nothing left to keep in step.

What is still written by hand is written by a *declared generator*: the release
metadata, the package inventory, the release payload and the activation
symlinks. Each has an entry in ``GENERATED_ROUTES`` and each lives in a function
the analyser's audit knows about. Anything else that copies or writes fails the
audit, which fails the closure closed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from install_routes import (  # noqa: E402 - the path above is what makes this importable
    InstallRoute,
    route_files,
    routes_for_profile,
)


def copy_file(source: Path, destination: Path, mode: int) -> None:
    """The one primitive. Everything installed goes through here."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, mode)


def copy_route(route: InstallRoute, source_root: Path, root: Path) -> list[str]:
    """Install one declared route, and report what it installed.

    ``root`` is ``/`` in a build. A test passes a directory, which is the only
    reason this function is testable at all — an installer that could only be
    exercised by building an image is an installer nobody exercises.
    """
    installed: list[str] = []
    for item, destination in route_files(route, source_root):
        target = root / destination.lstrip("/")
        copy_file(item, target, route.mode)
        installed.append(destination)
    return installed

#: Install routes whose destination is computed rather than written literally.
#:
#: These exist as a table, and the code below is *driven* by the table, for one
#: reason: ``build-input-closure.py`` cannot resolve a destination assembled
#: inside a loop, and an analyser that silently reports such a path as
#: "not installed" is worse than no analyser. A declaration the installer
#: itself obeys cannot drift from what the installer does — if the table is
#: wrong, the file lands somewhere unexpected and a test notices.
#:
#: ``sourceGlob`` is relative to the repository root; ``exclude`` drops any path
#: with a matching first path component; ``strip`` is the prefix removed before
#: joining onto ``destination``.
INSTALL_ROUTES = (
    {
        "id": "capability-code",
        "sourceGlob": "capability/**/*.py",
        "strip": "capability",
        "destination": "/usr/lib/bunny-os/python/capability",
        "mode": 0o444,
        # `testing` is the probe fixture and its unit; `services` is installed
        # separately, read-only, at the path the registry looks for.
        "exclude": ("testing", "services", "__pycache__"),
    },
    {
        "id": "capability-manifests",
        "sourceGlob": "capability/services/*.json",
        "strip": "capability/services",
        "destination": "/usr/share/bunny-os/capability/services",
        "mode": 0o444,
        "excludeStems": ("bunny-capability-probe",),
    },
    {
        "id": "companion-code",
        "sourceGlob": "companion/**/*.py",
        "strip": "companion",
        "destination": "/usr/lib/bunny-os/python/companion",
        "mode": 0o444,
        "exclude": ("__pycache__",),
    },
)


def install_capability(source: Path) -> None:
    """Install the capability runtime, its applicator, and its manifests.

    Table-driven, and explicit rather than a ``copy_tree`` of ``capability/``,
    because two of its subdirectories must not ship. The exclusions are
    asserted afterwards rather than assumed: a validation fixture reaching an
    installed system is the kind of mistake that stays invisible until somebody
    starts it.

    No bytecode is generated. See ``docs/CAPABILITY_INSTALLED.md``: a ``.pyc``
    embeds the source path and mtime, and pinning both well enough for two
    builds to agree costs more than the import time it saves on a system whose
    ``/usr`` is read-only at runtime anyway.
    """
    for route in INSTALL_ROUTES:
        destination = Path(route["destination"])
        strip = source / route["strip"]
        excluded = set(route.get("exclude", ()))
        excluded_stems = set(route.get("excludeStems", ()))
        for item in sorted(source.glob(route["sourceGlob"])):
            relative = item.relative_to(strip)
            if excluded.intersection(relative.parts):
                continue
            if item.stem in excluded_stems:
                continue
            copy_file(item, destination / relative, route["mode"])

    copy_file(
        source / "services/bunny-capability-supervisor/bunny_capability_supervisor.py",
        Path("/usr/libexec/bunny-capability-supervisor"), 0o555,
    )
    copy_file(
        source / "services/bunny-companion/bunny_companion_service.py",
        Path("/usr/libexec/bunny-companion-service"), 0o555,
    )
    copy_file(
        source / "config/bunny-os/capability-supervisor.json",
        Path("/etc/bunny-os/capability/supervisor.json"), 0o644,
    )

    # Assert what must not be there, and what must. A fixture that shipped
    # would be startable on a user's machine, and this is the cheapest place to
    # find out that it did.
    code_root = Path("/usr/lib/bunny-os/python/capability")
    manifest_root = Path("/usr/share/bunny-os/capability/services")
    for forbidden in sorted(code_root.rglob("*")):
        if {"testing", "__pycache__"}.intersection(forbidden.parts):
            raise SystemExit(f"BLOCKED: {forbidden} is a fixture and must not be installed")
    if list(manifest_root.glob("*probe*")):
        raise SystemExit("BLOCKED: the capability probe manifest must not be installed")
    for required in ("apply/applicator.py", "supervisor.py", "engine.py"):
        if not (code_root / required).is_file():
            raise SystemExit(f"BLOCKED: {required} was not installed")
    companion_root = Path("/usr/lib/bunny-os/python/companion")
    for required in ("runtime.py", "protocol.py", "gtk_shell.py"):
        if not (companion_root / required).is_file():
            raise SystemExit(f"BLOCKED: companion/{required} was not installed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=("developer", "minimal", "desktop", "recovery", "shell", "shell-test", "live", "beta"))
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--base-image", required=True)
    args = parser.parse_args()
    source = args.source
    artifact_manifest_path = source / "build/manifests/bunny-artifact.placeholder.json"
    artifact_payload = source / "build/artifacts/bunny"
    subprocess.run(["/usr/bin/python3", str(source / "build/scripts/verify-bunny-artifact.py"), str(artifact_manifest_path), str(artifact_payload)], check=True)
    artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))

    copy_tree(source / "services/bunny-system-broker/src/bunny_system_broker", Path("/usr/lib/bunny-system-broker/bunny_system_broker"))
    copy_tree(source / "tools/bunny-os/bunny_os", Path("/usr/lib/bunny-os/python/bunny_os"))
    copy_tree(source / "installer", Path("/usr/lib/bunny-installer/installer"))
    copy_file(source / "services/bunny-system-broker/bin/bunny-system-broker", Path("/usr/libexec/bunny-system-broker"), 0o555)
    copy_file(source / "services/bunny-update-agent/bunny_update_agent.py", Path("/usr/libexec/bunny-update-agent"), 0o555)
    copy_file(source / "tools/bunny-os/bin/bunny-os", Path("/usr/bin/bunny-os"), 0o555)
    copy_file(source / "tools/bunny-os/bin/bunny-os-info", Path("/usr/bin/bunny-os-info"), 0o555)
    # bunny-brlapi-key is here because its absence was measured, not noticed:
    # the unit shipped, finalisation removes /etc/brlapi.key from the archive,
    # and nothing installed the program that mints it on first boot — so an
    # installed system would have left BRLTTY users without a working key.
    script_names = ("bunny-health-check", "bunny-first-boot", "bunny-config-dir", "bunny-brlapi-key", "bunny-recovery-generator", "bunny-recovery-prepare", "bunny-recovery", "bunny-safe-graphics", "bunny-live-session")
    for name in script_names:
        destination = Path("/usr/lib/systemd/system-generators/bunny-recovery-generator") if name == "bunny-recovery-generator" else Path(f"/usr/libexec/{name}")
        copy_file(source / f"scripts/{name}.py", destination, 0o555)
    copy_file(source / "scripts/greenboot-bunny-health.sh", Path("/usr/libexec/greenboot/check/required.d/10-bunny-os-health"), 0o555)

    copy_tree(source / "systemd", Path("/usr/lib/systemd/system"))
    user_source = source / "systemd/user"
    copy_tree(user_source, Path("/usr/lib/systemd/user"))
    for misplaced in Path("/usr/lib/systemd/system/user").glob("*"):
        misplaced.unlink()
    try:
        Path("/usr/lib/systemd/system/user").rmdir()
    except OSError:
        pass
    copy_file(source / "config/polkit/art.comrade.bunny-os.policy", Path("/usr/share/polkit-1/actions/art.comrade.bunny-os.policy"), 0o644)
    copy_file(source / "config/tmpfiles/bunny-os.conf", Path("/usr/lib/tmpfiles.d/bunny-os.conf"), 0o644)
    # /usr/share/user-tmpfiles.d, not /usr/lib/user-tmpfiles.d: the latter is
    # not in systemd's --user search path and a rule placed there is never
    # read. Measured on fedora-bootc:44 — see config/user-tmpfiles/bunny-os.conf.
    copy_file(source / "config/user-tmpfiles/bunny-os.conf", Path("/usr/share/user-tmpfiles.d/bunny-os.conf"), 0o644)
    copy_file(source / "config/firewalld/bunny-default.xml", Path("/usr/lib/firewalld/zones/bunny-default.xml"), 0o644)
    copy_file(source / "config/systemd/60-bunny-os.preset", Path("/usr/lib/systemd/system-preset/60-bunny-os.preset"), 0o644)
    copy_file(source / "config/systemd/60-bunny-os-user.preset", Path("/usr/lib/systemd/user-preset/60-bunny-os.preset"), 0o644)
    copy_file(source / "config/sysctl/60-bunny-os.conf", Path("/usr/lib/sysctl.d/60-bunny-os.conf"), 0o644)
    copy_file(source / "desktop-integration/art.comrade.Bunny.desktop", Path("/usr/share/applications/art.comrade.Bunny.desktop"), 0o644)
    copy_file(source / "desktop-integration/bunny-desktop-launch.py", Path("/usr/libexec/bunny-desktop-launch"), 0o555)
    if args.profile in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        copy_tree(source / "shell/services/bunny_shell", Path("/usr/lib/bunny-shell/bunny_shell"))
        for executable in (source / "shell/services/bin").iterdir():
            if executable.is_file():
                copy_file(executable, Path("/usr/bin") / executable.name, 0o555)
        copy_file(source / "shell/services/bin/bunny-shell-service", Path("/usr/libexec/bunny-shell-service"), 0o555)
        copy_file(source / "shell/session/bunny-shell-session.py", Path("/usr/libexec/bunny-shell-session"), 0o555)
        copy_file(source / "shell/session/bunny.desktop", Path("/usr/share/wayland-sessions/bunny.desktop"), 0o644)
        copy_file(source / "shell/session/bunny-safe.desktop", Path("/usr/share/wayland-sessions/bunny-safe.desktop"), 0o644)
        extension_root = Path("/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org")
        copy_tree(source / "shell/components/gnome-shell-extension", extension_root)
        subprocess.run(["/usr/bin/glib-compile-schemas", str(extension_root / "schemas")], check=True)
        copy_tree(source / "shell/components/applications", Path("/usr/share/applications"))
        copy_file(source / "shell/components/nautilus/bunny-nautilus.py", Path("/usr/share/nautilus-python/extensions/bunny-nautilus.py"), 0o444)
        copy_file(source / "shell/components/dconf/10-bunny-shell", Path("/etc/dconf/db/local.d/10-bunny-shell"), 0o644)
        copy_file(source / "shell/components/dconf/profile-user", Path("/etc/dconf/profile/user"), 0o644)
        subprocess.run(["/usr/bin/dconf", "update"], check=True)
        copy_tree(source / "shell/themes", Path("/usr/share/bunny-shell/themes"), 0o444)
        copy_tree(source / "shell/assets/wallpapers", Path("/usr/share/backgrounds/bunny-os"), 0o444)
        copy_tree(source / "shell/assets/companion", Path("/usr/share/bunny-shell/companion"), 0o444)
        copy_tree(source / "shell/icons/hicolor", Path("/usr/share/icons/hicolor"), 0o444)
        copy_tree(source / "shell/schemas", Path("/usr/share/bunny-os/schemas/shell"), 0o444)
        subprocess.run(["/usr/bin/gtk-update-icon-cache", "--force", "/usr/share/icons/hicolor"], check=False)
    if args.profile in {"live", "beta"}:
        for executable in (source / "installer/bin").iterdir():
            if executable.is_file():
                destination = Path("/usr/libexec") / executable.name if executable.name == "bunny-installer-backend" else Path("/usr/bin") / executable.name
                copy_file(executable, destination, 0o555)
        copy_file(source / "installer/frontend/art.comrade.BunnyInstaller.desktop", Path("/usr/share/applications/art.comrade.BunnyInstaller.desktop"), 0o644)
        copy_file(source / "installer/first_run/art.comrade.BunnyFirstRun.desktop", Path("/usr/share/applications/art.comrade.BunnyFirstRun.desktop"), 0o644)
    if args.profile == "live":
        copy_file(source / "installer/config/iso.yaml", Path("/usr/lib/image-builder/bootc/iso.yaml"), 0o444)
        copy_file(source / "installer/config/bunny-os.conf", Path("/etc/anaconda/profile.d/bunny-os.conf"), 0o444)
        copy_file(source / "installer/config/interactive-defaults.ks", Path("/usr/share/anaconda/interactive-defaults.ks"), 0o444)
        copy_file(source / "installer/config/gdm-live.conf", Path("/etc/gdm/custom.conf"), 0o644)
        copy_file(source / "installer/config/20-bunny-live", Path("/etc/dconf/db/local.d/20-bunny-live"), 0o644)
        copy_file(source / "installer/frontend/art.comrade.BunnyInstaller-autostart.desktop", Path("/etc/xdg/autostart/art.comrade.BunnyInstaller.desktop"), 0o644)
        subprocess.run(["/usr/bin/dconf", "update"], check=True)
    copy_file(source / "build/manifests/update.disabled.json", Path("/etc/bunny-os/update.json"), 0o600)
    copy_file(artifact_manifest_path, Path("/usr/share/bunny-os/bunny-artifact.json"), 0o444)
    copy_file(source / "build/keys/revoked-keys.json", Path("/usr/share/bunny-os/update-keys/revoked-keys.json"), 0o444)
    # Qualification scaffolding, not a feature: the marker is how an update
    # and a rollback are observed to have changed the deployed root rather
    # than assumed to have. It ships because the N+1 fixture image must be a
    # real, separately qualified build differing from N in one harmless,
    # identifiable way — an arbitrary image handed to the update path would
    # test the path against nothing.
    copy_file(source / "config/qualification-update-marker.json", Path("/usr/share/bunny-os/qualification-update-marker.json"), 0o444)
    install_capability(source)
    copy_tree(source / "schemas", Path("/usr/share/bunny-os/schemas"), 0o444)
    copy_tree(source / "docs", Path("/usr/share/doc/bunny-os"), 0o444)
    copy_file(source / "ARCHITECTURE.md", Path("/usr/share/doc/bunny-os/ARCHITECTURE.md"), 0o444)
    copy_file(source / "README.md", Path("/usr/share/doc/bunny-os/README.md"), 0o444)

    timestamp = datetime.fromtimestamp(args.source_date_epoch, timezone.utc).isoformat().replace("+00:00", "Z") if args.source_date_epoch else "unspecified"

def install_all_routes(
    source_root: Path, profile: str, *, root: Path = Path("/"),
) -> dict[str, list[str]]:
    """Every route that applies to this profile, in declared order."""
    installed: dict[str, list[str]] = {}
    for route in routes_for_profile(profile):
        if route.id == "release-payload":
            # Its destination is computed from the artifact manifest, so it is
            # applied by install_release_payload rather than copied blind into a
            # directory literally named "*".
            continue
        installed[route.id] = copy_route(route, source_root, root)
    return installed


def install_release_payload(
    source_root: Path, artifact_manifest: dict, *, root: Path = Path("/"),
) -> str:
    """The verified release payload and the ``current`` symlink beside it."""
    payload = source_root / "build/artifacts/bunny"
    name = (
        artifact_manifest["bunnyVersion"] if artifact_manifest["status"] == "verified"
        else f'{artifact_manifest["bunnyVersion"]}-placeholder'
    )
    release_root = root / "opt/bunny/releases" / name
    release_root.mkdir(parents=True, exist_ok=True)
    if artifact_manifest["status"] == "verified":
        for item in artifact_manifest["files"]:
            copy_file(payload / item["path"], release_root / item["path"], int(item["mode"], 8))
    current = root / "opt/bunny/current"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(f"releases/{name}")
    return name


def write_release_metadata(arguments, artifact_manifest: dict, *, root: Path = Path("/")) -> dict:
    timestamp = (
        datetime.fromtimestamp(arguments.source_date_epoch, timezone.utc)
        .isoformat().replace("+00:00", "Z")
        if arguments.source_date_epoch else "unspecified"
    )
    metadata = {
        "schemaVersion": 1,
        "osVersion": arguments.os_version,
        "imageVersion": arguments.image_version,
        "profile": arguments.profile,
        "contractVersion": "1.0.0",
        "brokerVersion": "0.1.0",
        "recoveryVersion": "0.1.0",
        "bunnyVersion": artifact_manifest["bunnyVersion"],
        "bunnyArtifactStatus": artifact_manifest["status"],
        "bunnyProtocolVersion": 3,
        "baseDistribution": "Fedora",
        "baseVersion": "44",
        "baseImageReference": arguments.base_image,
        "sourceCommit": arguments.source_commit,
        "sourceDateEpoch": arguments.source_date_epoch,
        "buildTimestamp": timestamp,
        "buildTool": "OCI Containerfile + unified image-builder",
    }
    release = root / "usr/lib/bunny-os/release.json"
    release.parent.mkdir(parents=True, exist_ok=True)
    release.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(release, 0o444)
    return metadata


def write_package_inventory(*, root: Path = Path("/")) -> None:
    inventory = subprocess.run(
        ["/usr/bin/rpm", "-qa", "--qf", "%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n"],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout
    packages = root / "usr/lib/bunny-os/packages.txt"
    packages.parent.mkdir(parents=True, exist_ok=True)
    packages.write_text("".join(sorted(inventory.splitlines(keepends=True))), encoding="utf-8")
    os.chmod(packages, 0o444)


def create_state_directories(*, root: Path = Path("/")) -> None:
    state_paths = {
        "var/lib/bunny": 0o711,
        "var/cache/bunny": 0o711,
        "var/log/bunny": 0o750,
        "var/lib/bunny-os": 0o711,
        "var/lib/bunny-os/update": 0o700,
        "var/lib/bunny-os/recovery": 0o700,
        "var/lib/bunny-os/health": 0o700,
        "var/lib/bunny-os/support": 0o711,
    }
    for relative, mode in state_paths.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        os.chmod(path, mode)


def install_activation(profile: str) -> None:
    """Enable the units, and assert the activation landed.

    ``systemctl enable`` succeeding is a statement about a command; the symlink
    existing is a statement about the artifact, and the artifact is what gets
    installed. bunny-brlapi-key.service is here because an installed system
    measured it never running: the unit shipped with WantedBy=sysinit.target,
    nothing enabled it, and systemd disables what no preset names — so
    /etc/brlapi.key was never minted and BRLTTY had no authorisation key for the
    whole session.
    """
    subprocess.run([
        "/usr/bin/systemctl", "enable",
        "NetworkManager.service", "firewalld.service", "bunny-system-broker.socket",
        "bunny-health-check.service", "bunny-brlapi-key.service",
    ], check=True)
    subprocess.run(["/usr/bin/systemctl", "enable", "bunny-recovery-shell.service"], check=True)
    subprocess.run(["/usr/bin/systemctl", "--global", "enable", "bunny-first-boot.service", "bunny-config-dir.service", "bunny-companion.service"], check=True)
    if args.profile == "recovery":
    subprocess.run([
        "/usr/bin/systemctl", "--global", "enable",
        "bunny-first-boot.service", "bunny-config-dir.service",
    ], check=True)
    if profile == "recovery":
        subprocess.run(["/usr/bin/systemctl", "set-default", "bunny-recovery.target"], check=True)
    elif profile in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        subprocess.run(["/usr/bin/systemctl", "enable", "gdm.service"], check=True)
        if profile == "live":
            subprocess.run(["/usr/bin/systemctl", "enable", "bunny-live-session.service"], check=True)
        subprocess.run(["/usr/bin/systemctl", "set-default", "graphical.target"], check=True)
    else:
        subprocess.run(["/usr/bin/systemctl", "set-default", "multi-user.target"], check=True)
    subprocess.run(["/usr/bin/firewall-offline-cmd", "--set-default-zone=bunny-default"], check=True)

    # The user-tmpfiles rule has the same failure shape as an unactivated unit:
    # it is read from one search path, systemd never reports that it looked, and
    # a rule in the wrong directory is indistinguishable from no rule at all
    # until a fresh home fails to get its directories.
    user_tmpfiles_rule = Path("/usr/share/user-tmpfiles.d/bunny-os.conf")
    inert_rule = [] if user_tmpfiles_rule.is_file() else [
        f"the per-user tmpfiles rule (expected {user_tmpfiles_rule}; "
        "/usr/lib/user-tmpfiles.d is not a --user search path)"]

    required_activation = {
        "bunny-brlapi-key.service": Path(
            "/etc/systemd/system/sysinit.target.wants/bunny-brlapi-key.service"
        ),
        "bunny-health-check.service": Path(
            "/etc/systemd/system/multi-user.target.wants/bunny-health-check.service"
        ),
        # The two halves of the first-login correction. bunny-config-dir is what
        # makes bunny-first-boot's sandbox constructible, and bunny-first-boot
        # Requires= it, so an image where only one of them is activated starts no
        # first-boot flow at all.
        "bunny-config-dir.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-config-dir.service"
        ),
        "bunny-first-boot.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-first-boot.service"
        ),
        "bunny-companion.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-companion.service"
        ),
    }
    missing_activation = inert_rule + [
        f"{unit} (expected {link})"
        for unit, link in required_activation.items()
        if not link.is_symlink()
    ]
    if missing_activation:
        raise SystemExit(
            "BLOCKED: these units are not activated in the built filesystem: "
            + "; ".join(missing_activation)
            + ". A unit that ships without its enablement is a unit systemd will "
            "never start, which is how /etc/brlapi.key came to be absent on every "
            "installed system."
        )


def compile_desktop_assets(profile: str) -> None:
    """Turn copied sources into the compiled forms the desktop reads.

    Every product of this function is declared in ``GENERATED_ROUTES``. None of
    it copies a repository file; each command reads what the routes already
    installed and writes a compiled artefact beside it.
    """
    if profile not in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        return
    extension_root = Path("/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org")
    subprocess.run(["/usr/bin/glib-compile-schemas", str(extension_root / "schemas")], check=True)
    subprocess.run(["/usr/bin/dconf", "update"], check=True)
    subprocess.run(
        ["/usr/bin/gtk-update-icon-cache", "--force", "/usr/share/icons/hicolor"], check=False,
    )


def assert_no_stray_user_units() -> None:
    """``systemd/user`` is excluded from the system-unit route, and this proves it.

    The installer used to copy ``systemd/**`` wholesale into
    ``/usr/lib/systemd/system`` — user units included — and then delete the
    ``user`` subdirectory it had just written. The route excludes it instead, so
    the units are never written to the wrong place at all. This asserts the
    outcome rather than trusting the exclusion, because the failure it guards
    against is a user unit sitting in the system directory where systemd would
    read it with the wrong manager.
    """
    stray = Path("/usr/lib/systemd/system/user")
    if stray.exists():
        raise SystemExit(
            f"BLOCKED: {stray} exists. User units must reach /usr/lib/systemd/user "
            "only; a unit in the system directory is run by the system manager."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=(
        "developer", "minimal", "desktop", "recovery", "shell", "shell-test", "live", "beta",
    ))
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--base-image", required=True)
    args = parser.parse_args()
    source = args.source

    artifact_manifest_path = source / "build/manifests/bunny-artifact.placeholder.json"
    artifact_payload = source / "build/artifacts/bunny"
    subprocess.run([
        "/usr/bin/python3", str(source / "build/scripts/verify-bunny-artifact.py"),
        str(artifact_manifest_path), str(artifact_payload),
    ], check=True)
    artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))

    install_all_routes(source, args.profile)
    assert_no_stray_user_units()
    compile_desktop_assets(args.profile)
    write_release_metadata(args, artifact_manifest)
    write_package_inventory()
    install_release_payload(source, artifact_manifest)
    create_state_directories()
    install_activation(args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
