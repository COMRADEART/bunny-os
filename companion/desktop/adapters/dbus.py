# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A table of complete D-Bus calls, and an invoker that can make only those.

§7: *do not expose a generic D-Bus invocation layer*. The difference between a
D-Bus client and a D-Bus adapter is whether the destination is a parameter, so
here it is not one. :data:`DBUS_CALLS` holds entries in which the bus name, the
object path, the interface, the method and the argument signature are all fixed,
and :meth:`SessionBus.call` takes a **call identifier** plus arguments. There is
no argument through which a caller could name a bus, and adding a destination
means adding a line to this table — which is a change somebody reviews.

The connection is the *session* bus and only ever the session bus. A system-bus
call is authority over the machine rather than over a desk, and §1 says the
desktop broker has no system-wide action authority. There is no code here that
opens the system bus, so there is nothing to misconfigure.

**Cancellation is real.** Every call takes a :class:`GioCancellable` and passes
it to ``call_sync``; a stop raised while a portal dialog is open aborts the call
rather than waiting for the dialog. §10 asks for portal requests to be cancelled
where supported, and the two-part answer is here (abort the pending call) and in
:meth:`SessionBus.close_request` (tell the portal to drop the request it already
accepted).

**PyGObject is required and its absence is reported, not worked around.** A
machine without it has no D-Bus transport, which makes several actions
unavailable, and §17 wants that said rather than routed around with a subprocess
that pretends.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Mapping

from ..errors import DesktopCancelled, DesktopUnavailable

__all__ = [
    "DBUS_CALLS",
    "DBusCall",
    "GioCancellable",
    "SessionBus",
    "gio_available",
]

#: How long any one D-Bus call may take before it is abandoned. Portal calls
#: return a handle immediately; the ones that wait are the ones a wedged service
#: would hold forever.
DEFAULT_CALL_TIMEOUT_MS = 15_000


@dataclass(frozen=True)
class DBusCall:
    """One complete, fixed call. Every field except the arguments is constant."""

    call_id: str
    bus_name: str
    object_path: str
    interface: str
    method: str
    #: The GVariant signature of the argument tuple.
    signature: str
    #: What the call is for, in one line, for the audit record.
    purpose: str
    #: ``True`` when the call changes something. Read-only calls are permitted
    #: during a probe; mutating ones never are.
    mutating: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "callId": self.call_id,
            "busName": self.bus_name,
            "objectPath": self.object_path,
            "interface": self.interface,
            "method": self.method,
            "signature": self.signature,
            "purpose": self.purpose,
            "mutating": self.mutating,
        }


#: Every D-Bus call this build may make. Nine entries, and a reader can check
#: the whole desktop D-Bus surface by reading them.
DBUS_CALLS: Mapping[str, DBusCall] = {
    item.call_id: item
    for item in (
        DBusCall(
            "notifications.capabilities",
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "GetCapabilities",
            "()",
            "ask the notification daemon what it supports; also the availability probe",
        ),
        DBusCall(
            "notifications.notify",
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "Notify",
            "(susssasa{sv}i)",
            "show one notification",
            mutating=True,
        ),
        DBusCall(
            "notifications.close",
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "CloseNotification",
            "(u)",
            "withdraw a notification this build sent, on cancellation",
            mutating=True,
        ),
        DBusCall(
            "portal.version",
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.DBus.Properties",
            "Get",
            "(ss)",
            "read a portal interface version; the portal availability probe",
        ),
        DBusCall(
            "portal.open_uri",
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.OpenURI",
            "OpenURI",
            "(ssa{sv})",
            "hand one URI to the desktop's handler for its scheme",
            mutating=True,
        ),
        DBusCall(
            "portal.close_request",
            "org.freedesktop.portal.Desktop",
            # The object path is per-request and is supplied by the caller as an
            # argument rather than being part of the entry, because a request
            # handle is minted by the portal. It is validated against the portal
            # request prefix before use; see `close_request`.
            "",
            "org.freedesktop.portal.Request",
            "Close",
            "()",
            "withdraw a portal request this build made, on cancellation",
            mutating=True,
        ),
        DBusCall(
            "filemanager.show_items",
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            "ShowItems",
            "(ass)",
            "reveal one file in the file manager, selected",
            mutating=True,
        ),
        DBusCall(
            "filemanager.show_folders",
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            "ShowFolders",
            "(ass)",
            "open one folder in the file manager",
            mutating=True,
        ),
        DBusCall(
            "dbus.name_has_owner",
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            "(s)",
            "ask whether a service is actually running; every availability probe",
        ),
    )
}

#: The only object-path prefix ``portal.close_request`` will accept. A handle
#: the portal minted always begins with it; anything else is a caller trying to
#: reach an arbitrary object through the one entry that takes a path.
_PORTAL_REQUEST_PREFIX = "/org/freedesktop/portal/desktop/request/"


def gio_available() -> bool:
    """Whether PyGObject's Gio is importable. Cached by the import system."""
    try:
        import gi  # noqa: F401

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: F401
    except (ImportError, ValueError, AttributeError):
        return False
    return True


