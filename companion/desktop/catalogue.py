# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The nine actions this phase implements, and everything true about each.

A descriptor is not documentation. It is the data every other decision is made
from: whether a request may be built at all, which adapter may be reached, what
question the user is asked, whether an undo exists, and what a result of
``confirmed`` would have to observe. Writing those facts once, here, is what
stops the approval prompt and the executor disagreeing about what an action does
— which is the failure mode where a person consents to one sentence and a
different act happens.

**A declared action is not an available one, and that distinction is the whole
point of §6.** The seven words below are a ladder, and each rung is a different
question with a different answer source:

``declared``
    this build knows the action exists. A property of :data:`DESCRIPTORS` and
    of nothing else.
``available``
    this *machine, right now* could perform it — there is a graphical session,
    the portal or service it names is answering. Read from
    :mod:`companion.desktop.environment`, never inferred from an installed
    binary, because a binary on disk in a headless session performs nothing.
``eligible``
    this *task* may request it: the capability plan permits desktop actions,
    the classification is within the action's ceiling, the parameters validate.
``approved``
    a person said yes to these exact parameters, and the binding still matches.
``executing``
    the broker owns an attempt. Exactly one attempt owns an action at a time.
``completed``
    the attempt settled with an observation behind it.
``undone``
    a *separate* action, with its own approval and audit record, restored the
    previous state and verified it.

Nothing collapses two rungs. An action that is declared and unavailable reports
``unsupported`` with the reason; it does not silently become a no-op that looks
like success.

§5's deferred list is here too, as :data:`DEFERRED_ACTIONS`. They are named
rather than omitted so that a request for one produces a typed ``unsupported``
result that says *this is deliberately not implemented* — which is a different
sentence from ``unknown action`` and leads a caller to a different place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..privacy import DATA_CLASSES, rank
from .errors import DesktopSchemaError

__all__ = [
    "ACTION_IDS",
    "ACTION_STANDING",
    "BACKENDS",
    "DEFERRED_ACTIONS",
    "DESCRIPTORS",
    "DESKTOP_APPROVAL_ACTIONS",
    "RESOURCE_IMPACTS",
    "REVERSIBILITY_CLASSES",
    "ActionDescriptor",
    "descriptor_for",
    "is_deferred",
]

#: §6's ladder, in order. Each rung is answered by a different component; see
#: the module docstring for which, and why they are not merged.
ACTION_STANDING = (
    "declared",
    "available",
    "eligible",
    "approved",
    "executing",
    "completed",
    "undone",
)

#: §11's classification of what can be taken back.
#:
#: ``compensatable`` is the interesting one and it is not a softer
#: ``reversible``: it means a *different* act can offset the effect without
#: restoring the previous state. Clearing clipboard ownership does not put back
#: what was on the clipboard before, and calling that "reversible" would promise
#: a user something the desktop cannot deliver.
REVERSIBILITY_CLASSES = ("reversible", "compensatable", "irreversible", "unknown")

#: The typed adapters an action may reach. A descriptor naming anything outside
#: this tuple fails the import-time consistency check below, which is what keeps
#: "every backend call is an allowlisted typed adapter" (§7) true by
#: construction rather than by review.
BACKENDS = (
    "notification",
    "application-launch",
    "application-present",
    "settings",
    "audio-control",
    "clipboard",
    "uri-open",
    "file-reveal",
)

#: What performing an action costs the machine. Coarse on purpose: this feeds a
#: sentence in front of a user, and a figure precise enough to be interesting
#: would be precise enough to be wrong.
RESOURCE_IMPACTS = ("negligible", "moderate", "significant")

#: The approval classes this subsystem adds to
#: :data:`capability.apply.approval.SENSITIVE_ACTIONS`. Listed here as well so a
#: reader of the catalogue can see the whole approval surface without leaving
#: the file, and asserted equal to the capability set at import.
DESKTOP_APPROVAL_ACTIONS = (
    "change_device_state",
    "launch_application",
    "open_external_uri",
    "open_settings_surface",
    "reveal_file",
    "write_clipboard",
)


