#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Validate the GNOME extension, its schemas, and the desktop entries.
#
# Session entries and application launchers are different file kinds and were
# being validated with one tool that understands one of them:
#
#     /src/shell/session/bunny.desktop: error: file contains key "DesktopNames"
#     in group "Desktop Entry", but keys extending the format should start with "X-"
#
# `DesktopNames` is required in a GNOME session entry and is defined by the
# GNOME session specification. `desktop-file-validate` implements the
# freedesktop Desktop Entry Specification, where the key is unknown. Removing the
# key would break session selection; renaming it to `X-DesktopNames` would break
# it silently, which is worse.
#
# So the launchers go to desktop-file-validate, and the session entries are
# checked against the rules that actually apply to them.

set -euo pipefail

SRC="${1:-/src}"

cp -a "${SRC}/shell/components/gnome-shell-extension" /tmp/bunny-shell@bunny-os.org
glib-compile-schemas --strict /tmp/bunny-shell@bunny-os.org/schemas

# Application launchers: the freedesktop specification applies in full.
desktop-file-validate \
    "${SRC}"/shell/components/applications/*.desktop \
    "${SRC}"/installer/frontend/*.desktop \
    "${SRC}"/installer/first_run/*.desktop \
    "${SRC}"/desktop-integration/*.desktop
echo "application launchers validated against the Desktop Entry Specification"

# Session entries: GNOME session rules. DesktopNames is required, and
# desktop-file-validate is deliberately not run over these.
python3 - "${SRC}" <<'PY'
import configparser
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
failures = []
entries = sorted((root / "shell/session").glob("*.desktop"))
if not entries:
    raise SystemExit("no session entries found; the session directory is required")

for path in entries:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    name = path.name
    if not parser.has_section("Desktop Entry"):
        failures.append(f"{name}: no [Desktop Entry] section")
        continue
    entry = parser["Desktop Entry"]
    if entry.get("Type") != "Application":
        failures.append(f"{name}: Type is {entry.get('Type')!r}, expected Application")
    for key in ("Name", "Exec", "DesktopNames"):
        if not entry.get(key):
            failures.append(f"{name}: missing {key}")
    names = entry.get("DesktopNames", "")
    if names and not names.rstrip(";").split(";")[0]:
        failures.append(f"{name}: DesktopNames is empty")

if failures:
    raise SystemExit("session entry validation failed:\n  " + "\n  ".join(failures))
print(f"{len(entries)} session entries validated against the GNOME session rules")
PY

gnome-extensions pack --force --out-dir=/tmp /tmp/bunny-shell@bunny-os.org
echo "extension packed"
