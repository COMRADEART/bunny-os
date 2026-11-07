# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live task-rail runtime over the authenticated Companion presentation stream.

Display-free. Connects through ``CompanionClient.get_presentation_state`` only —
never invents progress, never grants approvals, never claims absolute Wayland
placement. Layout visibility is controlled by Adaptive Hybrid state
(Desktop hides the rail; Focus/Studio show it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .adaptive_layout import (
    AdaptiveLayoutState,
    ScreenRect,
    hyprland_dispatch_plan,
    normalise_layout,
    retain_task_cursor,
    solve,
)
from .task_rail import build_task_rail, rail_outranks_work


class PresentationClient(Protocol):
    """Minimal authenticated Companion client surface the rail may use."""

    def health(self) -> Mapping[str, Any]: ...

    def list_sessions(self) -> Mapping[str, Any]: ...

    def list_tasks(self) -> Mapping[str, Any]: ...

    def get_presentation_state(
        self,
        task_id: str | None = None,
        *,
        session_id: str | None = None,
        after_sequence: int = 0,
    ) -> Mapping[str, Any]: ...


# Accessible names — host tests assert these strings stay stable.
RAIL_ACCESSIBLE_NAME = "Bunny task timeline"
RAIL_STATUS_ACCESSIBLE_NAME = "Current task status"
RAIL_STAGES_ACCESSIBLE_NAME = "Task stages"
RAIL_OPEN_TRUST_NAME = "Open Trust for this Bunny action"
RAIL_PAUSE_NAME = "Pause this Bunny task"
RAIL_CANCEL_NAME = "Cancel this Bunny task"
RAIL_COLLAPSE_NAME = "Collapse task timeline"
RAIL_EXPAND_NAME = "Expand task timeline"
RAIL_DESKTOP_HINT = "Switch to Desktop layout"


def presentation_to_rail_input(state: Mapping[str, Any]) -> dict[str, Any]:
    """Map PresentationState.to_json() into build_task_rail()'s input shape.

    Progress is taken only when the runtime supplied a finite measured value
    that is not the zero placeholder for "unknown". A bare 0.0 with a working
    phase is treated as unspecified (no invented percent).
    """
    phase = str(state.get("phase") or "idle")
    caption = str(
        state.get("statusText")
        or state.get("errorSummary")
        or state.get("resultSummary")
        or state.get("currentOperation")
        or ""
    )
    progress = state.get("progress")
    percent: float | None
    if isinstance(progress, (int, float)) and not isinstance(progress, bool):
        value = float(progress)
        # PresentationState defaults progress to 0.0; only forward when clearly set.
        if value > 0.0 or phase in {"success", "presenting_result"}:
            percent = max(0.0, min(100.0, value * 100.0 if value <= 1.0 else value))
        else:
            percent = None
    else:
        percent = None

    approvals = state.get("approvals") or []
    approval = None
    if isinstance(approvals, list) and approvals:
        first = approvals[0]
        if isinstance(first, Mapping):
            approval = {
                "id": first.get("requestId") or first.get("id") or "",
                "summary": first.get("reason") or first.get("action") or caption,
            }

    warnings: list[str] = []
    for item in state.get("observations") or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("severity") or "").lower() in {"warning", "error", "critical"}:
            summary = str(item.get("summary") or "").strip()
            if summary:
                warnings.append(summary)

    stages: list[str] = []
    tool = str(state.get("currentTool") or "").strip()
    operation = str(state.get("currentOperation") or "").strip()
    if operation:
        stages.append(operation)
    if tool and tool not in stages:
        stages.append(tool)
    if state.get("activeExecutor"):
        stages.append(f"Executor: {state.get('activeExecutor')}")

    return {
        "phase": phase,
        "basePhase": state.get("basePhase") or phase,
        "caption": caption,
        "status": caption,
        "taskId": state.get("taskId") or "",
        "sequence": state.get("revision"),
        "percent": percent,
        "stages": stages,
        "stageIndex": 0 if stages else -1,
        "approval": approval,
        "approvalId": (approval or {}).get("id", ""),
        "warnings": warnings,
        "files": [],
        "disconnected": False,
    }


