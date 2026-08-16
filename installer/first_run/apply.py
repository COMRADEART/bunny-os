# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the choices made during installation into a configured desktop.

§30: when onboarding closes, the desktop should already reflect the theme, the
text scale, high contrast, reduced motion, the Bunny mode, the chosen apps, the
privacy choices and the locale — and the person should not have to set any of it
again in Settings.

§28 is the same requirement stated from the other side: first run must not ask
for anything installation already collected. The way to satisfy both is to *use*
what installation collected, which is what this module does.

## Three states, deliberately kept apart

`installer/setup_state.py` writes **what was chosen** to
``/var/lib/bunny-setup/choices.json``. This module applies it and writes **what
was applied** to ``~/.local/state/bunny-os/applied.json``. Neither of those is
**what is true**, which lives in gsettings, ``/etc/locale.conf`` and the account
database, and which `build/scripts/verify-installed-choices.py` reads
independently.

§45 forbids inferring the third from the first. Keeping the second separate is
what makes the comparison meaningful: a setting that was chosen, recorded as
applied, and is not actually set is a defect that this separation can see and a
single document cannot.

## Every application is attempted, and failures do not stop the rest

A `gsettings` key that does not exist on this build should not prevent the text
scale being set. Each application is independent, each records its own outcome,
and :func:`apply_all` reports every failure rather than raising on the first —
because the person is looking at a desktop, and the useful outcome is "eleven of
twelve settings took, and here is the one that did not".

## What it will not do

Touch anything privileged. The locale, the keyboard layout and the timezone are
installed by Anaconda from the kickstart, which is where they belong; this module
reads them back to *verify*, and does not set them. A first-run helper that could
call `localectl` would be a first-run helper that runs as root, and §28's
architecture (ADR-014) is explicit that it is an unprivileged user application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from installer.setup_state import CHOICES_ON_TARGET, Choices

__all__ = ["Application", "APPLIED_STATE", "apply_all", "load_choices", "record_applied"]

#: Per-user, because the choices are per-user and a second account on the machine
#: did not make them.
APPLIED_STATE = Path("~/.local/state/bunny-os/applied.json")


@dataclass
class Application:
    """One setting, and what happened when it was applied."""

    key: str
    intent: str
    applied: bool = False
    detail: str = ""
    #: What was asked for, for the report. Never a secret; nothing here is one.
    value: Any = None

    def as_record(self) -> Mapping[str, Any]:
        return {"key": self.key, "intent": self.intent, "applied": self.applied,
                "detail": self.detail, "value": self.value}


