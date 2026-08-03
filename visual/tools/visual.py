#!/usr/bin/python3
"""Build, preview, test, render, and package Bunny Desktop Visual Phase V1."""

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
BUILD = ROOT / "build" / "visual"
STAGE = BUILD / "stage"
EXTENSION_UUID = "bunny-desktop-v1@bunny-os.org"


def run(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(argv, cwd=ROOT, env=env, check=True)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def setup() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    tools = {
        name: shutil.which(name)
        for name in ("make", "gnome-shell", "gnome-session", "dbus-run-session", "glib-compile-schemas", "wf-recorder")
    }
    write_json(BUILD / "setup.json", {
        "schemaVersion": 1,
        "hostPlatform": sys.platform,
        "tools": {name: {"available": bool(path), "path": path} for name, path in tools.items()},
        "note": "Missing graphical tools limit nested/runtime review but do not block deterministic source checks.",
    })
    print(f"Visual workspace prepared at {BUILD}")
    for name, path in tools.items():
        print(f"  {name}: {path or 'unavailable'}")
    return 0


def validate_json() -> None:
    targets = [
        *ROOT.glob("visual/tokens/*.json"), *ROOT.glob("visual/assets/**/*.json"),
        *ROOT.glob("visual/screenshots/*.json"), *ROOT.glob("visual/demo/*.json"),
        ROOT / "sessions/bunny-visual-preview.json", ROOT / "shell/bunny-shell-extension/metadata.json",
        ROOT / "shell/bunny-shell-extension/mock-state.json",
    ]
    for path in targets:
        json.loads(path.read_text(encoding="utf-8"))


def copy_file(source: Path, destination: Path, *, executable: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if executable:
        destination.chmod(0o755)


def copy_tree(source: Path, destination: Path, *, exclude: set[str] | None = None) -> None:
    excluded = exclude or set()
    for path in source.rglob("*"):
        if not path.is_file() or any(part in {"__pycache__"} for part in path.parts) or path.name in excluded:
            continue
        copy_file(path, destination / path.relative_to(source))


def stage_package() -> dict[str, object]:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    session_mapping = {
        "bunny-visual-preview.desktop": "usr/share/wayland-sessions/bunny-visual-preview.desktop",
        "bunny-visual-preview.session": "usr/share/gnome-session/sessions/bunny-visual-preview.session",
        "bunny-visual-preview.json": "usr/share/gnome-shell/modes/bunny-visual-preview.json",
        "bunny-visual-preview-session": "usr/libexec/bunny-visual-preview-session",
    }
    for source, destination in session_mapping.items():
        copy_file(ROOT / "sessions" / source, STAGE / destination, executable=source == "bunny-visual-preview-session")

    extension_target = STAGE / "usr/share/gnome-shell/extensions" / EXTENSION_UUID
    copy_tree(ROOT / "shell/bunny-shell-extension", extension_target, exclude={"mock-state.json"})
    schema_source = ROOT / "shell/bunny-shell-extension/schemas/org.bunnyos.desktop.visual-v1.gschema.xml"
    copy_file(schema_source, STAGE / "usr/share/glib-2.0/schemas/org.bunnyos.desktop.visual-v1.gschema.xml")

    copy_tree(ROOT / "apps/common/bunny_visual", STAGE / "usr/lib/bunny-visual-v1/bunny_visual")
    for app_dir in sorted((ROOT / "apps").glob("bunny-*")):
        if not app_dir.is_dir():
            continue
        executable = app_dir / app_dir.name
        if executable.is_file():
            copy_file(executable, STAGE / "usr/bin" / executable.name, executable=True)
        for desktop in app_dir.glob("*.desktop"):
            copy_file(desktop, STAGE / "usr/share/applications" / desktop.name)

    for path in (BUILD / "icons/symbolic").glob("*.svg"):
        copy_file(path, STAGE / "usr/share/icons/hicolor/scalable/status" / path.name)
    for path in (BUILD / "icons/apps").glob("*.svg"):
        copy_file(path, STAGE / "usr/share/icons/hicolor/scalable/apps" / path.name)
    for path in (BUILD / "wallpapers").glob("*.svg"):
        copy_file(path, STAGE / "usr/share/backgrounds/bunny-visual-v1" / path.name)

    copy_tree(ROOT / "visual/assets/logo", STAGE / "usr/share/bunny-visual-v1/logo")
    copy_tree(ROOT / "visual/assets/illustrations", STAGE / "usr/share/bunny-visual-v1/illustrations")
    copy_tree(ROOT / "visual/assets/login", STAGE / "usr/share/bunny-visual-v1/login-concept")
    copy_tree(ROOT / "visual/assets/sounds", STAGE / "usr/share/bunny-visual-v1/sound-specification")
    copy_tree(ROOT / "visual/assets/boot", STAGE / "usr/share/bunny-visual-v1/boot-concept")
    for path in (ROOT / "visual/assets/boot").glob("bunny-visual-preview.*"):
        copy_file(path, STAGE / "usr/share/plymouth/themes/bunny-visual-preview" / path.name)
    copy_file(ROOT / "visual/assets/boot/bunny-plymouth.svg", STAGE / "usr/share/plymouth/themes/bunny-visual-preview/bunny-plymouth.svg")

    doc = STAGE / "usr/share/doc/bunny-visual-v1/PROTOTYPE-NOTICE.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "VISUAL PROTOTYPE ONLY\nNOT RELEASE QUALIFIED\nDO NOT MERGE OR SET AS THE DEFAULT SESSION\n",
        encoding="utf-8", newline="\n",
    )

    compiler = shutil.which("glib-compile-schemas")
    compiled = False
    if compiler:
        run([compiler, str(extension_target / "schemas")])
        compiled = True

    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    manifest = {
        "schemaVersion": 1,
        "product": "Bunny Desktop Visual Phase V1",
        "status": "VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE",
        "defaultSessionChanged": False,
        "mockFixturePackaged": False,
        "gsettingsSchemasCompiled": compiled,
        "fileCount": len(files),
        "files": [
            {"path": str(path.relative_to(STAGE)).replace('\\', '/'), "sha256": sha256(path.read_bytes()).hexdigest()}
            for path in files
        ],
    }
    write_json(BUILD / "build-manifest.json", manifest)
    return manifest


def build() -> int:
    setup()
    validate_json()
    run([sys.executable, str(ROOT / "visual/tools/generate_css.py"), "--check"])
    started = time.perf_counter()
    run([sys.executable, str(ROOT / "visual/tools/render_assets.py"), "all"])
    for path in (ROOT / "apps").rglob("*.py"):
        py_compile.compile(str(path), doraise=True)
    manifest = stage_package()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    write_json(BUILD / "performance.json", {
        "schemaVersion": 1,
        "measurementScope": "deterministic asset generation and package staging; not live GNOME UI latency",
        "assetAndStageMilliseconds": elapsed_ms,
        "renderedWallpapers": len(list((BUILD / "wallpapers").glob("*.svg"))),
        "renderedScreenshots": len(list((BUILD / "screenshots").glob("*.svg"))),
        "continuousPollingLoopsFound": False,
        "networkRequestsFromVisualLayer": 0,
        "liveShellMeasurementsAvailable": False,
    })
    print(f"Staged {manifest['fileCount']} files in {elapsed_ms} ms")
    return 0


def tests() -> int:
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests/visual", "-t", ".", "-v"])
    run([sys.executable, "-m", "unittest", "tests.accessibility.test_visual_v1_accessibility", "-v"])
    return 0


def a11y() -> int:
    output = BUILD / "accessibility/audit.json"
    run([sys.executable, str(ROOT / "visual/tools/a11y_audit.py"), "--output", str(output)])
    print(output)
    return 0


def screenshots() -> int:
    environment = dict(os.environ)
    environment["BUNNY_VISUAL_MOCK_MODE"] = "1"
    run([sys.executable, str(ROOT / "visual/tools/render_assets.py"), "screenshots"], env=environment)
    print("All renders are visibly marked VISUAL MOCK DATA and are review artifacts only.")
    return 0


def preview() -> int:
    if not sys.platform.startswith("linux") or not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        print("visual-preview requires a Linux graphical session with GTK 4 and libadwaita", file=sys.stderr)
        return 2
    environment = dict(os.environ)
    environment.update(BUNNY_VISUAL_PREVIEW="1", BUNNY_VISUAL_MOCK_MODE="1")
    executable = ROOT / "apps/bunny-command-center/bunny-command-center"
    return subprocess.call([sys.executable, str(executable)], cwd=ROOT, env=environment)


def nested_preview() -> int:
    required = {name: shutil.which(name) for name in ("dbus-run-session", "gnome-shell")}
    if not all(required.values()):
        print("visual-preview-nested requires dbus-run-session and gnome-shell on Linux", file=sys.stderr)
        return 2
    build()
    environment = dict(os.environ)
    share = STAGE / "usr/share"
    environment.update(
        BUNNY_VISUAL_PREVIEW="1",
        BUNNY_VISUAL_MOCK_MODE="1",
        XDG_DATA_DIRS=f"{share}:{environment.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share')}",
        GSETTINGS_SCHEMA_DIR=str(STAGE / "usr/share/gnome-shell/extensions" / EXTENSION_UUID / "schemas"),
    )
    command = [required["dbus-run-session"], "--", required["gnome-shell"], "--nested", "--wayland", "--mode=bunny-visual-preview"]
    return subprocess.call(command, cwd=ROOT, env=environment)


def package() -> int:
    if os.environ.get("BUNNY_VISUAL_MOCK_MODE") == "1":
        print("Refusing to package while BUNNY_VISUAL_MOCK_MODE=1", file=sys.stderr)
        return 2
    build()
    target = BUILD / "bunny-desktop-visual-v1-prototype.tar.gz"
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(STAGE.rglob("*")):
                    if not path.is_file():
                        continue
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(STAGE)).replace('\\', '/'))
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime = 0
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
    print(f"Created non-release prototype package {target}")
    return 0


def clean() -> int:
    resolved = BUILD.resolve()
    expected_parent = (ROOT / "build").resolve()
    if resolved.parent != expected_parent or resolved.name != "visual":
        raise RuntimeError("refusing to clean an unexpected path")
    if resolved.exists():
        shutil.rmtree(resolved)
    print(f"Removed generated visual outputs from {resolved}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "preview", "preview-nested", "build", "test", "a11y", "screenshot", "package", "clean"))
    command = parser.parse_args().command
    return {
        "setup": setup, "preview": preview, "preview-nested": nested_preview,
        "build": build, "test": tests, "a11y": a11y, "screenshot": screenshots,
        "package": package, "clean": clean,
    }[command]()


if __name__ == "__main__":
    raise SystemExit(main())
