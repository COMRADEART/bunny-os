# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One typed adapter per declared operation, and no way to express another.

§7's rule is that every backend call is represented by an allowlisted typed
adapter, and the way that is kept is by having no generic layer for one to be
smuggled through. There are exactly two transports in this package and both are
closed:

:mod:`~companion.desktop.adapters.dbus`
    a **table** of complete D-Bus calls — bus name, object path, interface,
    method and argument signature, all four fixed per entry. The invoker takes
    a call *identifier* and arguments; there is no parameter through which a
    caller could name a bus. That is the difference between a D-Bus adapter and
    a D-Bus client, and §7 asks for the first.
:mod:`~companion.desktop.adapters.command`
    an executable allowlist and an argv builder, on top of the hardened runner
    :mod:`companion.voice.execution` already provides. Argument arrays only, a
    built environment rather than an inherited one, trusted directories rather
    than ``PATH``, and a child that is always reaped.

Each adapter above them exposes one method that performs one declared thing.
None takes a command, a path, a bus name or an interface. An adapter that could
be asked to do something other than its declared operation would be a generic
execution surface wearing a specific name.

The adapters:

``NotificationAdapter``      show one notification
``ApplicationLaunchAdapter`` start one installed application
``ApplicationPresentAdapter`` raise one application's window, or say it cannot
``SettingsAdapter``          open one allowlisted settings page; read and set
                             do-not-disturb
``AudioControlAdapter``      read and set the output volume and mute
``ClipboardAdapter``         take ownership of the clipboard with given text,
                             and release it
``UriOpenAdapter``           open one already-parsed URI
``FileRevealAdapter``        reveal one already-resolved path
``PortalAdapter``            the xdg-desktop-portal client the two openers use

Every one of them reports *unavailable* honestly. There is no adapter here that
returns success when it did nothing, and the tests assert that by running the
whole catalogue in an environment with no session at all.
"""

from __future__ import annotations

__all__ = ["ADAPTER_IDS"]

#: Every adapter this package ships, by the name §7 gives it. Asserted against
#: the descriptor table's ``backend`` values at import of
#: :mod:`companion.desktop.adapters.base`, so an adapter added without a
#: descriptor — or a descriptor naming an adapter that does not exist — fails
#: closed rather than at the moment somebody tries to use it.
ADAPTER_IDS = (
    "NotificationAdapter",
    "ApplicationLaunchAdapter",
    "ApplicationPresentAdapter",
    "SettingsAdapter",
    "AudioControlAdapter",
    "ClipboardAdapter",
    "UriOpenAdapter",
    "FileRevealAdapter",
    "PortalAdapter",
)