@dataclass(frozen=True)
class ActionDescriptor:
    """Everything §6 requires an action to state about itself.

    Undeclared fails closed in the same sense as
    :class:`companion.tools.ToolDeclaration`: the defaults describe the action
    that needs the *most* care, so an entry added without thought asks for
    approval, claims no undo, and admits no confirming observation.
    """

    action_id: str
    schema_version: int
    summary: str
    backend: str
    #: The approval class this action is asked about under. Every action in this
    #: phase has one: there is no unapproved desktop effect, and the policy
    #: pre-authorisation in §4.2 relaxes *who answers*, never *whether a binding
    #: exists*.
    approval_class: str
    #: The most sensitive data this action may be given. A clipboard write can
    #: carry personal text; a settings page cannot carry anything at all.
    privacy_ceiling: str = "internal"
    reversibility: str = "irreversible"
    #: The action id that undoes this one, when one exists. Empty means undo is
    #: not offered, and §11 forbids inventing one — "silently kill the
    #: application" is not an undo for having launched it.
    undo_action_id: str = ""
    #: Whether the *dispatch* can be stopped once begun. Distinct from
    #: reversibility: a portal request can be cancelled mid-flight and a
    #: notification that has already been handed to the daemon cannot.
    supports_cancellation: bool = True
    #: Whether the backend offers a read-back that proves the effect. Only
    #: actions with this may ever produce ``confirmed`` (§12).
    supports_verification: bool = False
    requires_user_session: bool = True
    #: The portal interface or service that must answer. Empty means the action
    #: needs no service beyond a session.
    required_service: str = ""
    #: What the user will see happen. Written as a sentence because it is shown
    #: to them, and a label like "performs action" is what §18 forbids.
    expected_visibility: str = ""
    resource_impact: str = "negligible"
    #: Desktop environments this is known to work in. ``("*",)`` means the
    #: mechanism is environment-independent (a freedesktop standard).
    supported_environments: tuple[str, ...] = ("*",)
    known_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.backend not in BACKENDS:
            raise DesktopSchemaError(
                f"{self.action_id!r} names backend {self.backend!r}, which is not an "
                f"allowlisted adapter; expected one of {list(BACKENDS)}"
            )
        if self.privacy_ceiling not in DATA_CLASSES:
            raise DesktopSchemaError(f"{self.action_id!r} has an unknown privacy ceiling")
        if self.reversibility not in REVERSIBILITY_CLASSES:
            raise DesktopSchemaError(f"{self.action_id!r} has an unknown reversibility class")
        if self.resource_impact not in RESOURCE_IMPACTS:
            raise DesktopSchemaError(f"{self.action_id!r} has an unknown resource impact")
        if not self.expected_visibility:
            raise DesktopSchemaError(
                f"{self.action_id!r} does not say what the user will see; §18 forbids a "
                "vague label and the descriptor is where the precise one comes from"
            )
        if self.reversibility == "reversible" and not self.undo_action_id:
            raise DesktopSchemaError(
                f"{self.action_id!r} claims to be reversible and names no undo action; "
                "reversible without a way to reverse is a promise nothing keeps"
            )
        if self.undo_action_id and self.reversibility == "irreversible":
            raise DesktopSchemaError(
                f"{self.action_id!r} is declared irreversible and names an undo action"
            )

    def accepts(self, classification: str) -> bool:
        """Whether data of this class may be given to this action."""
        return rank(classification) <= rank(self.privacy_ceiling)

    @property
    def undoable(self) -> bool:
        return bool(self.undo_action_id)

    def to_json(self) -> dict[str, Any]:
        return {
            "actionId": self.action_id,
            "schemaVersion": self.schema_version,
            "summary": self.summary,
            "backend": self.backend,
            "approvalClass": self.approval_class,
            "privacyCeiling": self.privacy_ceiling,
            "reversibility": self.reversibility,
            "undoActionId": self.undo_action_id,
            "undoSupported": self.undoable,
            "supportsCancellation": self.supports_cancellation,
            "supportsVerification": self.supports_verification,
            "requiresUserSession": self.requires_user_session,
            "requiredService": self.required_service,
            "expectedVisibility": self.expected_visibility,
            "resourceImpact": self.resource_impact,
            "supportedEnvironments": list(self.supported_environments),
            "knownLimitations": list(self.known_limitations),
        }


