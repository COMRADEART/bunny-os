#!/usr/bin/env python3
"""Developer entry point for Bunny OS Visual Phase V3.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.
"""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "visual-v3"
STAGE = BUILD / "stage"
CRATE = ROOT / "compositor" / "bunny-shell"
NOTICE_LINES = (
    "BUNNY WAYLAND SHELL EXPERIMENT",
    "NOT RELEASE QUALIFIED",
    "DO NOT USE AS THE DEFAULT SESSION",
)
NOTICE = " — ".join(NOTICE_LINES)


def banner() -> None:
    for line in NOTICE_LINES:
        print(line)


def run(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True) -> int:
    completed = subprocess.run(argv, cwd=cwd or ROOT, env=env, check=False)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def tool_table() -> dict[str, str | None]:
    names = (
        "cargo",
        "rustc",
        "pkg-config",
        "wayland-info",
        "Xwayland",
        "dbus-run-session",
        "gtk4-demo",
        "gtk4-widget-factory",
        "foot",
        "weston",
        "pipewire",
        "xdg-desktop-portal",
        "qemu-system-x86_64",
    )
    return {name: shutil.which(name) for name in names}


def library_table() -> dict[str, str | None]:
    libraries = (
        "wayland-server",
        "wayland-client",
        "xkbcommon",
        "libinput",
        "libudev",
        "libseat",
        "gbm",
        "egl",
        "glesv2",
        "pixman-1",
        "libdrm",
        "gtk4",
        "gtk4-layer-shell-0",
    )
    found: dict[str, str | None] = {}
    for library in libraries:
        try:
            completed = subprocess.run(
                ["pkg-config", "--modversion", library],
                capture_output=True,
                text=True,
                check=False,
            )
            found[library] = completed.stdout.strip() or None
        except FileNotFoundError:
            found[library] = None
    return found


def setup() -> int:
    banner()
    BUILD.mkdir(parents=True, exist_ok=True)
    record = {
        "schemaVersion": 1,
        "notice": list(NOTICE_LINES),
        "hostPlatform": sys.platform,
        "tools": tool_table(),
        "libraries": library_table() if sys.platform.startswith("linux") else {},
    }
    write_json(BUILD / "setup.json", record)
    missing = [name for name, path in record["tools"].items() if path is None]
    print(f"Prepared {BUILD}")
    if missing:
        print(f"Not present on this host: {', '.join(missing)}")
    return 0


def linux_only(command: str) -> int | None:
    if sys.platform.startswith("linux"):
        return None
    print(f"{command} requires Linux with a Wayland development stack", file=sys.stderr)
    return 2


def validate_sources() -> None:
    for path in sorted((ROOT / "visual-v3").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "shell-ui").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "apps/common/bunny_shell_v3").rglob("*.py")):
        py_compile.compile(str(path), doraise=True)
    for path in sorted((ROOT / "shell-ui").rglob("*.py")):
        py_compile.compile(str(path), doraise=True)


def build() -> int:
    banner()
    setup()
    started = time.perf_counter()
    validate_sources()
    if (guard := linux_only("bunny-shell-build")) is not None:
        print("Source validation passed; the compositor itself builds on Linux only.")
        return guard
    run(["cargo", "build", "--release"], cwd=CRATE)
    elapsed = (time.perf_counter() - started) * 1000
    write_json(
        BUILD / "build.json",
        {
            "schemaVersion": 1,
            "notice": list(NOTICE_LINES),
            "buildMilliseconds": round(elapsed, 3),
            "binary": str(CRATE / "target/release/bunny-shell"),
        },
    )
    print(f"Built the experimental compositor in {elapsed:.0f} ms")
    return 0


def tests() -> int:
    banner()
    failures = 0
    for directory in ("tests/compositor_v3", "tests/shell_ui_v3", "tests/security_v3", "tests/accessibility_v3"):
        if (ROOT / directory).is_dir():
            failures |= run(
                [sys.executable, "-m", "unittest", "discover", "-s", directory, "-t", ".", "-v"],
                check=False,
            )
    if sys.platform.startswith("linux") and shutil.which("cargo"):
        failures |= run(["cargo", "test", "--release"], cwd=CRATE, check=False)
    return 1 if failures else 0


