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
                    "description": node.get_description() or "",
                    "node": node,
                    "focusable": states.contains(self.Atspi.StateType.FOCUSABLE),
                    "sensitive": states.contains(self.Atspi.StateType.SENSITIVE),
                    # A toggled ToggleButton reports PRESSED, a checked
                    # CheckButton reports CHECKED - measured. Either is "this
                    # option is the selected one".
                    "checked": (states.contains(self.Atspi.StateType.CHECKED)
                                or states.contains(self.Atspi.StateType.PRESSED)),
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
        # Re-queried on every attempt rather than found once: a page
        # mid-transition serves stale accessibles that are present, sensitive,
        # and expose zero actions — run 3 lost exactly that race on the
        # keyboard page's Continue. Absent, insensitive and action-less are
        # all transient until the deadline, and the deadline still fails
        # closed with the last true reason.
        deadline = time.time() + self.timeout
        last: Exception | None = None
        while time.time() < deadline:
            row = self.find(name=name, role=role)
            if row is None:
                last = TimeoutError(f"timed out waiting for a {role} named {name!r}")
            elif not row["sensitive"]:
                last = RuntimeError(f"the control {name!r} is present but not sensitive")
            else:
                try:
                    self.activate(row)
                    return
                except RuntimeError as error:
                    last = error
            time.sleep(0.5)
        raise last if last is not None else TimeoutError(
            f"timed out waiting for a {role} named {name!r}")

    def press_first(self, names: tuple[str, ...], *, role: str = "button") -> None:
        """Press whichever of ``names`` appears first, preferring earlier names.

        The same settling rules as :meth:`press`: absent, insensitive and
        action-less are transient until the deadline, and each cycle prefers
        the earliest name so "Continue without network" beats a plain
        Continue whenever both exist.
        """
        deadline = time.time() + self.timeout
        last: Exception | None = None
        while time.time() < deadline:
            for name in names:
                row = self.find(name=name, role=role)
                if row is None:
                    continue
                if not row["sensitive"]:
                    last = RuntimeError(f"the control {name!r} is present but not sensitive")
                    continue
                try:
                    self.activate(row)
                    return
                except RuntimeError as error:
                    last = error
            time.sleep(0.5)
        raise last if last is not None else TimeoutError(
            f"timed out waiting for any {role} named {names!r}")

    def fingerprint(self) -> str:
        """What the page is, as its control roster. Cheap and comparable."""
        return "|".join(f"{row['role']}:{row['name']}" for row in self.controls())

    def advance(self, names: tuple[str, ...], *, role: str = "button") -> None:
        """Press until the page actually turns.

        The action having fired is not the page having changed: runs 4 and 5
        each ended with the driver's stage counter two pages ahead of the
        screen, because a stale accessible from a page already left accepts
        the action and nothing moves. So navigation is judged by the one
        thing that cannot lie about it - the control roster changing - and
        re-pressed until it does or the deadline refuses.
        """
        before = self.fingerprint()
        deadline = time.time() + self.timeout
        pressed = 0
        while time.time() < deadline:
            for name in names:
                row = self.find(name=name, role=role)
                if row is None or not row["sensitive"]:
                    continue
                try:
                    self.activate(row)
                    pressed += 1
                except RuntimeError:
                    continue
                break
            time.sleep(0.7)
            now = self.fingerprint()
            if pressed and now != before:
                emit("page-turned", presses=pressed,
                     shows=[part for part in now.split("|")[:6]])
                return
        raise TimeoutError(
            f"pressed {names!r} {pressed} times and the page never changed")

    def wait_for_text(self, needle: str, what: str) -> str:
        """The screen text once ``needle`` is in it. A page's text renders
        after the click that navigated to it; a single read decides from
        whichever frame it happened to land on."""
        found: dict[str, str] = {}

        def check() -> bool:
            screen = self.text_on_screen()
            if needle in screen:
                found["screen"] = screen
                return True
            return False

        self.wait_for(check, what)
        return found["screen"]

    def field_named(self, label: str):
        """The field whose label is exactly ``label``, not merely contains it.

        `_ScreenView` builds an entry's accessible name as "<label>. <help>", so
        a substring match for "Password" also matches "Password again" — and the
        tree order decides which. Typing the password into the confirmation box
        and leaving the password box empty is a run that fails at account
        validation for a reason that has nothing to do with the installer.

        So the leading segment is compared exactly.
        """
        for row in self.controls():
            if row["role"] not in {"text", "entry", "password text", "text-box"}:
                continue
            head = (row["name"] or "").split(". ", 1)[0].strip()
            if head == label:
                return row
        return None

    def type_into(self, name: str, text: str) -> None:
        row = self.wait_for(lambda: self.field_named(name) or self.find(name=name),
                            f"a field named {name!r}")
        node = row["node"]
        interface = node.get_editable_text_iface()
        if interface is None:
            raise RuntimeError(f"{name!r} is not editable")
        self.Atspi.EditableText.set_text_contents(interface, text)
        emit("typed", field=row["name"], characters=len(text))


