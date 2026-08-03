"""Experimental-session policy for the Bunny Wayland shell.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Every gate here fails closed: an unreadable or unexpected input refuses the
session rather than assuming it is safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


NOTICE_LINES = (
    "BUNNY WAYLAND SHELL EXPERIMENT",
    "NOT RELEASE QUALIFIED",
    "DO NOT USE AS THE DEFAULT SESSION",
)

EXPERIMENTAL_MODE_VARIABLE = "BUNNY_SHELL_EXPERIMENTAL"

GNOME_SESSION_FILES = (
    "gnome.desktop",
    "gnome-wayland.desktop",
    "gnome-xorg.desktop",
)


@dataclass(frozen=True)
class SessionRefusal(Exception):
    """Raised when the experimental session must not start."""

    reason: str

    def __str__(self) -> str:
        return self.reason


def parse_session_file(text: str) -> dict[str, str]:
    """Parse the experimental session manifest.

    The format is the gnome-session key/value form. Comments and the section
    header are ignored; repeated keys take the last value.
    """

    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def components(values: dict[str, str], key: str) -> list[str]:
    raw = values.get(key, "")
    return [item for item in (part.strip() for part in raw.split(";")) if item]


def check_experimental_mode(environment: dict[str, str]) -> None:
    if environment.get(EXPERIMENTAL_MODE_VARIABLE) != "1":
        raise SessionRefusal(
            f"refusing to start: set {EXPERIMENTAL_MODE_VARIABLE}=1 to run the experimental shell"
        )


def gnome_is_selectable(search_paths: list[Path]) -> bool:
    for directory in search_paths:
        for name in GNOME_SESSION_FILES:
            if (directory / name).is_file():
                return True
    return False


def check_gnome_fallback(search_paths: list[Path], environment: dict[str, str]) -> None:
    if gnome_is_selectable(search_paths):
        return
    if environment.get("BUNNY_SHELL_ALLOW_MISSING_GNOME") == "1":
        # Developer escape hatch for a container with no session files at all.
        # It is never set by the packaged session.
        return
    raise SessionRefusal(
        "refusing to start: GNOME is not installed as a selectable session; "
        "GNOME must remain the supported fallback"
    )


def check_not_default_session(environment: dict[str, str]) -> None:
    if environment.get("BUNNY_SHELL_IS_DEFAULT_SESSION") == "1":
        raise SessionRefusal(
            "refusing to start: the experimental shell must not be configured as the default session"
        )


def check_not_qualification_run(environment: dict[str, str]) -> None:
    if environment.get("BUNNY_QUALIFICATION_RUN"):
        raise SessionRefusal("refusing to start: a qualification run is in progress")


def authorise(environment: dict[str, str], session_search_paths: list[Path]) -> None:
    """Run every start gate. Raises SessionRefusal on the first failure."""

    check_experimental_mode(environment)
    check_gnome_fallback(session_search_paths, environment)
    check_not_default_session(environment)
    check_not_qualification_run(environment)


def default_session_search_paths() -> list[Path]:
    return [Path("/usr/share/wayland-sessions"), Path("/usr/share/xsessions")]
