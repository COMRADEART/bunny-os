# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The choices a person makes during setup, and how they survive the reboot.

§45 asks that first boot be verified by reading the *installed system* rather
than by trusting installer state, and §28 asks that first run never re-ask for
anything setup already collected. Both need one thing: a document that crosses
the reboot.

## The shape of the crossing

Setup runs in the live session and writes here. The installer backend hands the
document to the installation transaction, which places it on the target at
``/var/lib/bunny-setup/choices.json``. On first boot ``bunny-first-run`` reads
it, applies what it describes, and records what it applied.

Three separate things, deliberately:

*what was chosen* — this document, written in the live session;
*what was applied* — written on first boot by the thing that applied it;
*what is true* — read back out of gsettings, localectl, the account database.

§45's "do not infer from installer state" is exactly the distinction between the
first and the third. A qualification run compares them, and a preference that was
chosen, recorded as applied, and is not actually set is a defect this separation
can see and a single document could not.

## What is never in here

No password. No passphrase. No recovery key. No network credential.

`Choices.validate` refuses a document containing a key that looks like a secret,
the same way `installer.protocol` refuses a request payload and
`installer.first_run.state` refuses a state file. Credentials reach the target
through the installer backend's own protected channel — a file descriptor for
Anaconda, Secret Service for anything the desktop needs later — and never through
a JSON document that is written to a disk and read back by a different program.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

__all__ = [
    "CHOICES_ON_TARGET",
    "COMPANION_MODES",
    "Choices",
    "SCHEMA_VERSION",
    "SECRET_KEYS",
]

SCHEMA_VERSION = 1

#: Where the installed system reads it. Under /var so it survives an ostree
#: deployment change: /etc is merged on upgrade and /usr is read-only.
CHOICES_ON_TARGET = Path("/var/lib/bunny-setup/choices.json")

#: §16. Five, including off — `companionModes.js` has four, and a mode a person
#: can select in setup that the desktop cannot resolve would be a preference
#: that silently becomes something else.
COMPANION_MODES = ("full", "compact", "minimal", "text-only", "off")

SECRET_KEYS = frozenset({
    "password", "passphrase", "recoverykey", "rawkey", "providerkey",
    "token", "secret", "credential", "apikey", "psk",
})


