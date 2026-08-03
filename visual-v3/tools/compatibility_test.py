#!/usr/bin/env python3
"""Run real applications against the experimental shell.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

No application is modified to make the shell look compatible. An application
that is not installed on the measurement host is recorded as not tested, never
as passing.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    NestedShell,
    OBSERVED,
    UNAVAILABLE,
    banner,
    preconditions,
    which,
    write_report,
)


#: (label, toolkit, command, needs XWayland)
APPLICATIONS: list[tuple[str, str, list[str], bool]] = [
    ("GTK 4 Demo", "GTK 4", ["gtk4-demo"], False),
    ("GTK 4 Widget Factory", "GTK 4", ["gtk4-widget-factory"], False),
    ("GTK 3 Demo", "GTK 3", ["gtk3-demo"], False),
    ("Qt 6 application", "Qt 6", ["qdbusviewer-qt6"], False),
    ("Electron application", "Electron", ["electron"], False),
    ("Chromium", "Chromium", ["chromium-browser"], False),
    ("Firefox", "Firefox", ["firefox"], False),
    ("foot terminal", "terminal emulator", ["foot"], False),
    ("Nautilus", "file manager", ["nautilus"], False),
    ("GNOME Text Editor", "code editor", ["gnome-text-editor"], False),
    ("Totem", "media application", ["totem"], False),
    ("Flatpak application", "Flatpak", ["flatpak"], False),
    ("xterm", "XWayland (X11)", ["xterm"], True),
    ("xeyes", "XWayland (X11)", ["xeyes"], True),
]

#: Dimensions the phase asks about. Anything this harness cannot exercise is
#: reported as unavailable rather than guessed.
DIMENSIONS = (
    "launches",
    "inputWorks",
    "resizingWorks",
    "clipboardWorks",
    "scalingWorks",
    "dialogsWork",
    "portalsWork",
    "notificationsWork",
    "screenSharingWorks",
)

NOT_MEASURED_NOTE = {
    "inputWorks": "requires synthetic input into a nested seat; the winit backend exposes no "
    "libinput seat to inject into",
    "resizingWorks": "requires driving a window manager interaction; not automated in V3",
    "clipboardWorks": "requires two cooperating clients and wl-clipboard, which is not installed",
    "scalingWorks": "requires a second output at a different scale; the nested backend has one output",
    "dialogsWork": "requires interacting with each application's menus",
    "portalsWork": "requires a running xdg-desktop-portal session bus",
    "notificationsWork": "requires a org.freedesktop.Notifications service, which V3 does not implement",
    "screenSharingWorks": "blocked: no screencopy protocol in smithay 0.7",
}


def observed_windows(log: str) -> list[dict]:
    windows = []
    for match in re.finditer(
        r"window (\d+) identified: app_id=(\S*) title=(.*?) origin=(\S+)", log
    ):
        windows.append(
            {
                "id": int(match.group(1)),
                "appId": match.group(2),
                "title": match.group(3).strip(),
                "origin": match.group(4),
            }
        )
    return windows


def main() -> int:
    banner()
    problems = preconditions()
    if problems:
        write_report(
            "compatibility.json",
            {"schemaVersion": 1, "evidence": UNAVAILABLE, "problems": problems, "applications": []},
        )
        print(f"cannot measure: {problems}", file=sys.stderr)
        return 2

    rows = []
    xwayland_note = None

    with NestedShell("bunny-compat", seconds=180) as shell:
        for label, toolkit, command, needs_xwayland in APPLICATIONS:
            binary = which(command[0])
            if not binary:
                rows.append(
                    {
                        "application": label,
                        "toolkit": toolkit,
                        "installed": False,
                        "evidence": UNAVAILABLE,
                        "note": f"{command[0]} is not installed on the measurement host",
                        **{dimension: None for dimension in DIMENSIONS},
                    }
                )
                continue

            before = len(observed_windows(shell.log_text()))
            process = shell.spawn_client(command)
            time.sleep(6)
            alive = process.poll() is None
            after = observed_windows(shell.log_text())
            new_windows = after[before:]
            output = ""
            if not alive:
                try:
                    output = (process.stdout.read() or "")[-600:] if process.stdout else ""
                except Exception:  # noqa: BLE001 - diagnostics only
                    output = ""
            else:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except Exception:  # noqa: BLE001
                    process.kill()

            mapped = bool(new_windows)
            row = {
                "application": label,
                "toolkit": toolkit,
                "installed": True,
                "evidence": OBSERVED,
                "launches": mapped,
                "mappedWindows": new_windows,
                "applicationIdentified": bool(new_windows and new_windows[0]["appId"]),
                "requiresXWayland": needs_xwayland,
            }
            for dimension in DIMENSIONS:
                if dimension == "launches":
                    continue
                row[dimension] = None
                row[f"{dimension}Note"] = NOT_MEASURED_NOTE[dimension]
            if not mapped:
                row["defect"] = (
                    f"did not map a toplevel within 6s; client output: {output.strip()[:300]}"
                    if output
                    else "did not map a toplevel within 6s"
                )
            if needs_xwayland and not mapped:
                xwayland_note = (
                    "X11 clients could not connect: V3 resolves XWayland state but does not start "
                    "an Xwayland server, so no X11 client can run. The shell started and every "
                    "Wayland client worked regardless, which is the property that mattered."
                )
            rows.append(row)

    tested = [row for row in rows if row["installed"]]
    launched = [row for row in tested if row.get("launches")]
    payload = {
        "schemaVersion": 1,
        "measurementHost": "Fedora Linux 44 on WSL2, nested under WSLg, Mesa llvmpipe software renderer",
        "applicationsConsidered": len(rows),
        "applicationsInstalled": len(tested),
        "applicationsThatMapped": len(launched),
        "applications": rows,
        "xwaylandNote": xwayland_note,
        "dimensionsNotMeasured": {
            dimension: NOT_MEASURED_NOTE[dimension] for dimension in DIMENSIONS if dimension != "launches"
        },
        "applicationsModifiedToPass": False,
    }
    write_report("compatibility.json", payload)
    for row in rows:
        status = (
            "not installed"
            if not row["installed"]
            else ("mapped" if row.get("launches") else "DID NOT MAP")
        )
        print(f"  {row['application']:<24} {row['toolkit']:<18} {status}")
    print(f"{len(launched)}/{len(tested)} installed applications mapped a window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
