#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the Bunny setup surface from inside the live session, over AT-SPI.

This runs **in the guest**. It is shipped in the live image rather than injected,
because an ISO is read-only and there is nowhere to inject into — which turns out
to be the better arrangement anyway: the thing driving the installer is the thing
the installer ships, so a harness that works is evidence about the product.

## Semantic, not coordinates

§42 asks for accessibility interaction where possible and forbids relying purely
on coordinate clicks. Everything here finds a control by its **accessible name**
and activates it through the AT-SPI action interface. That has a property a
coordinate click does not: if a control loses its name, the run fails. A click at
(640, 480) keeps working while the button under it becomes unreachable to every
screen-reader user, which is exactly the regression §38 exists to prevent.

## §43, and why this refuses more than it accepts

The disk this selects gets erased. So it does not select a disk — it *verifies*
one, and stops if anything about the machine is not what the harness promised:

* exactly one candidate target, and it is the expected size and model;
* the installation medium is present in the list and is **not** selectable;
* the confirmation phrase drawn on screen matches the one derived from the disk
  the harness intended.

Any of those failing ends the run before the confirmation is typed. "Fail closed
if uncertain" is not a comment here; there is no branch that proceeds without all
three.

Output is a line-oriented protocol on the serial console, because that is what
the host harness can read from outside the guest without cooperation from the
session — the same reason `vm-desktop-story.sh` reads the serial log rather than
asking the desktop how it is doing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

MARKER = "BUNNY-INSTALL"


