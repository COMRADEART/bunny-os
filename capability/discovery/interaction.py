# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Displays, input devices, audio endpoints and cameras.

These determine whether the visual companion can run locally at all, so a wrong
answer here is expensive in both directions: claiming a display that is not
there starts a renderer that cannot draw, and missing one that is there leaves
a user staring at a machine that decided it was a server.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

from ..model import AudioFacts, DisplayFacts, absent, measured, unknown
from .sources import Deadline, iter_directory, read_first_line, read_text, sanitize

__all__ = ["probe_audio", "probe_display"]

_DRM_ROOT = "/sys/class/drm"
_INPUT_ROOT = "/sys/class/input"

# Event codes used below are all < 32, which is deliberate. The kernel prints
# capability bitmasks as space-separated `unsigned long` groups, so the group
# width is 32 bits on a 32-bit kernel and 64 on a 64-bit one, and the number of
# groups does not reveal which. Every bit tested here lives in the *last* group
# either way, so the parse is independent of word size and cannot silently
# misread. Anything above bit 31 would need that ambiguity resolved first.
_EV_KEY, _EV_REL, _EV_ABS = 1, 2, 3
_KEY_Q, _KEY_P, _KEY_A = 16, 25, 30
_REL_X, _REL_Y = 0, 1
_PROP_DIRECT = 1  # INPUT_PROP_DIRECT: the surface is the screen, i.e. a touchscreen

_MODE = re.compile(r"^(\d{2,5})x(\d{2,5})")


def _low_bits(bitmask: str | None) -> int:
    """The lowest 32 bits of a kernel capability bitmask."""
    if not bitmask:
        return 0
    groups = bitmask.split()
    if not groups:
        return 0
    try:
        return int(groups[-1], 16) & 0xFFFFFFFF
    except ValueError:
        return 0


def _has(bitmask: str | None, bit: int) -> bool:
    return bool(_low_bits(bitmask) >> bit & 1)


def _input_devices() -> tuple[bool | None, bool | None, bool | None]:
    """``(keyboard, pointer, touch)`` from the input class, or ``None`` each.

    A keyboard is not "anything that reports key events" — a power button and a
    lid switch both do, and a headless server would otherwise report a keyboard.
    The test is for the alphabetic block (Q, P and A), which is what
    distinguishes a device someone can type on from a device with three buttons.
    """
    if not Path(_INPUT_ROOT).is_dir():
        return None, None, None

    keyboard = pointer = touch = False
    for entry in iter_directory(_INPUT_ROOT, limit=256):
        if not entry.name.startswith("input"):
            continue
        capabilities = entry / "capabilities"
        events = read_first_line(capabilities / "ev")
        if not events:
            continue
        if _has(events, _EV_KEY):
            keys = read_first_line(capabilities / "key")
            if _has(keys, _KEY_Q) and _has(keys, _KEY_P) and _has(keys, _KEY_A):
                keyboard = True
        if _has(events, _EV_REL):
            relative = read_first_line(capabilities / "rel")
            if _has(relative, _REL_X) and _has(relative, _REL_Y):
                pointer = True
        if _has(events, _EV_ABS):
            properties = read_first_line(entry / "properties")
            if _has(properties, _PROP_DIRECT):
                touch = True
                pointer = True  # a touchscreen is a pointing device
    return keyboard, pointer, touch