def harness(name: str, extra: list[str] | None = None) -> int:
    """Run one of the measurement harnesses under visual-v3/tools/."""

    banner()
    script = ROOT / "visual-v3" / "tools" / name
    if not script.is_file():
        print(f"missing harness {script}", file=sys.stderr)
        return 2
    return run([sys.executable, str(script), *(extra or [])], check=False)


def run_nested(extra: list[str]) -> int:
    banner()
    if (guard := linux_only("bunny-shell-run-nested")) is not None:
        return guard
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        print("bunny-shell-run-nested needs an existing graphical session to nest inside", file=sys.stderr)
        return 2
    binary = CRATE / "target/release/bunny-shell"
    if not binary.is_file():
        print("run `make bunny-shell-build` first", file=sys.stderr)
        return 2
    environment = dict(os.environ)
    # A nested developer run must not replace the developer's session, so the
    # host display stays untouched and the shell opens inside a window.
    environment["BUNNY_SHELL_EXPERIMENTAL"] = "1"
    environment["BUNNY_SHELL_NESTED"] = "1"
    return run([str(binary), *extra], env=environment, check=False)


def run_vm(extra: list[str]) -> int:
    banner()
    if not shutil.which("qemu-system-x86_64"):
        print(
            "bunny-shell-run-vm needs qemu-system-x86_64 and a disposable overlay disk; "
            "no VM was started and nothing was measured",
            file=sys.stderr,
        )
        return 2
    script = ROOT / "visual-v3/tools/run_vm.sh"
    if not script.is_file():
        print(f"missing {script}", file=sys.stderr)
        return 2
    return run(["/bin/sh", str(script), *extra], check=False)


def stage_package() -> dict[str, object]:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    def copy_file(source: Path, destination: Path, *, executable: bool = False) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(0o755 if executable else 0o644)

    def copy_tree(source: Path, destination: Path) -> None:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            copy_file(path, destination / path.relative_to(source))

    sessions = {
        "bunny-shell-experimental.desktop": "usr/share/wayland-sessions/bunny-shell-experimental.desktop",
        "bunny-shell-experimental.session": "usr/share/bunny-shell-v3/bunny-shell-experimental.session",
        "bunny-shell-experimental.target": "usr/lib/systemd/user/bunny-shell-experimental.target",
        "bunny-shell-session.service": "usr/lib/systemd/user/bunny-shell-session.service",
        "bunny-shell-recovery.service": "usr/lib/systemd/user/bunny-shell-recovery.service",
    }
    for source, destination in sessions.items():
        copy_file(ROOT / "sessions" / source, STAGE / destination)
    for source, destination in {
        "bunny-shell-experimental-session": "usr/libexec/bunny-shell-experimental-session",
        "bunny-shell-supervisor": "usr/libexec/bunny-shell-supervisor",
    }.items():
        copy_file(ROOT / "sessions" / source, STAGE / destination, executable=True)

    copy_tree(ROOT / "apps/common/bunny_shell_v3", STAGE / "usr/lib/bunny-shell-v3/bunny_shell_v3")
    for component in sorted((ROOT / "shell-ui").iterdir()):
        if not component.is_dir() or component.name == "common":
            continue
        executable = component / f"bunny-{component.name}"
        if executable.is_file():
            copy_file(executable, STAGE / "usr/libexec" / executable.name, executable=True)
        for manifest in component.glob("*.json"):
            copy_file(manifest, STAGE / "usr/share/bunny-shell-v3/components" / component.name / manifest.name)

    binary = CRATE / "target/release/bunny-shell"
    compositor_packaged = binary.is_file()
    if compositor_packaged:
        copy_file(binary, STAGE / "usr/bin/bunny-shell", executable=True)

    for document in (
        "README.md",
        "PROTOTYPE_NOTICE.md",
        "ARCHITECTURE.md",
        "FRAMEWORK_DECISION.md",
        "PROTOCOL_SUPPORT.md",
        "SECURITY_MODEL.md",
        "ACCESSIBILITY_MODEL.md",
        "PERFORMANCE_MODEL.md",
        "COMPATIBILITY_MATRIX.md",
        "KNOWN_LIMITATIONS.md",
    ):
        source = ROOT / "visual-v3" / document
        if source.is_file():
            copy_file(source, STAGE / "usr/share/doc/bunny-shell-v3" / document)

    notice = STAGE / "usr/share/doc/bunny-shell-v3/PROTOTYPE-NOTICE.txt"
    notice.parent.mkdir(parents=True, exist_ok=True)
    notice.write_text("\n".join(NOTICE_LINES) + "\n", encoding="utf-8", newline="\n")

    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    forbidden = [
        path.relative_to(STAGE).as_posix()
        for path in files
        if "mock" in path.name.lower() or "fixture" in path.name.lower()
    ]
    if forbidden:
        raise RuntimeError(f"mock fixtures entered the V3 package: {forbidden}")

    # A packaged session that is a default session, or that replaces a GNOME
    # session file, is the failure this phase most needs to prevent.
    for path in files:
        relative = path.relative_to(STAGE).as_posix()
        if relative.startswith("usr/share/wayland-sessions/") and "bunny-shell-experimental" not in relative:
            raise RuntimeError(f"the V3 package must not ship another session file: {relative}")
    desktop = (STAGE / "usr/share/wayland-sessions/bunny-shell-experimental.desktop").read_text(encoding="utf-8")
    if "X-Bunny-Default-Session=false" not in desktop:
        raise RuntimeError("the experimental session entry must declare it is not the default session")

    manifest = {
        "schemaVersion": 1,
        "product": "Bunny OS Visual Phase V3 — experimental Wayland shell",
        "status": list(NOTICE_LINES),
        "defaultSessionChanged": False,
        "gnomeSessionRemoved": False,
        "qualificationTargetsChanged": False,
        "releaseGatesChanged": False,
        "qualifiedImageChanged": False,
        "compositorBinaryPackaged": compositor_packaged,
        "mockFixturePackaged": False,
        "fileCount": len(files),
        "files": [
            {"path": path.relative_to(STAGE).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}
            for path in files
        ],
    }
    write_json(BUILD / "build-manifest.json", manifest)
    return manifest


