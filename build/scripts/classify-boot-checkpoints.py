#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""How far did the installation medium get, and what says so.

## Why a ladder and not a verdict

The medium has one recorded outcome so far and it was "timeout after fifty
minutes". That is true and useless: it does not distinguish a machine that never
started from one that reached a graphical session and idled, and both had
happened at different times without anyone being able to tell them apart from
the harness output.

Nine checkpoints, each with the evidence that establishes it and the evidence
that refutes it, produce a statement of the form "BOOT-6 failed, here is the
line". That is a diagnosis. "Timeout" is not.

## The rules the classifier follows

  * A checkpoint that has a *negative* match fails, even if a positive also
    matched. `Reached target Initrd Root File System` followed by `Entering
    emergency mode` is not a pass with a footnote.
  * A checkpoint after the first failure is NOT-REACHED, not FAIL. A boot that
    died in the initramfs did not fail to start a graphical target; it never got
    the chance, and recording nine failures for one fault buries it.
  * Ordering is checked where ordering is the evidence. The markers that show
    real userspace — `Reached target Basic System`, a graphical target — also
    appear in the initramfs' own systemd. What distinguishes them is that they
    come *after* the switch. So those checkpoints require their match to fall
    later in the log than the switch-root line, and a boot that never switched
    cannot satisfy them by matching initramfs output.
  * A checkpoint whose evidence is an image says so. It is reported PASS only
    on a measurement (the frame is not blank), and its `needsLook` flag stays
    set, because a measurement can tell a rendered interface from a black
    screen and cannot tell it from the wrong interface.

Usage:
    classify-boot-checkpoints.py --serial LOG --screens DIR
                                 --harness-outcome NAME --json REPORT
Exit status: 0 when every checkpoint passed, 2 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Checkpoint(NamedTuple):
    name: str
    title: str
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    after: str | None       # must match later in the log than this checkpoint's line
    screenshot: str | None  # a frame recorded beside this checkpoint
    # What the frame is worth as evidence. Three roles, because the three cases
    # are genuinely different and collapsing them gets two checkpoints wrong:
    #
    #   supporting  recorded, never changes the verdict. BOOT-1 is answered by
    #               output of any kind; a machine that started and produced no
    #               video has not failed to start, and failing it there would
    #               name the wrong rung.
    #   sufficient  a non-blank frame establishes the checkpoint on its own.
    #               BOOT-2 needs this and it is not a convenience: GRUB renders
    #               to the video console and writes nothing at all to serial, so
    #               a checkpoint requiring a serial match would fail on every
    #               correct boot. The corroboration is BOOT-3 — the kernel only
    #               starts because a menu entry was selected, and a menu that
    #               was not there could not have been navigated.
    #   required    both halves. BOOT-9 has serial evidence that a session
    #               started and frame evidence that something drew, and neither
    #               alone is the claim being made.
    screenshot_role: str
    note: str


# The switch is the hinge of the whole sequence: before it, every systemd marker
# comes from the initramfs, and after it from the real root. It is named here so
# the later checkpoints can require ordering against it.
SWITCH = "BOOT-6"

