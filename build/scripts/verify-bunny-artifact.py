#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed verification for an upstream Bunny release directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re


FIELDS = {"schemaVersion", "status", "bunnyVersion", "protocolVersion", "contractRange", "architecture", "runtimeMode", "files", "sourceCommit"}


def fail(message: str) -> None:
    raise SystemExit(f"Bunny artifact rejected: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("payload", type=Path)
    args = parser.parse_args()
    value = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != FIELDS:
        fail("manifest fields do not match schema 1")
    if value["schemaVersion"] != 1 or value["protocolVersion"] != 3 or value["contractRange"] != ">=1.0.0 <2.0.0":
        fail("protocol or contract is incompatible")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["bunnyVersion"]) or not re.fullmatch(r"[a-f0-9]{40}", value["sourceCommit"]):
        fail("version or source commit is invalid")
    if value["status"] == "placeholder":
        if value["runtimeMode"] != "placeholder" or value["files"] != []:
            fail("placeholder must contain no runtime files")
        print("Verified explicit non-functional Bunny placeholder")
        return 0
    if value["status"] != "verified" or value["runtimeMode"] != "tauri-supervised":
        fail("unknown artifact status or runtime mode")
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    if value["architecture"] != machine:
        fail("artifact architecture does not match build architecture")
    if not isinstance(value["files"], list) or not value["files"]:
        fail("verified release has no files")
    root = args.payload.resolve(strict=True)
    declared: set[str] = set()
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "mode"}:
            fail("invalid file record")
        relative = item["path"]
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts or relative in declared:
            fail("unsafe or duplicate artifact path")
        declared.add(relative)
        candidate = root / relative
        if candidate.is_symlink():
            fail("artifact file may not be a symlink")
        path = candidate.resolve(strict=True)
        if root not in path.parents or not path.is_file():
            fail("artifact file escapes payload or is not regular")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            fail(f"digest mismatch: {relative}")
        actual_mode = f"{os.stat(path).st_mode & 0o7777:04o}"
        if actual_mode != item["mode"]:
            fail(f"mode mismatch: {relative}")
    actual = {str(path.relative_to(root)).replace(os.sep, "/") for path in root.rglob("*") if path.is_file() and path.name != ".gitkeep"}
    if actual != declared:
        fail("payload contains undeclared or missing files")
    required = {"bunny-desktop", "bunny-core", "ccgrep"}
    if not required.issubset({Path(path).name for path in declared}):
        fail("Tauri-supervised release is missing required runtime binaries")
    print(f'Verified Bunny {value["bunnyVersion"]} release with {len(declared)} files')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
