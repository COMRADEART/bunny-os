# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What this machine can actually do, asked of the machine rather than of a list.

§16's rule is one sentence — *do not infer availability solely from installed
binaries* — and it is the rule most easily broken by accident, because checking
for a binary is easy and asking a service is not. Every probe reached from here
asks the service:

* the notification daemon is asked whether it **owns its bus name**, not whether
  ``notify-send`` exists;
* the portal is asked for the **version of its OpenURI interface**, not whether
  ``xdg-desktop-portal`` is installed;
* the mixer is asked for ``pactl info``, which fails when no sound server is
  running however installed ``pactl`` is;
* the clipboard is decided from which **compositor socket** is in the
  environment, and then from whether the matching helper exists — in that order,
  because a Wayland session with only ``xclip`` installed has no clipboard this
  build can take.

The four postures §16 names come out of that, and they are a ladder rather than
a taxonomy:

``desktop-actions-available``
    a graphical session and the services the catalogue needs.
``limited-desktop-actions``
    a graphical session and some of them. The report says which are missing and
    why, per action, so a refusal later can quote a reason that was measured
    rather than assumed.
``notification-only``
    no graphical session and a notification path that still works. This is a
    real configuration — a headless user service with a notification daemon —
    and collapsing it into "headless" would refuse something that works.
``headless-no-desktop-actions``
    nothing. §17's behaviour, and the report says so per action rather than
    failing each one at the moment it is attempted.

**Reduced interruption is a preference, not a capability**, and it is kept
separate for that reason. A user who has asked for fewer interruptions has not
made notifications impossible; they have made an unrequested one a bad idea. The
report carries the preference and the broker applies it to the *approval* — a
notification under reduced interruption is never sent unasked — rather than
reporting the action unavailable, which would be a lie about the machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import stat
import threading
from typing import Any, Mapping, Sequence

from .adapters.application import ApplicationLaunchAdapter, ApplicationPresentAdapter
from .adapters.audio import AudioControlAdapter
from .adapters.base import Availability
from .adapters.clipboard import ClipboardAdapter
from .adapters.dbus import SessionBus
from .adapters.filereveal import FileRevealAdapter
from .adapters.notification import NotificationAdapter
from .adapters.portal import PortalAdapter
from .adapters.settings import SettingsAdapter, current_desktop
from .adapters.uri import UriOpenAdapter
from .catalogue import ACTION_IDS, DESCRIPTORS

__all__ = [
    "DESKTOP_POSTURES",
    "DesktopAdapters",
    "DesktopEnvironmentReport",
    "ServiceStanding",
    "adopt_graphical_environment",
    "graphical_session",
    "probe_environment",
    "session_type",
]

#: §16's four outcomes, most capable first.
DESKTOP_POSTURES = (
    "desktop-actions-available",
    "limited-desktop-actions",
    "notification-only",
    "headless-no-desktop-actions",
)

#: Actions that remain possible without a graphical session. §17: audio may,
#: when a user audio session exists; notifications may, degraded; everything
#: else may not.
_HEADLESS_CANDIDATES = frozenset({
    "desktop.notification.show",
    "desktop.audio.set-volume",
})


def session_type() -> str:
    """``wayland``, ``x11``, or ``none``, from the sockets rather than a claim.

    ``XDG_SESSION_TYPE`` is checked *last*. It is a declaration by the session
    manager and it is wrong on more machines than the sockets are — notably
    under XWayland, where it says ``wayland`` for a client that has only
    ``DISPLAY``.
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    declared = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    return declared if declared in ("wayland", "x11") else "none"


def graphical_session() -> bool:
    return session_type() != "none"


def adopt_graphical_environment() -> dict[str, str]:
    """Find the display this process was started too early to be told about.

    Measured on a booted system, not anticipated. `bunny-companion.service` is
    `WantedBy=graphical-session.target` and ordered only after
    `graphical-session-pre.target`, so it starts *while* the target is being
    reached — two seconds before gnome-session imports `WAYLAND_DISPLAY` and
    `DISPLAY` into the user manager's environment. Its own environment
    therefore has `XDG_SESSION_TYPE=wayland` and neither display variable, and
    every adapter that asks for one refuses for the life of the session:

        there is no graphical session, so a launched application would have
        nowhere to appear

    A spoken "Open Files" reached the launcher, was approved, and was answered
    with that sentence on a machine with a desktop plainly on screen. The
    defect hid for a long time because *restarting* the service — which any
    development iteration does — picks the variables up and makes it work.

    The unit ordering is fixed as well; this exists because ordering is a
    promise about start time and this is a fact about the machine. The socket
    is the evidence: `$XDG_RUNTIME_DIR` is the user's own directory, 0700, and
    a `wayland-N` socket in it is a display this user can use. Nothing is
    invented — if there is no socket, nothing is adopted and the refusal
    stands.

    Returns what it set, for the record. Idempotent.
    """
    adopted: dict[str, str] = {}
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        return adopted
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime:
        return adopted
    try:
        entries = sorted(os.listdir(runtime))
    except OSError:
        return adopted
    for entry in entries:
        # `wayland-0`, not `wayland-0.lock`: the socket, not its lock file.
        if not entry.startswith("wayland-") or entry.endswith(".lock"):
            continue
        candidate = os.path.join(runtime, entry)
        try:
            if not stat.S_ISSOCK(os.stat(candidate).st_mode):
                continue
        except OSError:
            continue
        os.environ["WAYLAND_DISPLAY"] = entry
        adopted["WAYLAND_DISPLAY"] = entry
        return adopted
    return adopted


@dataclass(frozen=True)
class ServiceStanding:
    """One backend's answer, and the words it answered with."""

    adapter_id: str
    available: bool
    mechanism: str = ""
    service: str = ""
    detail: str = ""
    probe_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "available": self.available,
            "mechanism": self.mechanism,
            "service": self.service,
            "detail": self.detail,
            "probeSeconds": round(self.probe_seconds, 6),
        }


