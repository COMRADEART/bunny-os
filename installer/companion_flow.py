# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup experience as data: what Bunny says, and what Bunny may not decide.

The installer and the first-run experience are two different programs that have
to feel like one conversation, so the conversation lives here — as values — and
both of them render it. That is not tidiness. A copy of the wording in each
program is a copy that drifts, and the sentence a person reads before they let a
disk be erased is not a sentence that should exist in two versions.

The division that matters is in :attr:`Stage.authority`:

``companion``
    Bunny explains and Bunny may act. Choosing a wallpaper, setting a keyboard
    layout, agreeing to a notification preference.
``installer``
    The underlying installer decides and performs. Bunny narrates and nothing
    more. Every partitioning, formatting and bootloader step is here.
``user``
    Nothing proceeds until a person does something specific — not a Next button,
    a *specific* thing, named in :attr:`Stage.confirmation`.

§3 is explicit that the visual Companion must never become the authority for
destructive disk actions. :func:`may_proceed` is how that is enforced rather than
intended: a stage whose authority is ``user`` returns ``False`` until the exact
confirmation it names has been given, and no amount of Companion state changes
that. The Companion has no field in this module through which it could.

**The Companion's state is derived, never authored.** :attr:`Stage.companion`
names a phase from :data:`companion.presentation.PRESENTATION_PHASES`, and the
installer's own progress is what moves it. A Companion that could pick its own
expression during an install would be a Companion whose worried face meant
nothing.

**Technical detail is present and folded away.** Each stage carries
``advanced``, which is the real vocabulary — device nodes, filesystem types, LUKS
parameters, subvolume layout. §3 asks that plain language be the default and the
technical detail remain available; hiding it entirely would make the installer
unusable by the people most able to help when it goes wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "AUTHORITIES",
    "FIRST_RUN_STAGES",
    "INSTALL_STAGES",
    "PROGRESS_STAGES",
    "Stage",
    "may_proceed",
    "stage",
    "stages_for",
]

AUTHORITIES = ("companion", "installer", "user")


@dataclass(frozen=True)
class Stage:
    """One step of setup, and who is allowed to decide it."""

    key: str
    #: What Bunny says, in the first person, in one or two sentences.
    says: str
    #: The heading above the controls. Short; the Companion carries the tone.
    heading: str
    authority: str
    #: The companion presentation phase this stage puts the surface into.
    companion: str
    #: Names the exact act that unlocks the stage, for ``user`` authority.
    #: ``None`` for every other authority, so a stage cannot half-require one.
    confirmation: str | None = None
    #: Plain-language description of what the confirmation actually authorises.
    confirmation_consequence: str = ""
    #: The technical vocabulary, behind a disclosure. Rendered verbatim.
    advanced: tuple[str, ...] = ()
    #: Whether skipping is offered, and what skipping means.
    skippable: bool = True
    skip_note: str = ""

    def __post_init__(self) -> None:
        if self.authority not in AUTHORITIES:
            raise ValueError(f"unknown stage authority: {self.authority!r}")
        if (self.authority == "user") != (self.confirmation is not None):
            raise ValueError(f"{self.key}: only a user-authority stage names a confirmation")
        if self.confirmation is not None and not self.confirmation_consequence:
            raise ValueError(f"{self.key}: a confirmation must say what it authorises")
        if self.skippable and self.authority == "user":
            raise ValueError(f"{self.key}: a stage that needs a person cannot be skippable")

    def as_record(self) -> Mapping[str, Any]:
        return {
            "key": self.key,
            "says": self.says,
            "heading": self.heading,
            "authority": self.authority,
            "companion": self.companion,
            "confirmation": self.confirmation,
            "confirmationConsequence": self.confirmation_consequence,
            "advanced": list(self.advanced),
            "skippable": self.skippable,
            "skipNote": self.skip_note,
        }


