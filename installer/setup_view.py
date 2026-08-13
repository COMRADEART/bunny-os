# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What each setup screen contains — as data, so two renderers cannot disagree.

`companion_flow` says what Bunny *says* and who is allowed to decide. This module
says what is actually *on the screen*: the controls, the warnings, the buttons,
and — for every screen without exception — the sentence a screen reader gets.

## Why this is not in the GTK code

Two things render setup. The GTK4 application a person uses, and the story
harness that draws all thirteen states in about a second without booting
anything. §35 requires the second to exist so that visual iteration does not cost
an image build, and the previous phase is the argument for it: five defects
shipped to a booted guest and one screenshot found all five while the test suite
went from 245 to 249 passing.

A harness that rendered its own idea of a screen would find defects in itself. So
the screens are values here, both renderers consume them, and a field that is
missing is missing in both.

## The rule this module exists to enforce

§9 and §38: *the Companion character cannot be required to understand the
installer, and all state must have equivalent accessible text.* That is not a
guideline that can be met by remembering it. :attr:`Screen.announcement` is
mandatory and :meth:`Screen.__post_init__` refuses a screen without one, so a
screen that a screen reader could not describe cannot be constructed.

The stronger version applies to destruction. §12 requires the confirmation
surface to name the exact disk and the exact action. A screen built from a
:class:`~installer.storage.models.DiskInfo` cannot name a different disk than the
plan targets, because it is handed the disk rather than a string — and
:func:`confirm_erase_screen` puts the consequence into the announcement itself,
so an assistive technology user is told what will be erased in the same breath as
everyone else. §39 and §40 then ask that this text survive 200 % scaling and high
contrast, which is a question about the renderer, not about this file — but the
text cannot go missing here, which is the failure the story harness caught in the
Trust prompt.

## What is deliberately absent

No secret ever reaches a :class:`Field`. The passphrase and password screens
carry a ``secret`` field kind whose ``value`` is always ``None``; the renderer
holds the characters for as long as it takes to hand them to the installer
backend through a file descriptor, and this module never sees them. That mirrors
`installer.protocol`, which refuses a payload containing a key named
``password``, and `installer.encryption.plans`, which carries a reference and not
a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterable, Mapping, Sequence

from installer.companion_flow import Stage, stage
from installer.storage.models import DiskInfo
from installer.storage.safety import SafetyFinding, confirmation_phrase, disk_identity

__all__ = [
    "Action",
    "Field",
    "Screen",
    "Warning",
    "FIELD_KINDS",
    "WARNING_LEVELS",
    "accessibility_screen",
    "account_screen",
    "appearance_screen",
    "apps_screen",
    "companion_screen",
    "complete_screen",
    "confirm_erase_screen",
    "encryption_screen",
    "failure_screen",
    "first_boot_screen",
    "installing_screen",
    "keyboard_screen",
    "language_screen",
    "network_screen",
    "privacy_screen",
    "review_screen",
    "storage_screen",
    "welcome_screen",
]

#: ``secret`` never carries a value. ``info`` is a read-only row — a fact the
#: screen states rather than a thing the person chooses.
FIELD_KINDS = ("choice", "multi-choice", "text", "secret", "toggle", "info")

#: ``danger`` is reserved for data destruction. Nothing else may use it, so a
#: renderer can give it a treatment that means exactly one thing.
WARNING_LEVELS = ("info", "caution", "danger")


@dataclass(frozen=True)
class Option:
    """One choice within a field."""

    value: str
    label: str
    #: The honest detail — cost, account requirement, what it sends where.
    note: str = ""
    #: ``False`` renders it visible but unselectable, with ``note`` saying why.
    available: bool = True

    def as_record(self) -> Mapping[str, Any]:
        return {"value": self.value, "label": self.label, "note": self.note, "available": self.available}


@dataclass(frozen=True)
class Field:
    """One control."""

    key: str
    kind: str
    label: str
    #: Plain-language help. §15 asks each privacy choice to say what data is
    #: involved and where it goes; this is where that sentence lives.
    help: str = ""
    value: Any = None
    options: tuple[Option, ...] = ()
    required: bool = False

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"{self.key}: unknown field kind {self.kind!r}")
        if self.kind in {"choice", "multi-choice"} and not self.options:
            raise ValueError(f"{self.key}: a choice field needs options")
        if self.kind == "secret" and self.value is not None:
            raise ValueError(f"{self.key}: a secret field may not carry a value")

    def as_record(self) -> Mapping[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "help": self.help,
            "value": self.value,
            "options": [option.as_record() for option in self.options],
            "required": self.required,
        }