CHECKPOINTS: tuple[Checkpoint, ...] = (
    Checkpoint(
        "BOOT-1", "firmware starts the medium",
        positive=(r"SeaBIOS|BdsDxe|EFI |Booting from|Press \[Tab\]|GNU GRUB|"
                  r"Loading Linux|Linux version",),
        negative=(),
        after=None, screenshot="01-grub-menu", screenshot_role="supporting",
        note="Any output at all — from the firmware, the bootloader or the "
             "kernel — means the machine started the medium. The screenshot is "
             "the independent half: firmware that renders nothing and says "
             "nothing has not started anything.",
    ),
    Checkpoint(
        "BOOT-2", "GRUB renders its menu",
        positive=(r"GNU GRUB|Try or Install Bunny OS",),
        negative=(r"error: no such device|error: file .* not found|"
                  r"Entering rescue mode",),
        after=None, screenshot="01-grub-menu", screenshot_role="sufficient",
        note="GRUB draws to the video console and not to serial, so the "
             "screenshot taken before the first keypress is the primary "
             "evidence. The corroboration is BOOT-3: the kernel only starts "
             "because four Downs and a Return selected an entry, and a menu "
             "that was not there could not have been navigated.",
    ),
    Checkpoint(
        "BOOT-3", "the kernel starts",
        positive=(r"Linux version \S+",),
        negative=(r"Kernel panic|not syncing:",),
        after=None, screenshot=None, screenshot_role="none",
        note="The kernel banner on the serial console. It appears only on the "
             "entry that carries console=ttyS0, which is the one this harness "
             "selects; its absence on other entries is the harness's doing and "
             "not the medium's.",
    ),
    Checkpoint(
        "BOOT-4", "the initramfs starts and does not fail to find a live root",
        positive=(r"dracut-cmdline|dracut-pre-udev|dracut-initqueue|"
                  r"Reached target .*[Ii]nitrd|running in initrd",),
        negative=(r"Entering emergency mode|You are in emergency mode|"
                  r"dracut-initqueue.*[Tt]imeout|"
                  r"Warning: /dev/disk/by-label/.* does not exist|"
                  r"Warning: Could not boot|"
                  r"Failed to find a root filesystem|"
                  r"Cannot find (a )?root",),
        after=None, screenshot=None, screenshot_role="none",
        note="The failure this whole repair is about lands here. Every negative "
             "pattern is a way the initramfs says it has no root to switch to: "
             "the by-label warning is what a CDLABEL that matches nothing "
             "produces, and 'Failed to find a root filesystem' is "
             "dmsquash-live-root.sh's own die() when the squashfs is not a "
             "shape it can use.",
    ),
    Checkpoint(
        "BOOT-5", "the live root is located",
        positive=(r"root was live:.*is now|"
                  r"Mounted /run/initramfs/live|"
                  r"Mounting /sysroot|Mounted /sysroot|"
                  r"Reached target .*Initrd Root File System|"
                  r"initrd-root-fs\.target",),
        negative=(r"Failed to mount /sysroot|Timed out waiting for device|"
                  r"Dependency failed for /sysroot",),
        after=None, screenshot=None, screenshot_role="none",
        note="parse-dmsquash-live.sh prints 'root was live:CDLABEL=…, is now "
             "live:/dev/disk/by-label/…' when it rewrites the argument, which "
             "is the most direct statement that the module read the command "
             "line. The /sysroot mount is the same fact one step later and "
             "survives a quieter console.",
    ),
    Checkpoint(
        "BOOT-6", "initrd-switch-root.service succeeds",
        positive=(r"Starting Switch Root|Switching root|initrd-switch-root",),
        negative=(r"Failed to start initrd-switch-root|"
                  r"Failed to start Switch Root|"
                  r"initrd-switch-root\.service: Failed",),
        after=None, screenshot=None, screenshot_role="none",
        note="The exact line the first boot of this medium showed on screen was "
             "'Failed to start initrd-switch-root.service'. Reaching the "
             "service is not the same as succeeding at it, which is why BOOT-7 "
             "does not take this checkpoint's word for it and requires real-root "
             "output positioned after this line.",
    ),
    Checkpoint(
        "BOOT-7", "real userspace is PID 1",
        positive=(r"Reached target .*(Basic System|basic\.target|"
                  r"Multi-User System|multi-user\.target)|"
                  r"Starting (NetworkManager|D-Bus System Message Bus)|"
                  r"Started (D-Bus System Message Bus|Permit User Sessions)",),
        negative=(r"Freezing execution|Kernel panic|"
                  r"Failed to execute /init|Failed to switch root",),
        after=SWITCH, screenshot=None, screenshot_role="none",
        note="Every one of these markers can also be produced by the systemd "
             "inside the initramfs, so the pattern alone proves nothing. What "
             "proves it is position: the match has to fall after the switch, "
             "and this is the only reason ordering is modelled at all.",
    ),
    Checkpoint(
        "BOOT-8", "the graphical target starts",
        positive=(r"Reached target .*(Graphical Interface|graphical\.target)|"
                  r"Started GNOME Display Manager|Starting GNOME Display Manager",),
        negative=(r"Failed to start GNOME Display Manager|"
                  r"gdm.*Failed to start|Dependency failed for .*[Gg]raphical",),
        after=SWITCH, screenshot=None, screenshot_role="none",
        note="GDM is configured for automatic login as bunny-live by "
             "installer/config/gdm-live.conf, so the display manager starting "
             "is the step before a session exists rather than a prompt.",
    ),
    Checkpoint(
        "BOOT-9", "the Bunny setup surface appears",
        # The two Bunny units the surface cannot exist without, not the generic
        # session markers this checkpoint asked for first. `Started Session N of
        # User bunny-live` and `user-1000.slice` never appear on the console:
        # systemd stops printing status once graphical.target is reached, and
        # the autologin session starts after that. So a checkpoint waiting for
        # them waits for something the console will not carry, and run 11 —
        # which reached the setup surface — was reported as a failure.
        #
        # bunny-live-session.service creates the live account; without it there
        # is nobody for GDM to log in. bunny-installer-backend.service is the
        # privileged half the surface talks to; without it the surface draws and
        # finds no backend. Both are Bunny's own, both are on the console, and
        # both are prerequisites rather than proxies.
        # No `\.service` suffix, because systemd truncates its status lines to
        # the console width and elides the middle:
        #
        #   [  OK  ] Finished bunny-live-session.servic…he ephemeral Bunny OS live session.
        #   [  OK  ] Started bunny-installer-backend.se… - Bunny OS live installer backend.
        #
        # A pattern ending in `.service` matches the kmsg copy and not the
        # console one, and the kmsg copy is only there when the journal is
        # forwarded. Run 11 reached the setup surface and was reported a failure
        # for exactly that reason.
        positive=(r"Finished bunny-live-session|"
                  r"Started bunny-installer-backend|"
                  r"Started Session \d+ of User bunny-live|"
                  r"Started User Manager for UID|"
                  r"BunnyInstaller|bunny-setup",),
        negative=(r"Failed to start bunny-live-session|"
                  r"Failed to start bunny-installer-backend|"
                  r"Dependency failed for bunny-instal|"
                  r"gdm-autologin.*failed|"
                  r"Failed to start User Manager|"
                  r"oh no! something has gone wrong",),
        after=SWITCH, screenshot="03-session", screenshot_role="required",
        note="Half of this is unavoidably visual: units that started are not the "
             "same as a window that drew. The serial half establishes that the "
             "live account exists and the installer backend is listening; the "
             "frame establishes that the screen is not blank. Neither says the "
             "surface is the *right* one — a display manager's login screen is "
             "also not blank — so this checkpoint keeps needsLook set and the "
             "phase is not closed on it without somebody opening the png.",
    ),
)