_V = 1

#: §4's catalogue. Nine entries, and the shortness is the design: every action
#: here is one a person can be shown in a sentence and can undo or refuse
#: without understanding the implementation.
DESCRIPTORS: Mapping[str, ActionDescriptor] = {
    item.action_id: item
    for item in (
        # -- §4.1 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.notification.show",
            schema_version=_V,
            summary="Show a desktop notification",
            backend="notification",
            approval_class="interrupt_user_work",
            # A notification body is shown on a screen that may be visible to
            # somebody else in the room. Personal is the honest ceiling; secret
            # material does not go on a lock screen.
            privacy_ceiling="personal",
            reversibility="irreversible",
            supports_cancellation=True,
            # org.freedesktop.Notifications returns an id, which proves the
            # daemon accepted the request and proves nothing about a person
            # having seen it. §12: that is `accepted-not-confirmed`, and the
            # descriptor says so by declining to claim verification.
            supports_verification=False,
            required_service="org.freedesktop.Notifications",
            expected_visibility="A notification appears in the notification area.",
            known_limitations=(
                "The daemon returning an id proves acceptance, not delivery or display.",
                "A notification already handed to the daemon cannot be withdrawn reliably.",
                "Do-not-disturb may suppress display without reporting that it did.",
            ),
        ),
        # -- §4.2 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.application.launch",
            schema_version=_V,
            summary="Launch an installed application",
            backend="application-launch",
            approval_class="launch_application",
            # Only an application id and, at most, already-approved files. The
            # id is public and the files carry their own classification, which
            # the request checks separately.
            privacy_ceiling="personal",
            # §11: not automatically reversible. Killing what was started is not
            # an undo, it is a second act with its own consequences.
            reversibility="irreversible",
            supports_cancellation=True,
            supports_verification=False,
            required_service="org.freedesktop.portal.OpenURI",
            expected_visibility="The application starts and its window appears.",
            resource_impact="moderate",
            known_limitations=(
                "A successful launch call does not prove the application drew a window.",
                "An application already running may be activated rather than started.",
                "No undo: an application that was started stays started.",
            ),
        ),
        # -- §4.3 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.application.present",
            schema_version=_V,
            summary="Bring an application's window to the front",
            backend="application-present",
            approval_class="interrupt_user_work",
            privacy_ceiling="internal",
            reversibility="irreversible",
            supports_cancellation=True,
            supports_verification=False,
            required_service="org.freedesktop.portal.Request",
            expected_visibility="The application's window is raised, if the compositor allows it.",
            # Named rather than starred: focus control is exactly where
            # compositors differ, and a descriptor claiming "*" here would be
            # the fake success §4.3 forbids.
            supported_environments=("GNOME", "KDE", "X11"),
            known_limitations=(
                "Wayland compositors may refuse activation; the result is UNSUPPORTED, not success.",
                "Focus-stealing prevention is respected and is not worked around.",
                "No synthetic Alt-Tab, no synthetic pointer events, in any environment.",
            ),
        ),
        # -- §4.4 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.settings.open",
            schema_version=_V,
            summary="Open a settings page",
            backend="settings",
            approval_class="open_settings_surface",
            # A page identifier from a closed list. There is nothing here that
            # could carry user material.
            privacy_ceiling="internal",
            reversibility="irreversible",
            supports_cancellation=True,
            supports_verification=False,
            expected_visibility="The settings application opens at the named page.",
            supported_environments=("GNOME", "KDE"),
            known_limitations=(
                "Opens the page; never changes the setting on it.",
                "Page identifiers are mapped per environment and an unmapped one is UNSUPPORTED.",
            ),
        ),
        # -- §4.5 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.audio.set-volume",
            schema_version=_V,
            summary="Set the output volume",
            backend="audio-control",
            approval_class="change_device_state",
            privacy_ceiling="internal",
            reversibility="reversible",
            undo_action_id="desktop.audio.set-volume",
            supports_cancellation=True,
            # The one action with a genuine read-back: the mixer can be asked
            # what the volume now is, and `confirmed` means that answer matched.
            supports_verification=True,
            required_service="pulseaudio-or-pipewire",
            expected_visibility="The output volume changes and the volume indicator moves.",
            known_limitations=(
                "Only the default or an explicitly approved output sink; no per-application control.",
                "Read-back is rounded to whole percent, so a one-step difference reads as equal.",
                "A sink that disappeared between approval and execution is refused, not substituted.",
            ),
        ),
        # -- §4.6 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.notifications.set-do-not-disturb",
            schema_version=_V,
            summary="Turn do-not-disturb on or off",
            backend="settings",
            approval_class="change_device_state",
            privacy_ceiling="internal",
            reversibility="reversible",
            undo_action_id="desktop.notifications.set-do-not-disturb",
            supports_cancellation=True,
            supports_verification=True,
            required_service="desktop-settings",
            expected_visibility="Notification banners stop or resume appearing.",
            supported_environments=("GNOME", "KDE"),
            known_limitations=(
                "Environments without a do-not-disturb setting report UNSUPPORTED rather than pretending.",
                "The previous value is read before the change; if it cannot be read, undo is not offered.",
            ),
        ),
        # -- §4.7 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.clipboard.copy-text",
            schema_version=_V,
            summary="Copy text to the clipboard",
            backend="clipboard",
            approval_class="write_clipboard",
            # The one action that carries user material by design. Sensitive is
            # the ceiling and not secret: secret never leaves the runtime, and a
            # clipboard is readable by every application the user runs.
            privacy_ceiling="sensitive",
            # §11: compensatable *only* where ownership can be released. Not
            # reversible — releasing ownership does not restore what was there.
            reversibility="compensatable",
            supports_cancellation=True,
            # Ownership can be observed; the *content* is never read back,
            # because reading the clipboard is forbidden by §13 even to check
            # our own write.
            supports_verification=True,
            required_service="wayland-or-x11-selection",
            expected_visibility="The text becomes available to paste.",
            known_limitations=(
                "The existing clipboard contents are never read, so a copy cannot be verified by content.",
                "Ownership is verified; what the next paste yields is not, and is not claimed.",
                "Releasing ownership does not restore whatever was on the clipboard before.",
                "Detected credential-shaped text is refused outright rather than copied.",
            ),
        ),
        # -- §4.8 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.uri.open",
            schema_version=_V,
            summary="Open a URI in its handler",
            backend="uri-open",
            approval_class="open_external_uri",
            # A URI can name a personal resource. It cannot carry secret
            # material, and query parameters are never logged (§13).
            privacy_ceiling="personal",
            reversibility="irreversible",
            supports_cancellation=True,
            supports_verification=False,
            required_service="org.freedesktop.portal.OpenURI",
            expected_visibility="The handler for the URI's scheme opens it.",
            known_limitations=(
                "Only https, http, mailto and file; every other scheme is refused.",
                "A redirect the handler follows does not broaden what was approved.",
                "mailto opens a composer and never sends.",
                "The opener accepting a URI does not prove the handler displayed it.",
            ),
        ),
        # -- §4.9 --------------------------------------------------------------
        ActionDescriptor(
            action_id="desktop.file.reveal",
            schema_version=_V,
            summary="Show a file or folder in the file manager",
            backend="file-reveal",
            approval_class="reveal_file",
            privacy_ceiling="personal",
            reversibility="irreversible",
            supports_cancellation=True,
            supports_verification=False,
            required_service="org.freedesktop.FileManager1",
            expected_visibility="The file manager opens with the item selected.",
            known_limitations=(
                "The path must already exist in the task's canonical context; a provider cannot name one.",
                "Symlinks are resolved before the approved-root check, and the resolved path is what is approved.",
                "Reveals only. Nothing is opened, moved, changed or deleted.",
            ),
        ),
    )
}

