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
import platform
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
        # The Public Alpha's whole success path begins here. Without these two
        # symlinks a person logs into a freshly installed machine and no
        # companion appears — which is what every image before this one did.
        "bunny-companion.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-companion.service"
        ),
        "bunny-companion-window.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-companion-window.service"
        ),
        "bunny-first-run.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-first-run.service"
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