@dataclass(frozen=True)
class Warning:
    """Something the person is told before they act."""

    level: str
    text: str
    #: Set when a blocker stops the journey rather than colouring it.
    blocks: bool = False

    def __post_init__(self) -> None:
        if self.level not in WARNING_LEVELS:
            raise ValueError(f"unknown warning level {self.level!r}")
        if not self.text.strip():
            raise ValueError("a warning with no text is not a warning")

    def as_record(self) -> Mapping[str, Any]:
        return {"level": self.level, "text": self.text, "blocks": self.blocks}


@dataclass(frozen=True)
class Action:
    """A button.

    ``accessible_name`` is separate from ``label`` and always populated. The one
    genuinely unnamed control the previous phase found was a button whose label
    was empty until there was something to offer, and it took an AT-SPI walk on a
    booted guest to find it. Here it cannot happen: the name defaults to the
    label and an empty label with no name is a construction error.
    """

    id: str
    label: str
    accessible_name: str = ""
    #: ``primary`` is the forward action, ``safe`` the one that changes nothing,
    #: ``danger`` the one that destroys data.
    tone: str = "primary"
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.tone not in {"primary", "safe", "danger", "quiet"}:
            raise ValueError(f"{self.id}: unknown action tone {self.tone!r}")
        name = self.accessible_name or self.label
        if not name.strip():
            raise ValueError(f"{self.id}: an action needs an accessible name")
        object.__setattr__(self, "accessible_name", name)

    def as_record(self) -> Mapping[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "accessibleName": self.accessible_name,
            "tone": self.tone,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class Screen:
    """One setup screen, complete."""

    key: str
    heading: str
    #: Bunny's sentence, from `companion_flow`. Never authored here.
    says: str
    #: A `companion.presentation` phase. Derived from the stage, never chosen.
    companion: str
    authority: str
    fields: tuple[Field, ...] = ()
    warnings: tuple[Warning, ...] = ()
    actions: tuple[Action, ...] = ()
    advanced: tuple[str, ...] = ()
    #: The whole screen as one sentence, for Orca. Mandatory.
    announcement: str = ""
    #: For ``user`` authority: the exact act that unlocks the screen.
    confirmation: str | None = None
    progress: tuple[Mapping[str, Any], ...] = dataclass_field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.announcement.strip():
            raise ValueError(f"{self.key}: every screen needs an accessible announcement (§9, §38)")
        if not self.actions:
            raise ValueError(f"{self.key}: a screen with no action is a dead end")
        danger = [item for item in self.warnings if item.level == "danger"]
        if danger:
            # §11: never hide destructive consequences behind friendly language.
            # The announcement is what a screen-reader user gets *instead of*
            # seeing the red panel, so the words have to be in it.
            missing = [item for item in danger if item.text not in self.announcement]
            if missing:
                raise ValueError(
                    f"{self.key}: a danger warning is not in the announcement, so it is "
                    f"invisible to a screen reader: {missing[0].text!r}"
                )

    def as_record(self) -> Mapping[str, Any]:
        return {
            "key": self.key,
            "heading": self.heading,
            "says": self.says,
            "companion": self.companion,
            "authority": self.authority,
            "fields": [item.as_record() for item in self.fields],
            "warnings": [item.as_record() for item in self.warnings],
            "actions": [item.as_record() for item in self.actions],
            "advanced": list(self.advanced),
            "announcement": self.announcement,
            "confirmation": self.confirmation,
            "progress": [dict(item) for item in self.progress],
        }


def _from(key: str) -> Stage:
    return stage(key)


def _back(enabled: bool = True) -> Action:
    return Action("back", "Back", tone="quiet", enabled=enabled)


def _next(label: str = "Continue") -> Action:
    return Action("next", label, tone="primary")


# ------------------------------------------------------------------ screens


def welcome_screen(*, advanced_available: bool = True) -> Screen:
    """§5. The Companion, a sentence, and one button.

    Deliberately three actions and no form. *Accessibility* is here rather than
    later because §8 requires it to be reachable before the rest of setup, and a
    person who needs 200 % text to read the language list cannot be asked to read
    the language list first.
    """
    entry = _from("welcome")
    return Screen(
        key="welcome",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        actions=(
            Action("start", "Get started", tone="primary"),
            Action("accessibility", "Accessibility", tone="quiet"),
            Action(
                "advanced",
                "Installation details",
                accessible_name="Installation details, for advanced users",
                tone="quiet",
                enabled=advanced_available,
            ),
        ),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Three choices: Get started, "
            "Accessibility, or Installation details."
        ),
    )


