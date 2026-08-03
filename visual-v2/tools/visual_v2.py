#!/usr/bin/env python3
"""Developer entry point for Bunny Desktop Visual Phase V2.

VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN.
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
BUILD = ROOT / "build" / "visual-v2"
STAGE = BUILD / "stage"
EXTENSION_UUID = "bunny-desktop-v2@bunny-os.org"
NOTICE = "VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN"


def run(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(argv, cwd=ROOT, env=env, check=True)


def setup() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    tools = {
        name: shutil.which(name)
        for name in ("gnome-shell", "gnome-session", "dbus-run-session", "glib-compile-schemas")
    }
    (BUILD / "setup.json").write_text(
        json.dumps({"schemaVersion": 1, "notice": NOTICE, "hostPlatform": sys.platform, "tools": tools}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(NOTICE)
    print(f"Prepared {BUILD}")
    return 0


def validate_json() -> None:
    for path in sorted((ROOT / "visual-v2").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "shell" / "bunny-desktop-v2").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    json.loads((ROOT / "sessions" / "bunny-desktop-preview.json").read_text(encoding="utf-8"))


def copy_file(source: Path, destination: Path, *, executable: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if executable:
        destination.chmod(0o755)


def copy_tree(source: Path, destination: Path, *, exclude: set[str] | None = None) -> None:
    excluded = exclude or set()
    for path in source.rglob("*"):
        if not path.is_file() or path.name in excluded or "__pycache__" in path.parts:
            continue
        copy_file(path, destination / path.relative_to(source))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def stage_package() -> dict[str, object]:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    sessions = {
        "bunny-desktop-preview.desktop": "usr/share/wayland-sessions/bunny-desktop-preview.desktop",
        "bunny-desktop-preview.session": "usr/share/gnome-session/sessions/bunny-desktop-preview.session",
        "bunny-desktop-preview.json": "usr/share/gnome-shell/modes/bunny-desktop-preview.json",
        "bunny-desktop-preview-session": "usr/libexec/bunny-desktop-preview-session",
    }
    for source, destination in sessions.items():
        copy_file(ROOT / "sessions" / source, STAGE / destination, executable=source.endswith("-session"))

    extension = ROOT / "shell/bunny-desktop-v2"
    extension_target = STAGE / "usr/share/gnome-shell/extensions" / EXTENSION_UUID
    copy_tree(extension, extension_target, exclude={"mock-state.json"})
    schema = extension / "schemas/org.bunnyos.desktop.visual-v2.gschema.xml"
    schema_target = STAGE / "usr/share/glib-2.0/schemas/org.bunnyos.desktop.visual-v2.gschema.xml"
    copy_file(schema, schema_target)

    copy_tree(ROOT / "apps/common/bunny_visual_v2", STAGE / "usr/lib/bunny-visual-v2/bunny_visual_v2")
    for app_dir in sorted((ROOT / "apps").glob("bunny-*-v2")):
        executable = app_dir / app_dir.name
        if executable.is_file():
            copy_file(executable, STAGE / "usr/bin" / executable.name, executable=True)
        for desktop in app_dir.glob("*.desktop"):
            copy_file(desktop, STAGE / "usr/share/applications" / desktop.name)

    copy_tree(ROOT / "visual-v2/tokens", STAGE / "usr/share/bunny-visual-v2/tokens")
    copy_tree(ROOT / "visual-v2/assets/character", STAGE / "usr/share/bunny-visual-v2/character")
    copy_tree(ROOT / "visual-v2/assets/logos", STAGE / "usr/share/bunny-visual-v2/logos")
    copy_tree(ROOT / "visual-v2/assets/wallpapers", STAGE / "usr/share/bunny-visual-v2/wallpapers")
    copy_tree(ROOT / "visual-v2/assets/boot", STAGE / "usr/share/bunny-visual-v2/concepts/boot")
    copy_tree(ROOT / "visual-v2/assets/login", STAGE / "usr/share/bunny-visual-v2/concepts/login")
    copy_file(ROOT / "visual-v2/assets/system-concepts.json", STAGE / "usr/share/bunny-visual-v2/concepts/system-concepts.json")
    for wallpaper in (ROOT / "visual-v2/assets/wallpapers").glob("*.svg"):
        copy_file(wallpaper, STAGE / "usr/share/backgrounds/bunny-visual-v2" / wallpaper.name)
    copy_file(ROOT / "visual-v2/assets/LICENSE.md", STAGE / "usr/share/doc/bunny-visual-v2/ASSET-LICENSE.md")
    for document in ("README.md", "VISUAL_SYSTEM.md", "DUAL_MODE_SPEC.md", "CHARACTER_USAGE_POLICY.md", "ACCESSIBILITY_SPEC.md", "PERFORMANCE_SPEC.md", "PROTOTYPE_NOTICE.md"):
        copy_file(ROOT / "visual-v2" / document, STAGE / "usr/share/doc/bunny-visual-v2" / document)
    copy_file(ROOT / "VISUAL_PHASE_V2_REPORT.md", STAGE / "usr/share/doc/bunny-visual-v2/VISUAL_PHASE_V2_REPORT.md")
    copy_file(ROOT / "visual-v2/reports/KNOWN_LIMITATIONS.md", STAGE / "usr/share/doc/bunny-visual-v2/KNOWN_LIMITATIONS.md")
    for document in ("BUNNY_DESKTOP_V2_ARCHITECTURE.md", "BUNNY_DUAL_MODE_STATE_MODEL.md", "BUNNY_VISUAL_SECURITY_BOUNDARY.md", "VISUAL_PHASE_V3_OPTIONS.md"):
        copy_file(ROOT / "docs" / document, STAGE / "usr/share/doc/bunny-visual-v2" / document)

    notice = STAGE / "usr/share/doc/bunny-visual-v2/PROTOTYPE-NOTICE.txt"
    notice.parent.mkdir(parents=True, exist_ok=True)
    notice.write_text("VISUAL PROTOTYPE ONLY\nNOT RELEASE QUALIFIED\nDO NOT MERGE INTO MAIN\n", encoding="utf-8", newline="\n")

    compiler = shutil.which("glib-compile-schemas")
    compiled = False
    if compiler:
        run([compiler, str(schema_target.parent)])
        compiled = True

    files = sorted(path for path in STAGE.rglob("*") if path.is_file())
    mock_paths = [path for path in files if "mock-state" in path.name or "screenshots" in path.parts]
    manifest = {
        "schemaVersion": 2,
        "product": "Bunny Desktop Visual Phase V2",
        "status": ["VISUAL PROTOTYPE ONLY", "NOT RELEASE QUALIFIED", "DO NOT MERGE INTO MAIN"],
        "defaultSessionChanged": False,
        "qualificationTargetsChanged": False,
        "releaseGatesChanged": False,
        "mockFixturePackaged": bool(mock_paths),
        "gsettingsSchemasCompiled": compiled,
        "characterAssetsRedistributionCleared": False,
        "fileCount": len(files),
        "files": [
            {"path": path.relative_to(STAGE).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}
            for path in files
        ],
    }
    if manifest["mockFixturePackaged"]:
        raise RuntimeError("mock fixtures or screenshot artifacts entered the V2 package")
    write_json(BUILD / "build-manifest.json", manifest)
    return manifest


def build() -> int:
    setup()
    started = time.perf_counter()
    validate_json()
    run([sys.executable, str(ROOT / "visual-v2/tools/generate_css.py"), "--check"])
    run([sys.executable, str(ROOT / "visual-v2/tools/generate_gtk_css.py"), "--check"])
    run([sys.executable, str(ROOT / "visual-v2/tools/render_wallpapers.py"), "--check"])
    run([sys.executable, str(ROOT / "visual-v2/tools/render_system_concepts.py"), "--check"])
    run([sys.executable, str(ROOT / "visual-v2/tools/render_screenshots.py"), "--check"])
    for path in sorted((ROOT / "apps").rglob("*.py")):
        if "bunny_visual_v2" in path.parts:
            py_compile.compile(str(path), doraise=True)
    run([sys.executable, str(ROOT / "visual-v2/tools/performance_audit.py"), "--output", str(BUILD / "performance/static-audit.json")])
    manifest = stage_package()
    write_json(BUILD / "performance/build.json", {
        "schemaVersion": 1,
        "notice": NOTICE,
        "deterministicBuildAndStageMilliseconds": round((time.perf_counter() - started) * 1000, 3),
        "liveShellMeasurement": False,
        "idleCpuMeasured": False,
    })
    print(f"Design sources current; staged {manifest['fileCount']} non-release prototype files")
    return 0


def tests() -> int:
    for directory in ("tests/visual_v2", "tests/accessibility_v2", "tests/shell_v2"):
        run([sys.executable, "-m", "unittest", "discover", "-s", directory, "-t", ".", "-v"])
    return 0


def a11y() -> int:
    output = BUILD / "accessibility/audit.json"
    run([sys.executable, str(ROOT / "visual-v2/tools/a11y_audit.py"), "--output", str(output)])
    print(output)
    return 0


def screenshots() -> int:
    environment = dict(os.environ)
    environment["BUNNY_VISUAL_MOCK_MODE"] = "1"
    run([sys.executable, str(ROOT / "visual-v2/tools/render_screenshots.py"), "--check"], env=environment)
    data = json.loads((ROOT / "visual-v2/screenshots/scenarios.json").read_text(encoding="utf-8"))
    records = []
    for scenario in data["scenarios"]:
        path = ROOT / "visual-v2/screenshots/rendered" / f"{scenario['id']}.svg"
        records.append({"id": scenario["id"], "path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()})
    write_json(BUILD / "screenshots-manifest.json", {"schemaVersion": 2, "notice": NOTICE, "functionalEvidence": False, "artifacts": records})
    print("All screenshots are visibly labelled VISUAL MOCK DATA and are review artifacts only")
    return 0


def preview() -> int:
    if not sys.platform.startswith("linux") or not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        print("visual-v2-preview requires a Linux graphical session with GTK 4 and libadwaita", file=sys.stderr)
        return 2
    build()
    environment = dict(os.environ)
    environment.update(
        BUNNY_VISUAL_V2_PREVIEW="1",
        BUNNY_VISUAL_MOCK_MODE="1",
        GSETTINGS_SCHEMA_DIR=str(STAGE / "usr/share/glib-2.0/schemas"),
    )
    return subprocess.call([sys.executable, str(ROOT / "apps/bunny-control-center-v2/bunny-control-center-v2")], cwd=ROOT, env=environment)


def nested_preview() -> int:
    required = {name: shutil.which(name) for name in ("dbus-run-session", "gnome-shell")}
    if not sys.platform.startswith("linux") or not all(required.values()):
        print("visual-v2-preview-nested requires dbus-run-session and gnome-shell on Linux", file=sys.stderr)
        return 2
    build()
    environment = dict(os.environ)
    share = STAGE / "usr/share"
    environment.update(
        BUNNY_VISUAL_V2_PREVIEW="1",
        BUNNY_VISUAL_MOCK_MODE="1",
        XDG_DATA_DIRS=f"{share}:{environment.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share')}",
        GSETTINGS_SCHEMA_DIR=str(STAGE / "usr/share/glib-2.0/schemas"),
    )
    return subprocess.call([required["dbus-run-session"], "--", required["gnome-shell"], "--nested", "--wayland", "--mode=bunny-desktop-preview"], cwd=ROOT, env=environment)


def package() -> int:
    if os.environ.get("BUNNY_VISUAL_MOCK_MODE") == "1":
        print("Refusing to package while BUNNY_VISUAL_MOCK_MODE=1", file=sys.stderr)
        return 2
    build()
    target = BUILD / "bunny-desktop-visual-v2-prototype.tar.gz"
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
    print(f"Created non-release prototype package {target}")
    return 0


def clean() -> int:
    resolved = BUILD.resolve()
    expected = (ROOT / "build" / "visual-v2").resolve()
    if resolved != expected:
        raise RuntimeError("refusing to clean an unexpected path")
    if resolved.exists():
        shutil.rmtree(resolved)
    print(f"Removed {resolved}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "build", "preview", "preview-nested", "test", "a11y", "screenshots", "package", "clean"))
    command = parser.parse_args().command
    if command == "setup":
        return setup()
    if command == "build":
        return build()
    if command == "test":
        return tests()
    if command == "a11y":
        return a11y()
    if command == "screenshots":
        return screenshots()
    if command == "preview":
        return preview()
    if command == "preview-nested":
        return nested_preview()
    if command == "package":
        return package()
    if command == "clean":
        return clean()
    raise AssertionError(f"unhandled command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