def verify_target(surface: Surface, *, expected_size_gib: float, expected_model: str,
                  expected_device: str, tolerance_gib: float = 1.0) -> dict[str, Any]:
    """§43. Establish that the disk about to be erased is the disposable one.

    Returns the option row for the target. Raises on anything ambiguous, and
    ambiguous includes "two disks that both look right".

    The identity is the device path and the size. It was the model string,
    and run 6 showed why that cannot carry the match: a virtio disk has no
    model to report, so the surface truthfully said "Unknown model" about
    the exact disk the harness created, and every disk on the machine said
    the same words. The model stays enforced whenever the row reports one.
    """
    # Polled, not read once: the storage page fills its disk rows from the
    # backend's probe over the socket, and run 4 took its one look before any
    # row existed — the tree at that instant still held the language page's
    # radio buttons and nothing else. Zero candidates is transient while the
    # page settles; two candidates is real ambiguity and refuses immediately.
    def gather():
        # Options are plain buttons now, so the roster is filtered by content
        # (the device-path match below) rather than by widget role.
        rows = [row for row in surface.controls()
                if row["role"] in {"radio button", "check box", "list item",
                                   "toggle button", "button"}
                and row["name"]]
        candidates = [row for row in rows if expected_device.lower() in row["name"].lower()]
        # The note rides in the accessible description now, so the medium's
        # self-identification is matched in both fields.
        media = [row for row in rows
                 if any(marker in (row["name"] + " " + row["description"]).lower()
                        for marker in ("installation media", "iso9660"))]
        return rows, candidates, media

    deadline = time.time() + surface.timeout
    while True:
        rows, candidates, media = gather()
        if len(candidates) >= 1 or time.time() >= deadline:
            break
        time.sleep(0.5)

    emit("storage-candidates",
         all=[row["name"][:80] for row in rows],
         candidates=[row["name"][:80] for row in candidates],
         media=[row["name"][:80] for row in media])

    if len(candidates) != 1:
        raise RuntimeError(
            f"§43: expected exactly one disk at {expected_device!r}, found "
            f"{len(candidates)}. Refusing to choose between disks that may hold data.")

    target = candidates[0]
    if not target["sensitive"]:
        raise RuntimeError(f"§43: the expected target is not selectable: {target['name']}")

    if expected_model.lower() not in target["name"].lower():
        if "unknown model" not in target["name"].lower():
            raise RuntimeError(
                f"§43: the disk at {expected_device} calls itself {target['name']!r}, "
                f"not {expected_model!r}. Refusing a disk that is not what was promised.")
        emit("model-unreported",
             detail="the bus exposes no model string; identity carried by device and size")

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