def accessibility_screen(*, current: Mapping[str, Any] | None = None) -> Screen:
    """§8. Available before the rest of setup, and applied immediately.

    Every control here changes the installer as it is set. That is the whole
    point of the section — a person must not have to finish installing to get the
    text size that lets them read the install.
    """
    entry = _from("accessibility")
    values = dict(current or {})
    return Screen(
        key="accessibility",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field(
                "textScale", "choice", "Text size",
                help="Changes immediately, here and on the installed system.",
                value=values.get("textScale", 1.0),
                options=(
                    Option("1.0", "Normal"),
                    Option("1.25", "Large"),
                    Option("1.5", "Larger"),
                    Option("2.0", "Largest"),
                ),
            ),
            Field(
                "highContrast", "toggle", "High contrast",
                help="Stronger borders and a plain background behind every control.",
                value=values.get("highContrast", False),
            ),
            Field(
                "reducedMotion", "toggle", "Reduce motion",
                help="Bunny stops moving. Nothing is communicated by animation alone.",
                value=values.get("reducedMotion", False),
            ),
            Field(
                "screenReader", "toggle", "Screen reader",
                help="Starts Orca now and enables it on the installed system.",
                value=values.get("screenReader", False),
            ),
            Field(
                "captions", "toggle", "Captions",
                help="Shows in text everything Bunny says aloud.",
                value=values.get("captions", False),
            ),
            Field(
                "companionTextOnly", "toggle", "Text-only Bunny",
                help="Bunny becomes words with no picture. Setup works the same.",
                value=values.get("companionTextOnly", False),
            ),
        ),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Six settings: text size, high contrast, "
            "reduce motion, screen reader, captions, and text-only Bunny. Each one "
            "takes effect immediately."
        ),
    )


def language_screen(*, detected: Mapping[str, str] | None = None) -> Screen:
    """§7. Detected defaults are shown as detected, never applied silently."""
    entry = _from("language_region")
    found = dict(detected or {})
    return Screen(
        key="language_region",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field(
                "language", "choice", "Language", required=True,
                value=found.get("language"),
                options=(
                    Option("en-GB", "English (United Kingdom)"),
                    Option("en-US", "English (United States)"),
                    Option("fr-FR", "Français (France)"),
                    Option("de-DE", "Deutsch (Deutschland)"),
                    Option("es-ES", "Español (España)"),
                ),
            ),
            Field(
                "region", "choice", "Region", required=True,
                help="Sets date, time and number formats.",
                value=found.get("region"),
                options=(
                    Option("GB", "United Kingdom"),
                    Option("US", "United States"),
                    Option("FR", "France"),
                    Option("DE", "Germany"),
                    Option("ES", "Spain"),
                ),
            ),
            Field(
                "timezone", "choice", "Time zone", required=True,
                value=found.get("timezone"),
                options=(
                    Option("Europe/London", "London"),
                    Option("Europe/Paris", "Paris"),
                    Option("Europe/Berlin", "Berlin"),
                    Option("America/New_York", "New York"),
                ),
            ),
            Field(
                "detected", "info", "Detected",
                help=found.get("source", "No network, so nothing was detected. Choose below."),
            ),
        ),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Choose a language, a region and a time "
            "zone. Nothing is applied until you continue."
        ),
    )


