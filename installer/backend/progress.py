# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map what the installer is doing onto what Bunny says it is doing.

There are two stage vocabularies in this tree and they are both correct.

`installer.backend.state.STAGES` has twelve entries and is the *engine's*:
Partitioning, Encrypting, Creating filesystems, Installing bootloader. It exists
so that `InstallationState.destructive_write_started` can be answered exactly —
`WRITE_BOUNDARY` is an index into it — and that answer decides whether a failure
screen says "your data is unchanged" or "your data is gone".

`installer.companion_flow.PROGRESS_STAGES` has seven and is the *person's*:
Getting the disk ready, Copying the system, Setting up security. §23 asks that
the progress screen use real installer states, and it also asks that the
experience be understandable by a nontechnical person. Seven plain phrases are
that; "Installing bootloader" is not.

Without a mapping the two drift, and the drift is invisible: the Companion says
"Copying the system" while the engine formats a partition, and nobody can tell
because both are plausible. :data:`STAGE_TO_PROGRESS` is total over the engine's
stages and :func:`_assert_total` fails at import if a stage is ever added to one
without the other.

**There is no percentage here.** `InstallationState.percent` exists and this
module does not use it, because a fraction computed from a stage index is a
number that moves smoothly while nothing is known about how long a stage takes.
§23 is explicit: if only stage progress exists, show stage progress.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from installer.backend.state import STAGES, WRITE_BOUNDARY
from installer.companion_flow import PROGRESS_STAGES

__all__ = ["STAGE_TO_PROGRESS", "progress_rows", "companion_phase_for"]

#: Engine stage -> the person's stage key. Every entry of `STAGES` appears.
STAGE_TO_PROGRESS: Mapping[str, str] = {
    "Preparing": "prepare",
    "Validating storage": "prepare",
    "Partitioning": "prepare",
    "Encrypting": "security",
    "Creating filesystems": "prepare",
    "Deploying Bunny OS": "copy",
    "Installing bootloader": "security",
    "Creating user": "user",
    "Installing recovery": "capsules",
    "Configuring hardware": "preferences",
    "Final verification": "finalise",
    "Complete": "finalise",
}


def _assert_total() -> None:
    missing = [stage for stage in STAGES if stage not in STAGE_TO_PROGRESS]
    if missing:
        raise RuntimeError(
            "installer.backend.progress does not map every engine stage; "
            f"missing: {missing}"
        )
    unknown = sorted(set(STAGE_TO_PROGRESS.values()) - {key for key, _ in PROGRESS_STAGES})
    if unknown:
        raise RuntimeError(
            "installer.backend.progress maps to stages the Companion does not "
            f"show: {unknown}"
        )


_assert_total()

#: Where the engine's stages sit relative to the first write, so the Companion
#: can be honest about whether anything has happened to the disk yet.
_ORDER = {name: index for index, name in enumerate(STAGES)}


def progress_rows(engine_stage: str) -> tuple[dict[str, Any], ...]:
    """`PROGRESS_STAGES` with a status each, from the engine's current stage.

    A person's stage is ``done`` only when *every* engine stage that maps to it
    is behind us. Encryption maps to "Setting up security" and so does the
    bootloader; marking security done when LUKS finished would show a completed
    step while the thing that makes the machine bootable had not started.
    """
    current = _ORDER.get(engine_stage, 0)
    rows: list[dict[str, Any]] = []
    for key, label in PROGRESS_STAGES:
        indices = [_ORDER[name] for name, mapped in STAGE_TO_PROGRESS.items()
                   if mapped == key]
        if not indices:
            status = "waiting"
        elif current > max(indices):
            status = "done"
        elif current >= min(indices):
            status = "active"
        else:
            status = "waiting"
        rows.append({"key": key, "label": label, "status": status})
    return tuple(rows)


def companion_phase_for(status: str, engine_stage: str) -> str:
    """The `companion.presentation` phase this installer state puts Bunny in.

    §6 requires the Companion's setup states to derive from installer state, and
    this is that derivation — one function, no caller choosing a face. In
    particular there is no cheerful phase reachable from a failure and no
    "working" phase reachable from a stopped install.
    """
    if status == "failed":
        return "error"
    if status == "cancelled":
        return "cancelled"
    if status == "complete":
        return "success"
    if status != "installing":
        return "planning"
    # Past the write boundary the machine is committed; before it, nothing has
    # happened to the disk yet and Bunny is still preparing.
    if _ORDER.get(engine_stage, 0) >= WRITE_BOUNDARY:
        return "working"
    return "planning"