#: The graphical installer, in order. The first stage is the Companion alone on a
#: light background; a dense partition table as the first thing a person sees is
#: the experience §3 exists to replace.
INSTALL_STAGES: tuple[Stage, ...] = (
    Stage(
        key="welcome",
        says="Hi. I'm Bunny. I'll help set up your computer.",
        heading="Welcome",
        authority="companion",
        companion="idle",
        advanced=("Installer build and target architecture", "Live session log at journalctl -b"),
        skip_note="",
    ),
    Stage(
        key="language_region",
        says="Which language should I use?",
        heading="Language and region",
        authority="companion",
        companion="understanding",
        advanced=("locale, LANG and LC_* values", "timezone database entry"),
    ),
    Stage(
        key="keyboard",
        says="Let's check your keyboard before you type anything important.",
        heading="Keyboard",
        authority="companion",
        companion="listening",
        advanced=("X11 layout and variant", "Wayland xkb rules"),
        skippable=False,
        skip_note="A wrong layout makes a disk password impossible to type back.",
    ),
    Stage(
        key="network",
        says="I can connect to Wi-Fi now, or you can do it later. Nothing here needs the internet.",
        heading="Network",
        authority="companion",
        companion="working",
        advanced=("NetworkManager connection profile", "DNS and proxy configuration"),
        skip_note="Setup works offline. Updates and optional apps come later.",
    ),
    Stage(
        key="storage",
        says="I need to know where to install. I won't change anything until you say so.",
        heading="Where to install",
        authority="installer",
        companion="planning",
        advanced=(
            "Block device, model and serial",
            "Existing partition table and filesystems",
            "Proposed GPT layout, ESP size and root subvolumes",
        ),
        skippable=False,
        skip_note="",
    ),
    Stage(
        key="confirm_erase",
        says="This is the part I can't decide for you. Read what's about to happen, then confirm it yourself.",
        heading="Confirm",
        authority="user",
        companion="waiting_for_approval",
        confirmation="type-the-disk-name",
        confirmation_consequence=(
            "Everything on the disk you name will be erased, including any other operating "
            "system on it. This cannot be undone."
        ),
        advanced=(
            "Exact wipefs, sgdisk and mkfs commands",
            "Partitions that will be destroyed, with their current contents' sizes",
        ),
        skippable=False,
    ),
    Stage(
        key="encryption",
        says="I can encrypt the disk. If you forget the passphrase, nobody can recover what's on it — not even me.",
        heading="Encryption",
        authority="user",
        companion="waiting_for_approval",
        confirmation="enter-passphrase-twice",
        confirmation_consequence=(
            "The disk is encrypted with the passphrase you type. There is no reset and no "
            "back door; a forgotten passphrase means the data is gone."
        ),
        advanced=("LUKS2 header, cipher and key derivation cost", "TPM binding, if a TPM is present"),
        skippable=False,
    ),
    Stage(
        key="account",
        says="Who is this computer for?",
        heading="Your account",
        authority="companion",
        companion="understanding",
        advanced=("Username, UID, groups and shell", "Home directory location"),
        skippable=False,
        skip_note="",
    ),
    Stage(
        key="accessibility",
        says="Would you like larger text, more contrast, less movement, or a screen reader? You can change all of this later.",
        heading="Accessibility",
        authority="companion",
        companion="listening",
        advanced=("Orca autostart", "text-scaling-factor", "prefers-reduced-motion"),
        skip_note="Defaults follow the system settings you can change any time.",
    ),
    Stage(
        key="privacy",
        says="Everything is off unless you turn it on. I'll tell you what each one means.",
        heading="Privacy",
        authority="companion",
        companion="understanding",
        advanced=("Telemetry endpoints (none configured)", "Crash report destination", "Search index scope"),
    ),
    Stage(
        key="companion_behaviour",
        says="How much of me would you like on screen?",
        heading="Bunny",
        authority="companion",
        companion="idle",
        advanced=("Presentation implementation ladder", "Autostart unit and session target"),
        skip_note="You can turn me off entirely and the desktop works the same.",
    ),
    Stage(
        key="applications",
        says="I can set up a few apps now. Each one gets its own protected space, and I'll ask before any of them touch your files.",
        heading="Apps",
        authority="companion",
        companion="planning",
        advanced=("Catalogue entry ids and package sources", "Declared permission sets per capsule"),
        skip_note="You can add apps whenever you like.",
    ),
    Stage(
        key="install",
        says="I'm setting things up now.",
        heading="Installing",
        authority="installer",
        companion="working",
        advanced=("Per-step installer transaction journal", "bootc deployment target"),
        skippable=False,
        skip_note="",
    ),
    Stage(
        key="finish",
        says="Done. Restart when you're ready and I'll be there.",
        heading="Ready",
        authority="companion",
        companion="success",
        advanced=("Installed image digest", "Deployment and rollback targets"),
        skippable=False,
        skip_note="",
    ),
)