def keyboard_screen(*, layout: str | None = None) -> Screen:
    """§7. Not skippable, and the reason is stated on the screen."""
    entry = _from("keyboard")
    return Screen(
        key="keyboard",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field(
                "layout", "choice", "Keyboard layout", required=True, value=layout,
                options=(
                    Option("gb", "English (UK)"),
                    Option("us", "English (US)"),
                    Option("fr", "French (AZERTY)"),
                    Option("de", "German (QWERTZ)"),
                ),
            ),
            Field(
                "test", "text", "Type here to check it",
                help="What you type is not saved and is not sent anywhere.",
            ),
        ),
        warnings=(
            Warning("caution", entry.skip_note or "A wrong layout makes a disk password impossible to type back."),
        ),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Choose a layout and type in the test box "
            "to check it. A wrong layout makes a disk password impossible to type back."
        ),
    )


def network_screen(*, connected: bool = False, networks: Sequence[str] = ()) -> Screen:
    """§10. Offline is a supported path and the screen says so first."""
    entry = _from("network")
    options = tuple(Option(name, name) for name in networks) or (
        Option("none", "No networks found", note="Setup continues without one.", available=False),
    )
    return Screen(
        key="network",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field(
                "status", "info", "Connection",
                help="Connected." if connected else "Not connected. Installation does not need it.",
            ),
            Field("network", "choice", "Available networks", options=options),
            Field(
                "password", "secret", "Network password",
                help="Held only while connecting. It is not written to setup state.",
            ),
        ),
        actions=(_back(), Action("skip", "Continue without network", tone="safe"), _next("Connect")),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Installation works offline. Online AI "
            "providers are the only thing that needs a connection, and they are set "
            "up later, not now."
        ),
    )


def storage_screen(*, disks: Sequence[DiskInfo], selected: DiskInfo | None = None,
                   findings: Mapping[str, Sequence[SafetyFinding]] | None = None) -> Screen:
    """§11. What is on the disk, and what Bunny intends to do to it.

    The options are built from real :class:`DiskInfo` values, and a disk with a
    blocking finding is rendered *visible and unselectable* with the reason
    attached rather than filtered out. A disk that silently vanishes from the
    list is a disk the person will go looking for.
    """
    entry = _from("storage")
    per_disk = dict(findings or {})
    options: list[Option] = []
    for disk in disks:
        blocking = [item for item in per_disk.get(disk.id, ()) if item.blocks]
        existing = ", ".join(sorted({item.name for item in disk.existingOperatingSystems}))
        note = blocking[0].message if blocking else (
            f"Currently holds: {existing}." if existing else "Appears to be empty."
        )
        options.append(Option(disk.id, disk_identity(disk), note=note, available=not blocking))

    warnings: list[Warning] = []
    if selected is not None:
        for item in per_disk.get(selected.id, ()):
            level = "danger" if item.severity == "danger" else "caution" if item.severity == "warning" else "caution"
            warnings.append(Warning(level, item.message, blocks=item.blocks))

    danger_text = " ".join(item.text for item in warnings if item.level == "danger")
    announcement = (
        f"{entry.heading}. {entry.says} "
        + (f"{len(options)} disk{'s' if len(options) != 1 else ''} found. " if options else "No disks found. ")
        + (f"Selected: {disk_identity(selected)}. " if selected is not None else "Nothing is selected yet. ")
        + "Nothing is written to any disk on this screen."
        + (f" {danger_text}" if danger_text else "")
    )
    return Screen(
        key="storage",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("targetDisk", "choice", "Install to", required=True,
                  value=selected.id if selected is not None else None, options=tuple(options)),
        ),
        warnings=tuple(warnings),
        actions=(_back(), _next("Review what happens")),
        advanced=entry.advanced,
        announcement=announcement,
    )


