"""Notifications, including Bunny action notifications.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The rule that shapes this module: a completed notification is never shown until
the backend confirms completion. "Probably finished" is not a state, and the
transition table has no path from RUNNING to COMPLETED that the shell can take
on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import itertools


class Urgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


class Category(str, Enum):
    APPLICATION = "application"
    SYSTEM = "system"
    BUNNY_ACTION = "bunny-action"


class ActionState(str, Enum):
    """Lifecycle of a Bunny action notification."""

    PROPOSED = "proposed"
    WAITING_FOR_APPROVAL = "waiting for approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled back"


#: Legal transitions. COMPLETED is reachable only from RUNNING, and only via
#: confirm_completion(), which requires backend confirmation.
_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    ActionState.PROPOSED: frozenset({ActionState.WAITING_FOR_APPROVAL, ActionState.FAILED}),
    ActionState.WAITING_FOR_APPROVAL: frozenset({ActionState.RUNNING, ActionState.FAILED}),
    ActionState.RUNNING: frozenset({ActionState.COMPLETED, ActionState.FAILED, ActionState.ROLLED_BACK}),
    ActionState.COMPLETED: frozenset({ActionState.ROLLED_BACK}),
    ActionState.FAILED: frozenset({ActionState.ROLLED_BACK}),
    ActionState.ROLLED_BACK: frozenset(),
}


class TransitionRefused(Exception):
    """Raised when a state change would misrepresent what happened."""


_counter = itertools.count(1)


@dataclass
class Notification:
    app_id: str
    summary: str
    body: str = ""
    category: Category = Category.APPLICATION
    urgency: Urgency = Urgency.NORMAL
    action_state: ActionState | None = None
    group_key: str = ""
    identifier: int = field(default_factory=lambda: next(_counter))
    dismissed: bool = False

    def __post_init__(self) -> None:
        if self.category is Category.BUNNY_ACTION and self.action_state is None:
            self.action_state = ActionState.PROPOSED
        if not self.group_key:
            self.group_key = self.app_id

    @property
    def critical(self) -> bool:
        return self.urgency is Urgency.CRITICAL

    def advance(self, target: ActionState, *, backend_confirmed: bool = False) -> None:
        """Move a Bunny action to a new state.

        Reaching COMPLETED requires ``backend_confirmed=True``. The shell cannot
        decide that an operation succeeded.
        """

        if self.category is not Category.BUNNY_ACTION or self.action_state is None:
            raise TransitionRefused("only Bunny action notifications have a state")
        if target not in _TRANSITIONS[self.action_state]:
            raise TransitionRefused(f"{self.action_state.value} cannot become {target.value}")
        if target is ActionState.COMPLETED and not backend_confirmed:
            raise TransitionRefused(
                "a completed notification requires backend confirmation of completion"
            )
        self.action_state = target


class NotificationCenter:
    """Live banners, grouping, history and Do Not Disturb."""

    def __init__(self, *, history_limit: int = 100) -> None:
        self.history_limit = history_limit
        self._live: list[Notification] = []
        self._history: list[Notification] = []
        self.do_not_disturb = False

    def post(self, notification: Notification) -> bool:
        """Post a notification. Returns whether a banner is shown.

        Do Not Disturb suppresses the *banner*, never the record: the
        notification still reaches history, and a critical one still interrupts.
        """

        self._history.append(notification)
        if len(self._history) > self.history_limit:
            self._history = self._history[-self.history_limit :]
        show_banner = notification.critical or not self.do_not_disturb
        if show_banner:
            self._live.append(notification)
        return show_banner

    def live(self) -> list[Notification]:
        return [item for item in self._live if not item.dismissed]

    def history(self) -> list[Notification]:
        return list(self._history)

    def dismiss(self, identifier: int) -> bool:
        for notification in self._live:
            if notification.identifier == identifier:
                notification.dismissed = True
                return True
        return False

    def groups(self) -> dict[str, list[Notification]]:
        grouped: dict[str, list[Notification]] = {}
        for notification in self.live():
            grouped.setdefault(notification.group_key, []).append(notification)
        return grouped

    def takes_focus(self) -> bool:
        """A notification never takes keyboard focus, critical or not.

        A critical notification interrupts visually and stays until dismissed.
        It still does not move the keyboard, because the user may be typing a
        password into the window underneath.
        """

        return False