class GioCancellable:
    """A stop signal the D-Bus layer can actually act on.

    Wraps :class:`Gio.Cancellable` where Gio is present and degrades to a plain
    flag where it is not, so that the calling code is the same in both cases and
    a test can raise a stop without a session bus.
    """

    def __init__(self) -> None:
        self._flag = threading.Event()
        self._native: Any = None
        if gio_available():
            from gi.repository import Gio

            self._native = Gio.Cancellable.new()

    @property
    def native(self) -> Any:
        return self._native

    @property
    def cancelled(self) -> bool:
        return self._flag.is_set()

    def cancel(self) -> bool:
        """Raise the stop. Returns whether this call was the one that raised it."""
        if self._flag.is_set():
            return False
        self._flag.set()
        if self._native is not None:
            self._native.cancel()
        return True

    def check(self, where: str) -> None:
        if self._flag.is_set():
            raise DesktopCancelled(
                f"the action was cancelled {where}", effect_known=False, effect_prevented=True
            )


class SessionBus:
    """The session bus, reachable only through :data:`DBUS_CALLS`.

    One connection per instance, opened lazily and kept, because opening a bus
    connection per action would show up in §24's latency figures as the cost of
    the action rather than as the cost of connecting.
    """

    def __init__(self) -> None:
        self._connection: Any = None
        self._guard = threading.RLock()
        self._closed = False

    # -- connection --------------------------------------------------------

    def connect(self) -> Any:
        with self._guard:
            if self._closed:
                raise DesktopUnavailable("this session bus connection has been closed")
            if self._connection is not None:
                return self._connection
            if not gio_available():
                raise DesktopUnavailable(
                    "PyGObject is not installed, so this build has no D-Bus transport and "
                    "cannot reach the desktop's services"
                )
            from gi.repository import Gio, GLib

            try:
                self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            except GLib.Error as exc:
                raise DesktopUnavailable(
                    f"the session bus could not be reached: {exc.message}"
                ) from None
            return self._connection

    def close(self) -> None:
        """Drop the connection. Called on shutdown so a restart starts clean."""
        with self._guard:
            self._connection = None
            self._closed = True

    @property
    def connected(self) -> bool:
        with self._guard:
            return self._connection is not None

    # -- calling -----------------------------------------------------------

    def call(
        self,
        call_id: str,
        arguments: tuple[Any, ...] = (),
        *,
        cancellable: GioCancellable | None = None,
        timeout_ms: int = DEFAULT_CALL_TIMEOUT_MS,
        object_path: str = "",
    ) -> Any:
        """Make one call from the table, and return its unpacked reply.

        ``object_path`` is accepted for the single entry whose path is minted by
        the portal, and is refused for every other entry — so the parameter
        cannot become a general way to address an object.
        """
        entry = DBUS_CALLS.get(call_id)
        if entry is None:
            raise DesktopUnavailable(
                f"{call_id!r} is not a declared D-Bus call; this build makes only the calls in "
                "companion.desktop.adapters.dbus.DBUS_CALLS"
            )
        if entry.object_path:
            if object_path and object_path != entry.object_path:
                raise DesktopUnavailable(
                    f"{call_id!r} has a fixed object path and one was supplied"
                )
            path = entry.object_path
        else:
            if not object_path.startswith(_PORTAL_REQUEST_PREFIX):
                raise DesktopUnavailable(
                    f"{call_id!r} may only address a portal request handle, and "
                    f"{object_path!r} is not one"
                )
            path = object_path

        if cancellable is not None:
            cancellable.check("before the call was made")

        connection = self.connect()
        from gi.repository import GLib

        try:
            payload = GLib.Variant(entry.signature, arguments)
        except (TypeError, ValueError) as exc:
            # A signature mismatch is a programming error in this package, not a
            # caller's fault, and it is raised rather than turned into a refusal
            # so it cannot be mistaken for a policy decision.
            raise DesktopUnavailable(
                f"{call_id!r} was given arguments that do not match its declared signature "
                f"{entry.signature}: {exc}"
            ) from None

        try:
            reply = connection.call_sync(
                entry.bus_name,
                path,
                entry.interface,
                entry.method,
                payload,
                None,
                0,  # Gio.DBusCallFlags.NONE
                int(timeout_ms),
                cancellable.native if cancellable is not None else None,
            )
        except GLib.Error as exc:
            if cancellable is not None and cancellable.cancelled:
                raise DesktopCancelled(
                    f"the {entry.method} call was cancelled",
                    effect_known=False,
                    # The call was aborted in flight. Whether the service had
                    # already acted is genuinely unknown, and §10 forbids
                    # claiming prevention that was not verified.
                    effect_prevented=False,
                ) from None
            raise DesktopUnavailable(
                f"{entry.bus_name} {entry.method} failed: {exc.message}"
            ) from None
        return reply.unpack() if reply is not None else None

    def name_has_owner(self, bus_name: str) -> bool:
        """Whether a service is actually running, rather than merely installed.

        §16: availability is not inferred from an installed binary. This is the
        question that replaces that inference, and it is the same question the
        desktop itself asks before dispatching to a service.
        """
        try:
            result = self.call("dbus.name_has_owner", (bus_name,), timeout_ms=2_000)
        except DesktopUnavailable:
            return False
        return bool(result and result[0])

    def close_request(self, handle: str, *, cancellable: GioCancellable | None = None) -> bool:
        """Withdraw a portal request. Best effort, and honest about being one.

        Returns whether the portal accepted the withdrawal. A ``False`` here is
        recorded rather than swallowed: §10 says a cancellation that could not
        prevent an effect must say so, and a portal that would not drop a
        request is exactly that case.
        """
        try:
            self.call("portal.close_request", (), object_path=handle, cancellable=None, timeout_ms=2_000)
        except (DesktopUnavailable, DesktopCancelled):
            return False
        return True
