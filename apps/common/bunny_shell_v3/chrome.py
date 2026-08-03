"""The Bunny top bar and dock.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .model import BackendState, ShellState


class Region(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass(frozen=True)
class TopBarItem:
    key: str
    region: Region
    label: str
    backend: BackendState = BackendState.UNAVAILABLE
    privacy: bool = False


# The required top bar contents. Order within a region is presentation order.
TOP_BAR_ITEMS: tuple[TopBarItem, ...] = (
    TopBarItem("bunny-symbol", Region.LEFT, "Bunny", BackendState.CONNECTED),
    TopBarItem("bunny-os", Region.LEFT, "Bunny OS", BackendState.CONNECTED),
    TopBarItem("activity", Region.LEFT, "Workspace", BackendState.CONNECTED),
    TopBarItem("date", Region.CENTER, "Date", BackendState.CONNECTED),
    TopBarItem("time", Region.CENTER, "Time", BackendState.CONNECTED),
    TopBarItem("focus-mode", Region.CENTER, "FocusMode", BackendState.CONNECTED),
    TopBarItem("notifications", Region.RIGHT, "Notifications", BackendState.CONNECTED),
    TopBarItem("microphone", Region.RIGHT, "Microphone in use", privacy=True),
    TopBarItem("camera", Region.RIGHT, "Camera in use", privacy=True),
    TopBarItem("screen-capture", Region.RIGHT, "Screen being captured", privacy=True),
    TopBarItem("network", Region.RIGHT, "Network"),
    TopBarItem("vpn", Region.RIGHT, "VPN"),
    TopBarItem("bluetooth", Region.RIGHT, "Bluetooth"),
    TopBarItem("audio", Region.RIGHT, "Audio"),
    TopBarItem("power", Region.RIGHT, "Power"),
    TopBarItem("battery", Region.RIGHT, "Battery"),
)


class TopBarModel:
    """What the top bar shows, given the shell state.

    The guide character is not a possible item. There is no code path that could
    place one here, because the item table is a closed constant.
    """

    def __init__(self, state: ShellState) -> None:
        self.state = state

    def items(self, region: Region) -> list[TopBarItem]:
        return [item for item in TOP_BAR_ITEMS if item.region is region]

    def visible_items(self, region: Region) -> list[TopBarItem]:
        """Items actually rendered, after layout and privacy rules."""

        result = []
        for item in self.items(region):
            if item.privacy:
                # A privacy indicator appears exactly when it is active, and
                # once active nothing may remove it.
                if self.state.indicators[item.key].active:
                    result.append(item)
                continue
            if self.state.layout_mode.value == "compact" and item.key in {"bunny-os", "date"}:
                # CompactLayout drops redundant labels, never an indicator.
                continue
            result.append(item)
        return result

    def character_permitted(self) -> bool:
        """The top bar never shows the guide character, in any mode."""

        return False

    def contains_character(self) -> bool:
        return any(item.key == "character" for item in TOP_BAR_ITEMS)


@dataclass
class DockItem:
    """One dock entry.

    ``entry_id`` is a desktop entry identifier. The dock never holds a command
    line, so it cannot launch one.
    """

    entry_id: str
    name: str
    pinned: bool = False
    window_ids: list[int] = field(default_factory=list)
    urgent: bool = False

    @property
    def running(self) -> bool:
        return bool(self.window_ids)

    @property
    def multiple_windows(self) -> bool:
        return len(self.window_ids) > 1


class DockAction(str, Enum):
    LAUNCH = "launch"
    FOCUS_EXISTING = "focus-existing"
    SHOW_WINDOW_LIST = "show-window-list"


class DockModel:
    """Dock ordering, overflow and activation policy."""

    def __init__(self, state: ShellState, *, max_visible: int = 12) -> None:
        self.state = state
        self.max_visible = max_visible
        self.items: list[DockItem] = []

    def add(self, item: DockItem) -> None:
        self.items.append(item)

    def remove(self, entry_id: str) -> bool:
        """Remove an item. A running application is never removed outright.

        Unpinning a running application leaves it in the dock until it exits,
        which is what stops the icon vanishing from under the user's pointer.
        """

        for item in self.items:
            if item.entry_id == entry_id:
                if item.running:
                    item.pinned = False
                    return True
                self.items.remove(item)
                return True
        return False

    def reorder(self, entry_id: str, position: int) -> bool:
        for index, item in enumerate(self.items):
            if item.entry_id == entry_id:
                if not 0 <= position < len(self.items):
                    return False
                self.items.insert(position, self.items.pop(index))
                return True
        return False

    def ordered(self) -> list[DockItem]:
        """Pinned items first, then running unpinned ones, each in insertion order."""

        pinned = [item for item in self.items if item.pinned]
        running = [item for item in self.items if not item.pinned and item.running]
        return pinned + running

    def visible(self) -> list[DockItem]:
        return self.ordered()[: self.max_visible]

    def overflow(self) -> list[DockItem]:
        return self.ordered()[self.max_visible :]

    def activate(self, entry_id: str) -> DockAction | None:
        """What clicking a dock item does.

        Never a shell command: the result is one of three typed actions.
        """

        for item in self.ordered():
            if item.entry_id != entry_id:
                continue
            if not item.running:
                return DockAction.LAUNCH
            if item.multiple_windows:
                return DockAction.SHOW_WINDOW_LIST
            return DockAction.FOCUS_EXISTING
        return None

    def keyboard_order(self) -> list[str]:
        """Tab order. Overflow is reachable, so no item is keyboard-unreachable."""

        return [item.entry_id for item in self.ordered()]

    def auto_hide(self) -> bool:
        """The dock hides in FocusMode and stays put otherwise."""

        return self.state.focus_mode

    def placement_output(self, outputs: list[str]) -> str | None:
        """The dock lives on the primary output only.

        Stated rather than emergent: a dock on every output competes with itself
        for the running-application indicators.
        """

        return outputs[0] if outputs else None

    def character_permitted(self) -> bool:
        return False