def confirm_erase_screen(*, disk: DiskInfo, encrypted: bool, keeps_data: bool = False) -> Screen:
    """§12. The one screen the Companion may not decide.

    Built from the ``DiskInfo`` itself, so the disk named in the warning is the
    disk in the plan by construction rather than by care. The confirmation phrase
    is `storage.safety.confirmation_phrase`, which the backend independently
    re-derives and compares in ``assert_confirmed`` — typing it here proves
    nothing until the backend agrees.
    """
    entry = _from("confirm_erase")
    identity = disk_identity(disk)
    phrase = confirmation_phrase(disk)
    destroys = ", ".join(sorted({item.name for item in disk.existingOperatingSystems}))
    consequence = f"Everything on {identity} will be erased. This cannot be undone."
    return Screen(
        key="confirm_erase",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("disk", "info", "Disk", help=identity),
            Field("action", "info", "What happens", help="Erase the whole disk and install Bunny OS."),
            Field("existing", "info", "What is lost",
                  help=f"An existing installation of: {destroys}." if destroys
                       else "No other operating system was detected on it."),
            Field("encryption", "info", "Encryption",
                  help="The disk will be encrypted." if encrypted else "The disk will not be encrypted."),
            Field("phrase", "text", f"Type {phrase} to confirm", required=True,
                  help="Typed by hand, so that a mis-click cannot erase a disk."),
        ),
        warnings=(Warning("danger", consequence),),
        actions=(
            _back(),
            Action("confirm", "Erase and install", accessible_name=f"Erase {identity} and install Bunny OS",
                   tone="danger", enabled=False),
        ),
        advanced=entry.advanced,
        confirmation=entry.confirmation,
        announcement=(
            f"{entry.heading}. {consequence} "
            + (f"It currently holds: {destroys}. " if destroys else "")
            + ("The new installation will be encrypted. " if encrypted else "The new installation will not be encrypted. ")
            + f"To continue you must type the phrase {phrase} exactly."
        ),
    )


def encryption_screen(*, offered: bool = True) -> Screen:
    """§13. Including the sentence that says nobody can recover it."""
    entry = _from("encryption")
    return Screen(
        key="encryption",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("enabled", "toggle", "Encrypt this disk", value=offered,
                  help="Protects what is on the disk if the computer is lost or stolen. "
                       "It does not protect you while you are logged in."),
            Field("passphrase", "secret", "Passphrase", required=True,
                  help="You will type this every time the computer starts."),
            Field("passphraseAgain", "secret", "Passphrase again", required=True),
            Field("recoveryKey", "info", "Recovery key",
                  help="A recovery key is generated and shown once, before installation begins. "
                       "Write it down. It is the only other way in."),
        ),
        warnings=(
            Warning("caution",
                    "If you forget the passphrase and lose the recovery key, the data is gone. "
                    "Bunny cannot recover it and neither can anyone else."),
        ),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        confirmation=entry.confirmation,
        announcement=(
            f"{entry.heading}. {entry.says} Type a passphrase twice. A recovery key is "
            "shown once before installation begins. If you forget the passphrase and "
            "lose the recovery key, the data is gone: it cannot be recovered by Bunny "
            "or by anyone else."
        ),
    )


def account_screen(*, display_name: str | None = None, username: str | None = None,
                   device_name: str | None = None, errors: Sequence[str] = ()) -> Screen:
    """§14. Password handled by the system, never by Bunny's task log."""
    entry = _from("account")
    return Screen(
        key="account",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("displayName", "text", "Your name", required=True, value=display_name,
                  help="What Bunny calls you."),
            Field("username", "text", "Username", required=True, value=username,
                  help="Lower-case letters, digits, dash and underscore."),
            Field("password", "secret", "Password", required=True),
            Field("passwordAgain", "secret", "Password again", required=True),
            Field("deviceName", "text", "Device name", value=device_name,
                  help="Optional. Used on networks. No hardware serial number is included."),
        ),
        warnings=tuple(Warning("caution", text) for text in errors),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Enter your name, a username, and a password "
            "twice. A device name is optional. "
            + (" ".join(errors) if errors else "")
        ).strip(),
    )