@dataclass(frozen=True)
class DesktopEnvironmentReport:
    """What can be done here, per action, with the reason for each answer."""

    posture: str
    session: str
    desktop: str
    graphical: bool
    services: tuple[ServiceStanding, ...] = ()
    #: Actions whose backend answered. Declared *and* available (§6).
    available_actions: tuple[str, ...] = ()
    #: Action id to the sentence explaining why it is not available.
    unavailable_actions: Mapping[str, str] = field(default_factory=dict)
    #: The user has asked for fewer interruptions. A preference, applied to the
    #: approval rather than to availability; see the module docstring.
    reduced_interruption: bool = False
    #: §17: whether this build may open a URI with no graphical session. Off
    #: unless a policy explicitly turns it on.
    headless_uri_policy: bool = False
    #: Capability-plan facts this decision was read against, for the record.
    capability_signals: Mapping[str, Any] = field(default_factory=dict)
    probe_seconds: float = 0.0

    def permits(self, action_id: str) -> bool:
        return action_id in self.available_actions

    def reason(self, action_id: str) -> str:
        if action_id in self.available_actions:
            return ""
        return self.unavailable_actions.get(
            action_id, f"{action_id} is not available in this session"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "posture": self.posture,
            "session": self.session,
            "desktop": self.desktop,
            "graphical": self.graphical,
            "services": [item.to_json() for item in self.services],
            "availableActions": list(self.available_actions),
            "unavailableActions": dict(self.unavailable_actions),
            "reducedInterruption": self.reduced_interruption,
            "headlessUriPolicy": self.headless_uri_policy,
            "capabilitySignals": dict(self.capability_signals),
            "probeSeconds": round(self.probe_seconds, 6),
        }


class DesktopAdapters:
    """The nine adapters, sharing one session-bus connection.

    Shared because opening a bus connection per action would put connection
    setup into §24's per-action latency figures, and because §23 counts D-Bus
    connections — a set that opened one per adapter would report nine where one
    is correct.
    """

    def __init__(self, *, bus: SessionBus | None = None, desktop: str = "") -> None:
        self.bus = bus if bus is not None else SessionBus()
        self.portal = PortalAdapter(self.bus)
        self.notification = NotificationAdapter(self.bus)
        self.launch = ApplicationLaunchAdapter(self.bus)
        self.present = ApplicationPresentAdapter(self.bus)
        self.settings = SettingsAdapter(desktop or current_desktop())
        self.audio = AudioControlAdapter()
        self.clipboard = ClipboardAdapter()
        self.uri = UriOpenAdapter(self.portal)
        self.file_reveal = FileRevealAdapter(self.bus)
        self._guard = threading.RLock()

    def resource_counts(self) -> dict[str, int]:
        """The counters §23 reads. Zero at rest is the whole assertion."""
        return {
            "portalHandles": self.portal.outstanding,
            "clipboardOwners": self.clipboard.outstanding,
            "notificationsTracked": self.notification.outstanding,
            "dbusConnections": 1 if self.bus.connected else 0,
        }

    def release_all(self, reason: str = "shutting down") -> dict[str, int]:
        """Give up every held resource. Idempotent, and reports what it dropped."""
        with self._guard:
            released = {
                "portalHandles": len(self.portal.release_all(reason)),
                "clipboardOwners": self.clipboard.release_all(reason),
                # Settings windows are *reaped*, never signalled. One still open
                # is the user's window; one that has closed is a process-table
                # entry this build owes the machine.
                "settingsWindowsReaped": self.settings.reap(),
            }
            # Notifications already delivered stay delivered. §10 requires
            # completed effects to be preserved honestly, so this drops the
            # bookkeeping and claims nothing about the screen.
            self.notification.forget_all()
        return released

    def close(self) -> None:
        self.release_all("closing")
        self.bus.close()