@dataclass
class TaskRailRuntime:
    """Polls Companion presentation and projects the Adaptive Hybrid task rail."""

    client: PresentationClient | None = None
    layout_state: AdaptiveLayoutState = field(default_factory=AdaptiveLayoutState)
    task_id: str = ""
    session_id: str = ""
    revision: int = 0
    presentation: dict[str, Any] = field(default_factory=dict)
    rail: dict[str, Any] = field(default_factory=dict)
    connection_error: str = ""
    disconnected: bool = False
    collapsed: bool = False
    last_events: list[Mapping[str, Any]] = field(default_factory=list)

    def visible_for_layout(self, layout: str | None = None) -> bool:
        name = normalise_layout(layout or self.layout_state.layout)
        return name in {"focus", "studio"}

    def connect(self) -> bool:
        if self.client is None:
            self.connection_error = "no Companion client configured"
            self.disconnected = True
            self._rebuild_rail()
            return False
        try:
            self.client.health()
            sessions = self.client.list_sessions().get("sessions", [])
            if isinstance(sessions, list) and sessions:
                latest = sessions[-1]
                if isinstance(latest, Mapping):
                    self.session_id = str(latest.get("sessionId") or self.session_id)
            if not self.task_id:
                tasks = self.client.list_tasks().get("tasks", [])
                if isinstance(tasks, list) and tasks:
                    unfinished = [
                        item
                        for item in tasks
                        if isinstance(item, Mapping)
                        and item.get("state") not in ("completed", "failed", "cancelled")
                    ]
                    chosen = (
                        unfinished
                        or [item for item in tasks if isinstance(item, Mapping)]
                    )[-1]
                    self.task_id = str(chosen.get("taskId") or "")
                    self.session_id = str(chosen.get("sessionId") or "") or self.session_id
            self.connection_error = ""
            self.disconnected = False
        except Exception as exc:  # noqa: BLE001 - surface disconnect honestly
            self.connection_error = str(exc)
            self.disconnected = True
            self._rebuild_rail()
            return False
        return self.refresh(full=True)

    def refresh(self, *, full: bool = False) -> bool:
        if self.client is None:
            self.disconnected = True
            self.connection_error = self.connection_error or "no Companion client configured"
            self._rebuild_rail()
            return False
        if full:
            self.revision = 0
        try:
            answer = self.client.get_presentation_state(
                self.task_id or None,
                session_id=self.session_id or None,
                after_sequence=self.revision,
            )
        except Exception as exc:  # noqa: BLE001
            self.connection_error = str(exc)
            self.disconnected = True
            self._rebuild_rail()
            return False

        self.connection_error = ""
        self.disconnected = False
        events = answer.get("events")
        self.last_events = [item for item in events if isinstance(item, Mapping)] if isinstance(events, list) else []
        served = answer.get("state")
        if isinstance(served, Mapping):
            self.presentation = dict(served)
            self.task_id = str(served.get("taskId") or self.task_id)
            self.session_id = str(served.get("sessionId") or self.session_id)
            revision = served.get("revision")
            if isinstance(revision, int) and not isinstance(revision, bool):
                self.revision = revision
        answer_revision = answer.get("revision")
        if isinstance(answer_revision, int) and not isinstance(answer_revision, bool):
            self.revision = max(self.revision, answer_revision)

        # Retain cursor into Adaptive layout state without inventing task truth.
        approval_id = ""
        approvals = self.presentation.get("approvals") or []
        if isinstance(approvals, list) and approvals and isinstance(approvals[0], Mapping):
            approval_id = str(approvals[0].get("requestId") or "")
        self.layout_state = retain_task_cursor(
            self.layout_state,
            task_id=self.task_id,
            event_sequence=self.revision,
            approval_id=approval_id,
        )
        self._rebuild_rail()
        return True

    def set_layout(self, layout: str, *, collapsed: bool | None = None) -> AdaptiveLayoutState:
        self.layout_state = retain_task_cursor(
            self.layout_state,
            layout=layout,
            task_id=self.task_id or self.layout_state.task_id,
            event_sequence=self.revision if self.revision else self.layout_state.event_sequence,
            approval_id=self.layout_state.approval_id,
        )
        if collapsed is not None:
            self.collapsed = bool(collapsed)
        elif normalise_layout(layout) == "desktop":
            self.collapsed = True
        self._rebuild_rail()
        return self.layout_state

    def geometry(
        self,
        *,
        width: int = 1920,
        height: int = 1080,
        scale: float = 1.0,
        monitor_id: str = "primary",
    ) -> dict[str, Any]:
        solution = solve(
            ScreenRect(width=width, height=height),
            layout=self.layout_state.layout,
            scale=scale,
            rail_collapsed=self.collapsed,
        )
        plan = hyprland_dispatch_plan(solution)
        return {
            "monitorId": monitor_id,
            "visible": self.visible_for_layout(),
            "solution": solution.to_json(),
            "dispatch": plan,
            "absolutePlacementAvailable": False,
        }

    def surface_model(self) -> dict[str, Any]:
        """Everything a GTK/Wayland consumer needs to draw, including a11y names."""
        visible = self.visible_for_layout()
        rail = dict(self.rail)
        if self.disconnected or rail.get("disconnected"):
            phase_note = "Disconnected from Companion"
        else:
            phase_note = str(rail.get("label") or "Ready")
        return {
            "schema": "bunny.task-rail-surface/1",
            "visible": visible,
            "layout": self.layout_state.layout,
            "collapsed": self.collapsed,
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "revision": self.revision,
            "connectionError": self.connection_error,
            "disconnected": self.disconnected,
            "rail": rail,
            "outranksWork": rail_outranks_work(rail),
            "acceptFocus": bool(rail.get("approval") or rail.get("phase") == "waiting_for_approval"),
            "absolutePlacementAvailable": False,
            "accessible": {
                "windowName": RAIL_ACCESSIBLE_NAME,
                "statusName": RAIL_STATUS_ACCESSIBLE_NAME,
                "stagesName": RAIL_STAGES_ACCESSIBLE_NAME,
                "openTrust": RAIL_OPEN_TRUST_NAME,
                "pause": RAIL_PAUSE_NAME,
                "cancel": RAIL_CANCEL_NAME,
                "collapse": RAIL_COLLAPSE_NAME,
                "expand": RAIL_EXPAND_NAME,
                "desktopHint": RAIL_DESKTOP_HINT,
                "announcement": rail.get("announcement") or phase_note,
            },
            "keyboard": {
                "escapeCollapses": True,
                "hHidesToDesktop": True,
                "tabCyclesActions": True,
                "enterActivatesDefault": True,
            },
        }

    def simulate_compositor_restart(self) -> dict[str, Any]:
        """Prove layout + task cursor survive a compositor restart (state only)."""
        preserved = AdaptiveLayoutState.from_json(self.layout_state.to_json())
        # Drop ephemeral connection; reconnect path must replay from revision.
        previous_revision = self.revision
        self.disconnected = True
        self.connection_error = "compositor restart"
        self._rebuild_rail()
        self.layout_state = preserved
        reconnected = self.connect() if self.client is not None else False
        return {
            "preservedLayout": preserved.layout,
            "preservedTaskId": preserved.task_id,
            "preservedEventSequence": preserved.event_sequence,
            "preservedApprovalId": preserved.approval_id,
            "previousRevision": previous_revision,
            "reconnected": reconnected,
            "revisionAfter": self.revision,
            "absolutePlacementAvailable": False,
        }

    def _rebuild_rail(self) -> None:
        payload = presentation_to_rail_input(self.presentation) if self.presentation else {
            "phase": "idle",
            "caption": "",
            "taskId": self.task_id,
        }
        if self.disconnected:
            payload["phase"] = "disconnected"
            payload["disconnected"] = True
            if self.connection_error:
                payload["caption"] = self.connection_error
        self.rail = build_task_rail(
            payload,
            collapsed=self.collapsed or not self.visible_for_layout(),
            layout=self.layout_state.layout,
        )
        if self.disconnected:
            self.rail["disconnected"] = True
            self.rail["attention"] = True