def privacy_screen(*, values: Mapping[str, bool] | None = None) -> Screen:
    """§15. Every switch says what data, where it goes, and whether it is optional.

    All default off. §15 asks for conservative defaults and no dark patterns; the
    honest form of that is that the affirmative action is always the one that
    shares more, and it is never pre-selected.
    """
    entry = _from("privacy")
    chosen = dict(values or {})
    rows = (
        ("diagnostics", "Diagnostics",
         "Counts of which Bunny features are used. No file names, no text you type. "
         "Sent to ComradeArt. Optional; off by default."),
        ("crashReports", "Crash reports",
         "A stack trace when something crashes, plus the OS version. Can contain a file "
         "path. Sent to ComradeArt when you approve each one. Optional; off by default."),
        ("feedback", "Feedback",
         "Only what you write and choose to send. Nothing is collected in the background."),
        ("location", "Location services",
         "Approximate location from nearby Wi-Fi names. Used by apps that ask, one at a "
         "time. Never leaves this computer unless an app you allowed sends it."),
        ("microphone", "Microphone available to apps",
         "Off means no app can record, including Bunny. You can still allow one app later."),
        ("camera", "Camera available to apps",
         "Off means no app can see the camera. You can still allow one app later."),
        ("onlineAI", "Online AI providers",
         "Sends what you ask Bunny to a provider you choose and pay for. Off means Bunny "
         "works only with what is on this computer. Set up later, never during install."),
        ("remoteProcessing", "Remote processing",
         "Lets a task run on another machine you own. Off by default."),
    )
    return Screen(
        key="privacy",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=tuple(
            Field(key, "toggle", label, help=help_text, value=bool(chosen.get(key, False)))
            for key, label, help_text in rows
        ),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Eight settings, every one off: "
            + ", ".join(label.lower() for _, label, _ in rows)
            + ". Each says what data is involved and where it goes."
        ),
    )


def appearance_screen(*, scheme: str = "system", accent: str = "violet") -> Screen:
    """§17. Curated, not a theme gallery."""
    return Screen(
        key="appearance",
        heading="Appearance",
        says="How would you like it to look? You can change this whenever you want.",
        companion="understanding",
        authority="companion",
        fields=(
            Field("scheme", "choice", "Light or dark", value=scheme,
                  options=(
                      Option("light", "Light"),
                      Option("dark", "Dark"),
                      Option("system", "Match the time of day"),
                  )),
            Field("accent", "choice", "Accent colour", value=accent,
                  options=(
                      Option("violet", "Violet"),
                      Option("teal", "Teal"),
                      Option("amber", "Amber"),
                      Option("rose", "Rose"),
                  )),
            Field("wallpaper", "choice", "Background", value="bunny-default",
                  options=(
                      Option("bunny-default", "Bunny"),
                      Option("plain", "Plain colour"),
                      Option("photograph", "Photograph"),
                  )),
        ),
        actions=(_back(), _next()),
        advanced=("GTK and shell colour scheme keys", "Wallpaper asset digest"),
        announcement=(
            "Appearance. Choose light, dark, or matching the time of day; an accent "
            "colour; and a background. Three choices, all changeable later in Settings."
        ),
    )


def companion_screen(*, mode: str = "full", voice: bool = False,
                     captions: bool = True, at_login: bool = True) -> Screen:
    """§16. Five modes, including Off.

    Off is a mode and not an absence: the system must remain fully usable with no
    Companion at all, and a person who chooses it should be told what still
    happens — Trust prompts still appear, because they are the system asking, not
    Bunny asking.
    """
    entry = _from("companion_behaviour")
    return Screen(
        key="companion_behaviour",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("mode", "choice", "How much of Bunny", value=mode,
                  options=(
                      Option("full", "Full", note="A character, captions and controls."),
                      Option("compact", "Compact", note="A smaller character in the corner."),
                      Option("minimal", "Minimal", note="A small figure and an indicator, no captions."),
                      Option("text-only", "Text only", note="Words, no picture."),
                      Option("off", "Off", note="No Bunny surface at all. Permission requests still appear."),
                  )),
            Field("voice", "toggle", "Speak aloud", value=voice,
                  help="Bunny says things as well as showing them."),
            Field("captions", "toggle", "Always show captions", value=captions,
                  help="Everything Bunny says appears as text, whether or not it is spoken."),
            Field("atLogin", "toggle", "Start Bunny when I log in", value=at_login),
        ),
        actions=(_back(), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} Five choices: full, compact, minimal, text "
            "only, or off. With Bunny off the desktop works exactly the same and "
            "permission requests still appear, because those come from the system."
        ),
    )


