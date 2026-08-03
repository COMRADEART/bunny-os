"""Portals, PipeWire and screen-capture consent.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Screen capture is the capability with the widest gap between "works" and "is
safe". The rule here: a capture proceeds only when the portal granted it for an
explicitly selected source *and* the privacy indicator can actually be shown.
If the indicator cannot be displayed, the capture is refused — capture without
a visible indicator is precisely the failure this rule exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import shutil
import subprocess


class Evidence(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ServiceProbe:
    name: str
    bus_name: str
    present: bool
    evidence: Evidence
    detail: str = ""


#: The portal interfaces the shell needs, and what each is for.
REQUIRED_PORTALS: tuple[tuple[str, str], ...] = (
    ("org.freedesktop.portal.Screenshot", "screenshots, with per-request consent"),
    ("org.freedesktop.portal.ScreenCast", "screen sharing, with explicit source selection"),
    ("org.freedesktop.portal.FileChooser", "opening and saving files without filesystem access"),
    ("org.freedesktop.portal.OpenURI", "handing a URI to the right application"),
    ("org.freedesktop.portal.Settings", "reading the desktop colour scheme and contrast"),
)


def _dbus_names() -> tuple[list[str], Evidence, str]:
    """List the names on the session bus.

    Returns the names, how confident we are, and a note. A missing busctl means
    unavailable, never an assumption that nothing is running.
    """

    busctl = shutil.which("busctl")
    if not busctl:
        return ([], Evidence.UNAVAILABLE, "busctl is not installed")
    try:
        completed = subprocess.run(
            [busctl, "--user", "--no-pager", "--list", "--acquired"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return ([], Evidence.UNAVAILABLE, f"busctl failed: {error}")
    if completed.returncode != 0:
        return ([], Evidence.UNAVAILABLE, completed.stderr.strip()[:200] or "no session bus")
    names = [line.split()[0] for line in completed.stdout.splitlines()[1:] if line.strip()]
    return (names, Evidence.OBSERVED, "")


def probe_services() -> list[ServiceProbe]:
    """Probe the portal and PipeWire services actually present."""

    names, evidence, detail = _dbus_names()
    probes = [
        ServiceProbe(
            name="xdg-desktop-portal",
            bus_name="org.freedesktop.portal.Desktop",
            present="org.freedesktop.portal.Desktop" in names,
            evidence=evidence,
            detail=detail,
        ),
        ServiceProbe(
            name="PipeWire",
            bus_name="org.freedesktop.PipeWire",
            present=bool(shutil.which("pipewire")),
            evidence=Evidence.OBSERVED if shutil.which("pipewire") else Evidence.UNAVAILABLE,
            detail="binary presence only; no PipeWire session was established",
        ),
    ]
    return probes


class CaptureSource(str, Enum):
    OUTPUT = "output"
    WINDOW = "window"
    REGION = "region"


class CaptureRefusal(str, Enum):
    NO_PORTAL_AUTHORISATION = "no-portal-authorisation"
    NO_SOURCE_SELECTED = "no-source-selected"
    INDICATOR_UNAVAILABLE = "indicator-unavailable"
    COMPOSITOR_SCREENSHOT_NOT_PERMITTED = "compositor-screenshot-not-permitted"


@dataclass(frozen=True)
class CaptureRequest:
    app_id: str
    source: CaptureSource | None
    portal_token: str | None
    #: True only after the user picked the source in the portal dialog.
    user_selected_source: bool


@dataclass(frozen=True)
class CaptureGrant:
    app_id: str
    source: CaptureSource
    token: str
    indicator_key: str = "screen-capture"


def authorise_capture(
    request: CaptureRequest, *, indicator_available: bool
) -> CaptureGrant | CaptureRefusal:
    """Decide a capture request. Every failure path is a refusal, not a warning."""

    if not request.portal_token:
        return CaptureRefusal.NO_PORTAL_AUTHORISATION
    if request.source is None or not request.user_selected_source:
        return CaptureRefusal.NO_SOURCE_SELECTED
    if not indicator_available:
        return CaptureRefusal.INDICATOR_UNAVAILABLE
    return CaptureGrant(app_id=request.app_id, source=request.source, token=request.portal_token)


def unrestricted_compositor_screenshot_permitted(app_id: str) -> bool:
    """Whether an ordinary application may screenshot through the compositor.

    Never. The compositor implements no screencopy protocol, and would refuse
    even if it did: a screenshot path that bypasses the portal bypasses consent.
    """

    _ = app_id
    return False


#: Character Mode must not obscure a capture indicator. The indicator lives in
#: the top bar, which the character can never occupy, so this holds by
#: construction — recorded here so the security report can cite the mechanism
#: rather than a promise.
CAPTURE_INDICATOR_SURFACE = "top-bar"


def indicator_obscurable_by_character() -> bool:
    from .runtime import character_permitted

    return character_permitted(CAPTURE_INDICATOR_SURFACE)


@dataclass(frozen=True)
class ClipboardPolicy:
    """Clipboard ownership and lifetime.

    Wayland clipboard ownership belongs to the client that offered the data. The
    compositor holds a reference to the offer, not the bytes: reading requires a
    transfer from the owning client, so when that client exits the offer dies
    with it.
    """

    persists_to_disk: bool = False
    survives_owner_exit: bool = False
    sensitive_clearing_enabled: bool = False
    primary_selection_supported: bool = True
    image_supported: bool = True

    def describe(self) -> str:
        return (
            "Clipboard data is owned by the offering client for as long as that client "
            "lives. The compositor stores no clipboard content and writes none to disk. "
            "Sensitive-clipboard clearing was evaluated and is deliberately not enabled: "
            "silently emptying a user's clipboard loses data the user expected to keep."
        )
