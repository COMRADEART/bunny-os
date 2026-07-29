#!/usr/bin/python3
"""Verify exact release build tool versions declared by release engineering."""

import argparse
import json
import re
import subprocess


def output(argv: list[str]) -> str:
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-builder", required=True)
    parser.add_argument("--podman", required=True)
    args = parser.parse_args()
    image_builder = json.loads(output(["image-builder", "version", "--format=json"]))
    value = image_builder.get("image-builder", image_builder)
    actual_builder = str(value.get("version", "")) if isinstance(value, dict) else ""
    match = re.search(r"podman version ([0-9][0-9A-Za-z.+-]*)", output(["podman", "--version"]), re.IGNORECASE)
    actual_podman = match.group(1) if match else ""
    if actual_builder != args.image_builder or actual_podman != args.podman:
        raise SystemExit(f"toolchain mismatch: image-builder={actual_builder!r}, podman={actual_podman!r}")
    print(f"verified release toolchain image-builder={actual_builder} podman={actual_podman}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

