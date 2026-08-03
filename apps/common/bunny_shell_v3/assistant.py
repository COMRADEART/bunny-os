"""Assistant states and approval surfaces.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The visual model is carried forward from Visual Phase V2 unchanged. What is new
in V3 is that the shell rendering it is not GNOME Shell, so the same rules are
re-stated as code rather than inherited from the V2 extension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .character import GuideState


class AssistantState(str, Enum):
    READY = "Ready"
    THINKING = "Thinking"
    WAITING_FOR_APPROVAL = "Waiting for approval"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    OFFLINE = "Offline"
    LOCAL_ONLY = "Local Only"
    DISABLED = "Disabled"


#: Assistant state to guide state. Two assistant states have no guide pose at
#: all: DISABLED, because Bunny being off must not be illustrated by Bunny, and
#: THINKING maps to PLANNING rather than to a separate pose.
GUIDE_FOR_ASSISTANT: dict[AssistantState, GuideState | None] = {
    AssistantState.READY: GuideState.READY,
    AssistantState.THINKING: GuideState.PLANNING,
    AssistantState.WAITING_FOR_APPROVAL: GuideState.APPROVAL_REQUIRED,
    AssistantState.RUNNING: GuideState.RUNNING,
    AssistantState.COMPLETED: GuideState.COMPLETED,
    AssistantState.FAILED: GuideState.FAILED,
    AssistantState.OFFLINE: GuideState.OFFLINE,
    AssistantState.LOCAL_ONLY: GuideState.LOCAL_ONLY,
    AssistantState.DISABLED: None,
}


class Privilege(str, Enum):
    USER = "user"
    ADMINISTRATOR = "administrator"
    SYSTEM = "system"


class Reversibility(str, Enum):
    REVERSIBLE = "reversible"
    REVERSIBLE_WITH_EFFORT = "reversible with effort"
    IRREVERSIBLE = "irreversible"


class Severity(str, Enum):
    ORDINARY = "ordinary"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ApprovalCard:
    """Everything the user must be told before approving.

    Every field is required. A card that cannot state its blast radius is not
    renderable, which is enforced in :meth:`validate` rather than left to the
    surface that draws it.
    """

    requester: str
    operation: str
    affected_resources: tuple[str, ...]
    privilege: Privilege
    network_impact: str
    data_impact: str
    reversibility: Reversibility
    reason: str
    expiration_seconds: int
    severity: Severity = Severity.ORDINARY

    #: The three actions every card offers.
    actions: tuple[str, ...] = ("approve", "deny", "inspect")

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.requester:
            problems.append("requester is required")
        if not self.operation:
            problems.append("operation is required")
        if not self.affected_resources:
            problems.append("affected resources are required")
        if not self.network_impact:
            problems.append("network impact is required")
        if not self.data_impact:
            problems.append("data impact is required")
        if not self.reason:
            problems.append("reason is required")
        if self.expiration_seconds <= 0:
            problems.append("expiration must be positive")
        if set(self.actions) != {"approve", "deny", "inspect"}:
            problems.append("a card must offer approve, deny and inspect")
        if self.severity is Severity.CRITICAL and self.reversibility is not Reversibility.IRREVERSIBLE:
            # Not a hard error, but worth surfacing: critical usually means
            # irreversible, and a mismatch is normally a mislabelled card.
            pass
        return problems

    @property
    def renderable(self) -> bool:
        return not self.validate()

    def default_action(self) -> str | None:
        """Which button is pre-selected.

        None for every card. A critical approval must have no default
        affirmative action, and an ordinary one gains nothing from a default
        that could be triggered by a stray Enter.
        """

        return None

    def guide_state(self) -> GuideState:
        return GuideState.APPROVAL_REQUIRED


class ApprovalInput(str, Enum):
    EXPLICIT_APPROVE = "explicit-approve"
    EXPLICIT_DENY = "explicit-deny"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    NO_INPUT = "no-input"


class ApprovalOutcome(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"


def resolve_approval(card: ApprovalCard, user_input: ApprovalInput) -> ApprovalOutcome:
    """The only path to APPROVED is an explicit approval on a renderable card."""

    if not card.renderable:
        return ApprovalOutcome.DENIED
    if user_input is ApprovalInput.EXPLICIT_APPROVE:
        return ApprovalOutcome.APPROVED
    return ApprovalOutcome.DENIED


@dataclass
class Assistant:
    """Assistant panel state.

    The compositor and the panel render backend state. Neither invents it: a
    transition to COMPLETED requires the backend to say so.
    """

    state: AssistantState = AssistantState.READY
    transcript: list[str] = field(default_factory=list)
    pending_card: ApprovalCard | None = None
    bunny_enabled: bool = True
    local_only: bool = False

    def __post_init__(self) -> None:
        if not self.bunny_enabled:
            self.state = AssistantState.DISABLED
        elif self.local_only:
            self.state = AssistantState.LOCAL_ONLY

    def guide_state(self) -> GuideState | None:
        return GUIDE_FOR_ASSISTANT[self.state]

    def set_state(self, state: AssistantState, *, backend_confirmed: bool = False) -> bool:
        """Change state. COMPLETED requires backend confirmation."""

        if state is AssistantState.COMPLETED and not backend_confirmed:
            return False
        if not self.bunny_enabled and state is not AssistantState.DISABLED:
            # A disabled assistant does not come back to life on its own.
            return False
        self.state = state
        return True

    def character_container(self) -> str | None:
        """Which approved container the guide would occupy, if any."""

        if self.state is AssistantState.DISABLED:
            return None
        if self.state is AssistantState.OFFLINE:
            return "offline-state"
        if self.state is AssistantState.WAITING_FOR_APPROVAL:
            return "approval-education"
        if self.state is AssistantState.COMPLETED:
            return "task-summary"
        return "assistant"