def package() -> int:
    banner()
    if os.environ.get("BUNNY_SHELL_MOCK_MODE") == "1":
        print("Refusing to package while BUNNY_SHELL_MOCK_MODE=1", file=sys.stderr)
        return 2
    validate_sources()
    manifest = stage_package()
    target = BUILD / "bunny-shell-v3-experimental.tar.gz"
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(STAGE.rglob("*")):
                    if not path.is_file():
                        continue
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(STAGE).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime = 0
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
    print(f"Created non-release experimental package {target} ({manifest['fileCount']} files)")
    return 0


def clean() -> int:
    banner()
    resolved = BUILD.resolve()
    if resolved != (ROOT / "build" / "visual-v3").resolve():
        raise RuntimeError("refusing to clean an unexpected path")
    if resolved.exists():
        shutil.rmtree(resolved)
    target = CRATE / "target"
    if target.is_dir():
        shutil.rmtree(target)
    print(f"Removed {resolved} and the cargo target directory")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "setup",
            "build",
            "run-nested",
            "run-vm",
            "test",
            "protocol-test",
            "a11y-test",
            "security-test",
            "performance-test",
            "compatibility-test",
            "package",
            "clean",
        ),
    )
    parser.add_argument("extra", nargs="*")
    arguments = parser.parse_args()
    command = arguments.command

    if command == "setup":
        return setup()
    if command == "build":
        return build()
    if command == "test":
        return tests()
    if command == "run-nested":
        return run_nested(arguments.extra)
    if command == "run-vm":
        return run_vm(arguments.extra)
    if command == "protocol-test":
        return harness("protocol_test.py", arguments.extra)
    if command == "a11y-test":
        return harness("a11y_test.py", arguments.extra)
    if command == "security-test":
        return harness("security_test.py", arguments.extra)
    if command == "performance-test":
        return harness("performance_test.py", arguments.extra)
    if command == "compatibility-test":
        return harness("compatibility_test.py", arguments.extra)
    if command == "package":
        return package()
    if command == "clean":
        return clean()
    raise AssertionError(f"unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
