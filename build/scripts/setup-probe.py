#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-side probe of the Bunny setup surface.

The story harness draws the setup screens in a browser and cannot prove that GTK
lays them out the same way or that the accessibility tree contains anything. This
runs the real application, on a real display, and asks the questions a story
cannot:

* does every screen build under GTK at all;
* does every control have an accessible name in the tree GTK actually publishes;
* does the announcement reach the widget as a description;
* does a text-size change re-render the stylesheet rather than being recorded
  and ignored;
* does the destructive button stay insensitive until the exact phrase is typed.

It is not a VM run and does not claim to be. §52's ladder puts this at HOST
RUNTIME VALIDATED: it proves the surface works on a machine with GTK, and says
nothing about whether the installer ISO boots into it.

    python3 build/scripts/setup-probe.py                 --> JSON on stdout
    python3 build/scripts/setup-probe.py --screenshot D  --> also writes PNGs

The screenshot path needs a compositor. On the Fedora WSL host that is WSLg,
which is the same display the Companion work used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.frontend.setup import SetupApplication, _ScreenView, _gtk  # noqa: E402
from installer.setup_state import Choices                                 # noqa: E402
from installer.storage.models import DiskInfo                             # noqa: E402
from installer.storage.safety import assess_target, confirmation_phrase   # noqa: E402
from installer.theme_css import render_gtk_css, resolve                   # noqa: E402

#: The same disposable disk the story fixtures and the §42 harness use.
TARGET = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05", devicePath="/dev/vda", sizeBytes=80 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="QEMU HARDDISK", rotational=False, transport="virtio",
)


def _context() -> dict[str, Any]:
    return {
        "disks": (TARGET,),
        "findings": {TARGET.id: assess_target(TARGET, mode="erase_disk", on_ac_power=True)},
        "selectedDisk": TARGET,
        "selectedDiskIdentity": "QEMU HARDDISK — 80.0 GiB — /dev/vda",
        "networks": ("Home", "Coffee shop guest network"),
        "appChoices": (),
    }


def _walk(widget, Gtk, depth: int = 0) -> list[dict[str, Any]]:
    """The widget tree, with the roles GTK assigned.

    **This does not read accessible names, and an earlier version that tried
    reported seven false failures.** It inferred a name from ``get_label()`` or
    ``get_text()``, which a ``Gtk.Switch`` has neither of — so every switch and
    every entry looked nameless while `_ScreenView._name` had in fact set
    ``Gtk.AccessibleProperty.LABEL`` on all of them without raising.

    GTK4 offers no way to read an accessible name back from a widget. The only
    thing that can answer the question is AT-SPI, because AT-SPI is what Orca
    reads — so that check lives in :func:`atspi_probe`, which launches the real
    application and walks the real bus. What is left here is structure: roles,
    focusability, and whether every declared action exists as a control.
    """
    rows: list[dict[str, Any]] = []
    try:
        role = widget.get_accessible_role().value_nick
    except Exception:
        role = "unknown"
    label = ""
    try:
        if hasattr(widget, "get_label") and widget.get_label():
            label = widget.get_label()
        elif hasattr(widget, "get_child"):
            # Buttons are built with an explicit child label so that GTK's
            # internal one can be taken out of the accessibility tree, which
            # means `get_label()` is empty for every action on every screen.
            # This check reported thirteen missing action rows the moment that
            # change landed — correctly noticing the shape had changed, and
            # measuring something that no longer existed.
            child = widget.get_child()
            if child is not None and hasattr(child, "get_label") and child.get_label():
                label = child.get_label()
    except Exception:
        label = ""
    focusable = bool(getattr(widget, "get_focusable", lambda: False)())
    if role not in {"none", "presentation", "generic", "unknown"} or focusable:
        rows.append({
            "depth": depth,
            "role": role,
            "label": label,
            "focusable": focusable,
            "sensitive": bool(getattr(widget, "get_sensitive", lambda: True)()),
            "type": widget.__class__.__name__,
        })
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        rows.extend(_walk(child, Gtk, depth + 1))
        child = child.get_next_sibling()
    return rows