def _contains_secret(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in SECRET_KEYS or _contains_secret(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return False


@dataclass
class Choices:
    """Everything setup collected that is not a secret.

    Mutable, unlike most of this codebase's records, because it is filled in
    across a dozen screens and the alternative is a frozen dataclass rebuilt
    thirteen times. `validate` is what keeps it honest, and it is called before
    every write rather than at construction.
    """

    # §7
    language: str = "en-GB"
    region: str = "GB"
    timezone: str = "Europe/London"
    keyboard_layout: str = "gb"

    # §8 — collected first, applied to the installer immediately
    text_scale: float = 1.0
    high_contrast: bool = False
    reduced_motion: bool = False
    screen_reader: bool = False
    captions: bool = False

    # §14 — the account itself; the password is not here and never will be
    display_name: str = ""
    username: str = ""
    device_name: str = ""

    # §13 — whether, not what
    encryption_enabled: bool = False

    # §15 — every one off unless turned on
    privacy: dict[str, bool] = field(default_factory=lambda: {
        "diagnostics": False,
        "crashReports": False,
        "feedback": False,
        "location": False,
        "microphone": False,
        "camera": False,
        "onlineAI": False,
        "remoteProcessing": False,
    })

    # §17
    colour_scheme: str = "system"
    accent: str = "violet"
    wallpaper: str = "bunny-default"

    # §16
    companion_mode: str = "full"
    companion_voice: bool = False
    companion_captions: bool = True
    companion_at_login: bool = True

    # §18–§21 — catalogue entry ids only; nothing is fetched from a URL
    activities: list[str] = field(default_factory=list)
    applications: list[str] = field(default_factory=list)

    def validate(self) -> tuple[str, ...]:
        """Everything wrong with this document, or an empty tuple."""
        errors: list[str] = []
        if self.companion_mode not in COMPANION_MODES:
            errors.append(f"unknown companion mode: {self.companion_mode!r}")
        if self.colour_scheme not in {"light", "dark", "system"}:
            errors.append(f"unknown colour scheme: {self.colour_scheme!r}")
        # The four the accessibility screen offers. A scale outside this set has
        # no resolved theme, and `theme_css.resolve` would refuse it at the
        # moment the surface tried to draw — better to refuse it here.
        if self.text_scale not in {1.0, 1.25, 1.5, 2.0}:
            errors.append(f"text scale {self.text_scale} is not one of the offered sizes")
        for name in self.activities:
            if not isinstance(name, str) or not name.strip():
                errors.append("an activity is empty")
        for name in self.applications:
            if not isinstance(name, str) or not name.strip():
                errors.append("an application id is empty")
        if _contains_secret(self.privacy):
            errors.append("a secret-shaped key is present in the privacy choices")
        return tuple(errors)

    def as_record(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "locale": {
                "language": self.language,
                "region": self.region,
                "timezone": self.timezone,
                "keyboardLayout": self.keyboard_layout,
            },
            "accessibility": {
                "textScale": self.text_scale,
                "highContrast": self.high_contrast,
                "reducedMotion": self.reduced_motion,
                "screenReader": self.screen_reader,
                "captions": self.captions,
            },
            "account": {
                "displayName": self.display_name,
                "username": self.username,
                "deviceName": self.device_name,
            },
            "encryption": {"enabled": self.encryption_enabled},
            "privacy": dict(self.privacy),
            "appearance": {
                "colourScheme": self.colour_scheme,
                "accent": self.accent,
                "wallpaper": self.wallpaper,
            },
            "companion": {
                "mode": self.companion_mode,
                "voice": self.companion_voice,
                "captions": self.companion_captions,
                "atLogin": self.companion_at_login,
            },
            "applications": {
                "activities": list(self.activities),
                "selected": list(self.applications),
            },
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Choices":
        if record.get("schemaVersion") != SCHEMA_VERSION:
            raise ValueError("unsupported setup-choices schema version")
        if _contains_secret(record):
            raise ValueError("the setup-choices document contains a secret-shaped key")
        locale = record.get("locale", {})
        access = record.get("accessibility", {})
        account = record.get("account", {})
        appearance = record.get("appearance", {})
        companion = record.get("companion", {})
        applications = record.get("applications", {})
        value = cls(
            language=str(locale.get("language", "en-GB")),
            region=str(locale.get("region", "GB")),
            timezone=str(locale.get("timezone", "Europe/London")),
            keyboard_layout=str(locale.get("keyboardLayout", "gb")),
            text_scale=float(access.get("textScale", 1.0)),
            high_contrast=bool(access.get("highContrast", False)),
            reduced_motion=bool(access.get("reducedMotion", False)),
            screen_reader=bool(access.get("screenReader", False)),
            captions=bool(access.get("captions", False)),
            display_name=str(account.get("displayName", "")),
            username=str(account.get("username", "")),
            device_name=str(account.get("deviceName", "")),
            encryption_enabled=bool(record.get("encryption", {}).get("enabled", False)),
            privacy={str(k): bool(v) for k, v in dict(record.get("privacy", {})).items()},
            colour_scheme=str(appearance.get("colourScheme", "system")),
            accent=str(appearance.get("accent", "violet")),
            wallpaper=str(appearance.get("wallpaper", "bunny-default")),
            companion_mode=str(companion.get("mode", "full")),
            companion_voice=bool(companion.get("voice", False)),
            companion_captions=bool(companion.get("captions", True)),
            companion_at_login=bool(companion.get("atLogin", True)),
            activities=[str(item) for item in applications.get("activities", [])],
            applications=[str(item) for item in applications.get("selected", [])],
        )
        errors = value.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return value

    # ------------------------------------------------------------- storage

    def save(self, path: Path) -> None:
        """Write atomically, refusing to persist anything secret-shaped.

        The same temp-file-and-rename `first_run.state` uses. Setup can be
        interrupted by the person closing it, by the live session restarting, or
        by the §26 fallback taking over from a crashed Companion; a half-written
        document read by any of those is a resumable flow that resumes into
        nonsense.
        """
        errors = self.validate()
        if errors:
            raise ValueError("refusing to save invalid setup choices: " + "; ".join(errors))
        record = self.as_record()
        if _contains_secret(record):
            raise ValueError("refusing to persist a secret-shaped key")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".choices-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, sort_keys=True, indent=1)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: Path) -> "Choices":
        return cls.from_record(json.loads(path.read_text(encoding="utf-8")))

    # -------------------------------------------------------------- theme

    def theme_options(self) -> dict[str, Any]:
        """The arguments `theme_css.resolve` needs, from the accessibility choices.

        Setup itself always draws light. §34 asks for the clean white direction
        and §5 for a light opening scene; the *installed* system honours
        ``colour_scheme``, which is a different surface on a different machine
        state. High contrast overrides both, because a person who asked for
        maximum separation asked for it now.
        """
        return {
            "scheme": "light",
            "high_contrast": self.high_contrast,
            "text_scale": self.text_scale,
            "reduced_motion": self.reduced_motion,
        }

    def summary_rows(self, *, disk_identity: str, erases: bool) -> tuple[tuple[str, str], ...]:
        """§22's review table. Ordered so the disk consequence is not last."""
        privacy_on = sorted(name for name, value in self.privacy.items() if value)
        return (
            ("Language", self.language),
            ("Region and time zone", f"{self.region} · {self.timezone}"),
            ("Keyboard", self.keyboard_layout),
            ("Install to", disk_identity),
            ("What happens to it", "Erased completely" if erases else "Kept"),
            ("Encryption", "On, with a passphrase and a recovery key"
                           if self.encryption_enabled else "Off"),
            ("Account", f"{self.display_name} ({self.username}), administrator"),
            ("Privacy", ", ".join(privacy_on) if privacy_on else "Everything off"),
            ("Appearance", f"{self.colour_scheme}, {self.accent} accent"),
            ("Bunny", f"{self.companion_mode}"
                      f"{', captions on' if self.companion_captions else ''}"
                      f"{', starts at login' if self.companion_at_login else ''}"),
            ("Apps", ", ".join(self.applications) if self.applications else "None"),
            ("Text size", f"{int(self.text_scale * 100)}%"),
            ("High contrast", "On" if self.high_contrast else "Off"),
            ("Reduce motion", "On" if self.reduced_motion else "Off"),
            ("Screen reader", "On" if self.screen_reader else "Off"),
        )
