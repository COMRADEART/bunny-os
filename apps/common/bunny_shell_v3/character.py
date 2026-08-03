"""Character Mode: the bounded illustration component.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The guide character is not a compositor surface. It is a widget inside a
containing panel, which is what makes every rule below enforceable: it cannot
float over an application window because it has no surface of its own, and it
cannot be focused because it is not a focusable widget.

Character Mode uses the existing canonical character family from Visual Phase
V2 (``visual-v2/assets/character/bunny-guide/v1``). V3 creates no new face,
wardrobe or body style.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path


class GuideState(str, Enum):
    """The approved guide states."""

    READY = "Ready"
    WELCOME = "Welcome"
    COMPOSING = "Composing"
    PLANNING = "Planning"
    TEACHING = "Teaching"
    APPROVAL_REQUIRED = "Approval required"
    RUNNING = "Running"
    COMPLETED = "Completed"
    WARNING = "Warning"
    FAILED = "Failed"
    OFFLINE = "Offline"
    LOCAL_ONLY = "Local Only"
    MILESTONE = "Milestone"


#: The approved state-to-pose mapping. Exactly the table from the phase brief.
POSE_FOR_STATE: dict[GuideState, str] = {
    GuideState.READY: "idle-neutral",
    GuideState.WELCOME: "welcome-wave",
    GuideState.COMPOSING: "typing",
    GuideState.PLANNING: "thinking",
    GuideState.TEACHING: "explaining",
    GuideState.APPROVAL_REQUIRED: "requesting-approval",
    GuideState.RUNNING: "task-running",
    GuideState.COMPLETED: "task-completed",
    GuideState.WARNING: "warning",
    GuideState.FAILED: "error",
    GuideState.OFFLINE: "offline",
    GuideState.LOCAL_ONLY: "privacy-mode",
    GuideState.MILESTONE: "celebrating",
}

#: States that assert something went right. Each needs an observed success.
SUCCESS_STATES = frozenset({GuideState.COMPLETED, GuideState.MILESTONE})

#: Containers where the character may appear.
APPROVED_CONTAINERS = frozenset(
    {
        "assistant",
        "welcome",
        "approval-education",
        "diagnostics-guidance",
        "offline-state",
        "recovery-guidance",
        "task-summary",
    }
)

#: Surfaces where the character is forbidden, whatever the mode.
FORBIDDEN_CONTAINERS = frozenset(
    {
        "wallpaper",
        "desktop",
        "top-bar",
        "dock",
        "application-window",
        "password-field",
        "authentication-dialog",
        "lock-screen",
        "lock-screen-credentials",
        "overview",
    }
)


class CharacterRefusal(str, Enum):
    NOT_CHARACTER_MODE = "not-character-mode"
    FORBIDDEN_CONTAINER = "forbidden-container"
    UNKNOWN_CONTAINER = "unknown-container"
    ALREADY_DISPLAYED = "already-displayed"
    SUCCESS_NOT_OBSERVED = "success-not-observed"
    FOCUS_MODE_CONTINUOUS = "focus-mode-continuous"
    ASSET_MISSING = "asset-missing"


@dataclass(frozen=True)
class CharacterPlacement:
    container: str
    state: GuideState
    pose: str
    asset: str
    semantic_description: str


class CharacterLayer:
    """Owns the single permitted character instance.

    Exactly one placement can exist at a time. The invariant is held by this
    object rather than by convention, so two panels cannot each show a guide.
    """

    #: The canonical family, from V2. Never a new one.
    ASSET_ROOT = Path("visual-v2/assets/character/bunny-guide/v1")

    def __init__(self, repository_root: Path, *, character_mode: bool = False) -> None:
        self.root = repository_root
        self.character_mode = character_mode
        self.focus_mode = False
        self._placement: CharacterPlacement | None = None
        self._manifest: dict | None = None
        self._loaded_poses: set[str] = set()

    # -- assets ---------------------------------------------------------

    def manifest(self) -> dict:
        if self._manifest is None:
            path = self.root / self.ASSET_ROOT / "manifest.json"
            self._manifest = json.loads(path.read_text(encoding="utf-8"))
        return self._manifest

    def available_poses(self) -> set[str]:
        return {entry["slug"] for entry in self.manifest()["states"]}

    def semantic_description(self, pose: str) -> str:
        for entry in self.manifest()["states"]:
            if entry["slug"] == pose:
                return entry["semanticDescription"]
        return ""

    def asset_path(self, pose: str) -> Path:
        return self.root / self.ASSET_ROOT / f"{pose}.png"

    # -- placement ------------------------------------------------------

    @property
    def placement(self) -> CharacterPlacement | None:
        return self._placement

    @property
    def displayed_count(self) -> int:
        return 1 if self._placement else 0

    def show(
        self,
        container: str,
        state: GuideState,
        *,
        success_observed: bool = False,
        continuous: bool = False,
    ) -> CharacterPlacement | CharacterRefusal:
        """Place the character, or refuse and say why.

        ``success_observed`` must be True for a state that asserts success. The
        shell cannot decide a task succeeded; only an observed backend result
        can.
        """

        if not self.character_mode:
            return CharacterRefusal.NOT_CHARACTER_MODE
        if container in FORBIDDEN_CONTAINERS:
            return CharacterRefusal.FORBIDDEN_CONTAINER
        if container not in APPROVED_CONTAINERS:
            # Unknown containers are refused, not permitted by default.
            return CharacterRefusal.UNKNOWN_CONTAINER
        if self._placement is not None:
            return CharacterRefusal.ALREADY_DISPLAYED
        if state in SUCCESS_STATES and not success_observed:
            return CharacterRefusal.SUCCESS_NOT_OBSERVED
        if self.focus_mode and continuous:
            # A momentary appearance during FocusMode is allowed; a persistent
            # one is not.
            return CharacterRefusal.FOCUS_MODE_CONTINUOUS

        pose = POSE_FOR_STATE[state]
        if pose not in self.available_poses():
            return CharacterRefusal.ASSET_MISSING

        placement = CharacterPlacement(
            container=container,
            state=state,
            pose=pose,
            asset=str(self.ASSET_ROOT / f"{pose}.png"),
            semantic_description=self.semantic_description(pose),
        )
        self._placement = placement
        # Only the active pose is loaded; the previous one is released.
        self._loaded_poses = {pose}
        return placement

    def hide(self) -> None:
        self._placement = None
        self._loaded_poses.clear()

    def loaded_poses(self) -> set[str]:
        """Textures currently held. Never more than the active pose."""

        return set(self._loaded_poses)

    # -- interaction ----------------------------------------------------

    @staticmethod
    def focusable() -> bool:
        """The character is never focusable and never blocks input."""

        return False

    @staticmethod
    def accepts_input() -> bool:
        return False

    def animation_duration_ms(self, requested: int, *, reduced_motion: bool) -> int:
        return 0 if reduced_motion else requested

    def accessible_text(self) -> str:
        """What assistive technology is told.

        The character carries no information of its own — it illustrates the
        containing panel's state — so the description is the panel's state in
        words, and a screen reader user loses nothing by not seeing it.
        """

        if self._placement is None:
            return ""
        return self._placement.semantic_description


def scaled_size(
    natural: tuple[int, int], available: tuple[int, int]
) -> tuple[int, int]:
    """Fit the illustration into the available box, preserving aspect ratio."""

    natural_width, natural_height = natural
    box_width, box_height = available
    if natural_width <= 0 or natural_height <= 0 or box_width <= 0 or box_height <= 0:
        return (0, 0)
    scale = min(box_width / natural_width, box_height / natural_height)
    return (max(1, int(natural_width * scale)), max(1, int(natural_height * scale)))