def apps_screen(*, activities: Sequence[str] = (), choices: Sequence[Mapping[str, Any]] = ()) -> Screen:
    """§18–§20. Activities first, then a small curated set with honest labels.

    ``choices`` comes from `catalog.selection.choices_for`, which already carries
    cost, licence, account requirement, sandbox status and a curator-written
    ``differences`` sentence. Nothing here invents a comparison.
    """
    entry = _from("applications")
    activity_options = (
        Option("everyday", "Everyday", note="Web, mail, photos, music."),
        Option("creative", "Creative work", note="Images, video, audio, design."),
        Option("development", "Development", note="Editors, toolchains, containers."),
        Option("school", "School", note="Documents, reading, note taking."),
        Option("office", "Office and productivity", note="Documents, spreadsheets, slides."),
        Option("media", "Media", note="Watching and listening."),
        Option("gaming", "Gaming", note="Games and the runtimes they need."),
    )
    # Built from `catalog.selection.ApplicationChoice.as_record()` verbatim. §20
    # lists what must be shown — name, source, licence/cost, authentication,
    # sandbox status — and every one of those is already a curated field. The
    # only thing done here is joining them; no label is invented and no
    # comparison is made, because `differences` is the curator's sentence and is
    # shown as written.
    app_options = tuple(
        Option(
            str(item.get("entryId")),
            str(item.get("name")),
            note=" · ".join(
                part for part in (
                    str(item.get("cost") or ""),
                    str(item.get("commitmentNote") or ""),
                    "protected space" if item.get("sandboxCompatible")
                    else str(item.get("sandboxNote") or "not sandboxed"),
                    str(item.get("blockedReason") or ""),
                ) if part
            ),
            available=not item.get("blockedReason") and bool(item.get("installable", True)),
        )
        for item in choices
    ) or (Option("none", "Nothing selected", note="Apps can be added at any time.", available=False),)

    return Screen(
        key="applications",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("activities", "multi-choice", "What do you use this computer for?",
                  value=list(activities), options=activity_options,
                  help="Bunny suggests a few apps from this. Nothing is installed without you choosing it."),
            Field("applications", "multi-choice", "Suggested apps", options=app_options,
                  help="Each one shows what it costs, where it comes from, and whether it runs in a protected space."),
            Field("permissions", "info", "Permissions",
                  help="Every app starts with nothing. It asks the first time it needs your files, "
                       "camera, microphone or the network."),
        ),
        actions=(_back(), Action("skip", "Skip apps", tone="safe"), _next()),
        advanced=entry.advanced,
        announcement=(
            f"{entry.heading}. {entry.says} First choose what you use the computer for, "
            "then pick from a small suggested list. Every app shows its cost, its source "
            "and whether it runs in a protected space. You can skip this entirely, and "
            "installation does not need it."
        ),
    )


def review_screen(*, summary: Sequence[tuple[str, str]], disk: DiskInfo,
                  encrypted: bool) -> Screen:
    """§22. The last screen before anything is written."""
    identity = disk_identity(disk)
    consequence = f"Everything on {identity} will be erased. This cannot be undone."
    return Screen(
        key="review",
        heading="Review",
        says="Here's everything you chose. Read the part in red before you continue.",
        companion="reviewing",
        authority="companion",
        fields=tuple(Field(f"row-{index}", "info", label, help=value)
                     for index, (label, value) in enumerate(summary)),
        warnings=(Warning("danger", consequence),),
        actions=(
            _back(),
            Action("install", "Install Bunny OS",
                   accessible_name=f"Install Bunny OS, erasing {identity}", tone="danger"),
        ),
        advanced=("Full installation plan document", "Validated plan digest"),
        announcement=(
            "Review. " + consequence + " "
            + ("The disk will be encrypted. " if encrypted else "The disk will not be encrypted. ")
            + "Your choices: "
            + "; ".join(f"{label}: {value}" for label, value in summary)
            + ". Continue to begin installing, or go back to change anything."
        ),
    )


def installing_screen(*, stages: Sequence[Mapping[str, Any]], current: str | None,
                      detail: str = "") -> Screen:
    """§23. Real installer stages. No invented percentage.

    ``stages`` are `companion_flow.PROGRESS_STAGES` with a status each. There is
    no ``percent`` field anywhere in this screen, which is the honest form of
    "if only stage progress exists, show stage progress".
    """
    entry = _from("install")
    done = [item for item in stages if item.get("status") == "done"]
    label = next((str(item.get("label")) for item in stages if item.get("key") == current), "")
    return Screen(
        key="install",
        heading=entry.heading,
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("currentStage", "info", "Now", help=label or "Starting"),
            Field("detail", "info", "Detail", help=detail) if detail else
            Field("detail", "info", "Detail", help="Working."),
        ),
        actions=(Action("cancel", "Cancel", accessible_name="Cancel the installation", tone="safe"),),
        advanced=entry.advanced,
        progress=tuple(dict(item) for item in stages),
        announcement=(
            f"{entry.heading}. Step {len(done) + 1} of {len(stages)}: {label or 'starting'}. "
            + (f"{detail} " if detail else "")
            + "Do not turn the computer off."
        ),
    )