#: What the Companion shows while the installer works. Each row is a real
#: installer phase, not a decorative one, so a person watching learns something
#: true about where the time goes.
PROGRESS_STAGES: tuple[tuple[str, str], ...] = (
    ("prepare", "Getting the disk ready"),
    ("copy", "Copying the system"),
    ("security", "Setting up security"),
    ("user", "Making your account"),
    ("capsules", "Preparing app spaces"),
    ("preferences", "Applying what you chose"),
    ("finalise", "Finishing up"),
)

#: First boot. Shorter, and every stage is companion authority — nothing here
#: destroys anything, so nothing here needs a typed confirmation.
FIRST_RUN_STAGES: tuple[Stage, ...] = (
    Stage(
        key="hello",
        says="You're set up. Let me show you three things and then get out of your way.",
        heading="Hello",
        authority="companion",
        companion="idle",
        advanced=("Session type, compositor and GPU driver in use",),
    ),
    Stage(
        key="what_you_chose",
        says="Here's what you picked during setup. Change any of it now if you like.",
        heading="Your choices",
        authority="companion",
        companion="presenting_result",
        advanced=("first-run.json state document",),
    ),
    Stage(
        key="capsules_explained",
        says="Every app here runs in its own space. It can't see your files, or another app's, until you say so.",
        heading="App Capsules",
        authority="companion",
        companion="understanding",
        advanced=("Isolation backend in use and what it enforces", "Per-capsule directory layout"),
    ),
    Stage(
        key="trust_explained",
        says="When an app wants something, I'll ask you in plain words. You can change your mind later in Settings.",
        heading="Permissions",
        authority="companion",
        companion="waiting_for_approval",
        advanced=("Permission categories and the Linux mechanism behind each",),
    ),
    Stage(
        key="try_something",
        says="Ask me to do something. I'll show you exactly what I'm doing while I do it.",
        heading="Try me",
        authority="companion",
        companion="listening",
        advanced=("Task workspace projection", "Capability to application mapping"),
    ),
    Stage(
        key="done",
        says="That's everything. I'll be in the corner if you need me.",
        heading="Ready",
        authority="companion",
        companion="success",
        advanced=(),
    ),
)

_BY_KEY = {entry.key: entry for entry in INSTALL_STAGES + FIRST_RUN_STAGES}


def stage(key: str) -> Stage:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(f"no setup stage called {key!r}") from None


def stages_for(flow: str) -> tuple[Stage, ...]:
    if flow == "install":
        return INSTALL_STAGES
    if flow == "first-run":
        return FIRST_RUN_STAGES
    raise KeyError(f"no such flow: {flow!r}")


def may_proceed(entry: Stage, *, confirmations: Sequence[str]) -> bool:
    """Whether setup may move past ``entry``.

    The whole of §3's safety rule. A stage whose authority is ``user`` requires
    its own named confirmation to be present, and nothing else — not a Next
    button, not a Companion state, not a preference. A caller that wanted to skip
    it would have to add the confirmation string, which is a thing a reviewer can
    see in a diff.
    """
    if entry.authority != "user":
        return True
    return entry.confirmation in set(confirmations)
