# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Show one notification, and be precise about what that proves.

``org.freedesktop.Notifications.Notify`` returns an unsigned integer: the id the
daemon assigned. That id proves the daemon accepted the request. It does not
prove the notification was displayed, that it was not suppressed by
do-not-disturb, or that anybody saw it. So this adapter reports an
acknowledgement and the result state is ``accepted-not-confirmed``, which is the
*normal* outcome for a notification rather than a degraded one.

Three of the argument slots are pinned rather than parameterised, and each is a
capability this phase does not have:

``actions``
    always empty. §4.1 forbids arbitrary notification actions, and an action is
    a button that sends a signal back to us naming a key the notification
    supplied — which is a callback channel a provider would eventually be able
    to name. There is no parameter for it here and none in the schema.
``app_icon``
    a fixed themed icon name. A path here would be a file the daemon reads on
    our behalf, which is an arbitrary-file-read with extra steps.
``replaces_id``
    always zero on send. Replacing a notification is a way to alter something a
    user has already seen, and nothing in this catalogue needs it. The id is
    kept only so that :meth:`NotificationAdapter.close` can withdraw *our own*
    notification during cancellation.

The `notify-send` path exists for a session whose daemon is not on the bus but
whose desktop still shows notifications. It is not a hidden fallback: the
mechanism is recorded in the outcome, surfaces show it, and §24's measurements
separate the two.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping

from ..errors import DesktopCancelled, DesktopUnavailable
from ..parameters import MAX_NOTIFICATION_TIMEOUT_MS
from .base import AdapterOutcome, Availability, acknowledged, failure
from .command import have, run_command
from .dbus import GioCancellable, SessionBus, gio_available

__all__ = ["NOTIFICATION_BUS_NAME", "NotificationAdapter"]

NOTIFICATION_BUS_NAME = "org.freedesktop.Notifications"

#: The application name and icon every notification carries. Constants, so a
#: notification from this build is identifiable as one and neither field is a
#: place for caller-supplied material.
_APPLICATION_NAME = "Bunny Companion"
_APPLICATION_ICON = "dialog-information"
_DESKTOP_ENTRY = "art.comrade.Bunny"

#: The freedesktop urgency values.
_URGENCY = {"low": 0, "normal": 1, "critical": 2}