def failure_screen(*, headline: str, explanation: str, stage_key: str,
                   wrote_to_disk: bool, recovery: Sequence[Action] = (),
                   diagnostics_path: str = "") -> Screen:
    """§25, §46, §47. Stops safely and says what is true about the disk.

    ``wrote_to_disk`` is not cosmetic. §25 forbids continuing after a destructive
    operation fails unless the backend supports recovery, and a person standing in
    front of a failed install needs to know whether their old data is still there.
    The two sentences below are different facts and the screen never guesses
    between them — the caller is handed the value by the installer backend.
    """
    return Screen(
        key="failure",
        heading="Installation stopped",
        says="Something went wrong and I stopped. Nothing else will happen until you choose.",
        companion="error",
        authority="installer",
        fields=(
            Field("headline", "info", "What happened", help=headline),
            Field("explanation", "info", "Why", help=explanation),
            Field("stage", "info", "Where it stopped", help=stage_key),
            Field("diskState", "info", "Your disk",
                  help="The disk was already being written to when this failed, so its previous "
                       "contents are gone." if wrote_to_disk else
                       "Nothing had been written to the disk yet. Its previous contents are unchanged."),
            Field("diagnostics", "info", "Diagnostics",
                  help=diagnostics_path or "Kept in this session at /run/bunny-installer/diagnostics."),
        ),
        warnings=(
            (Warning("danger", "Everything that was on the disk has already been erased. "
                               "This cannot be undone."),)
            if wrote_to_disk else
            (Warning("caution", "Nothing was written to the disk."),)
        ),
        actions=tuple(recovery) or (
            Action("retry", "Try again", tone="primary"),
            Action("details", "Show details", tone="quiet"),
            Action("quit", "Shut down", tone="safe"),
        ),
        advanced=("Installer transaction journal", "Backend error class and stage"),
        announcement=(
            f"Installation stopped. {headline} {explanation} It stopped at {stage_key}. "
            + ("Everything that was on the disk has already been erased. This cannot be undone. "
               if wrote_to_disk else "Nothing was written to the disk. ")
            + "Diagnostics have been kept."
        ),
    )


def complete_screen(*, name: str = "") -> Screen:
    """§27. A completion state in the person's language, then Restart."""
    entry = _from("finish")
    return Screen(
        key="complete",
        heading="Bunny OS is ready",
        says=entry.says,
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("next", "info", "What happens next",
                  help="The computer restarts and starts from its own disk. "
                       "You can remove the installation media when it does."),
        ),
        actions=(
            Action("restart", "Restart", tone="primary"),
            Action("details", "Installation details", tone="quiet"),
        ),
        advanced=entry.advanced,
        announcement=(
            "Bunny OS is ready. " + entry.says + " Restart to start using it. "
            "You can remove the installation media when the computer restarts."
        ),
    )


def first_boot_screen(*, name: str, mode: str = "full") -> Screen:
    """§29. A continuation, not a second wizard.

    It knows the person's name because installation collected it, and §28 forbids
    asking again for anything setup already has.
    """
    entry = _from("hello")
    greeting = f"Welcome, {name}." if name.strip() else "Welcome."
    return Screen(
        key="first_boot",
        heading=greeting,
        says="Your computer is ready. Would you like a quick look around, or shall I get out of your way?",
        companion=entry.companion,
        authority=entry.authority,
        fields=(
            Field("summary", "info", "Ready",
                  help="Your language, keyboard, appearance and accessibility settings are already applied."),
        ),
        actions=(
            Action("tour", "Show me around", tone="primary"),
            Action("start", "Start using Bunny OS", tone="safe"),
        ),
        advanced=entry.advanced,
        announcement=(
            f"{greeting} Your computer is ready. Your language, keyboard, appearance and "
            "accessibility settings are already applied. Two choices: show me around, or "
            "start using Bunny OS."
        ),
    )
