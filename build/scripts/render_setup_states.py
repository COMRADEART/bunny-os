#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render every setup screen to JSON, for the story harness to draw.

## Why a generated file rather than a JavaScript copy

The setup screens are built in Python, because the authorities they read are
Python: `installer.storage.safety` decides what is dangerous,
`installer.companion_flow` decides what Bunny says, `catalog.selection` decides
what an application costs. The story harness is JavaScript, because it renders
the same St stylesheet the desktop does.

There are two ways to bridge that. One is to write the screens again in
JavaScript, which is the thing `installer/companion_flow.py` opens by warning
against: *"a copy of the wording in each program is a copy that drifts, and the
sentence a person reads before they let a disk be erased is not a sentence that
should exist in two versions."* The other is to generate, which is what
`shell/themes/tokens.json` already does in the opposite direction — tokens are
authored in JavaScript and generated for the Python consumers.

So this generates, and `tests/installer/test_setup_states.py` re-runs it and
fails if the committed file differs. A stale story is then a failing test rather
than a screen nobody noticed had changed.

## The fixtures

Two of everything that can be long. §35 asks the harness to test long strings,
and the failure mode it is looking for is a container sized around a plausible
value: a disk called ``QEMU HARDDISK`` fits anywhere, and a disk called
``Samsung SSD 990 PRO with Heatsink 4TB`` is the one that clips the sentence
saying what is about to be erased.

    python build/scripts/render_setup_states.py
        -> qualification/installer/setup-states.json
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog.registry import load_catalog                      # noqa: E402
from catalog.selection import MachineFacts, choices_for        # noqa: E402
from installer.companion_flow import PROGRESS_STAGES           # noqa: E402
from installer.setup_view import (                             # noqa: E402
    accessibility_screen,
    account_screen,
    appearance_screen,
    apps_screen,
    companion_screen,
    complete_screen,
    confirm_erase_screen,
    encryption_screen,
    failure_screen,
    first_boot_screen,
    installing_screen,
    keyboard_screen,
    language_screen,
    network_screen,
    privacy_screen,
    review_screen,
    storage_screen,
    welcome_screen,
)
from installer.storage.models import DiskInfo, ExistingOS, PartitionInfo  # noqa: E402
from installer.hardware.preflight import MINIMUM_SETUP_DISPLAY  # noqa: E402
from installer.storage.safety import assess_target             # noqa: E402
from installer.theme_css import render_gtk_css, resolve, theme_key  # noqa: E402

OUTPUT = ROOT / "qualification" / "installer" / "setup-states.json"

#: The configurations §35 asks the harness to render: dark and light, 200 % text,
#: high contrast in both schemes, and reduced motion. The story harness renders
#: exactly these and fails if one is absent, so adding a configuration there
#: without regenerating here is a visible error rather than an unstyled panel.
STORY_THEMES = (
    ("dark", {"scheme": "dark"}),
    ("light", {"scheme": "light"}),
    ("dark @200%", {"scheme": "dark", "text_scale": 2.0}),
    ("light @200%", {"scheme": "light", "text_scale": 2.0}),
    ("high contrast dark", {"scheme": "dark", "high_contrast": True}),
    ("high contrast light", {"scheme": "light", "high_contrast": True}),
    ("dark, reduced motion", {"scheme": "dark", "reduced_motion": True}),
)


# ------------------------------------------------------------------ fixtures

#: The disposable virtual disk the §42 harness installs onto. This is the disk a
#: qualification run actually sees, so it is the one the story draws.
TARGET = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05",
    devicePath="/dev/vda",
    sizeBytes=80 * 1024**3,
    logicalSectorSize=512,
    physicalSectorSize=512,
    removable=False,
    readOnly=False,
    model="QEMU HARDDISK",
    serialRedacted="sha256:0a1b2c3d4e5f",
    rotational=False,
    transport="virtio",
    partitions=(),
)