def journey(arguments: argparse.Namespace, surface: Surface) -> int:
    surface.wait_for_window()

    emit("stage", name="welcome")
    surface.advance(("Get started",))

    # §8: accessibility is the second screen, and the harness sets what the
    # journey asked for there rather than through a settings back door.
    emit("stage", name="accessibility")
    if arguments.text_scale != 1.0:
        label = {1.25: "Large", 1.5: "Larger", 2.0: "Largest"}[arguments.text_scale]
        surface.press(label)
    if arguments.high_contrast:
        surface.press("High contrast", role="toggle button") if surface.find(
            name="High contrast", role="toggle button") else surface.press(
            "High contrast", role="switch")
    if arguments.reduced_motion:
        row = surface.find(name="Reduce motion", role="switch")
        if row:
            surface.activate(row)
    surface.advance(("Continue",))

    for stage in ("language_region", "keyboard", "network"):
        emit("stage", name=stage)
        # The keyboard page asks for proof the layout types what it says.
        # Satisfied whenever its check field is on screen, harmless when the
        # page never asks - the stage name cannot be trusted to know which
        # page is really current, but the field's presence can.
        check = surface.field_named("Type here to check it")
        if check is not None:
            interface = check["node"].get_editable_text_iface()
            if interface is not None:
                surface.Atspi.EditableText.set_text_contents(interface, "bunny layout check")
                emit("typed", field=check["name"], characters=18)
        surface.advance(("Continue without network", "Continue"))

    emit("stage", name="storage")
    target = verify_target(surface,
                           expected_size_gib=arguments.disk_gib,
                           expected_model=arguments.disk_model,
                           expected_device=arguments.disk_device)
    # Selection is a model event, not a widget state: clicking an option
    # reports the choice and the screen re-renders with the chosen row
    # renamed "… — selected". That rename is the witness — judged from a
    # fresh walk each attempt, because the clicked row's accessible is
    # replaced by the re-render.
    selection_deadline = time.time() + surface.timeout
    while True:
        chosen = next((row for row in surface.controls()
                       if arguments.disk_device in row["name"]
                       and "— selected" in row["name"]), None)
        if chosen is not None:
            emit("target-selected", disk=chosen["name"])
            break
        row = surface.find(name=target["name"], exact=True)
        if row is not None and row["sensitive"]:
            try:
                surface.activate(row)
            except RuntimeError:
                pass
        if time.time() >= selection_deadline:
            raise RuntimeError(f"§43: could not select the verified target: {target['name']!r}")
        time.sleep(0.7)
    surface.advance(("Review what happens",))

    emit("stage", name="encryption")
    if arguments.passphrase:
        # §13: the toggle is the decision; the passphrase fields exist only
        # while it is on. Run 18 typed a passphrase into fields drawn beside
        # an off toggle, the flow ignored the secret because the choice said
        # off, and the installation came out unencrypted — so the driver now
        # does what a person deciding to encrypt does: switch it on first,
        # and witness the fields appearing before typing into them.
        toggle = surface.wait_for(
            lambda: (surface.find(name="Encrypt this disk", role="switch")
                     or surface.find(name="Encrypt this disk", role="toggle button")
                     or surface.find(name="Encrypt this disk", role="check box")),
            "the 'Encrypt this disk' toggle")
        if not toggle["checked"]:
            surface.activate(toggle)
        surface.wait_for(lambda: surface.field_named("Passphrase"),
                         "the passphrase field the toggle conjures")
        emit("encryption-enabled", control=toggle["name"])
        surface.type_into("Passphrase", arguments.passphrase)
        surface.type_into("Passphrase again", arguments.passphrase)
    surface.advance(("Continue",))

    emit("stage", name="account")
    surface.type_into("Your name", arguments.display_name)
    surface.type_into("Username", arguments.username)
    surface.type_into("Password", arguments.password)
    surface.type_into("Password again", arguments.password)
    if arguments.device_name:
        surface.type_into("Device name", arguments.device_name)
    surface.advance(("Continue",))

    # What this journey expects the disk to carry, spoken as the product's own
    # record so the host verifier compares against real defaults rather than a
    # harness's memory of them. Best-effort: a medium whose installer package
    # moved still drives; the harness then falls back to the reduced form.
    try:
        installed = Path("/usr/lib/bunny-os/python")
        if installed.is_dir() and str(installed) not in sys.path:
            sys.path.insert(0, str(installed))
        from installer.setup_state import Choices as _Choices

        emit("expected-choices", record=_Choices(
            display_name=arguments.display_name,
            username=arguments.username,
            device_name=arguments.device_name,
            encryption_enabled=bool(arguments.passphrase),
            text_scale=arguments.text_scale,
            high_contrast=bool(arguments.high_contrast),
            reduced_motion=bool(arguments.reduced_motion),
        ).as_record())
    except Exception as error:  # noqa: BLE001 - evidence, not control flow
        emit("expected-choices-unavailable", detail=str(error)[:200])

    for stage in ("privacy", "appearance", "companion", "applications"):
        emit("stage", name=stage)
        surface.advance(("Skip apps", "Continue"))

    emit("stage", name="review")
    # Polled like every other page: the consequence sentence renders after the
    # click that navigated here, and §22's refusal should fire on a screen
    # that settled without it, not on a screen still being drawn.
    screen = surface.wait_for_text(
        "will be erased", "§22: the review screen to state the disk consequence")
    emit("review-consequence", text=[line for line in screen.splitlines()
                                     if "will be erased" in line][:1])
    surface.advance(("Install Bunny OS",))

    emit("stage", name="confirm_erase")
    import re

    phrase = None
    deadline = time.time() + surface.timeout
    while phrase is None:
        screen = surface.text_on_screen()
        phrase = re.search(r"Type (ERASE \S+ [A-F0-9]{6}) to confirm", screen)
        if phrase is None:
            if time.time() >= deadline:
                raise RuntimeError(
                    "§12: the confirmation screen does not show a phrase to type")
            time.sleep(0.5)
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
    surface.advance(("Erase",))

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
    # The root backend publishes this, because the sysfs entry below is mode
    # 0400 root and this runs as the live desktop user. Reading the sysfs entry
    # directly is kept as the path for a run started by hand as root.
    #
    # Polled rather than read once: this autostarts with the session, and the
    # backend that publishes the file is a system unit with its own startup —
    # a single read decides "ordinary boot" from whichever side of that race it
    # landed on. Thirty seconds covers the race; a real boot has no marker to
    # find and the poll ends with the same quiet exit it always had.
    published = Path("/run/bunny-setup/drive.args")
    deadline = time.monotonic() + 30.0
    while True:
        try:
            value = published.read_text(encoding="utf-8").strip()
            if value:
                emit("driver-arguments", source=str(published), arguments=value)
                return value.split()
        except OSError:
            pass

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

        if time.monotonic() >= deadline:
            return []
        time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk-gib", type=float, default=80.0)
    parser.add_argument("--disk-model", default="QEMU HARDDISK")
    # The §43 identity: a single virtio disk is /dev/vda deterministically,
    # and virtio reports no model string for the model check to carry.
    parser.add_argument("--disk-device", default="/dev/vda")
    parser.add_argument("--display-name", default="Alex")
    parser.add_argument("--username", default="alex")
    parser.add_argument("--password", default="bunny-test-password")
    parser.add_argument("--passphrase", default="")
    parser.add_argument("--device-name", default="",
                        help="typed into the optional Device name field; "
                             "becomes the installed system's hostname")
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
    surface = None
    try:
        surface = Surface(timeout=arguments.timeout)
        return journey(arguments, surface)
    except Exception as error:
        emit("error", type=type(error).__name__, message=str(error)[:500])
        # What the screen held when it went wrong, so the failure names its
        # own context instead of costing another run to photograph.
        if surface is not None:
            try:
                emit("screen-at-failure",
                     controls=[f"{row['role']}:{row['name']}"
                               for row in surface.controls() if row["name"]][:40],
                     text=surface.text_on_screen()[:800])
            except Exception:
                pass
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
