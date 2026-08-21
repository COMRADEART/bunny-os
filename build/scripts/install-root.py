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
import base64
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from install_routes import (  # noqa: E402 - the path above is what makes this importable
    InstallRoute,
    route_files,
    routes_for_profile,
)


def copy_file(source: Path, destination: Path, mode: int) -> None:
    """The one primitive. Everything installed goes through here.

    The destination is **removed** before it is written, and that is not
    tidiness. ``shutil.copyfile`` opens the destination for truncation, which
    writes *through* an existing hardlink — so installing over a file an RPM
    ships as one member of a hardlink group silently rewrites every other
    member of that group.

    Measured on the release candidate: Fedora's ``accountsservice`` ships
    ``/usr/share/accountsservice/user-templates/{standard,administrator}`` as
    hardlinks to each other, and installing Bunny's two templates over them
    left both paths holding whichever route ran last — 495 bytes of the
    administrator template under both names, still sharing one inode. The
    behaviour happened to survive it (the two templates carry the same
    ``[User]`` block), which is exactly why a check that only asked "did the
    session come out right" would have missed it.

    Unlinking first gives each destination its own inode, which is what
    ``install(1)`` does and what every caller here already assumes.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
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
    # §39: one build identity, and the two fields that make it one.
    #
    # ``buildId`` is derived from the commit and SOURCE_DATE_EPOCH rather than
    # counted, so two builds of one tree at one epoch carry the same id. A
    # counter would make every rebuild a different build even when nothing about
    # it differed, which is the opposite of what the qualification phase needs.
    #
    # ``releaseChannel`` is one of the two §40 names. It comes from the build
    # argument and is validated here rather than trusted: an image labelled with
    # a channel this build does not define is an image nobody can reason about,
    # and "development" is the honest fallback because it promises least.
    channel = getattr(arguments, "release_channel", "development") or "development"
    if channel not in ("development", "alpha"):
        channel = "development"
    commit = arguments.source_commit if arguments.source_commit != "unknown" else ""
    build_id = f"{commit[:12]}.{int(arguments.source_date_epoch or 0)}" if commit else "unknown"
    metadata = {
        "schemaVersion": 1,
        "osVersion": arguments.os_version,
        "imageVersion": arguments.image_version,
        "releaseChannel": channel,
        "buildId": build_id,
        "architecture": platform.machine(),
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
    write_os_release(metadata, root=root)
    return metadata


def write_os_release(metadata: dict, *, root: Path = Path("/")) -> None:
    """Put the Bunny identity where the operating system's own tools look.

    §39 asks for the identity in ``/etc/os-release`` or appropriate release
    metadata. ``release.json`` is the appropriate metadata and it is written
    above; this is the other half, because "appropriate metadata" is not what
    GNOME's About screen, ``hostnamectl`` or a bug reporter reads. A machine
    that calls itself "Fedora Linux 44" in every system surface is a machine
    whose bug reports go to Fedora.

    Appended rather than rewritten. The base fields — ``ID``, ``VERSION_ID``,
    ``PLATFORM_ID``, ``CPE_NAME`` — are what the package manager, SELinux policy
    and bootc all key off, and a downstream that rewrote them would break
    updates in order to change a string. So Fedora's file keeps every field it
    had, and the Bunny ones are added: ``NAME`` and ``PRETTY_NAME`` are replaced
    because they are display strings and nothing keys off them, and
    ``VARIANT``/``VARIANT_ID`` are the documented place for exactly this.

    Written to ``/usr/lib/os-release``. ``/etc/os-release`` is a symlink to it on
    every bootc image, and ``/usr`` is the half that belongs to the image.
    """
    path = root / "usr/lib/os-release"
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        # No base file to extend. Refusing is wrong — the image would then have
        # no Bunny identity at all — and inventing ID/VERSION_ID would be worse,
        # so only the fields that are ours get written.
        original = ""
    display = (
        f"Bunny OS Alpha {'.'.join(str(metadata['osVersion']).split('.')[:2])}"
        if metadata.get("releaseChannel") == "alpha"
        else f"Bunny OS {metadata['osVersion']} ({metadata.get('releaseChannel', 'development')})"
    )
    replaced = {"NAME", "PRETTY_NAME", "VARIANT", "VARIANT_ID", "HOME_URL",
                "BUG_REPORT_URL", "SUPPORT_URL", "DOCUMENTATION_URL"}
    kept = [
        line for line in original.splitlines()
        if not any(line.startswith(f"{key}=") for key in replaced)
    ]
    added = [
        'NAME="Bunny OS"',
        f'PRETTY_NAME="{display}"',
        f'VARIANT="{display}"',
        f'VARIANT_ID={metadata.get("releaseChannel", "development")}',
        'HOME_URL="https://bunny-os.org/"',
        'DOCUMENTATION_URL="file:///usr/share/doc/bunny-os/README.md"',
        'SUPPORT_URL="file:///usr/share/doc/bunny-os/TROUBLESHOOTING.md"',
        'BUG_REPORT_URL="file:///usr/share/doc/bunny-os/REPORTING_BUGS.md"',
        f'BUNNY_OS_VERSION={metadata["osVersion"]}',
        f'BUNNY_OS_CHANNEL={metadata.get("releaseChannel", "development")}',
        f'BUNNY_OS_BUILD_ID={metadata.get("buildId", "unknown")}',
        f'BUNNY_OS_COMMIT={metadata["sourceCommit"]}',
        f'BUNNY_OS_PROFILE={metadata["profile"]}',
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*kept, *added]) + "\n", encoding="utf-8")
    os.chmod(path, 0o444)


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
    # The user units, enabled globally so every account gets them.
    #
    # A preset file is not an enablement. `/usr/lib/systemd/user-preset/60-bunny-os.preset`
    # has named bunny-companion.service since the integration branch, and the
    # comment beside it says "enabled rather than left to the desktop entry" —
    # and it was not enabled, on any image ever built, because nothing runs
    # `systemctl --global preset-all` and the user manager does not apply presets
    # by itself. Measured on the first booted Alpha image: `systemctl --user
    # is-enabled bunny-companion.service bunny-companion-window.service` answered
    # `disabled` twice, and the runtime was `inactive` in a live graphical
    # session. The companion has never started at login on a built image.
    #
    # This is the same failure shape as bunny-brlapi-key.service, for the same
    # reason, and it is caught the same way: by asserting the symlink below
    # rather than by trusting the command above.
    #
    # `bunny-companion-window.service` is deliberately **not** in this list.
    # The runtime is the thing that has to be running at login; the window is a
    # GTK client of it, and enabling it meant a full application window opened
    # over the middle of the desktop at every login — on top of the
    # shell-rendered character, which is the desktop's own representation of the
    # same assistant. Two Bunnies, one covering the other.
    #
    # The unit is still shipped and still startable: the Applications grid has
    # the entry, the dock tile runs it, and `systemctl --user start
    # bunny-companion-window.service` works. What changed is that nothing starts
    # it for you.
    subprocess.run([
        "/usr/bin/systemctl", "--global", "enable",
        "bunny-first-boot.service", "bunny-config-dir.service",
        "bunny-companion.service",
        "bunny-first-run.service",
    ], check=True)
    # Masked, not disabled. `--global disable` writes into /etc/systemd/user and
    # can remove a symlink it put there; gnome-software.service is wanted from
    # /usr/lib/systemd/user, which disable cannot reach. Measured: after
    # `--global disable`, the unit still started and still made the connection.
    # A mask is /etc/systemd/user/gnome-software.service -> /dev/null, which
    # overrides the vendor path.
    subprocess.run([
        "/usr/bin/systemctl", "--global", "mask", "gnome-software.service",
    ], check=False)
    if profile == "recovery":
        subprocess.run(["/usr/bin/systemctl", "set-default", "bunny-recovery.target"], check=True)
    elif profile in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        subprocess.run(["/usr/bin/systemctl", "enable", "gdm.service"], check=True)
        if profile == "live":
            # Both halves of the live installer. `bunny-live-session` creates the
            # ephemeral account and writes the marker carrying its UID;
            # `bunny-installer-backend` reads that marker, serves the installer
            # protocol on a socket only that UID may open, and publishes the
            # session token the setup surface authenticates with.
            #
            # Without the second, the medium boots into a setup surface that
            # finds no backend, reports "no disks found" on a machine with a
            # disk, and can install nothing. The unit shipped with
            # WantedBy=graphical.target and nothing wanted it — the exact shape
            # of the brlapi failure this function's docstring is about.
            # Three units, not two: the backend's destructive executor drives
            # Anaconda's Boss over the private bus, and run 11 of Journey A
            # proved nothing on the medium ever started that bus — every
            # confirmed installation ended at "destructive executor is
            # unavailable" with the wire to it working perfectly.
            subprocess.run([
                "/usr/bin/systemctl", "enable",
                "bunny-live-session.service", "bunny-installer-backend.service",
                "bunny-anaconda-bus.service",
            ], check=True)
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
        # The Public Alpha's whole success path begins here. Without this
        # symlink a person logs into a freshly installed machine and the
        # assistant's backend is not running — which is what every image before
        # the Public Alpha branch did.
        "bunny-companion.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-companion.service"
        ),
        "bunny-first-run.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-first-run.service"
        ),
    }

    # Live-only, and asserted the same way: the symlink is the artifact, the
    # command is only a claim about a command.
    if profile == "live":
        required_activation["bunny-installer-backend.service"] = Path(
            "/etc/systemd/system/graphical.target.wants/bunny-installer-backend.service"
        )
        required_activation["bunny-live-session.service"] = Path(
            "/etc/systemd/system/graphical.target.wants/bunny-live-session.service"
        )
        required_activation["bunny-anaconda-bus.service"] = Path(
            "/etc/systemd/system/graphical.target.wants/bunny-anaconda-bus.service"
        )

    #: Units that must **not** be activated, and why.
    #:
    #: The same fail-closed idea pointed the other way. `--global enable` is not
    #: the only thing that can create one of these symlinks — a preset applied
    #: by hand, a leftover from an earlier image, a merge that restored a line —
    #: and the cost of the window unit being enabled is not subtle: a GTK
    #: application window opens over the shell-rendered character at every
    #: login, which is the defect this release removed.
    #:
    #: Asserting the absence is what makes "we stopped enabling it" a property
    #: of the built filesystem rather than of one line in this file.
    forbidden_activation = {
        "bunny-companion-window.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-companion-window.service"
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

    unwanted_activation = [
        f"{unit} (found {link})"
        for unit, link in forbidden_activation.items()
        if link.exists() or link.is_symlink()
    ]
    if unwanted_activation:
        raise SystemExit(
            "BLOCKED: these units are activated and must not be: "
            + "; ".join(unwanted_activation)
            + ". The companion window is a client of the runtime and opens over "
            "the shell-rendered character; the runtime is what has to start at "
            "login. Open the window from the Applications grid instead."
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


def expand_vendored_voice_wheels(
    profile: str,
    *,
    root: Path = Path("/"),
) -> None:
    """Expand pinned CPU-only wheels after verifying the wheel and its RECORD.

    Fedora 44's ``python3-torch`` is a ROCm build whose *hard* dependency
    closure includes several gigabytes of GPU libraries. Bunny voice is CPU
    inference, so the image carries PyTorch's official manylinux CPU wheel
    instead. This is deliberately a build-time expansion: no package manager,
    network request or first-run extraction is reachable on an installed OS.
    """
    if profile not in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        return
    wheel_root = root / "usr/lib/bunny-os/voice-runtime/wheels"
    manifest_path = wheel_root / "MANIFEST.json"
    try:
        raw = manifest_path.read_bytes()
        if len(raw) > 64 * 1024:
            raise ValueError("wheel manifest is oversized")
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"BLOCKED: the neural voice wheel manifest is invalid: {exc}") from exc
    wheels = manifest.get("wheels") if isinstance(manifest, dict) else None
    if manifest.get("schemaVersion") != 1 or not isinstance(wheels, list) or not wheels:
        raise SystemExit("BLOCKED: the neural voice wheel manifest has no supported wheel set")

    install_root = root / "usr/lib/bunny-os/voice-runtime/site-packages"
    install_root.mkdir(parents=True, exist_ok=True)
    for record in wheels:
        if not isinstance(record, dict):
            raise SystemExit("BLOCKED: a neural voice wheel record is malformed")
        file_name = record.get("fileName")
        digest = record.get("sha256")
        size = record.get("sizeBytes")
        if (
            not isinstance(file_name, str)
            or Path(file_name).name != file_name
            or not file_name.endswith(".whl")
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or size <= 0
        ):
            raise SystemExit("BLOCKED: a neural voice wheel identity is unsafe")
        wheel_path = wheel_root / file_name
        try:
            if wheel_path.stat().st_size != size:
                raise ValueError("size mismatch")
            wheel_hash = hashlib.sha256()
            with wheel_path.open("rb") as wheel_stream:
                for block in iter(lambda: wheel_stream.read(1024 * 1024), b""):
                    wheel_hash.update(block)
            actual = wheel_hash.hexdigest()
        except (OSError, ValueError) as exc:
            raise SystemExit(f"BLOCKED: {file_name} cannot be verified: {exc}") from exc
        if actual != digest:
            raise SystemExit(f"BLOCKED: {file_name} failed its pinned SHA-256")

        try:
            archive = zipfile.ZipFile(wheel_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise SystemExit(f"BLOCKED: {file_name} is not a valid wheel archive: {exc}") from exc
        with archive:
            members = archive.infolist()
            if not 1 <= len(members) <= 20_000:
                raise SystemExit(f"BLOCKED: {file_name} has an unsafe member count")
            total = sum(item.file_size for item in members)
            if total <= 0 or total > 1024 * 1024 * 1024:
                raise SystemExit(f"BLOCKED: {file_name} has an unsafe expanded size")

            record_names = [item.filename for item in members if item.filename.endswith(".dist-info/RECORD")]
            if len(record_names) != 1:
                raise SystemExit(f"BLOCKED: {file_name} does not carry exactly one RECORD")
            try:
                rows = {
                    row[0]: (row[1], row[2])
                    for row in csv.reader(archive.read(record_names[0]).decode("utf-8").splitlines())
                    if len(row) == 3
                }
            except (KeyError, UnicodeDecodeError, csv.Error) as exc:
                raise SystemExit(f"BLOCKED: {file_name} RECORD cannot be read: {exc}") from exc

            for item in members:
                parts = Path(item.filename).parts
                mode = (item.external_attr >> 16) & 0o177777
                if (
                    not item.filename
                    or item.filename.startswith(("/", "\\"))
                    or ".." in parts
                    or any(part.endswith(".data") for part in parts)
                    or stat.S_ISLNK(mode)
                    or item.file_size > 768 * 1024 * 1024
                ):
                    raise SystemExit(f"BLOCKED: {file_name} contains an unsafe member")
                if item.is_dir():
                    continue
                expected = rows.get(item.filename)
                if expected is None:
                    raise SystemExit(f"BLOCKED: {file_name} RECORD omits {item.filename}")
                expected_hash, expected_size = expected
                if expected_size and (not expected_size.isdigit() or int(expected_size) != item.file_size):
                    raise SystemExit(f"BLOCKED: {file_name} member size verification failed")

                target = install_root.joinpath(*parts)
                try:
                    target.resolve(strict=False).relative_to(install_root.resolve(strict=True))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
                    member_hash = hashlib.sha256()
                    copied = 0
                    with archive.open(item, "r") as source, os.fdopen(descriptor, "wb") as output:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            output.write(block)
                            member_hash.update(block)
                            copied += len(block)
                    os.chmod(target, 0o555 if mode & 0o111 else 0o444)
                except (FileExistsError, OSError, ValueError) as exc:
                    raise SystemExit(f"BLOCKED: {file_name} member cannot be installed: {exc}") from exc
                if copied != item.file_size:
                    raise SystemExit(f"BLOCKED: {file_name} member extraction was truncated")
                if expected_hash:
                    algorithm, separator, encoded = expected_hash.partition("=")
                    observed = base64.urlsafe_b64encode(member_hash.digest()).rstrip(b"=").decode("ascii")
                    if algorithm != "sha256" or not separator or observed != encoded:
                        raise SystemExit(f"BLOCKED: {file_name} RECORD hash verification failed")
        # The installed root needs the expanded runtime, not a second compressed
        # copy. The immutable manifest remains as the provenance of the removed
        # build-time staging file.
        wheel_path.unlink()


def assert_voice_image_payload(
    profile: str,
    installed: dict[str, list[str]],
    *,
    root: Path = Path("/"),
) -> None:
    """Refuse a desktop image whose declared local voice stack is incomplete.

    Package installation and route copying are deliberately separate build
    stages.  Either can exit successfully while still producing an unusable
    feature: a package may not contain the executable we expected, or a tree
    route whose source disappeared may copy zero files.  Check the resulting
    filesystem, because that is what a fresh installation receives.
    """
    if profile not in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        return

    required_routes = (
        "companion-package",
        "speech-recognition-models",
        "speech-synthesis-model-pocket",
        "speech-synthesis-model-kitten",
        "speech-synthesis-runtime",
        "speech-recognition-licenses",
        "speech-recognition-provenance",
        "shell-commands",
        "user-units",
    )
    problems = [
        f"install route {route_id!r} copied no files"
        for route_id in required_routes
        if not installed.get(route_id)
    ]

    required_files = (
        "usr/bin/pw-record",
        "usr/bin/parec",
        "usr/bin/arecord",
        "usr/bin/espeak-ng",
        "usr/bin/spd-say",
        "usr/bin/bunny-voice-neural-worker",
        "usr/lib/bunny-os/python/companion/speech/vosk_runtime.py",
        "usr/lib/bunny-os/python/companion/voice/neural_worker.py",
        "usr/lib/bunny-os/voice-runtime/site-packages/pocket_tts/__init__.py",
        "usr/lib/bunny-os/voice-runtime/site-packages/pocket_tts-2.1.0.dist-info/METADATA",
        "usr/lib/bunny-os/voice-runtime/site-packages/torch/__init__.py",
        "usr/lib/bunny-os/voice-runtime/site-packages/torch-2.9.1+cpu.dist-info/METADATA",
        "usr/lib/bunny-os/voice-runtime/wheels/MANIFEST.json",
        "usr/lib/systemd/user/bunny-companion.service",
        "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/.bunny-model.json",
        "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/am/final.mdl",
        "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/graph/Gr.fst",
        "usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/graph/HCLr.fst",
        "usr/share/bunny-os/voice/pocket/english/manifest.json",
        "usr/share/bunny-os/voice/pocket/english/config.yaml",
        "usr/share/bunny-os/voice/pocket/english/model.safetensors",
        "usr/share/bunny-os/voice/pocket/english/tokenizer.model",
        "usr/share/bunny-os/voice/pocket/english/voices/caro_davy.safetensors",
        "usr/share/bunny-os/voice/kitten/nano-int8/manifest.json",
        "usr/share/bunny-os/voice/kitten/nano-int8/config.json",
        "usr/share/bunny-os/voice/kitten/nano-int8/kitten_tts_nano_v0_8.onnx",
        "usr/share/bunny-os/voice/kitten/nano-int8/voices.npz",
        "usr/share/licenses/bunny-os-voice/Apache-2.0.txt",
        "usr/share/licenses/bunny-os-voice/pocket-tts/MIT.txt",
        "usr/share/licenses/bunny-os-voice/pocket-model/CC-BY-4.0.txt",
        "usr/share/licenses/bunny-os-voice/voice-zero/CC0-1.0.txt",
        "usr/share/licenses/bunny-os-voice/kitten-tts/Apache-2.0.txt",
        "usr/share/doc/bunny-os/voice-provenance.json",
    )
    for relative in required_files:
        target = root / relative
        try:
            present = target.is_file() and target.stat().st_size > 0
        except OSError:
            present = False
        if not present:
            problems.append(f"/{relative} is missing or empty")

    runtime_candidates = (
        root / "usr/lib64/libvosk.so",
        root / "usr/lib/libvosk.so",
    )
    if not any(path.is_file() for path in runtime_candidates):
        problems.append("libvosk.so is absent from both /usr/lib64 and /usr/lib")

    # On the real image root, prove that every native/Python runtime needed by
    # the isolated worker imports under the system interpreter. File-name
    # guesses are not reliable for architecture-tagged extension modules, and
    # an RPM transaction may succeed while a dependency is still unusable.
    if root == Path("/"):
        probe = subprocess.run(
            [
                "/usr/bin/python3", "-I", "-c",
                (
                    "import sys; "
                    "sys.path.insert(0, '/usr/lib/bunny-os/voice-runtime/site-packages'); "
                    "import beartype, einops, numpy, onnxruntime, pydantic, requests, "
                    "safetensors, scipy, sentencepiece, torch, yaml, pocket_tts"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout or "import probe failed").strip()
            problems.append(f"neural TTS runtime import failed: {detail[:512]}")

    if problems:
        raise SystemExit(
            "BLOCKED: the desktop voice payload is incomplete: "
            + "; ".join(problems)
            + ". A source implementation is not an installed-system feature."
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
    # §40's two channels. Defaulted rather than required, so every existing
    # caller keeps working and produces a development image — which is what an
    # unlabelled build is.
    parser.add_argument("--release-channel", default="development",
                        choices=("development", "alpha"))
    args = parser.parse_args()
    source = args.source

    artifact_manifest_path = source / "build/manifests/bunny-artifact.placeholder.json"
    artifact_payload = source / "build/artifacts/bunny"
    subprocess.run([
        "/usr/bin/python3", str(source / "build/scripts/verify-bunny-artifact.py"),
        str(artifact_manifest_path), str(artifact_payload),
    ], check=True)
    artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))

    installed = install_all_routes(source, args.profile)
    expand_vendored_voice_wheels(args.profile)
    assert_no_stray_user_units()
    assert_voice_image_payload(args.profile, installed)
    compile_desktop_assets(args.profile)
    write_release_metadata(args, artifact_manifest)
    write_package_inventory()
    install_release_payload(source, artifact_manifest)
    create_state_directories()
    install_activation(args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
