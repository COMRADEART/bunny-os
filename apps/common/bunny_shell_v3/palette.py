"""The Bunny command palette.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The palette's single most important property: **typed text is a query, never a
command.** A query that matches nothing produces no results. There is no
"run this as a command" fallback, and no result type that carries a command
line, so no amount of typing can reach a shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Behavior(str, Enum):
    """What a result will do, shown on every result without exception."""

    OPEN = "Open"
    SWITCH = "Switch"
    CHANGE = "Change"
    APPROVAL_REQUIRED = "Approval required"
    PRIVILEGED = "Privileged"
    POWER_ACTION = "Power action"


class Source(str, Enum):
    APPLICATIONS = "installed applications"
    WINDOWS = "open windows"
    WORKSPACES = "workspaces"
    BUNNY_SETTINGS = "Bunny settings"
    SYSTEM_SETTINGS = "system settings"
    RECENT_FILES = "recent files"
    DIAGNOSTICS = "diagnostics"
    APPROVALS = "approvals"
    LAYOUT_MODES = "layout modes"
    VISUAL_MODES = "visual modes"
    POWER_ACTIONS = "power actions"


#: Sources that need Bunny AI. When Bunny is disabled these are omitted; every
#: other source keeps working, which is what makes the palette usable with
#: Bunny off.
AI_DEPENDENT_SOURCES = frozenset()


@dataclass(frozen=True)
class Result:
    """One palette result.

    ``target`` identifies what to act on — a desktop entry id, a window id, a
    workspace index, a settings key. It is never a command line, and
    :meth:`CommandPalette.resolve` refuses anything that looks like one.
    """

    key: str
    title: str
    subtitle: str
    source: Source
    behavior: Behavior
    target: str

    @property
    def requires_approval(self) -> bool:
        return self.behavior in (Behavior.APPROVAL_REQUIRED, Behavior.PRIVILEGED)


def is_safe_target(value: str) -> bool:
    """Reject anything that could be a path, a command line or an injection."""

    if not value or len(value) > 255:
        return False
    return all(character.isalnum() or character in ".-_:" for character in value)


class CommandPalette:
    """Searches the registered sources. Executes nothing itself."""

    def __init__(self, *, bunny_enabled: bool = True) -> None:
        self.bunny_enabled = bunny_enabled
        self._results: list[Result] = []

    def register(self, result: Result) -> None:
        if not is_safe_target(result.target):
            raise ValueError(f"unsafe palette target rejected: {result.target!r}")
        self._results.append(result)

    def available_sources(self) -> list[Source]:
        if self.bunny_enabled:
            return list(Source)
        return [source for source in Source if source not in AI_DEPENDENT_SOURCES]

    def search(self, query: str) -> list[Result]:
        """Match results by title and subtitle.

        An empty query returns nothing rather than everything, so the palette
        never opens onto a wall of power actions.
        """

        text = query.strip().lower()
        if not text:
            return []
        available = set(self.available_sources())
        matches = [
            result
            for result in self._results
            if result.source in available
            and (text in result.title.lower() or text in result.subtitle.lower())
        ]
        # Stable, predictable ordering: exact title matches first, then by
        # source declaration order, then alphabetically.
        source_order = {source: index for index, source in enumerate(Source)}
        matches.sort(
            key=lambda result: (
                0 if result.title.lower() == text else 1,
                source_order[result.source],
                result.title.lower(),
            )
        )
        return matches

    def resolve(self, result: Result) -> dict[str, str]:
        """Turn a chosen result into a typed request.

        Privileged and approval-required results are routed to the approval
        backend rather than performed. The palette never performs them itself.
        """

        if not is_safe_target(result.target):
            raise ValueError(f"unsafe palette target rejected: {result.target!r}")
        if result.requires_approval:
            return {
                "kind": "approval-request",
                "operation": result.target,
                "behavior": result.behavior.value,
            }
        if result.behavior is Behavior.POWER_ACTION:
            return {"kind": "power-action", "action": result.target}
        if result.source is Source.APPLICATIONS:
            return {"kind": "launch-desktop-entry", "entry_id": result.target}
        if result.source is Source.WINDOWS:
            return {"kind": "focus-window", "window_id": result.target}
        if result.source is Source.WORKSPACES:
            return {"kind": "switch-workspace", "index": result.target}
        return {"kind": "change-setting", "key": result.target}


def default_results() -> list[Result]:
    """The results the shell registers with no backend attached.

    These are shell-owned actions only. Applications, windows, recent files and
    approvals arrive from their backends; when a backend is absent its results
    are simply absent, never faked.
    """

    results = [
        Result(
            "workspace-1",
            "Workspace 1",
            "Switch to the first workspace",
            Source.WORKSPACES,
            Behavior.SWITCH,
            "0",
        ),
        Result(
            "mode-regular",
            "Regular Mode",
            "No guide character",
            Source.VISUAL_MODES,
            Behavior.CHANGE,
            "visual-mode:regular",
        ),
        Result(
            "mode-character",
            "Character Mode",
            "Show the Bunny guide where approved",
            Source.VISUAL_MODES,
            Behavior.CHANGE,
            "visual-mode:character",
        ),
        Result(
            "layout-compact",
            "CompactLayout",
            "Denser spacing",
            Source.LAYOUT_MODES,
            Behavior.CHANGE,
            "layout-mode:compact",
        ),
        Result(
            "diagnostics",
            "Diagnostics",
            "Compositor, renderer, displays and protocols",
            Source.DIAGNOSTICS,
            Behavior.OPEN,
            "diagnostics",
        ),
        Result(
            "lock",
            "Lock Screen",
            "Lock this session",
            Source.POWER_ACTIONS,
            Behavior.POWER_ACTION,
            "lock",
        ),
        Result(
            "log-out",
            "Log Out",
            "End this session",
            Source.POWER_ACTIONS,
            Behavior.POWER_ACTION,
            "log-out",
        ),
        Result(
            "restart",
            "Restart",
            "Restart this computer",
            Source.POWER_ACTIONS,
            Behavior.POWER_ACTION,
            "restart",
        ),
        Result(
            "power-off",
            "Power Off",
            "Shut down this computer",
            Source.POWER_ACTIONS,
            Behavior.POWER_ACTION,
            "power-off",
        ),
    ]
    return results
