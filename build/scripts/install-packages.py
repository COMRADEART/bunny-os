#!/usr/bin/python3
"""Install an explicit package-set union without inheriting host packages."""

from __future__ import annotations

import argparse
import configparser
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlparse


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
    if args.release_build == "1":
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
    subprocess.run(
        ["/usr/bin/dnf", "--assumeyes", "--setopt=install_weak_deps=False", *repository_args, "install", *packages],
        check=True,
        env={"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
