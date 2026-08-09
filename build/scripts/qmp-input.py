#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Move the pointer, press the button, type on the keyboard — from outside the guest.

## Why this exists

The desktop shell shipped with one acceptance criterion open: "Files and
Terminal can launch — both resolve and are in the dock. **Not clicked** — the
harness has no pointer." Everything the desktop was known to do, it was known to
do because a program asked it a question. Nothing had ever pressed anything.

Running `nautilus` over SSH proves nothing about that. The path a dock tile
takes is pointer motion → libinput → Mutter → Clutter pick → the tile's
`button-release-event` → `makeActivatable`'s handler → `ApplicationLauncher` →
`Shell.App.activate` → a systemd scope → a window Mutter has to map and place.
Every one of those steps is a place the desktop can be wrong while a shell
command is right, and three of them have been wrong before.

## Why QMP and not something in the guest

`input-send-event` injects at the QEMU device layer. The events arrive at the
guest kernel from an emulated tablet and keyboard, go through evdev and
libinput, and reach Mutter as ordinary hardware input. There is no test hook, no
accessibility action, no synthesised Clutter event, and nothing in the guest can
tell the difference between this and a person — which is the property that makes
the result worth having. `xdotool` needs X; `ydotool` needs a uinput device and
a daemon inside the image; Clutter event synthesis would test the desktop's
handlers while skipping the compositor that dispatches to them.

Absolute coordinates need an absolute pointing device, so the harness gives the
guest a `virtio-tablet-pci`. QEMU's absolute axis range is 0..32767 regardless
of the display size, so every coordinate is scaled here and the display size has
to be passed in — a click computed against the wrong resolution lands somewhere
plausible and wrong, which is the failure this comment exists to prevent.
"""

from __future__ import annotations

import argparse
import sys
import time

from qmp_client import Qmp

#: QEMU's absolute axis range, from `hw/input/`. Not a screen size.
ABS_MAX = 32767

#: QEMU key names for the characters a harness needs to type. QEMU takes key
#: *names* (`qcode`), not characters, so anything typed has to be spelled out.
#: Only what the interaction script actually sends is here; a missing character
#: is an error rather than a silently dropped keystroke.
QCODE = {
    " ": "spc", "-": "minus", "_": ("shift", "minus"), ".": "dot", "/": "slash",
    ":": ("shift", "semicolon"), ";": "semicolon", ",": "comma",
    "=": "equal", "+": ("shift", "equal"), "'": "apostrophe",
    "~": ("shift", "grave_accent"), "$": ("shift", "4"),
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    QCODE[_letter] = _letter
    QCODE[_letter.upper()] = ("shift", _letter)
for _digit in "0123456789":
    QCODE[_digit] = _digit


class Pointer:
    """The emulated tablet and keyboard, addressed in screen pixels."""

    def __init__(self, qmp: Qmp, width: int, height: int) -> None:
        self._qmp = qmp
        self._width = width
        self._height = height

    def _absolute(self, x: int, y: int) -> list[dict]:
        return [
            {"type": "abs", "data": {"axis": "x",
                                     "value": int(x * ABS_MAX / max(1, self._width - 1))}},
            {"type": "abs", "data": {"axis": "y",
                                     "value": int(y * ABS_MAX / max(1, self._height - 1))}},
        ]

    def move(self, x: int, y: int) -> None:
        self._qmp.execute("input-send-event", events=self._absolute(x, y))

    def click(self, x: int, y: int, *, button: str = "left", settle: float = 0.35) -> None:
        """Move, pause, press, pause, release.

        The pauses are not superstition. A press that arrives in the same input
        frame as the motion that positioned it can be picked against the actor
        under the *previous* position, because Clutter's pick happens on the
        motion event and the button event carries no coordinates of its own.
        Moving first and letting a frame pass is what a pointer physically does.
        """
        self.move(x, y)
        time.sleep(settle)
        self._qmp.execute("input-send-event", events=[
            {"type": "btn", "data": {"down": True, "button": button}},
        ])
        time.sleep(0.12)
        self._qmp.execute("input-send-event", events=[
            {"type": "btn", "data": {"down": False, "button": button}},
        ])

    def key(self, *names: str, hold: float = 0.05) -> None:
        """Press a chord — `key("alt", "f4")` — and release it in reverse."""
        down = [{"type": "key", "data": {"down": True,
                                         "key": {"type": "qcode", "data": name}}}
                for name in names]
        up = [{"type": "key", "data": {"down": False,
                                       "key": {"type": "qcode", "data": name}}}
              for name in reversed(names)]
        self._qmp.execute("input-send-event", events=down)
        time.sleep(hold)
        self._qmp.execute("input-send-event", events=up)

    def type_text(self, text: str, *, delay: float = 0.05) -> None:
        for character in text:
            code = QCODE.get(character)
            if code is None:
                raise ValueError(f"no QEMU key name for {character!r}")
            self.key(*(code if isinstance(code, tuple) else (code,)))
            time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(prog="qmp-input")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--move", nargs=2, type=int, metavar=("X", "Y"))
    parser.add_argument("--click", nargs=2, type=int, metavar=("X", "Y"))
    parser.add_argument("--key", action="append", default=[],
                        help="a chord, as QEMU key names joined by '+' (alt+f4)")
    parser.add_argument("--type", dest="text")
    arguments = parser.parse_args()

    try:
        qmp = Qmp(arguments.socket)
    except (OSError, RuntimeError) as exc:
        print(f"qmp-input: cannot reach {arguments.socket}: {exc}", file=sys.stderr)
        return 3

    pointer = Pointer(qmp, arguments.width, arguments.height)
    try:
        if arguments.move:
            pointer.move(*arguments.move)
        if arguments.click:
            pointer.click(*arguments.click)
        for chord in arguments.key:
            pointer.key(*chord.split("+"))
        if arguments.text:
            pointer.type_text(arguments.text)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"qmp-input: {exc}", file=sys.stderr)
        return 5
    finally:
        qmp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
