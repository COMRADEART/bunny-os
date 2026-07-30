#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install an explicit package-set union without inheriting host packages."""

from __future__ import annotations

import argparse
import configparser
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlparse


def disable_repository_file(path: Path) -> None:
    """Set ``enabled=0`` in every section of a repository definition.

    ``--disablerepo=*`` only covers the invocation it is passed to. A package
    scriptlet that shells out to dnf, or a later step that forgets the flag,
    would see the base image's repositories enabled and could reach the network.
    Disabling them in the files closes that, and leaves the definitions in place
    so the installed system still knows what its repositories are.
    """
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if not parser.sections():
        return
    for section in parser.sections():
        parser.set(section, "enabled", "0")
        parser.set(section, "countme", "0")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        parser.write(handle)


def package_file(path: Path) -> list[str]:
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            values.append(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=("developer", "minimal", "desktop", "recovery", "shell", "shell-test", "live", "beta"))
    parser.add_argument("--release-build", required=True, choices=("0", "1"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    profile_path = args.root.parent / "profiles" / f"{args.profile}.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    packages = sorted({package for name in profile["packageSets"] for package in package_file(args.root / f"{name}.txt")})
    repository_args: list[str] = []

    # Hermetic mode: install from the retained snapshot and nothing else.
    #
    # Both halves of the previous comparison resolved their package sets against
    # live Fedora repositories, an hour apart. They agreed, and agreeing was
    # luck — Fedora publishes continuously. Here the set was decided once by the
    # resolution stage, materialised, signed and verified; this step installs it
    # and resolves nothing.
    #
    # `repo_gpgcheck` is deliberately 0 and that is not a relaxation. It checks
    # a detached GPG signature over repomd.xml, which a Fedora mirror provides
    # and a local snapshot does not. What replaces it is stronger: the snapshot
    # manifest is signed, it carries the SHA-256 of repomd.xml, and
    # verify-package-snapshot.py checks both *before* the build container
    # starts. `gpgcheck=1` stays on, so every RPM's own Fedora signature is
    # still verified at install time by rpm itself.
    snapshot_root = os.environ.get("BUNNY_SNAPSHOT_ROOT", "")
    if snapshot_root:
        if not Path(snapshot_root, "repodata", "repomd.xml").is_file():
            raise SystemExit(
                f"hermetic build: no repository metadata at {snapshot_root}/repodata/repomd.xml. "
                "The snapshot is not mounted, and a build that cannot see it must fail rather "
                "than fall back to a live repository."
            )
        Path("/etc/yum.repos.d").mkdir(parents=True, exist_ok=True)
        # Every repository the base image ships is disabled by file, not only by
        # --disablerepo, so that a scriptlet or a nested dnf call cannot re-enable
        # one behind this step's back.
        for existing in Path("/etc/yum.repos.d").glob("*.repo"):
            disable_repository_file(existing)
        # The snapshot is verified against **Fedora's own keys**, not against a
        # key this project holds. Every RPM in it is byte-identical to the one
        # Fedora published, signature included, and configuring Fedora's key
        # here is what lets rpm check that at install time.
        #
        # The first hermetic build failed exactly here, and the failure was the
        # check working:
        #
        #   Transaction failed: Signature verification failed.
        #   OpenPGP check for package "NetworkManager-wifi-1:1.56.1-2.fc44.x86_64"
        #   ... has failed: The repository does not have any OpenPGP keys configured.
        #
        # The wrong fix would have been gpgcheck=0. Re-signing the packages with
        # the development snapshot key would have been worse: it would replace
        # Fedora's trust with ours while looking like an improvement.
        # Scoped to the release that signed this snapshot, not every key Fedora
        # has ever published. A glob of `RPM-GPG-KEY-fedora-*` matched **300**
        # keys back to Fedora 7 — which would configure the build to accept a
        # signature from any of them, and is the opposite of pinning.
        release = subprocess.run(
            ["/usr/bin/rpm", "-E", "%fedora"], capture_output=True, text=True
        ).stdout.strip()
        architecture = subprocess.run(
            ["/usr/bin/rpm", "-E", "%_arch"], capture_output=True, text=True
        ).stdout.strip()
        fedora_keys = [
            path
            for path in (
                Path(f"/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-{release}-primary"),
                Path(f"/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-{release}-{architecture}"),
            )
            if path.is_file()
        ]
        if not fedora_keys:
            raise SystemExit(
                f"hermetic build: no Fedora {release} signing key at /etc/pki/rpm-gpg. Every RPM "
                "must retain its original trusted signature, and without the key that signature "
                "cannot be checked. Refusing rather than installing unverified packages."
            )
        Path("/etc/yum.repos.d/bunny-snapshot.repo").write_text(
            "[bunny-fedora-snapshot]\n"
            "name=Bunny OS retained Fedora snapshot\n"
            f"baseurl=file://{snapshot_root}\n"
            "enabled=1\n"
            "gpgcheck=1\n"
            "repo_gpgcheck=0\n"
            "gpgkey=" + "\n       ".join(f"file://{key}" for key in fedora_keys) + "\n"
            "countme=0\n"
            "metadata_expire=-1\n"
            "skip_if_unavailable=0\n",
            encoding="utf-8",
            newline="\n",
        )
        print(
            f"hermetic install: {len(fedora_keys)} Fedora signing keys configured: "
            + ", ".join(key.name for key in fedora_keys)
        )
        repository_args = [
            "--disablerepo=*",
            "--enablerepo=bunny-fedora-snapshot",
            "--setopt=countme=0",
            # Without this, a package missing from the snapshot is a warning and
            # the transaction proceeds with a smaller set — which is precisely
            # the silent fallback this mode exists to make impossible.
            "--setopt=strict=1",
            "--setopt=skip_if_unavailable=0",
        ]
    elif args.release_build == "1":
        repository = args.root.parent / "repositories" / "fedora-44-snapshot.repo"
        if not repository.is_file():
            raise SystemExit("release build requires reviewed build/repositories/fedora-44-snapshot.repo")
        config = configparser.ConfigParser()
        config.read(repository, encoding="utf-8")
        if config.sections() != ["bunny-fedora-snapshot"]:
            raise SystemExit("snapshot repository must contain only [bunny-fedora-snapshot]")
        section = config["bunny-fedora-snapshot"]
        baseurl = urlparse(section.get("baseurl", ""))
        if baseurl.scheme != "https" or section.get("gpgcheck") != "1" or section.get("repo_gpgcheck") != "1" or section.get("enabled") != "1":
            raise SystemExit("snapshot repository requires HTTPS, gpgcheck=1, repo_gpgcheck=1, enabled=1")
        shutil.copyfile(repository, "/etc/yum.repos.d/bunny-fedora-snapshot.repo")
        repository_args = ["--disablerepo=*", "--enablerepo=bunny-fedora-snapshot"]
    environment = {"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}

    # The build clock, scoped to the package transaction and to nothing else.
    #
    # rpm stamps every installed header with INSTALLTIME from the system clock,
    # which is why /usr/share/rpm/rpmdb.sqlite differed between two builders.
    # libfaketime is bind-mounted in by the caller and LD_PRELOADed here; it is
    # never installed into the image, and the override ends when dnf exits.
    #
    # No network operation happens under it: the snapshot is a file:// repository,
    # so there is no TLS handshake whose certificate validity could be affected.
    # RPM signature verification still runs against the real Fedora keys, and the
    # epoch is the candidate commit's own timestamp, which is inside their
    # validity. See docs/adr/ADR-028-deterministic-package-manager-state.md.
    faketime_library = os.environ.get("BUNNY_FAKETIME_LIBRARY", "")
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH", "")
    transaction_environment = dict(environment)
    if faketime_library and source_date_epoch:
        if not Path(faketime_library).is_file():
            raise SystemExit(
                f"hermetic build: BUNNY_FAKETIME_LIBRARY names {faketime_library}, which is not "
                "present. Continuing would stamp the rpm database with wall-clock install times "
                "and produce an artifact that cannot reproduce, without saying so."
            )
        # A separate environment for the transaction, not a mutation of the
        # shared one. The lock declares the override is scoped to the package
        # transaction; applying it to the rpm queries either side of the
        # transaction would be broader than declared, and the first version of
        # this did exactly that — the `before` snapshot ran under LD_PRELOAD and
        # rpm exited 1 with a message nobody captured.
        # libfaketime's `@` prefix means "absolute, frozen", and the value after
        # it is a *formatted date*, not a Unix timestamp:
        #
        #   libfaketime: In parse_ft_string(), failed to parse FAKETIME timestamp.
        #
        # SOURCE_DATE_EPOCH is seconds, so it is converted here. UTC explicitly:
        # the two builders are in different time zones, and a local-time
        # rendering would give them different frozen clocks from the same epoch —
        # which is the exact class of difference this is meant to remove.
        frozen = datetime.datetime.fromtimestamp(
            int(source_date_epoch), datetime.timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")
        transaction_environment["LD_PRELOAD"] = faketime_library
        transaction_environment["FAKETIME"] = f"@{frozen}"
        transaction_environment["FAKETIME_FMT"] = "%Y-%m-%d %H:%M:%S"
        # Monotonic clocks drive timeouts and progress reporting rather than
        # recorded state. Freezing them makes dnf's own waits misbehave and
        # changes nothing in the artifact.
        transaction_environment["FAKETIME_DONT_FAKE_MONOTONIC"] = "1"
        transaction_environment["TZ"] = "UTC"

    before = installed_nevras(environment)
    subprocess.run(
        ["/usr/bin/dnf", "--assumeyes", "--setopt=install_weak_deps=False", *repository_args, "install", *packages],
        check=True,
        env=transaction_environment,
    )
    after = installed_nevras(environment)

    if snapshot_root:
        verify_against_lock(before, after, Path(snapshot_root))

    # Package minimisation. A profile may declare packages that arrive in the
    # base image but that this profile does not want. The removal is verified
    # rather than trusted: anything in protected.txt that was installed before
    # the removal must still be installed after it, so a cascade that silently
    # takes recovery, accessibility, firmware, installer or security
    # functionality with it fails the build instead of shipping.
    removals = [str(name) for name in profile.get("removePackages", [])]
    if removals:
        protected = package_file(args.root / "protected.txt")
        before = installed_subset(protected, environment)
        overlap = sorted(set(removals) & set(protected))
        if overlap:
            raise SystemExit(
                "refusing to remove protected packages: " + ", ".join(overlap)
            )
        subprocess.run(
            ["/usr/bin/dnf", "--assumeyes", "remove", *removals],
            check=True,
            env=environment,
        )
        after = installed_subset(protected, environment)
        lost = sorted(before - after)
        if lost:
            raise SystemExit(
                "package removal cascaded into protected packages: "
                + ", ".join(lost)
                + "; minimisation must not reduce recovery, accessibility, firmware, installer "
                "or security functionality"
            )
        print(f"minimisation: removed {', '.join(sorted(removals))}; {len(after)} protected packages intact")
    return 0


def installed_nevras(environment: dict[str, str]) -> set[str]:
    """Every installed package as ``name-epoch:version-release.arch``."""
    result = subprocess.run(
        ["/usr/bin/rpm", "--query", "--all", "--queryformat",
         "%{NAME}-%|EPOCH?{%{EPOCH}}:{0}|:%{VERSION}-%{RELEASE}.%{ARCH}\\n"],
        capture_output=True,
        text=True,
        env=environment,
    )
    if result.returncode != 0:
        # `check=True` would raise CalledProcessError, whose message is the
        # argument list and an exit status. That is what the first hermetic
        # build printed, and it named neither the cause nor anything to look at.
        raise SystemExit(
            f"rpm --query --all failed with exit {result.returncode}:\n"
            f"  stdout: {result.stdout.strip()[:500]}\n"
            f"  stderr: {result.stderr.strip()[:500]}"
        )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def verify_against_lock(before: set[str], after: set[str], snapshot_root: Path) -> None:
    """Every locked package installed, and nothing installed that is not locked.

    Both directions are checked because they fail differently. A locked package
    that did not install means the snapshot is incomplete and the image is
    missing something. A package that installed and is not locked means
    something reached a source nobody recorded — which is the failure the whole
    offline mode exists to prevent, and it would otherwise be invisible.
    """
    manifest = snapshot_root / "packages.json"
    if not manifest.is_file():
        raise SystemExit(
            f"hermetic build: no package inventory at {manifest}; the snapshot cannot be checked "
            "against what was installed"
        )
    locked = {
        f"{entry['name']}-{entry.get('epoch', '0')}:{entry['version']}-{entry['release']}."
        f"{entry['architecture']}"
        for entry in json.loads(manifest.read_text(encoding="utf-8"))
    }
    newly_installed = after - before

    # Configuring `gpgkey=` makes rpm import the key, and an imported key becomes
    # a `gpg-pubkey` pseudo-package in the database. It is a real new rpmdb entry
    # and the accounting check was right to notice it; it is not a package from
    # any repository, so it cannot be in the snapshot lock.
    #
    # It is allowed by name and then checked, rather than filtered out: the
    # version field of a gpg-pubkey entry is the key's fingerprint, and every
    # package in the snapshot recorded the key id that signed it. So each
    # imported key must be one that actually signed something here. A key that
    # signed nothing has no business being trusted by this image.
    signing_key_ids = {
        str(entry.get("signingKey", "")).lower()
        for entry in json.loads(manifest.read_text(encoding="utf-8"))
        if entry.get("signingKey")
    }
    imported_keys = {name for name in newly_installed if name.startswith("gpg-pubkey-")}
    unexpected_keys = [
        name
        for name in sorted(imported_keys)
        if not any(key_id and key_id in name.lower() for key_id in signing_key_ids)
    ]
    newly_installed = newly_installed - imported_keys

    missing = sorted(locked - after)
    unaccounted = sorted(newly_installed - locked)

    problems: list[str] = []
    if missing:
        problems.append(
            f"{len(missing)} locked packages are not installed: " + ", ".join(missing[:10])
        )
    if unaccounted:
        problems.append(
            f"{len(unaccounted)} installed packages are not in the snapshot lock: "
            + ", ".join(unaccounted[:10])
            + " — something was obtained from a source this build did not record"
        )
    if unexpected_keys:
        problems.append(
            f"{len(unexpected_keys)} GPG keys were imported that signed nothing in this snapshot: "
            + ", ".join(unexpected_keys)
            + " — a key that signed none of the installed packages should not be trusted by "
            "this image"
        )
    if problems:
        raise SystemExit(
            "hermetic build: the installed set does not match the snapshot lock:\n  "
            + "\n  ".join(problems)
        )
    print(
        f"hermetic install: {len(newly_installed)} packages installed, all {len(locked)} locked "
        f"packages accounted for; {len(imported_keys)} signing key(s) imported, each of which "
        "signed packages in this snapshot"
    )


def installed_subset(names: list[str], environment: dict[str, str]) -> set[str]:
    """Return which of ``names`` are currently installed."""
    if not names:
        return set()
    result = subprocess.run(
        ["/usr/bin/rpm", "--query", "--queryformat", "%{NAME}\\n", *names],
        capture_output=True,
        text=True,
        env=environment,
    )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and line.strip() in set(names)
    }


if __name__ == "__main__":
    raise SystemExit(main())