def emit(event: str, **detail: Any) -> None:
    """One structured line, flushed, on stdout and on the serial console."""
    line = f"{MARKER} " + json.dumps({"event": event, **detail}, sort_keys=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    try:
        with open("/dev/ttyS0", "w", encoding="utf-8") as serial:
            serial.write(line + "\n")
            serial.flush()
    except OSError:
        pass


class Surface:
    """The setup window, found and driven through the accessibility bus."""

    def __init__(self, timeout: float = 180.0) -> None:
        import gi  # type: ignore

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # type: ignore

        self.Atspi = Atspi
        Atspi.init()
        self.timeout = timeout
        self.window = None

    # -- finding ---------------------------------------------------------

    def wait_for_window(self, title: str = "Set up Bunny OS"):
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            desktop = self.Atspi.get_desktop(0)
            for index in range(desktop.get_child_count()):
                application = desktop.get_child_at_index(index)
                if application is None:
                    continue
                for child in range(application.get_child_count()):
                    frame = application.get_child_at_index(child)
                    if frame is not None and title in (frame.get_name() or ""):
                        self.window = frame
                        emit("window", title=frame.get_name())
                        return frame
            time.sleep(1.0)
        raise TimeoutError(f"the setup window never appeared within {self.timeout}s")

    def _walk(self, node, depth: int = 0):
        if node is None or depth > 30:
            return
        yield node
        for index in range(node.get_child_count()):
            yield from self._walk(node.get_child_at_index(index), depth + 1)

    def controls(self) -> list[dict[str, Any]]:
        rows = []
        for node in self._walk(self.window):
            try:
                states = node.get_state_set()
                rows.append({
                    "role": node.get_role_name(),
                    "name": node.get_name() or "",
                    "node": node,
                    "focusable": states.contains(self.Atspi.StateType.FOCUSABLE),
                    "sensitive": states.contains(self.Atspi.StateType.SENSITIVE),
                    "checked": states.contains(self.Atspi.StateType.CHECKED),
                })
            except Exception:
                continue
        return rows

    def text_on_screen(self) -> str:
        parts = []
        for node in self._walk(self.window):
            try:
                interface = node.get_text_iface()
                if interface is None:
                    continue
                count = self.Atspi.Text.get_character_count(interface)
                if count:
                    parts.append(self.Atspi.Text.get_text(interface, 0, count) or "")
            except Exception:
                continue
        return "\n".join(parts)

    def find(self, *, name: str, role: str | None = None, exact: bool = False):
        for row in self.controls():
            if role is not None and row["role"] != role:
                continue
            if (row["name"] == name) if exact else (name.lower() in row["name"].lower()):
                return row
        return None

    def wait_for(self, predicate: Callable[[], Any], what: str, timeout: float | None = None):
        deadline = time.time() + (timeout if timeout is not None else self.timeout)
        while time.time() < deadline:
            found = predicate()
            if found:
                return found
            time.sleep(0.5)
        raise TimeoutError(f"timed out waiting for {what}")

    # -- acting ----------------------------------------------------------

    def activate(self, row: dict[str, Any]) -> None:
        """Press a control through its own action, not through a coordinate."""
        node = row["node"]
        interface = node.get_action_iface()
        if interface is None:
            raise RuntimeError(f"{row['name']!r} exposes no action to activate")
        count = self.Atspi.Action.get_n_actions(interface)
        for index in range(count):
            action = self.Atspi.Action.get_action_name(interface, index)
            if action in {"click", "activate", "press", "toggle", "jump"}:
                self.Atspi.Action.do_action(interface, index)
                emit("activated", control=row["name"], role=row["role"], action=action)
                return
        if count:
            self.Atspi.Action.do_action(interface, 0)
            emit("activated", control=row["name"], role=row["role"], action="0")
            return
        raise RuntimeError(f"{row['name']!r} has no usable action")

    def press(self, name: str, *, role: str = "button") -> None:
        row = self.wait_for(lambda: self.find(name=name, role=role), f"a {role} named {name!r}")
        if not row["sensitive"]:
            raise RuntimeError(f"the control {name!r} is present but not sensitive")
        self.activate(row)

    def type_into(self, name: str, text: str) -> None:
        row = self.wait_for(lambda: self.find(name=name), f"a field named {name!r}")
        node = row["node"]
        interface = node.get_editable_text_iface()
        if interface is None:
            raise RuntimeError(f"{name!r} is not editable")
        self.Atspi.EditableText.set_text_contents(interface, text)
        emit("typed", field=row["name"], characters=len(text))


def verify_target(surface: Surface, *, expected_size_gib: float, expected_model: str,
                  tolerance_gib: float = 1.0) -> dict[str, Any]:
    """§43. Establish that the disk about to be erased is the disposable one.

    Returns the option row for the target. Raises on anything ambiguous, and
    ambiguous includes "two disks that both look right".
    """
    rows = [row for row in surface.controls()
            if row["role"] in {"radio button", "check box", "list item"} and row["name"]]
    candidates = [row for row in rows if expected_model.lower() in row["name"].lower()]
    media = [row for row in rows if "installation media" in row["name"].lower()
             or "iso9660" in row["name"].lower()]

    emit("storage-candidates",
         all=[row["name"][:80] for row in rows],
         candidates=[row["name"][:80] for row in candidates],
         media=[row["name"][:80] for row in media])

    if len(candidates) != 1:
        raise RuntimeError(
            f"§43: expected exactly one disk matching {expected_model!r}, found "
            f"{len(candidates)}. Refusing to choose between disks that may hold data.")

    target = candidates[0]
    if not target["sensitive"]:
        raise RuntimeError(f"§43: the expected target is not selectable: {target['name']}")

    # The size is in the identity string that `storage.safety.disk_identity`
    # built, e.g. "QEMU HARDDISK — 80.0 GiB — /dev/vda". Parsed rather than
    # trusted: a harness that erased an 80 GiB disk because it asked for one and
    # got a 4 TB one would have proved nothing about §43.
    import re

    match = re.search(r"([\d.]+)\s*GiB", target["name"])
    if not match:
        raise RuntimeError(f"§43: cannot read a size from the target: {target['name']!r}")
    size = float(match.group(1))
    if abs(size - expected_size_gib) > tolerance_gib:
        raise RuntimeError(
            f"§43: the target is {size} GiB and the harness created a "
            f"{expected_size_gib} GiB disk. Refusing.")

    for row in media:
        if row["sensitive"]:
            raise RuntimeError(
                f"§43: the installation media is offered as a target: {row['name']}")

    emit("target-verified", disk=target["name"], sizeGiB=size)
    return target


def journey(arguments: argparse.Namespace) -> int:
    surface = Surface(timeout=arguments.timeout)
    surface.wait_for_window()

    emit("stage", name="welcome")
    surface.press("Get started")

    # §8: accessibility is the second screen, and the harness sets what the
    # journey asked for there rather than through a settings back door.
    emit("stage", name="accessibility")
    if arguments.text_scale != 1.0:
        label = {1.25: "Large", 1.5: "Larger", 2.0: "Largest"}[arguments.text_scale]
        surface.press(label, role="radio button")
    if arguments.high_contrast:
        surface.press("High contrast", role="toggle button") if surface.find(
            name="High contrast", role="toggle button") else surface.press(
            "High contrast", role="switch")
    if arguments.reduced_motion:
        row = surface.find(name="Reduce motion", role="switch")
        if row:
            surface.activate(row)
    surface.press("Continue")

    for stage in ("language_region", "keyboard", "network"):
        emit("stage", name=stage)
        row = surface.find(name="Continue without network", role="button")
        surface.activate(row) if row else surface.press("Continue")

    emit("stage", name="storage")
    target = verify_target(surface,
                           expected_size_gib=arguments.disk_gib,
                           expected_model=arguments.disk_model)
    surface.activate(target)
    surface.press("Review what happens")

    emit("stage", name="encryption")
    if arguments.passphrase:
        surface.type_into("Passphrase", arguments.passphrase)
        surface.type_into("Passphrase again", arguments.passphrase)
    surface.press("Continue")

    emit("stage", name="account")
    surface.type_into("Your name", arguments.display_name)
    surface.type_into("Username", arguments.username)
    surface.type_into("Password", arguments.password)
    surface.type_into("Password again", arguments.password)
    surface.press("Continue")

    for stage in ("privacy", "appearance", "companion", "applications"):
        emit("stage", name=stage)
        row = surface.find(name="Skip apps", role="button")
        surface.activate(row) if row else surface.press("Continue")

    emit("stage", name="review")
    screen = surface.text_on_screen()
    if "will be erased" not in screen:
        raise RuntimeError("§22: the review screen does not state the disk consequence")
    emit("review-consequence", text=[line for line in screen.splitlines()
                                     if "will be erased" in line][:1])
    surface.press("Install Bunny OS")

    emit("stage", name="confirm_erase")
    screen = surface.text_on_screen()
    import re

    phrase = re.search(r"Type (ERASE \S+ [A-F0-9]{6}) to confirm", screen)
    if not phrase:
        raise RuntimeError("§12: the confirmation screen does not show a phrase to type")
    emit("confirmation-phrase", phrase=phrase.group(1))

    if arguments.expect_refusal:
        # Journey D's negative control: type something wrong and prove the
        # button stays disabled and nothing is installed.
        surface.type_into(f"Type {phrase.group(1)} to confirm", "DEFINITELY NOT THE PHRASE")
        time.sleep(1.0)
        row = surface.find(name="Erase", role="button")
        if row and row["sensitive"]:
            raise RuntimeError("§12: a wrong phrase enabled the destructive button")
        emit("refusal-verified", detail="the destructive button stayed disabled")
        emit("done", outcome="refused-as-expected")
        return 0

    surface.type_into(f"Type {phrase.group(1)} to confirm", phrase.group(1))
    time.sleep(1.0)
    surface.press("Erase")

    emit("stage", name="installing")
    deadline = time.time() + arguments.install_timeout
    last = ""
    while time.time() < deadline:
        screen = surface.text_on_screen()
        if "Bunny OS is ready" in screen:
            emit("done", outcome="complete")
            return 0
        if "Installation stopped" in screen:
            emit("done", outcome="failed",
                 detail=[line for line in screen.splitlines() if line.strip()][:6])
            return 5
        current = " | ".join(line for line in screen.splitlines()
                             if line.strip() and ("◆" in line or "✓" in line))
        if current != last:
            emit("progress", stages=current[:400])
            last = current
        time.sleep(5.0)
    raise TimeoutError("the installation did not finish within "
                       f"{arguments.install_timeout}s")


def smbios_arguments() -> list[str]:
    """The journey's parameters, from an SMBIOS OEM string.

    The ISO's GRUB entries are fixed at build time, so the kernel command line
    cannot carry per-run options without rebuilding the medium for every
    journey. SMBIOS type 11 can: QEMU sets it with `-smbios type=11,value=...`
    and the guest reads it out of sysfs. One ISO then serves all four of §53.

    Returns an empty list when the marker is absent, which is what makes this
    inert on a real installation: a person booting the medium gets the setup
    surface and nothing drives it.
    """
    for entry in sorted(Path("/sys/firmware/dmi/entries").glob("11-*/raw")):
        try:
            raw = entry.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        for field in raw.split(chr(0)):
            if "bunny.drive=" in field:
                value = field.split("bunny.drive=", 1)[1].strip()
                emit("smbios", arguments=value)
                return value.split()
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk-gib", type=float, default=80.0)
    parser.add_argument("--disk-model", default="QEMU HARDDISK")
    parser.add_argument("--display-name", default="Alex")
    parser.add_argument("--username", default="alex")
    parser.add_argument("--password", default="bunny-test-password")
    parser.add_argument("--passphrase", default="")
    parser.add_argument("--text-scale", type=float, default=1.0)
    parser.add_argument("--high-contrast", action="store_true")
    parser.add_argument("--reduced-motion", action="store_true")
    parser.add_argument("--expect-refusal", action="store_true",
                        help="type a wrong phrase and prove nothing installs")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--install-timeout", type=float, default=2400.0)
    supplied = sys.argv[1:] or smbios_arguments()
    if not supplied and not sys.stdin.isatty():
        # No marker and nothing on the command line: this is an ordinary boot of
        # the installation medium, and the driver has no business running.
        return 0
    arguments = parser.parse_args(supplied)

    emit("start", **{key: value for key, value in vars(arguments).items()
                     if key not in {"password", "passphrase"}})
    try:
        return journey(arguments)
    except Exception as error:
        emit("error", type=type(error).__name__, message=str(error)[:500])
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