#: The same screen with every string at the length a real machine can produce.
#: A 4 TB retail SSD with an existing Windows installation is not an edge case,
#: and the sentence naming it is the sentence §11 forbids hiding.
LONG_TARGET = DiskInfo(
    id="disk-9e8d7c6b5a4f3210",
    devicePath="/dev/nvme0n1",
    sizeBytes=4000 * 1000**3,
    logicalSectorSize=4096,
    physicalSectorSize=4096,
    removable=False,
    readOnly=False,
    model="Samsung SSD 990 PRO with Heatsink 4TB",
    serialRedacted="sha256:9f8e7d6c5b4a",
    rotational=False,
    transport="nvme",
    partitions=(
        PartitionInfo(
            id="part-aaa1", devicePath="/dev/nvme0n1p1", sizeBytes=260 * 1024**2,
            filesystem="vfat", label="SYSTEM", partLabel="EFI system partition",
        ),
        PartitionInfo(
            id="part-aaa2", devicePath="/dev/nvme0n1p3", sizeBytes=3800 * 1000**3,
            filesystem="ntfs", label="Windows — Local Disk with a very long volume label",
        ),
    ),
    existingOperatingSystems=(
        ExistingOS("windows", "Windows 11 Professional — Local Disk", False),
    ),
)

#: A disk that must appear in the list and must not be selectable: the stick the
#: installer is running from. §11's rule is that consequences are never hidden,
#: and a disk that disappears is a consequence hidden by omission.
MEDIA = DiskInfo(
    id="disk-000011112222aaaa",
    devicePath="/dev/sdb",
    sizeBytes=32 * 1024**3,
    logicalSectorSize=512,
    physicalSectorSize=512,
    removable=True,
    readOnly=False,
    model="SanDisk Ultra USB 3.0",
    partitions=(
        PartitionInfo(id="part-bbb1", devicePath="/dev/sdb1", sizeBytes=32 * 1024**3,
                      filesystem="iso9660", label="Bunny-OS-Alpha", installationMedia=True),
    ),
    installationMedia=True,
)

DISKS = (TARGET, LONG_TARGET, MEDIA)
FINDINGS = {disk.id: assess_target(disk, mode="erase_disk", on_ac_power=True) for disk in DISKS}

SUMMARY = (
    ("Language", "English (United Kingdom)"),
    ("Region and time zone", "United Kingdom · Europe/London"),
    ("Keyboard", "English (UK)"),
    ("Install to", "QEMU HARDDISK — 80.0 GiB — /dev/vda"),
    ("What happens to it", "Erased completely"),
    ("Encryption", "On, with a passphrase and a recovery key"),
    ("Account", "Alex (alex), administrator"),
    ("Privacy", "Everything off"),
    ("Appearance", "Light, violet accent"),
    ("Bunny", "Full, captions on, starts at login"),
    ("Apps", "LibreOffice"),
)

LONG_SUMMARY = tuple(
    (label, value if label != "Install to"
     else "Samsung SSD 990 PRO with Heatsink 4TB — 3725.3 GiB — /dev/nvme0n1")
    for label, value in SUMMARY
) + (
    ("What is lost", "An existing installation of: Windows 11 Professional — Local Disk"),
)


def _progress(active_index: int) -> list[dict[str, object]]:
    """`PROGRESS_STAGES` with a status each. Never a percentage — §23."""
    rows: list[dict[str, object]] = []
    for index, (key, label) in enumerate(PROGRESS_STAGES):
        status = "done" if index < active_index else "active" if index == active_index else "waiting"
        rows.append({"key": key, "label": label, "status": status})
    return rows


def _app_choices() -> list[dict[str, object]]:
    """Real catalogue records, so the honest labels are the catalogue's own."""
    registry = load_catalog()
    facts = MachineFacts(memory_bytes=8 * 1024**3, free_disk_bytes=70 * 1024**3, online=True)
    seen: dict[str, dict[str, object]] = {}
    for capability in ("write-document", "resize-image"):
        for choice in choices_for(capability, registry, machine=facts).choices:
            record = dict(choice.as_record())
            seen.setdefault(str(record["entryId"]), record)
    return sorted(seen.values(), key=lambda item: str(item["name"]))


