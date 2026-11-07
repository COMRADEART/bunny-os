# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collapsible task rail projected from Companion presentation fields only.

The rail never invents progress percentages, success, or stages. It draws what
``companion.presentation`` already projected: phase, captions, stages the
runtime named, approvals, files, warnings, and disconnect.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Keep aligned with companion.presentation.PRESENTATION_PHASES / shell taskState.
# Approval and error outrank ordinary work (Adaptive Hybrid Spec §6.3).
PHASE_PRIORITY = (
    "error",
    "blocked",
    "waiting_for_approval",
    "waiting_for_permission",
    "disconnected",
    "cancelling",
    "cancelled",
    "paused",
    "listening",
    "speaking",
    "understanding",
    "planning",
    "working",
    "reviewing",
    "presenting_result",
    "success",
    "starting",
    "recovering",
    "idle",
)

PHASE_LABELS = {
    "idle": "Ready",
    "starting": "Starting",
    "recovering": "Reconnecting",
    "understanding": "Understanding",
    "planning": "Planning",
    "waiting_for_approval": "Permission needed",
    "waiting_for_permission": "Permission needed",
    "listening": "Listening",
    "transcribing": "Listening",
    "speaking": "Speaking",
    "working": "Working",
    "reviewing": "Verifying",
    "presenting_result": "Presenting",
    "success": "Completed",
    "cancelling": "Stopping",
    "cancelled": "Cancelled",
    "paused": "Paused",
    "blocked": "Needs attention",
    "error": "Could not complete",
    "disconnected": "Disconnected",
}

ATTENTION_PHASES = frozenset(
    {
        "waiting_for_approval",
        "waiting_for_permission",
        "error",
        "blocked",
        "disconnected",
    }
)


def _text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_task_rail(
    presentation: Mapping[str, Any] | None,
    *,
    collapsed: bool = False,
    layout: str = "focus",
) -> dict[str, Any]:
    """Build a rail model from a presentation projection (or empty idle).

    ``presentation`` is expected to look like PresentationState.to_json() or a
    minimal subset: phase, caption/status, stages, stageIndex, percent (only if
    measured), taskId, sequence, approvals, files, warnings, disconnected.
    """
    data = dict(presentation or {})
    phase = str(data.get("phase") or data.get("basePhase") or "idle")
    if phase not in PHASE_LABELS:
        phase = "idle"

    caption = _text(data.get("caption") or data.get("status") or data.get("detail") or "")
    stages_raw = data.get("stages") or []
    if not isinstance(stages_raw, Sequence) or isinstance(stages_raw, (str, bytes)):
        stages_raw = []
    stage_index = data.get("stageIndex")
    if not isinstance(stage_index, int):
        stage_index = -1

    # Percent only when the runtime supplied a finite number — never invented.
    percent = data.get("percent")
    if not isinstance(percent, (int, float)) or isinstance(percent, bool):
        percent = None
    else:
        percent = max(0, min(100, float(percent)))

    stages: list[dict[str, Any]] = []
    for index, entry in enumerate(stages_raw):
        if isinstance(entry, Mapping):
            name = _text(entry.get("name") or entry.get("label") or "", limit=80)
            state = str(entry.get("state") or "")
        else:
            name = _text(entry, limit=80)
            state = ""
        if not name:
            continue
        if state in {"done", "current", "pending", "failed", "refused"}:
            glyph = state
        elif stage_index >= 0 and index < stage_index:
            glyph = "done"
        elif index == stage_index:
            glyph = "current"
        else:
            glyph = "pending"
        stages.append({"name": name, "glyph": glyph, "index": index})

    files_raw = data.get("files") or data.get("outputs") or []
    files: list[str] = []
    if isinstance(files_raw, Sequence) and not isinstance(files_raw, (str, bytes)):
        for item in files_raw:
            if isinstance(item, Mapping):
                display = _text(item.get("display") or item.get("path") or "", limit=120)
            else:
                display = _text(item, limit=120)
            if display:
                files.append(display)

    warnings_raw = data.get("warnings") or data.get("reviewWarnings") or []
    warnings: list[str] = []
    if isinstance(warnings_raw, Sequence) and not isinstance(warnings_raw, (str, bytes)):
        warnings = [_text(item, limit=160) for item in warnings_raw if _text(item)]

    approval = data.get("approval") or data.get("outstandingApproval")
    approval_model = None
    if isinstance(approval, Mapping) and approval:
        approval_model = {
            "id": _text(approval.get("id") or approval.get("approvalId") or "", limit=80),
            "summary": _text(approval.get("summary") or approval.get("title") or caption, limit=160),
            "persistent": True,
        }
    elif phase in {"waiting_for_approval", "waiting_for_permission"}:
        approval_model = {
            "id": _text(data.get("approvalId") or "", limit=80),
            "summary": caption or "Bunny needs your permission.",
            "persistent": True,
        }

    disconnected = bool(data.get("disconnected")) or phase == "disconnected"
    label = PHASE_LABELS.get(phase, "Ready")
    attention = phase in ATTENTION_PHASES or disconnected

    actions: list[dict[str, str]] = []
    if phase not in {"idle", "success", "cancelled", "error"}:
        actions.append({"id": "pause", "label": "Pause"})
        actions.append({"id": "cancel", "label": "Cancel"})
    if approval_model:
        actions = [
            {"id": "open-trust", "label": "Open Trust"},
            {"id": "cancel", "label": "Cancel"},
        ]
    if disconnected:
        actions = [{"id": "reconnect-info", "label": "What happened?"}]

    return {
        "schema": "bunny.task-rail/1",
        "layout": layout,
        "collapsed": bool(collapsed),
        "taskId": _text(data.get("taskId") or "", limit=80),
        "sequence": data.get("sequence") if isinstance(data.get("sequence"), int) else None,
        "phase": phase,
        "label": label,
        "caption": caption,
        "stages": stages,
        "percent": percent,
        "files": files,
        "warnings": warnings,
        "approval": approval_model,
        "attention": attention,
        "disconnected": disconnected,
        "actions": actions,
        # Screen-reader phrase — single announcement, no invented progress.
        "announcement": ". ".join(
            part
            for part in (
                label,
                caption,
                "Permission needed" if approval_model else "",
                "Disconnected" if disconnected else "",
                (f"{len(warnings)} warning(s)" if warnings else ""),
            )
            if part
        ),
        "priorityRank": _priority_rank(phase),
    }


def _priority_rank(phase: str) -> int:
    try:
        return PHASE_PRIORITY.index(phase)
    except ValueError:
        return len(PHASE_PRIORITY)


def rail_outranks_work(rail: Mapping[str, Any]) -> bool:
    """True when approval/error/disconnect must suppress decorative work chrome."""
    return bool(rail.get("attention") or rail.get("disconnected") or rail.get("approval"))