def probe_display(deadline: Deadline) -> DisplayFacts:
    connectors = [
        entry for entry in iter_directory(_DRM_ROOT, limit=128)
        if "-" in entry.name and entry.name.startswith("card")
    ]

    session_variable = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))

    if not Path(_DRM_ROOT).is_dir():
        # No DRM at all. A graphical session may still exist — a nested or
        # remote compositor, for instance — so the environment is consulted
        # before concluding anything.
        outputs = unknown(_DRM_ROOT, "DRM is not exposed")
        headless = (
            measured(False, "environment", "WAYLAND_DISPLAY or DISPLAY is set")
            if session_variable
            else unknown(_DRM_ROOT, "no DRM and no session variable; cannot distinguish headless from unprobed")
        )
        resolution = unknown(_DRM_ROOT)
    else:
        connected = [
            entry for entry in connectors
            if (read_first_line(entry / "status") or "").strip().lower() == "connected"
        ]
        outputs = measured(len(connected), f"{_DRM_ROOT}/*/status")
        headless = measured(
            not connected and not session_variable,
            f"{_DRM_ROOT}/*/status",
            "no connected connector and no session variable" if not connected else "at least one connector is connected",
        )
        widest = (0, 0)
        for entry in connected:
            text = read_text(entry / "modes", limit=8192) or ""
            for line in text.splitlines()[:64]:
                match = _MODE.match(line.strip())
                if match:
                    candidate = (int(match.group(1)), int(match.group(2)))
                    if candidate[0] * candidate[1] > widest[0] * widest[1]:
                        widest = candidate
                    break
        if widest != (0, 0):
            resolution = measured(f"{widest[0]}x{widest[1]}", f"{_DRM_ROOT}/*/modes")
        elif connected:
            resolution = unknown(f"{_DRM_ROOT}/*/modes", "connector is connected but published no parseable mode")
        else:
            resolution = absent(_DRM_ROOT, "no connected connector")

    keyboard, pointer, touch = _input_devices()
    if keyboard is None:
        keyboard_observation = unknown(_INPUT_ROOT, "input class not present")
        pointer_observation = unknown(_INPUT_ROOT, "input class not present")
        touch_observation = unknown(_INPUT_ROOT, "input class not present")
    else:
        keyboard_observation = measured(keyboard, _INPUT_ROOT, "alphabetic key block required")
        pointer_observation = measured(pointer, _INPUT_ROOT)
        touch_observation = measured(touch, _INPUT_ROOT, "INPUT_PROP_DIRECT")

    return DisplayFacts(
        headless=headless,
        connected_outputs=outputs,
        max_resolution=resolution,
        touch=touch_observation,
        keyboard=keyboard_observation,
        pointer=pointer_observation,
    )


def probe_audio(deadline: Deadline) -> AudioFacts:
    pcm = read_text("/proc/asound/pcm", limit=64 * 1024)
    if pcm is None:
        if Path("/proc/asound").is_dir():
            output = unknown("/proc/asound/pcm", "ALSA present but no PCM list")
            capture = unknown("/proc/asound/pcm", "ALSA present but no PCM list")
        else:
            output = absent("/proc/asound", "no ALSA subsystem; the machine has no sound devices")
            capture = absent("/proc/asound", "no ALSA subsystem; the machine has no sound devices")
    else:
        lowered = pcm.lower()
        output = measured("playback" in lowered, "/proc/asound/pcm")
        capture = measured("capture" in lowered, "/proc/asound/pcm")

    video = [entry for entry in iter_directory("/dev", limit=1024) if entry.name.startswith("video") and entry.name[5:].isdigit()]
    if not Path("/dev").is_dir():
        camera = unknown("/dev", "not readable")
    elif video:
        # A V4L2 node is not proof of a capture device: metadata and output
        # nodes share the namespace, and distinguishing them needs a
        # VIDIOC_QUERYCAP ioctl this probe deliberately does not perform.
        camera = measured(
            True,
            "/dev/video*",
            f"{len(video)} V4L2 node(s); capture capability was not queried by ioctl",
        )
    else:
        camera = absent("/dev/video*", "no V4L2 device nodes")

    return AudioFacts(output_present=output, input_present=capture, camera_present=camera)


def _asound_cards() -> list[str]:
    text = read_text("/proc/asound/cards", limit=8192) or ""
    return [sanitize(line, limit=64) for line in text.splitlines()[:32] if line.strip()]