@dataclass
class Applier:
    """Applies choices, records outcomes, raises nothing."""

    dry_run: bool = False
    results: list[Application] = field(default_factory=list)

    def _gsettings(self, schema: str, key: str, value: str, *, intent: str,
                   name: str) -> Application:
        record = Application(key=name, intent=intent, value=value)
        binary = shutil.which("gsettings")
        if binary is None:
            record.detail = "gsettings is not installed"
            self.results.append(record)
            return record
        if self.dry_run:
            record.detail = "dry run"
            self.results.append(record)
            return record
        try:
            completed = subprocess.run(
                [binary, "set", schema, key, value],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as error:
            record.detail = f"{type(error).__name__}: {error}"[:200]
            self.results.append(record)
            return record
        if completed.returncode == 0:
            record.applied = True
            record.detail = f"{schema} {key} = {value}"
        else:
            # A schema that does not exist on this build is a real outcome and
            # not a crash: the desktop still has to come up.
            record.detail = (completed.stderr or completed.stdout).strip()[:200]
        self.results.append(record)
        return record

    # -- the settings ----------------------------------------------------

    def appearance(self, choices: Choices) -> None:
        scheme = {"light": "default", "dark": "prefer-dark",
                  "system": "default"}.get(choices.colour_scheme, "default")
        self._gsettings("org.gnome.desktop.interface", "color-scheme", scheme,
                        intent=f"appearance: {choices.colour_scheme}", name="colourScheme")
        # GTK's own theme name has to agree, or the shell is dark and the apps
        # are not — which is the kind of half-applied theme that reads as a bug
        # in the desktop rather than as a setting that did not take.
        self._gsettings("org.gnome.desktop.interface", "gtk-theme",
                        "Adwaita-dark" if choices.colour_scheme == "dark" else "Adwaita",
                        intent="appearance: GTK theme", name="gtkTheme")

    def accessibility(self, choices: Choices) -> None:
        self._gsettings("org.gnome.desktop.interface", "text-scaling-factor",
                        f"{choices.text_scale}",
                        intent=f"text size {int(choices.text_scale * 100)}%",
                        name="textScale")
        self._gsettings("org.gnome.desktop.a11y.interface", "high-contrast",
                        "true" if choices.high_contrast else "false",
                        intent="high contrast", name="highContrast")
        self._gsettings("org.gnome.desktop.interface", "enable-animations",
                        "false" if choices.reduced_motion else "true",
                        intent="reduced motion", name="reducedMotion")
        self._gsettings("org.gnome.desktop.a11y.applications", "screen-reader-enabled",
                        "true" if choices.screen_reader else "false",
                        intent="screen reader", name="screenReader")

    def _companion_setting(self, section: str, field: str, value: str) -> tuple[bool, str]:
        """One write to the companion settings document, through its CLI.

        The document at ``~/.local/state/bunny-os/companion/settings.json`` is
        the single authority the window, the service and the CLI share; going
        through ``bunny-os companion settings set`` uses the same guarded
        read-modify-write they do rather than a second writer.
        """
        binary = shutil.which("bunny-os")
        if binary is None:
            return False, "bunny-os is not installed"
        if self.dry_run:
            # Not applied, same as _gsettings: a dry run changes nothing and
            # must not be recorded as if it had.
            return False, "dry run"
        try:
            completed = subprocess.run(
                [binary, "companion", "settings", "set", section, field, value],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, f"{type(error).__name__}: {error}"[:200]
        if completed.returncode == 0:
            return True, f"{section}.{field} = {value}"
        return False, (completed.stderr or completed.stdout).strip()[:200]

    def companion(self, choices: Choices) -> None:
        """The companion choices, into the companion's own settings document.

        There is no GSettings schema for the companion — an earlier version of
        this method wrote to ``art.comrade.BunnyShell``, which never existed
        anywhere, and every companion choice silently failed on the first real
        login. The authoritative store is `companion/settings.py`'s document.

        The five setup modes project onto what the document can say: ``off``
        is §6's Hidden (``character.visible``), ``text-only`` is the
        accessibility preference. ``compact`` and ``minimal`` have no
        persisted representation yet; recording them as applied would be the
        lie §45 forbids, so they apply the shared projection and report
        honestly that the chrome level did not land anywhere.
        """
        mode = choices.companion_mode
        record = Application(key="companionMode",
                             intent=f"Bunny presentation: {mode}", value=mode)
        visible_ok, visible_detail = self._companion_setting(
            "character", "visible", "false" if mode == "off" else "true")
        text_ok, text_detail = self._companion_setting(
            "accessibility", "text_only",
            "true" if mode == "text-only" else "false")
        representable = mode in ("full", "text-only", "off")
        record.applied = visible_ok and text_ok and representable
        record.detail = f"{visible_detail}; {text_detail}"[:200]
        if not representable:
            record.detail = (f"mode {mode!r} has no persisted representation; "
                             f"{record.detail}")[:200]
        self.results.append(record)

        captions = Application(key="companionCaptions", intent="captions",
                               value=choices.companion_captions)
        captions.applied, captions.detail = self._companion_setting(
            "accessibility", "captions_always",
            "true" if choices.companion_captions else "false")
        self.results.append(captions)

    def privacy(self, choices: Choices) -> None:
        """§15: every one off unless it was turned on, and none of them silently.

        The two that map to a real platform switch are set; the rest are Bunny's
        own and are recorded so the runtime reads them from one place. A
        privacy choice that was collected and then not applied is worse than one
        that was never offered.
        """
        self._gsettings("org.gnome.desktop.privacy", "report-technical-problems",
                        "true" if choices.privacy.get("crashReports") else "false",
                        intent="crash reports", name="crashReports")
        self._gsettings("org.gnome.system.location", "enabled",
                        "true" if choices.privacy.get("location") else "false",
                        intent="location services", name="location")

    def companion_autostart(self, choices: Choices) -> None:
        """§16 and §30: start Bunny at login, or do not.

        A preset is not an enablement — a previous phase found the Companion had
        never autostarted because only the preset was in place. So this writes
        the user unit link itself and reports whether the symlink exists
        afterwards, rather than trusting the command's exit code.
        """
        record = Application(key="companionAtLogin",
                             intent="start Bunny at login",
                             value=choices.companion_at_login)
        binary = shutil.which("systemctl")
        if binary is None:
            record.detail = "systemctl is not available"
            self.results.append(record)
            return
        if self.dry_run:
            record.detail = "dry run"
            self.results.append(record)
            return
        action = "enable" if choices.companion_at_login else "disable"
        try:
            subprocess.run([binary, "--user", action, "bunny-companion.service"],
                           capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as error:
            record.detail = f"{type(error).__name__}: {error}"[:200]
            self.results.append(record)
            return
        # The wants directory follows the unit's [Install] section, which is
        # WantedBy=graphical-session.target — not default.target. The first
        # real login found this assertion pointing at default.target.wants:
        # the enable had succeeded and the report still said the symlink was
        # absent.
        link = Path("~/.config/systemd/user/graphical-session.target.wants/"
                    "bunny-companion.service").expanduser()
        exists = link.exists() or link.is_symlink()
        record.applied = exists == bool(choices.companion_at_login)
        record.detail = f"symlink {'present' if exists else 'absent'} after {action}"
        self.results.append(record)


def load_choices(path: Path = CHOICES_ON_TARGET) -> Choices | None:
    """What installation collected, or ``None`` if it left nothing.

    ``None`` is a supported state: a system installed by some other means, or an
    upgrade from before this existed. First run then asks rather than assuming,
    which is the correct behaviour and the reason this returns instead of
    raising.
    """
    try:
        return Choices.load(path)
    except (OSError, ValueError):
        return None


def apply_all(choices: Choices, *, dry_run: bool = False) -> dict[str, Any]:
    """Apply everything, report everything, raise nothing."""
    applier = Applier(dry_run=dry_run)
    applier.appearance(choices)
    applier.accessibility(choices)
    applier.companion(choices)
    applier.privacy(choices)
    applier.companion_autostart(choices)

    results = [item.as_record() for item in applier.results]
    failed = [item for item in results if not item["applied"]]
    return {
        "schemaVersion": 1,
        "dryRun": dry_run,
        "applied": len(results) - len(failed),
        "total": len(results),
        "failures": failed,
        "results": results,
    }


def record_applied(report: Mapping[str, Any], *, path: Path = APPLIED_STATE) -> Path:
    """Write what was applied, separately from what was chosen.

    Atomically, and never merged into the choices document: §45's comparison
    needs the two to be independently written, and a single file that recorded
    both would make "chosen" and "applied" the same claim.
    """
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(temporary, target)
    target.chmod(0o600)
    return target