ACTION_IDS: tuple[str, ...] = tuple(DESCRIPTORS)

#: §5's list, as typed absences rather than as silence.
#:
#: Each maps to the sentence a caller is given. They are *not* actions: nothing
#: constructs a request for one, no adapter exists, and asking for one produces
#: ``unsupported`` with this reason. Naming them is what stops a later phase
#: adding "type into the focused window" as an obvious extension of a catalogue
#: that never said it was closed.
DEFERRED_ACTIONS: Mapping[str, str] = {
    "desktop.input.type": "Typing into an application is deliberately not implemented in this phase.",
    "desktop.input.click": "Clicking at coordinates is deliberately not implemented in this phase.",
    "desktop.input.drag": "Drag-and-drop is deliberately not implemented in this phase.",
    "desktop.window.resize": "Window resizing is deliberately not implemented in this phase.",
    "desktop.window.move": "Window moving is deliberately not implemented in this phase.",
    "desktop.browser.navigate": (
        "Browser navigation beyond opening an approved URI is deliberately not implemented in this phase."
    ),
    "desktop.form.fill": "Form filling is deliberately not implemented in this phase.",
    "desktop.mail.send": "Sending email is deliberately not implemented in this phase.",
    "desktop.message.send": "Sending messages is deliberately not implemented in this phase.",
    "desktop.file.edit": "Editing files is deliberately not implemented in this phase.",
    "desktop.file.delete": "Deleting files is deliberately not implemented in this phase.",
    "desktop.file.move": "Moving files is deliberately not implemented in this phase.",
    "desktop.file.upload": "Uploading files is deliberately not implemented in this phase.",
    "desktop.file.download-accept": "Accepting downloads is deliberately not implemented in this phase.",
    "desktop.terminal.open": "Opening a terminal with a command is deliberately not implemented in this phase.",
    "desktop.package.install": "Installing packages is deliberately not implemented in this phase.",
    "desktop.system.update": "System update is deliberately not implemented in this phase.",
    "desktop.account.change": "Account changes are deliberately not implemented in this phase.",
    "desktop.network.configure": "Network configuration is deliberately not implemented in this phase.",
    "desktop.screen.capture": "Screen capture is deliberately not implemented and is forbidden by §13.",
    "desktop.camera.control": "Camera control is deliberately not implemented and is forbidden by §13.",
    "desktop.remote.control": "Remote desktop control is deliberately not implemented in this phase.",
}


