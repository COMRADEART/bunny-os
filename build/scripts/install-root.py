#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install Bunny OS-owned files into a bootc container filesystem."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def copy_file(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, mode)


def copy_tree(source: Path, destination: Path, mode: int = 0o644) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_file() and not any(part in {"__pycache__", "node_modules", "target"} for part in item.parts):
            target = destination / item.relative_to(source)
            copy_file(item, target, mode)


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
    copy_tree(source / "schemas", Path("/usr/share/bunny-os/schemas"), 0o444)
    copy_tree(source / "docs", Path("/usr/share/doc/bunny-os"), 0o444)
    copy_file(source / "ARCHITECTURE.md", Path("/usr/share/doc/bunny-os/ARCHITECTURE.md"), 0o444)
    copy_file(source / "README.md", Path("/usr/share/doc/bunny-os/README.md"), 0o444)

    timestamp = datetime.fromtimestamp(args.source_date_epoch, timezone.utc).isoformat().replace("+00:00", "Z") if args.source_date_epoch else "unspecified"
    metadata = {
        "schemaVersion": 1,
        "osVersion": args.os_version,
        "imageVersion": args.image_version,
        "profile": args.profile,
        "contractVersion": "1.0.0",
        "brokerVersion": "0.1.0",
        "recoveryVersion": "0.1.0",
        "bunnyVersion": artifact_manifest["bunnyVersion"],
        "bunnyArtifactStatus": artifact_manifest["status"],
        "bunnyProtocolVersion": 3,
        "baseDistribution": "Fedora",
        "baseVersion": "44",
        "baseImageReference": args.base_image,
        "sourceCommit": args.source_commit,
        "sourceDateEpoch": args.source_date_epoch,
        "buildTimestamp": timestamp,
        "buildTool": "OCI Containerfile + unified image-builder",
    }
    release = Path("/usr/lib/bunny-os/release.json")
    release.parent.mkdir(parents=True, exist_ok=True)
    release.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(release, 0o444)
    inventory = subprocess.run(["/usr/bin/rpm", "-qa", "--qf", "%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n"], check=True, text=True, stdout=subprocess.PIPE).stdout
    Path("/usr/lib/bunny-os/packages.txt").write_text("".join(sorted(inventory.splitlines(keepends=True))), encoding="utf-8")
    os.chmod("/usr/lib/bunny-os/packages.txt", 0o444)

    release_name = artifact_manifest["bunnyVersion"] if artifact_manifest["status"] == "verified" else f'{artifact_manifest["bunnyVersion"]}-placeholder'
    release_root = Path("/opt/bunny/releases") / release_name
    release_root.mkdir(parents=True, exist_ok=True)
    if artifact_manifest["status"] == "verified":
        for item in artifact_manifest["files"]:
            copy_file(artifact_payload / item["path"], release_root / item["path"], int(item["mode"], 8))
    current = Path("/opt/bunny/current")
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(f"releases/{release_name}")
    state_paths = {
        Path("/var/lib/bunny"): 0o711,
        Path("/var/cache/bunny"): 0o711,
        Path("/var/log/bunny"): 0o750,
        Path("/var/lib/bunny-os"): 0o711,
        Path("/var/lib/bunny-os/update"): 0o700,
        Path("/var/lib/bunny-os/recovery"): 0o700,
        Path("/var/lib/bunny-os/health"): 0o700,
        Path("/var/lib/bunny-os/support"): 0o711,
    }
    for path, mode in state_paths.items():
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        os.chmod(path, mode)

    # bunny-brlapi-key.service is enabled here because an installed system
    # measured it never running: the unit ships with WantedBy=sysinit.target,
    # nothing enabled it, and systemd's default preset policy disables what no
    # preset names — so /etc/brlapi.key was never minted and BRLTTY had no
    # authorisation key for the whole session. This is the second half of the
    # same accessibility defect as the missing program: CI could see the
    # ExecStart that pointed nowhere, and only booting an installed system
    # could see the service that nothing started.
    subprocess.run(["/usr/bin/systemctl", "enable", "NetworkManager.service", "firewalld.service", "bunny-system-broker.socket", "bunny-health-check.service", "bunny-brlapi-key.service"], check=True)
    subprocess.run(["/usr/bin/systemctl", "enable", "bunny-recovery-shell.service"], check=True)
    subprocess.run(["/usr/bin/systemctl", "--global", "enable", "bunny-first-boot.service", "bunny-config-dir.service"], check=True)
    if args.profile == "recovery":
        subprocess.run(["/usr/bin/systemctl", "set-default", "bunny-recovery.target"], check=True)
    elif args.profile in {"developer", "desktop", "shell", "shell-test", "live", "beta"}:
        subprocess.run(["/usr/bin/systemctl", "enable", "gdm.service"], check=True)
        if args.profile == "live":
            subprocess.run(["/usr/bin/systemctl", "enable", "bunny-live-session.service"], check=True)
        subprocess.run(["/usr/bin/systemctl", "set-default", "graphical.target"], check=True)
    else:
        subprocess.run(["/usr/bin/systemctl", "set-default", "multi-user.target"], check=True)
    subprocess.run(["/usr/bin/firewall-offline-cmd", "--set-default-zone=bunny-default"], check=True)

    # Assert the activation landed, rather than trusting that the command that
    # was supposed to create it exited zero.
    #
    # The measured defect this closes was exactly this shape: the unit shipped,
    # the enablement did not exist, and nothing between the build and a booted
    # installed system noticed. `systemctl enable` succeeding is a statement
    # about a command; the symlink existing is a statement about the artifact,
    # and the artifact is what gets installed. A build that produced an image
    # whose accessibility service is inert must fail here, where it is cheap,
    # rather than on a device where it is silent.
    required_activation = {
        "bunny-brlapi-key.service": Path(
            "/etc/systemd/system/sysinit.target.wants/bunny-brlapi-key.service"
        ),
        "bunny-health-check.service": Path(
            "/etc/systemd/system/multi-user.target.wants/bunny-health-check.service"
        ),
        # The two halves of the first-login correction. bunny-config-dir is
        # what makes bunny-first-boot's sandbox constructible, and
        # bunny-first-boot Requires= it, so an image where only one of them is
        # activated starts no first-boot flow at all.
        "bunny-config-dir.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-config-dir.service"
        ),
        "bunny-first-boot.service": Path(
            "/etc/systemd/user/graphical-session.target.wants/bunny-first-boot.service"
        ),
    }
    missing_activation = [
        f"{unit} (expected {link})"
        for unit, link in required_activation.items()
        if not link.is_symlink()
    ]
    # The user-tmpfiles rule has the same failure shape as an unactivated
    # unit: it is read from one search path, systemd never says it looked, and
    # a rule in the wrong directory is indistinguishable from no rule at all
    # until a fresh home fails to get its directories.
    user_tmpfiles_rule = Path("/usr/share/user-tmpfiles.d/bunny-os.conf")
    if not user_tmpfiles_rule.is_file():
        missing_activation.append(
            f"the per-user tmpfiles rule (expected {user_tmpfiles_rule}; "
            "/usr/lib/user-tmpfiles.d is not a --user search path)")
    if missing_activation:
        raise SystemExit(
            "BLOCKED: these units are not activated in the built filesystem: "
            + "; ".join(missing_activation)
            + ". A unit that ships without its enablement is a unit systemd will "
            "never start, which is how /etc/brlapi.key came to be absent on every "
            "installed system."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