# systemd writes each message to the console twice: once through kmsg as plain
# text (`[    3.644867] systemd[1]: Reached target …`) and once as its own status
# output, coloured — `Failed to start \x1b[0;1;39minitrd-switch-root.service\x1b[0m`.
# A pattern reading `Failed to start initrd-switch-root` matches the first copy
# and not the second, which is survivable only for as long as both copies keep
# appearing. Stripping the escapes first makes every pattern work on either, and
# makes the line quoted back in the report readable instead of full of \x1b.
ANSI = re.compile(r"\x1b\[[0-9;?=<>]*[A-Za-z]|\x1b[()][A-B0-9]|\x1b[]][^\x07\x1b]*"
                  r"(?:\x07|\x1b\\)?|[\x00-\x08\x0b\x0c\x0e-\x1f]")


def load_lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", "replace")
    return [ANSI.sub("", line).rstrip() for line in text.splitlines()]


def excerpt(line: str, match: re.Match | None, width: int = 110) -> str:
    """The part of a line around the match, rather than the start of it.

    GRUB positions its cursor with escape sequences and emits no newline, so
    once the escapes are stripped its entire screen — and the first of the
    kernel's output after it — is a single line thousands of characters long.
    Quoting the beginning of that line reported the kernel's start as
    "Press enter to boot the selected OS", which is not evidence of anything.
    """
    if match is None:
        return line[:width].strip()
    start = max(0, match.start() - width // 4)
    end = min(len(line), match.end() + width)
    text = line[start:end].strip()
    return ("…" if start > 0 else "") + text + ("…" if end < len(line) else "")


def first_match(lines: list[str], patterns: tuple[str, ...],
                after_index: int | None) -> tuple[int, str] | None:
    if not patterns:
        return None
    combined = re.compile("|".join(patterns))
    start = 0 if after_index is None else after_index + 1
    for index in range(start, len(lines)):
        found = combined.search(lines[index])
        if found:
            return index, excerpt(lines[index], found)
    return None


def screen_evidence(screens: Path, name: str | None) -> dict | None:
    if name is None:
        return None
    stats = screens / f"{name}.stats.json"
    image = screens / f"{name}.png"
    record: dict = {"image": str(image) if image.exists() else None,
                    "stats": None, "blank": None}
    if stats.exists():
        try:
            loaded = json.loads(stats.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return record
        record["stats"] = loaded
        record["blank"] = loaded.get("blank")
    return record


def _frame_complaint(checkpoint: Checkpoint, screen: dict | None) -> str:
    if screen is None or screen.get("stats") is None:
        return (f"no frame was captured as {checkpoint.screenshot}, and this "
                "checkpoint has no other evidence")
    if screen.get("blank") is True:
        return f"the captured frame {checkpoint.screenshot} is blank"
    return f"the frame {checkpoint.screenshot} could not be measured"


def classify(serial: Path, screens: Path, harness_outcome: str) -> dict:
    lines = load_lines(serial)
    results: list[dict] = []
    indices: dict[str, int] = {}
    already_failed = False

    for checkpoint in CHECKPOINTS:
        after_index = indices.get(checkpoint.after) if checkpoint.after else None
        screen = screen_evidence(screens, checkpoint.screenshot)
        if checkpoint.after and after_index is None:
            # The checkpoint it depends on never matched, so a match here cannot
            # be positioned and cannot be trusted.
            status, matched, negative = "NOT-REACHED", None, None
        elif already_failed:
            status, matched, negative = "NOT-REACHED", None, None
        else:
            negative_hit = first_match(lines, checkpoint.negative, None)
            positive_hit = first_match(lines, checkpoint.positive, after_index)
            screen = screen_evidence(screens, checkpoint.screenshot)
            frame_shows_content = (
                checkpoint.screenshot_role in {"sufficient", "required"}
                and screen is not None and screen.get("blank") is False
            )

            if negative_hit is not None:
                status, matched = "FAIL", None
                negative = {"line": negative_hit[0] + 1, "text": negative_hit[1]}
            elif checkpoint.screenshot_role == "required":
                if positive_hit is None:
                    status, matched, negative = "FAIL", None, None
                elif not frame_shows_content:
                    status = "FAIL"
                    matched = {"line": positive_hit[0] + 1, "text": positive_hit[1]}
                    negative = {"line": None, "text": _frame_complaint(checkpoint, screen)}
                else:
                    status = "PASS"
                    matched = {"line": positive_hit[0] + 1, "text": positive_hit[1]}
                    negative = None
                    indices[checkpoint.name] = positive_hit[0]
            elif positive_hit is not None:
                status = "PASS"
                matched = {"line": positive_hit[0] + 1, "text": positive_hit[1]}
                negative = None
                indices[checkpoint.name] = positive_hit[0]
            elif frame_shows_content:
                # The serial console said nothing, and for this checkpoint it
                # was never going to. GRUB is the case: it renders to video and
                # writes no byte to ttyS0, so requiring a serial match here
                # would fail every correct boot there has ever been.
                status = "PASS"
                matched = {"line": None,
                           "text": f"no serial evidence; established by the frame "
                                   f"{checkpoint.screenshot}"}
                negative = None
            else:
                status, matched, negative = "FAIL", None, None
                if checkpoint.screenshot_role == "sufficient":
                    negative = {"line": None, "text": _frame_complaint(checkpoint, screen)}

        if status == "FAIL":
            already_failed = True

        results.append({
            "checkpoint": checkpoint.name,
            "title": checkpoint.title,
            "status": status,
            "matched": matched,
            "refutedBy": negative,
            "screen": screen,
            "screenshotRole": checkpoint.screenshot_role,
            # A measurement can tell a rendered interface from a black screen.
            # It cannot tell it from the wrong interface, so anything resting on
            # a frame keeps asking for somebody to open the png.
            "needsLook": checkpoint.screenshot_role in {"sufficient", "required"},
            "note": checkpoint.note,
        })

    passed = [r for r in results if r["status"] == "PASS"]
    reached = results[len(passed) - 1]["checkpoint"] if passed else None
    return {
        "schemaVersion": 1,
        "serialLines": len(lines),
        "harnessOutcome": harness_outcome,
        "reached": reached,
        "checkpoints": results,
        "status": "PASS" if len(passed) == len(CHECKPOINTS) else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, type=Path)
    parser.add_argument("--screens", required=True, type=Path)
    parser.add_argument("--harness-outcome", default="unknown")
    parser.add_argument("--json", type=Path, default=None)
    arguments = parser.parse_args(argv)

    if not arguments.serial.exists():
        print(f"FAIL: no serial log at {arguments.serial}", file=sys.stderr)
        return 2

    report = classify(arguments.serial, arguments.screens, arguments.harness_outcome)
    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print("")
    print(f"boot chain  ({report['serialLines']} serial lines, "
          f"harness outcome: {report['harnessOutcome']})")
    print("")
    for result in report["checkpoints"]:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "NOT-REACHED": "----"}[result["status"]]
        print(f"  [{mark}] {result['checkpoint']}  {result['title']}")
        if result["matched"]:
            print(f"           line {result['matched']['line']}: "
                  f"{result['matched']['text'][:110]}")
        if result["refutedBy"]:
            where = (f"line {result['refutedBy']['line']}: "
                     if result["refutedBy"]["line"] else "")
            print(f"           refuted by {where}{result['refutedBy']['text'][:110]}")
        if result["status"] == "FAIL" and not result["refutedBy"]:
            print("           no evidence of this stage in the serial log")
        if result["screen"] and result["screen"].get("stats"):
            stats = result["screen"]["stats"]
            print(f"           frame: {stats.get('distinctColours')} colours, "
                  f"sd {stats.get('standardDeviation')}, blank={stats.get('blank')}")
    print("")
    if report["status"] == "PASS":
        print("PASS: the medium reached BOOT-9.")
        print("      BOOT-2 and BOOT-9 rest partly on frames. Open the png "
              "before calling the phase closed:")
        for result in report["checkpoints"]:
            if result["needsLook"] and result["screen"] and result["screen"]["image"]:
                print(f"        {result['screen']['image']}")
        return 0
    print(f"FAIL: the medium reached {report['reached'] or 'nothing'}.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