def is_deferred(action_id: str) -> bool:
    return action_id in DEFERRED_ACTIONS


def descriptor_for(action_id: str) -> ActionDescriptor:
    """The descriptor for an action, or a refusal that distinguishes the reasons.

    Three different messages, because a caller does three different things with
    them: a deferred action is a decision, an unknown one is a mistake, and the
    difference is worth a user's time.
    """
    found = DESCRIPTORS.get(action_id)
    if found is not None:
        return found
    deferred = DEFERRED_ACTIONS.get(action_id)
    if deferred is not None:
        raise DesktopSchemaError(deferred)
    raise DesktopSchemaError(
        f"{action_id!r} is not a desktop action this build declares; the catalogue is "
        f"{', '.join(ACTION_IDS)}"
    )


# --------------------------------------------------------------------------- #
# Import-time consistency. Cheap, and each of these has a failure it prevents.
# --------------------------------------------------------------------------- #

def _check_catalogue() -> None:
    from capability.apply.approval import SENSITIVE_ACTIONS

    for _action_id, _item in DESCRIPTORS.items():
        if _item.approval_class not in SENSITIVE_ACTIONS:
            raise DesktopSchemaError(
                f"{_action_id!r} is approved under {_item.approval_class!r}, which is not a "
                "sensitive action; an approval class the store does not know cannot have a "
                "safe default and would be answerable by silence"
            )
        undo = _item.undo_action_id
        if undo and undo not in DESCRIPTORS:
            raise DesktopSchemaError(f"{_action_id!r} names undo action {undo!r}, which is not declared")
    overlap = set(DESCRIPTORS) & set(DEFERRED_ACTIONS)
    if overlap:
        raise DesktopSchemaError(
            f"{sorted(overlap)} are both implemented and deferred; one of the two lists is wrong"
        )
    missing = set(DESKTOP_APPROVAL_ACTIONS) - set(SENSITIVE_ACTIONS)
    if missing:
        raise DesktopSchemaError(
            f"the desktop approval classes {sorted(missing)} are not in "
            "capability.apply.approval.SENSITIVE_ACTIONS, so an unanswered question about one "
            "would not default to denial"
        )


_check_catalogue()