def probe() -> dict[str, Any]:
    Gtk = _gtk()
    findings: list[str] = []
    screens: list[dict[str, Any]] = []

    application = SetupApplication(Gtk, context=_context())

    for key, builder in application.flow:
        screen = builder()
        view = _ScreenView(Gtk, screen, on_action=lambda _i: None,
                           on_change=lambda _k, _v: None)
        tree = _walk(view.root, Gtk)
        controls = [row for row in tree if row["focusable"]]

        # Every action in the record must appear as a real, focusable control.
        # A button that the record declares and the tree does not contain is the
        # failure mode the story harness structurally cannot see.
        button_labels = {row["label"] for row in tree if row["role"] == "button"}
        missing = [action.label for action in screen.actions
                   if action.label not in button_labels]

        # §37: a screen a keyboard cannot reach is a screen a keyboard user
        # cannot complete, and every screen in this flow has at least one action.
        if not controls:
            findings.append(f"{key}: no focusable control on the screen")
        if view.unnamed:
            findings.append(f"{key}: GTK refused {len(view.unnamed)} accessibility property "
                            f"call(s): {view.unnamed[:3]}")
        if missing:
            findings.append(f"{key}: action(s) declared but not present as buttons: {missing}")

        screens.append({
            "key": key,
            "heading": screen.heading,
            "announcementChars": len(screen.announcement),
            "controls": len(controls),
            "buttons": sorted(button_labels),
            "roles": sorted({row["role"] for row in tree}),
        })

    # The stylesheet must actually differ when the text size does. A setting
    # that is recorded and does not re-render is §8's failure and it looks
    # identical to a working one from inside the code that set it.
    sheets = {}
    for scale in (1.0, 1.25, 1.5, 2.0):
        theme = resolve(scheme="light", text_scale=scale)
        sheets[scale] = render_gtk_css(theme)
    sizes = {scale: resolve(scheme="light", text_scale=scale)["type"]["body"]["size"]
             for scale in sheets}
    if len(set(sizes.values())) != len(sizes):
        findings.append(f"text scaling does not move the body size: {sizes}")
    if len(set(sheets.values())) != len(sheets):
        findings.append("two text scales rendered an identical stylesheet")

    # §12: the destructive button is insensitive until the phrase matches, and
    # the phrase is the one the backend will independently re-derive.
    phrase = confirmation_phrase(TARGET)
    confirm = __import__("installer.setup_view", fromlist=["confirm_erase_screen"]) \
        .confirm_erase_screen(disk=TARGET, encrypted=True)
    confirm_button = next(item for item in confirm.actions if item.id == "confirm")
    if confirm_button.enabled:
        findings.append("the destructive button is enabled before anything is typed")
    if phrase not in confirm.announcement:
        findings.append("the confirmation phrase is not announced")

    application.context["selectedDisk"] = TARGET
    application.view = _ScreenView(Gtk, confirm, on_action=lambda _i: None,
                                   on_change=lambda _k, _v: None)
    application.secrets["phrase"] = "not the phrase"
    application._refresh_confirm_button()
    if application.view.buttons["confirm"].get_sensitive():
        findings.append("a wrong phrase enabled the destructive button")
    application.secrets["phrase"] = phrase
    application._refresh_confirm_button()
    if not application.view.buttons["confirm"].get_sensitive():
        findings.append("the correct phrase did not enable the destructive button")

    return {
        "schemaVersion": 1,
        "evidenceLevel": "HOST RUNTIME VALIDATED",
        "note": "The setup surface built and walked under real GTK. Not a VM run.",
        "gtk": f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}",
        "confirmationPhrase": phrase,
        "textScaleBodySizes": {str(k): v for k, v in sizes.items()},
        "screens": screens,
        "findings": findings,
    }