def probe_environment(
    adapters: DesktopAdapters,
    *,
    accessibility: Any = None,
    capability_signals: Mapping[str, Any] | None = None,
    headless_uri_policy: bool = False,
    monotonic: Any = None,
) -> DesktopEnvironmentReport:
    """Ask every backend, once, and decide what may be attempted.

    ``accessibility`` is a
    :class:`companion.presentation.AccessibilityPreferences` or anything with the
    same attributes. Duck-typed rather than imported so that this module keeps no
    dependency on the presentation layer: the desktop package is the *effect*
    side and the presentation package is the *surface* side, and an import
    between them would eventually become a cycle.
    """
    import time as _time

    clock = monotonic or _time.monotonic
    started = clock()
    signals = dict(capability_signals or {})

    standings: list[ServiceStanding] = []

    def measure(adapter_id: str, probe: Any) -> Availability:
        at = clock()
        try:
            result = probe()
        except Exception as exc:  # a probe is allowed to fail; it is not allowed to raise
            result = Availability(False, detail=f"the probe failed: {type(exc).__name__}: {exc}")
        standings.append(ServiceStanding(
            adapter_id=adapter_id,
            available=result.available,
            mechanism=result.mechanism,
            service=result.service,
            detail=result.detail,
            probe_seconds=max(0.0, clock() - at),
        ))
        return result

    notification = measure("NotificationAdapter", adapters.notification.probe)
    portal = measure("PortalAdapter", adapters.portal.probe)
    launch = measure("ApplicationLaunchAdapter", adapters.launch.probe)
    present = measure("ApplicationPresentAdapter", adapters.present.probe)
    settings = measure("SettingsAdapter", adapters.settings.probe)
    dnd = measure("SettingsAdapter.doNotDisturb", adapters.settings.probe_do_not_disturb)
    audio = measure("AudioControlAdapter", adapters.audio.probe)
    clipboard = measure("ClipboardAdapter", adapters.clipboard.probe)
    reveal = measure("FileRevealAdapter", adapters.file_reveal.probe)

    graphical = graphical_session()
    per_action: dict[str, Availability] = {
        "desktop.notification.show": notification,
        "desktop.application.launch": launch,
        "desktop.application.present": present,
        "desktop.settings.open": settings,
        "desktop.audio.set-volume": audio,
        "desktop.notifications.set-do-not-disturb": dnd,
        "desktop.clipboard.copy-text": clipboard,
        "desktop.uri.open": portal,
        "desktop.file.reveal": reveal,
    }

    available: list[str] = []
    unavailable: dict[str, str] = {}
    for action_id in ACTION_IDS:
        answer = per_action[action_id]
        if not graphical:
            # §17's three cases, in order. The URI one is checked *first*
            # because it is the exception to the blanket refusal below, and an
            # earlier version of this loop had it second — where the `continue`
            # above it made the policy unreachable and the flag did nothing.
            if action_id == "desktop.uri.open":
                if headless_uri_policy and answer.available:
                    available.append(action_id)
                else:
                    unavailable[action_id] = (
                        "opening a URI with no graphical session is disabled by default; it "
                        "needs an explicitly supported headless policy"
                        if not headless_uri_policy
                        else answer.detail or "the URI opener is unavailable"
                    )
                continue
            if action_id not in _HEADLESS_CANDIDATES:
                # Said once per action rather than discovered at the moment of
                # attempt. The sentence names the *action*, because "there is no
                # graphical session" alone leaves a user wondering which part
                # failed.
                unavailable[action_id] = (
                    f"{DESCRIPTORS[action_id].summary.lower()} needs a graphical session and "
                    "there is none here"
                )
                continue
        if answer.available:
            available.append(action_id)
        else:
            unavailable[action_id] = answer.detail or f"{action_id} is unavailable"

    posture = _posture(graphical, tuple(available))
    return DesktopEnvironmentReport(
        posture=posture,
        session=session_type(),
        desktop=adapters.settings.desktop,
        graphical=graphical,
        services=tuple(standings),
        available_actions=tuple(available),
        unavailable_actions=dict(sorted(unavailable.items())),
        reduced_interruption=_reduced_interruption(accessibility),
        headless_uri_policy=bool(headless_uri_policy),
        capability_signals=signals,
        probe_seconds=max(0.0, clock() - started),
    )


def _posture(graphical: bool, available: Sequence[str]) -> str:
    if not graphical:
        if available and set(available) <= {"desktop.notification.show", "desktop.audio.set-volume"}:
            return "notification-only" if "desktop.notification.show" in available else (
                "headless-no-desktop-actions"
            )
        return "headless-no-desktop-actions"
    if len(available) == len(ACTION_IDS):
        return "desktop-actions-available"
    if available:
        return "limited-desktop-actions"
    # A graphical session in which nothing works. Rare, and reported as headless
    # rather than as "limited": limited implies something is possible.
    return "headless-no-desktop-actions"


def _reduced_interruption(accessibility: Any) -> bool:
    """Whether the user has asked for fewer interruptions.

    Read from whichever of the preference names is present, because the two
    surfaces that carry this — the presentation layer's
    ``AccessibilityPreferences`` and a client's own settings — spell it
    differently and neither is wrong.
    """
    if accessibility is None:
        return False
    for name in ("reduced_interruption", "prefer_text_only", "reduced_motion"):
        value = getattr(accessibility, name, None)
        if isinstance(value, bool) and value:
            return True
    return False