class NotificationAdapter:
    """Show one notification. That is the whole of its surface."""

    adapter_id = "NotificationAdapter"

    def __init__(self, bus: SessionBus | None = None) -> None:
        self._bus = bus if bus is not None else SessionBus()
        self._guard = threading.RLock()
        #: Ids this build sent, so cancellation can withdraw its own and only
        #: its own. A daemon-wide close would let a task dismiss a notification
        #: from another application.
        self._sent: list[int] = []

    # -- availability ------------------------------------------------------

    def probe(self) -> Availability:
        if gio_available():
            try:
                if self._bus.name_has_owner(NOTIFICATION_BUS_NAME):
                    capabilities = self._bus.call("notifications.capabilities", (), timeout_ms=2_000)
                    offered = tuple(capabilities[0]) if capabilities else ()
                    return Availability(
                        True, mechanism="dbus", service=NOTIFICATION_BUS_NAME,
                        detail=f"the daemon answered and offers {len(offered)} capabilities",
                    )
            except DesktopUnavailable:
                pass
        if have("notify-send"):
            return Availability(
                True, mechanism="notify-send", service="notify-send",
                detail=(
                    "no notification daemon answered on the session bus; notify-send is "
                    "installed and will be used, and this is recorded on every result"
                ),
            )
        return Availability(
            False, mechanism="", service=NOTIFICATION_BUS_NAME,
            detail="no notification daemon is running and notify-send is not installed",
        )

    def supports_markup(self) -> bool:
        """Whether the daemon parses markup in a body.

        Asked for the record rather than for a decision: the body is escaped
        either way, because escaping unconditionally is what makes the displayed
        text the text the task produced.
        """
        try:
            capabilities = self._bus.call("notifications.capabilities", (), timeout_ms=2_000)
        except DesktopUnavailable:
            return False
        return bool(capabilities and "body-markup" in tuple(capabilities[0]))

    # -- the one operation -------------------------------------------------

    def show(
        self,
        *,
        title: str,
        body: str = "",
        urgency: str = "normal",
        timeout_ms: int | None = None,
        cancellable: GioCancellable | None = None,
    ) -> AdapterOutcome:
        """Dispatch one notification.

        ``timeout_ms`` of ``None`` means "let the daemon decide", which is the
        ``-1`` the specification defines. Zero — "until dismissed" — is
        unreachable from here because the schema's range excludes it; §4.1 wants
        indefiniteness argued for, and it is argued for in
        :func:`companion.desktop.parameters.normalise` rather than smuggled
        through as a number.
        """
        if urgency not in _URGENCY:
            raise DesktopUnavailable(f"{urgency!r} is not a notification urgency")
        if timeout_ms is not None and not 0 < timeout_ms <= MAX_NOTIFICATION_TIMEOUT_MS:
            raise DesktopUnavailable("the notification timeout is outside the permitted range")
        if cancellable is not None:
            cancellable.check("before the notification was dispatched")

        started = time.monotonic()
        availability = self.probe()
        availability.require("desktop.notification.show")

        if availability.mechanism == "dbus":
            return self._show_over_dbus(
                title=title, body=body, urgency=urgency, timeout_ms=timeout_ms,
                cancellable=cancellable, started=started,
            )
        return self._show_over_command(
            title=title, body=body, urgency=urgency, timeout_ms=timeout_ms,
            cancellable=cancellable, started=started,
        )

    def _show_over_dbus(
        self, *, title: str, body: str, urgency: str, timeout_ms: int | None,
        cancellable: GioCancellable | None, started: float,
    ) -> AdapterOutcome:
        from gi.repository import GLib

        hints: dict[str, Any] = {
            "urgency": GLib.Variant("y", _URGENCY[urgency]),
            "desktop-entry": GLib.Variant("s", _DESKTOP_ENTRY),
            # The daemon may not log or persist the body. Advisory — a daemon is
            # free to ignore it — and set because asking costs nothing and §13
            # cares about where a task's words end up.
            "transient": GLib.Variant("b", timeout_ms is not None),
        }
        try:
            reply = self._bus.call(
                "notifications.notify",
                (
                    _APPLICATION_NAME,
                    0,                       # replaces_id: never replace
                    _APPLICATION_ICON,
                    title,
                    body,
                    [],                      # actions: always empty
                    hints,
                    -1 if timeout_ms is None else int(timeout_ms),
                ),
                cancellable=cancellable,
            )
        except DesktopCancelled:
            raise
        except DesktopUnavailable as exc:
            return failure("dbus", str(exc))
        notification_id = int(reply[0]) if reply else 0
        if notification_id:
            with self._guard:
                self._sent.append(notification_id)
        outcome = acknowledged(
            "dbus",
            detail="the notification daemon accepted the request and returned an id",
            notificationId=notification_id,
        )
        return _timed(outcome, started)

    def _show_over_command(
        self, *, title: str, body: str, urgency: str, timeout_ms: int | None,
        cancellable: GioCancellable | None, started: float,
    ) -> AdapterOutcome:
        arguments = [
            "--app-name", _APPLICATION_NAME,
            "--icon", _APPLICATION_ICON,
            "--urgency", urgency,
        ]
        if timeout_ms is not None:
            arguments += ["--expire-time", str(int(timeout_ms))]
        # The title and body are the last two positional arguments. They are the
        # one place caller-derived text reaches an argv here, and `--` is what
        # stops a title beginning with a dash being read as an option.
        arguments += ["--", title, body]
        outcome = run_command("notify-send", arguments, timeout_seconds=8.0, cancellation=None)
        if outcome.cancelled:
            raise DesktopCancelled(
                "the notification was cancelled while notify-send was running",
                effect_known=False, effect_prevented=False,
            )
        if not outcome.succeeded:
            return failure(
                "notify-send",
                outcome.stderr or f"notify-send exited {outcome.exit_code}",
            )
        return _timed(
            acknowledged(
                "notify-send",
                detail=(
                    "notify-send exited successfully; it returns no id, so this build cannot "
                    "withdraw this notification if the task is cancelled"
                ),
                notificationId=0,
            ),
            started,
        )

    # -- cancellation ------------------------------------------------------

    def close(self, notification_id: int) -> bool:
        """Withdraw one notification this build sent.

        Best effort and honest about it: a daemon may have already displayed and
        dismissed it, and the specification gives no way to tell the difference
        between "withdrawn before anybody saw it" and "withdrawn after". So this
        returns whether the daemon accepted the call, and the caller records a
        cancellation whose effect was *not* verified as prevented.
        """
        with self._guard:
            if notification_id not in self._sent:
                # Refusing to close an id we did not send is the check that
                # stops a task dismissing another application's notification.
                return False
        try:
            self._bus.call("notifications.close", (int(notification_id),), timeout_ms=2_000)
        except (DesktopUnavailable, DesktopCancelled):
            return False
        with self._guard:
            if notification_id in self._sent:
                self._sent.remove(notification_id)
        return True

    @property
    def outstanding(self) -> int:
        with self._guard:
            return len(self._sent)

    def forget_all(self) -> None:
        """Drop the sent-id list without withdrawing anything.

        Used at shutdown. A notification already delivered stays delivered —
        §10 requires completed effects to be preserved honestly — so this
        releases our bookkeeping and does not pretend to undo anything.
        """
        with self._guard:
            self._sent.clear()

    def close_connection(self) -> None:
        self.forget_all()
        self._bus.close()


def _timed(outcome: AdapterOutcome, started: float) -> AdapterOutcome:
    from dataclasses import replace

    return replace(outcome, duration_seconds=max(0.0, time.monotonic() - started))