def atspi_probe(*, screen: str, seconds: float = 6.0) -> dict[str, Any]:
    """Launch the real surface and read the tree Orca would read.

    This is the only check in this file that can answer §38's question, because
    an accessible name is not readable back from a GTK widget and *is* readable
    from AT-SPI. Everything else here is structure.

    The application is left running for the whole walk and terminated afterwards.
    That ordering is not incidental: the previous phase's Orca probe killed the
    process and then read a log the process rewrites on exit, and reported
    nothing twice before anyone noticed.
    """
    import subprocess
    import time

    import gi  # type: ignore

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi  # type: ignore

    Atspi.init()

    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);"
         "from installer.frontend.setup import run; raise SystemExit(run(['--screen', %r]))"
         % (str(ROOT), screen)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(ROOT),
    )

    found: dict[str, Any] = {"screen": screen, "controls": [], "findings": []}
    try:
        application = None
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(0.5)
            if child.poll() is not None:
                stderr = (child.stderr.read() or b"").decode("utf-8", "replace")
                found["findings"].append(
                    f"the setup surface exited before it could be walked: {stderr[-400:]}")
                return found
            desktop = Atspi.get_desktop(0)
            for index in range(desktop.get_child_count()):
                node = desktop.get_child_at_index(index)
                if node is not None and (node.get_name() or "").startswith("bunny"):
                    application = node
                    break
                # The application name is the executable's, which for a
                # `python3 -c` child is "python3". Match on the window title
                # instead, which the surface sets explicitly.
                if node is not None and node.get_child_count():
                    window = node.get_child_at_index(0)
                    if window is not None and "Bunny OS" in (window.get_name() or ""):
                        application = node
                        break
            if application is not None:
                break

        if application is None:
            found["findings"].append(
                "the setup surface never appeared on the accessibility bus; "
                "AT-SPI cannot confirm any accessible name")
            return found

        rows: list[dict[str, Any]] = []

        def content(node) -> str:
            """What Orca would read from a node that is not a control.

            **A label's text is not its accessible name.** An earlier version of
            this walk read `get_name()` only and reported every label on the
            screen as empty — the text was there the whole time, behind the
            AT-SPI Text interface, which is what Orca uses for paragraphs. That
            false reading is why this function exists rather than a `or ""`.
            """
            try:
                interface = node.get_text_iface()
                if interface is None:
                    return ""
                return Atspi.Text.get_text(
                    interface, 0, Atspi.Text.get_character_count(interface)) or ""
            except Exception:
                return ""

        def walk(node, depth: int = 0) -> None:
            if depth > 24:
                return
            try:
                role = node.get_role_name()
                name = node.get_name() or ""
                description = node.get_description() or ""
                states = node.get_state_set()
                focusable = states.contains(Atspi.StateType.FOCUSABLE)
                sensitive = states.contains(Atspi.StateType.SENSITIVE)
            except Exception:
                return
            text = content(node)
            if focusable or text or role in {"heading", "alert"}:
                rows.append({"role": role, "name": name, "description": description,
                             "text": text, "focusable": focusable, "sensitive": sensitive})
            for index in range(node.get_child_count()):
                child_node = node.get_child_at_index(index)
                if child_node is not None:
                    walk(child_node, depth + 1)

        walk(application)
        found["controls"] = rows

        # Window chrome belongs to the compositor, not to this surface.
        chrome = {"Minimize", "Maximize", "Close", "Restore"}
        controls = [row for row in rows
                    if row["focusable"] and row["name"] not in chrome]

        # A named exemption, with its reason, rather than a quiet filter.
        #
        # GTK4's ScrolledWindow publishes a focusable "scroll pane" with no
        # accessible name. That was measured against a stock GTK4 application
        # containing one button and nothing else, and it is nameless there too,
        # so it is a property of the toolkit on this platform rather than of
        # this surface. Setting GTK_ACCESSIBLE_PROPERTY_LABEL on the
        # ScrolledWindow and on its viewport, before and after `set_child`, does
        # not change it.
        #
        # It is exempted here and recorded in `platformLimitations` so it stays
        # visible, because the honest statement is "every control this surface
        # creates has a name, and the toolkit adds one that does not" — not
        # "no findings".
        exempt = [row for row in controls
                  if not row["name"].strip() and row["role"] == "scroll pane"]
        nameless = [row for row in controls
                    if not row["name"].strip() and row["role"] != "scroll pane"]
        found["platformLimitations"] = [
            "GTK4 ScrolledWindow publishes a focusable scroll pane with no accessible "
            "name; reproduced on a stock GTK4 application, not introduced here."
        ] if exempt else []
        headings = [row for row in rows if row["role"] == "heading"]

        found["summary"] = {
            "controls": len(controls),
            "headings": [row["name"] or row["text"] for row in headings],
            "readableText": len([row for row in rows if row["text"].strip()]),
        }

        if nameless:
            found["findings"].append(
                f"{len(nameless)} focusable control(s) reach Orca with no name: "
                f"{[row['role'] for row in nameless][:5]}")
        if not rows:
            found["findings"].append("the accessible tree is empty")
        # §38 asks that headings be verifiable. One per screen is the whole
        # point: GTK 4.22 turns every plain label into a heading, so a screen
        # reporting twenty is a screen whose heading navigation is useless.
        if len(headings) != 1:
            found["findings"].append(
                f"expected exactly one heading, found {len(headings)}: "
                f"{[row['name'] or row['text'] for row in headings][:6]}")
        announced = [row for row in rows if row["description"].strip()]
        if not announced:
            found["findings"].append(
                "no node carries an accessible description; the screen announcement "
                "does not reach an assistive technology")
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except Exception:                              # pragma: no cover
            child.kill()
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--atspi", metavar="SCREEN",
                        help="launch the surface on one screen and walk the real "
                             "accessibility bus")
    parser.add_argument("--atspi-all", action="store_true",
                        help="walk every screen in the flow, one launch each")
    args = parser.parse_args()
    if args.atspi_all:
        Gtk = _gtk()
        keys = [key for key, _ in SetupApplication(Gtk, choices=Choices()).flow]
        walks = [atspi_probe(screen=key) for key in keys]
        result = {
            "schemaVersion": 1,
            "evidenceLevel": "HOST RUNTIME VALIDATED",
            "note": "Every setup screen launched under GTK and walked over the real "
                    "AT-SPI bus. This is what Orca would find. Not a VM run.",
            "screens": walks,
            "findings": [f"{walk['screen']}: {item}"
                         for walk in walks for item in walk["findings"]],
        }
        document = json.dumps(result, indent=1, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(document, encoding="utf-8", newline="\n")
        for walk in walks:
            summary = walk.get("summary", {})
            sys.stderr.write("%-22s controls=%-3s headings=%-32s text=%-3s %s\n" % (
                walk["screen"], summary.get("controls"),
                str(summary.get("headings"))[:32], summary.get("readableText"),
                walk["findings"] or "ok"))
        return 0 if not result["findings"] else 4
    if args.atspi:
        result = atspi_probe(screen=args.atspi)
        document = json.dumps(result, indent=1, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(document, encoding="utf-8", newline="\n")
        sys.stdout.write(document)
        return 0 if not result["findings"] else 4
    report = probe()
    document = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8", newline="\n")
    sys.stdout.write(document)
    return 0 if not report["findings"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