def build() -> dict[str, object]:
    apps = _app_choices()
    screens = [
        ("welcome", welcome_screen()),
        ("language_region", language_screen(detected={"source": "Detected from the keyboard firmware: English (UK)."})),
        ("keyboard", keyboard_screen(layout="gb")),
        ("accessibility", accessibility_screen()),
        ("accessibility — all on", accessibility_screen(current={
            "textScale": 2.0, "highContrast": True, "reducedMotion": True,
            "screenReader": True, "captions": True, "companionTextOnly": True,
        })),
        ("network", network_screen(connected=False, networks=("Home", "Home-5G", "Coffee shop guest network"))),
        ("storage", storage_screen(disks=DISKS, selected=TARGET, findings=FINDINGS)),
        ("storage — long names, existing OS", storage_screen(disks=DISKS, selected=LONG_TARGET, findings=FINDINGS)),
        ("confirm_erase", confirm_erase_screen(disk=TARGET, encrypted=True)),
        ("confirm_erase — existing Windows", confirm_erase_screen(disk=LONG_TARGET, encrypted=True)),
        ("encryption", encryption_screen()),
        ("account", account_screen(display_name="Alex", username="alex", device_name="alex-laptop")),
        ("account — validation errors", account_screen(
            display_name="Alex", username="root",
            errors=("That username is reserved by the system. Try another one.",
                    "The two passwords are not the same."))),
        ("privacy", privacy_screen()),
        ("appearance", appearance_screen(scheme="light")),
        ("companion_behaviour", companion_screen()),
        ("applications", apps_screen(activities=("everyday", "office"), choices=apps)),
        ("review", review_screen(summary=SUMMARY, disk=TARGET, encrypted=True)),
        ("review — long", review_screen(summary=LONG_SUMMARY, disk=LONG_TARGET, encrypted=True)),
        ("installing", installing_screen(stages=_progress(1), current="copy",
                                         detail="Copying the system to /dev/vda")),
        ("installing — last stage", installing_screen(stages=_progress(6), current="finalise")),
        ("failure — before any write", failure_screen(
            headline="The disk is smaller than Bunny OS needs.",
            explanation="Bunny OS needs at least 40 GiB and this disk has 16 GiB.",
            stage_key="Getting the disk ready", wrote_to_disk=False)),
        ("failure — after a write", failure_screen(
            headline="Copying the system stopped part way through.",
            explanation="The installer could not read the rest of the image from the "
                        "installation media. This usually means the media is damaged.",
            stage_key="Copying the system", wrote_to_disk=True,
            diagnostics_path="/run/bunny-installer/diagnostics/install-2026-08-12.log")),
        ("complete", complete_screen(name="Alex")),
        ("first_boot", first_boot_screen(name="Alex")),
        ("first_boot — long name", first_boot_screen(
            name="Alexandra Bartholomew-Fitzgerald III")),
    ]
    # The stylesheet the setup surface actually ships, per configuration, so the
    # story draws the real CSS rather than an approximation of it.
    stylesheets = {}
    for name, options in STORY_THEMES:
        theme = resolve(**options)
        stylesheets[name] = {
            "key": theme_key(**options),
            "textScale": theme["textScale"],
            "highContrast": theme["highContrast"],
            "reducedMotion": theme["reducedMotion"],
            "cardWidth": theme["metric"]["cardWidth"],
            "css": render_gtk_css(theme),
        }

    return {
        "schemaVersion": 1,
        "note": (
            "Generated by build/scripts/render_setup_states.py from the real screen "
            "builders in installer/setup_view.py and the real GTK stylesheet renderer "
            "in installer/theme_css.py. Do not edit by hand; "
            "tests/installer/test_setup_states.py fails if this file is stale."
        ),
        "minimumDisplay": dict(MINIMUM_SETUP_DISPLAY),
        "progressStages": [{"key": key, "label": label} for key, label in PROGRESS_STAGES],
        "stylesheets": stylesheets,
        "screens": [{"title": title, **screen.as_record()} for title, screen in screens],
    }


def main() -> int:
    document = json.dumps(build(), indent=1, sort_keys=False, ensure_ascii=False) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {OUTPUT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
