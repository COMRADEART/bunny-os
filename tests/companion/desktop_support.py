# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures for the desktop-action tests: a desk that is not a desk.

The adapters here answer the way real ones do — an acknowledgement for the
things that can only be acknowledged, a read-back for the three that can be
verified — and record what they were asked. They are **not** a second
implementation of the broker's decisions: every refusal, every binding check,
every ledger transition and every result-state rule runs in the real code. What
is substituted is the last inch, where a D-Bus call or a process would be.

That substitution is what makes the security tests meaningful on any machine. A
test asserting "a traversal is refused" is worth having only if it runs
everywhere, and a test that needed a session bus would be skipped on the one
place it most matters — a continuous-integration runner with no desk at all.

The real adapters are exercised separately, on Linux, by the vertical slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from companion.desktop.adapters.base import (
    AdapterOutcome,
    Availability,
    acknowledged,
    failure,
    unsupported_outcome,
    verified,
)
from companion.desktop.broker import BrokerOptions, DesktopActionBroker
from companion.desktop.paths import PathContext

__all__ = [
    "FakeAdapters",
    "build_broker",
    "make_entry",
    "make_paths",
    "sample_parameters",
]


class _Recorder:
    """Every call this adapter received, in order, with its arguments."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]], name: str) -> None:
        self._calls = calls
        self._name = name

    def note(self, method: str, **arguments: Any) -> None:
        self._calls.append((f"{self._name}.{method}", dict(arguments)))


class _FakeNotification(_Recorder):
    adapter_id = "NotificationAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "notification")
        self.state = state
        self._next = 1

    def probe(self) -> Availability:
        return Availability(self.state["notification"], mechanism="fake", service="notifications")

    def show(self, *, title, body="", urgency="normal", timeout_ms=None, cancellable=None):
        self.note("show", title=title, body=body, urgency=urgency, timeoutMs=timeout_ms)
        if not self.state["notification"]:
            return unsupported_outcome("fake", "no notification daemon")
        identifier = self._next
        self._next += 1
        self.state["notifications"].append(identifier)
        return acknowledged("fake", detail="the daemon accepted it", notificationId=identifier)

    def close(self, notification_id: int) -> bool:
        self.note("close", notificationId=notification_id)
        if notification_id in self.state["notifications"]:
            self.state["notifications"].remove(notification_id)
            return True
        return False

    @property
    def outstanding(self) -> int:
        return len(self.state["notifications"])

    def forget_all(self) -> None:
        self.state["notifications"].clear()


class _FakeLaunch(_Recorder):
    adapter_id = "ApplicationLaunchAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "launch")
        self.state = state

    def probe(self) -> Availability:
        return Availability(self.state["launch"], mechanism="fake", service="gio")

    def running(self, entry) -> bool | None:
        return None

    def launch(self, entry, *, file_paths=(), uris=(), focus_existing=True, cancellable=None):
        self.note(
            "launch", applicationId=entry.application_id,
            files=list(file_paths), uris=[item.normalised for item in uris],
        )
        if not self.state["launch"]:
            return unsupported_outcome("fake", "no graphical session")
        return acknowledged("fake", detail="gio launched it", applicationId=entry.application_id)


class _FakePresent(_Recorder):
    adapter_id = "ApplicationPresentAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "present")
        self.state = state

    def probe(self) -> Availability:
        return Availability(self.state["present"], mechanism="fake", service="activation")

    def present(self, entry, *, window_identity="", cancellable=None):
        self.note("present", applicationId=entry.application_id, windowIdentity=window_identity)
        if not entry.dbus_activatable:
            return unsupported_outcome(
                "fake", f"{entry.application_id} does not declare DBusActivatable"
            )
        return acknowledged("fake", detail="activation requested")


class _FakeSettings(_Recorder):
    adapter_id = "SettingsAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "settings")
        self.state = state
        self.desktop = "GNOME"

    def probe(self) -> Availability:
        return Availability(self.state["settings"], mechanism="fake", service="settings")

    def probe_do_not_disturb(self) -> Availability:
        return Availability(self.state["dnd"], mechanism="fake", service="gsettings")

    def open_page(self, page, *, cancellable=None):
        self.note("open_page", page=page)
        if not self.state["settings"]:
            return unsupported_outcome("fake", "no settings mapping")
        return acknowledged("fake", detail=f"opened {page}", page=page)

    def read_do_not_disturb(self) -> bool | None:
        return self.state["dndValue"] if self.state["dnd"] else None

    def set_do_not_disturb(self, enabled, *, cancellable=None):
        self.note("set_do_not_disturb", enabled=enabled)
        if not self.state["dnd"]:
            return unsupported_outcome("fake", "do-not-disturb is not readable here")
        previous = self.state["dndValue"]
        self.state["dndValue"] = bool(enabled)
        return verified(
            "fake", detail="read back", matched=True, observed_value=bool(enabled),
            previousEnabled=previous,
        )


class _FakeAudio(_Recorder):
    adapter_id = "AudioControlAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "audio")
        self.state = state

    def probe(self) -> Availability:
        return Availability(self.state["audio"], mechanism="fake", service="mixer")

    def default_output_id(self) -> str:
        return self.state["sink"] if self.state["audio"] else ""

    def read(self, output_id=""):
        from companion.desktop.adapters.audio import AudioOutput

        if not self.state["audio"]:
            return None
        name = output_id or self.state["sink"]
        if name != self.state["sink"]:
            return None
        return AudioOutput(
            output_id=name, display_name="Speakers",
            percent=self.state["percent"], muted=self.state["muted"],
        )

    def default_output(self):
        return self.read("")

    def set_volume(self, *, output_id, percent, muted=None, cancellable=None):
        self.note("set_volume", outputId=output_id, percent=percent, muted=muted)
        if not self.state["audio"]:
            return unsupported_outcome("fake", "no mixer")
        if output_id != self.state["sink"]:
            return failure("fake", f"the output {output_id!r} is no longer present")
        previous = self.state["percent"]
        previous_muted = self.state["muted"]
        self.state["percent"] = int(percent)
        if muted is not None:
            self.state["muted"] = bool(muted)
        return verified(
            "fake", detail="read back", matched=True, observed_value=int(percent),
            previousPercent=previous, previousMuted=previous_muted,
            outputId=output_id, outputName="Speakers",
        )


class _FakeHold:
    """A stand-in selection, with the real clear-after timer.

    The *timer* is real on purpose. It is the part of the clear-after policy
    that can leave a thread behind, and a fixture that faked it would test
    nothing about the thing §23's thread counter exists to catch.
    """

    def __init__(self, state, clear_after_seconds: float = 0.0) -> None:
        import threading

        self.state = state
        self._held = True
        self.clear_after_seconds = max(0.0, float(clear_after_seconds))
        self.cleared_by_policy = False
        self._timer = None
        if self.clear_after_seconds > 0:
            self._timer = threading.Timer(self.clear_after_seconds, self._expire)
            self._timer.name = "bunny-clipboard-expiry"
            self._timer.daemon = True
            self._timer.start()

    def _expire(self) -> None:
        if self.release("the clear-after policy expired"):
            self.cleared_by_policy = True

    @property
    def held(self) -> bool:
        return self._held

    def release(self, reason="released") -> bool:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        if not self._held:
            return False
        self._held = False
        self.state["clipboardOwners"] = max(0, self.state["clipboardOwners"] - 1)
        return True


class _FakeClipboard(_Recorder):
    adapter_id = "ClipboardAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "clipboard")
        self.state = state
        self._holds: list[_FakeHold] = []

    def probe(self) -> Availability:
        return Availability(self.state["clipboard"], mechanism="fake", service="selection")

    def copy(self, text, *, cancellable=None, clear_after_seconds=0.0):
        # The digest, never the text: the fixture obeys §13 too, so a test that
        # accidentally asserted on the content would have to reach for it.
        import hashlib

        self.note("copy", digest=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                  length=len(text), clearAfterSeconds=clear_after_seconds)
        if not self.state["clipboard"]:
            return unsupported_outcome("fake", "no clipboard"), None
        hold = _FakeHold(self.state, clear_after_seconds)
        self._holds.append(hold)
        self.state["clipboardOwners"] += 1
        return verified(
            "fake", kind="ownership", detail="the selection is held", matched=True,
        ), hold

    def release(self, hold, reason="released") -> bool:
        self.note("release", reason=reason)
        released = hold.release(reason)
        if hold in self._holds:
            self._holds.remove(hold)
        return released

    def release_all(self, reason="shutting down") -> int:
        holds = list(self._holds)
        self._holds.clear()
        return sum(1 for item in holds if item.release(reason))

    @property
    def outstanding(self) -> int:
        return sum(1 for item in self._holds if item.held)


class _FakeUri(_Recorder):
    adapter_id = "UriOpenAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "uri")
        self.state = state

    def probe(self) -> Availability:
        return Availability(self.state["portal"], mechanism="fake", service="portal")

    def open(self, uri, *, cancellable=None):
        self.note("open", uri=uri.normalised, scheme=uri.scheme)
        if not self.state["portal"]:
            return unsupported_outcome("fake", "no portal")
        self.state["opened"].append(uri.normalised)
        return acknowledged("fake", detail="the portal accepted it")

    def cancel(self) -> bool:
        self.note("cancel")
        return False

    def settle(self) -> None:
        return None

    @property
    def outstanding(self) -> int:
        return 0


class _FakeReveal(_Recorder):
    adapter_id = "FileRevealAdapter"

    def __init__(self, calls, state) -> None:
        super().__init__(calls, "reveal")
        self.state = state

    def probe(self) -> Availability:
        return Availability(self.state["reveal"], mechanism="fake", service="file-manager")

    def reveal(self, path, *, cancellable=None):
        self.note("reveal", path=path.real_path, isDirectory=path.is_directory)
        if not self.state["reveal"]:
            return unsupported_outcome("fake", "no file manager")
        self.state["revealed"].append(path.real_path)
        return acknowledged("fake", detail="the file manager accepted it")


class _FakePortal:
    adapter_id = "PortalAdapter"

    def __init__(self, state) -> None:
        self.state = state

    def probe(self) -> Availability:
        return Availability(self.state["portal"], mechanism="fake", service="portal")

    @property
    def outstanding(self) -> int:
        return 0

    def release_all(self, reason="") -> tuple[str, ...]:
        return ()


class _FakeBus:
    connected = False

    def close(self) -> None:
        return None


class FakeAdapters:
    """A :class:`companion.desktop.environment.DesktopAdapters` that answers.

    Every flag in :attr:`state` turns one backend on or off, so a headless
    machine, a machine with no mixer and a machine with everything are three
    values rather than three environments.
    """

    def __init__(self, **overrides: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.state: dict[str, Any] = {
            "notification": True,
            "launch": True,
            "present": True,
            "settings": True,
            "dnd": True,
            "dndValue": False,
            "audio": True,
            "sink": "fake-sink",
            "percent": 35,
            "muted": False,
            "clipboard": True,
            "portal": True,
            "reveal": True,
            "notifications": [],
            "clipboardOwners": 0,
            "opened": [],
            "revealed": [],
        }
        self.state.update(overrides)
        self.bus = _FakeBus()
        self.notification = _FakeNotification(self.calls, self.state)
        self.launch = _FakeLaunch(self.calls, self.state)
        self.present = _FakePresent(self.calls, self.state)
        self.settings = _FakeSettings(self.calls, self.state)
        self.audio = _FakeAudio(self.calls, self.state)
        self.clipboard = _FakeClipboard(self.calls, self.state)
        self.uri = _FakeUri(self.calls, self.state)
        self.file_reveal = _FakeReveal(self.calls, self.state)
        self.portal = _FakePortal(self.state)

    def resource_counts(self) -> dict[str, int]:
        return {
            "portalHandles": 0,
            "clipboardOwners": self.clipboard.outstanding,
            "notificationsTracked": self.notification.outstanding,
            "dbusConnections": 0,
        }

    def release_all(self, reason: str = "") -> dict[str, int]:
        return {
            "portalHandles": 0,
            "clipboardOwners": self.clipboard.release_all(reason),
        }

    def close(self) -> None:
        self.release_all("closing")

    def called(self, method: str) -> tuple[dict[str, Any], ...]:
        return tuple(arguments for name, arguments in self.calls if name == method)


def build_broker(
    *,
    adapters: FakeAdapters | None = None,
    ledger_path: Path | None = None,
    graphical: bool = True,
    **options: Any,
) -> tuple[DesktopActionBroker, FakeAdapters]:
    """A real broker with a fake desk, already started and probed.

    ``graphical`` sets or clears the compositor variables for the duration of
    the returned broker's life, because
    :func:`companion.desktop.environment.graphical_session` reads the sockets —
    the right question in production and one a test has to be able to answer for
    itself. Restoring is the caller's business only if it builds a second broker
    with a different value; :func:`build_broker` leaves the variables as it set
    them, which is what makes ``graphical=False`` actually headless.
    """
    fake = adapters if adapters is not None else FakeAdapters()
    if graphical:
        os.environ["WAYLAND_DISPLAY"] = "wayland-test"
    else:
        for name in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE"):
            os.environ.pop(name, None)
    broker = DesktopActionBroker(BrokerOptions(
        adapters=fake, ledger_path=ledger_path, **options,
    ))
    broker.start()
    return broker, fake


@dataclass(frozen=True)
class _Entry:
    """A desktop entry the fake launcher accepts, without a file on disk."""

    application_id: str = "org.example.Thing"
    entry_path: str = "/usr/share/applications/org.example.Thing.desktop"
    root: str = "/usr/share/applications"
    display_name: str = "Thing"
    exec_program: str = "/usr/bin/thing"
    accepts_files: bool = True
    accepts_uris: bool = True
    terminal: bool = False
    dbus_activatable: bool = False
    user_installed: bool = False

    def accepts(self, *, uris: Sequence[str] = ()) -> bool:
        return not uris or self.accepts_files or self.accepts_uris


def make_entry(**overrides: Any) -> _Entry:
    return _Entry(**overrides)


def make_paths(*names: str, root: Path | None = None) -> tuple[PathContext, Path]:
    """A path context over a real temporary directory with real files in it.

    Real, because every interesting property of
    :class:`companion.desktop.paths.PathContext` is a filesystem property —
    symlink resolution, containment after resolution, existence, file type — and
    a fixture that faked the filesystem would be testing the fixture.
    """
    base = Path(root) if root is not None else Path(tempfile.mkdtemp())
    documents = base / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    entries: dict[str, str] = {}
    for index, name in enumerate(names):
        target = documents / name
        target.write_text("sample", encoding="utf-8")
        entries[f"ref-{index}"] = str(target)
    return PathContext.build(entries, roots=(documents,)), base


def sample_parameters(action_id: str, **overrides: Any) -> dict[str, Any]:
    """Valid parameters for one action, for the tests that vary one field."""
    defaults: Mapping[str, Mapping[str, Any]] = {
        "desktop.notification.show": {"title": "Hello", "body": "A body", "urgency": "normal"},
        "desktop.application.launch": {"applicationId": "org.example.Thing"},
        "desktop.application.present": {"applicationId": "org.example.Thing"},
        "desktop.settings.open": {"page": "sound"},
        "desktop.audio.set-volume": {"percent": 50, "outputId": "fake-sink"},
        "desktop.notifications.set-do-not-disturb": {"enabled": True},
        "desktop.clipboard.copy-text": {"text": "hello there", "classification": "internal"},
        "desktop.uri.open": {
            "uri": "https://example.com/docs",
            "expectedScheme": "https",
            "expectedDestinationClass": "web",
        },
        "desktop.file.reveal": {"pathReference": "ref-0"},
    }
    value = dict(defaults[action_id])
    value.update(overrides)
    return value
