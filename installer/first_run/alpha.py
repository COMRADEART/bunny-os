# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Public Alpha first run: ten pages that are about *this* machine.

The first-run application that existed before this was thirteen pages of static
copy with a Next button. It said "No multi-gigabyte model is downloaded
automatically", which is true, and it never looked to see whether one was there.
A person finished it knowing what Bunny OS does in general and nothing about
what their computer would actually do.

So the pages are the same ten :mod:`companion.onboarding` declares, and each one
that has a survey shows the survey's own sentence — the provider page says which
providers answered, the microphone page says how many devices were found and
whether a recognition model exists, the character page says which character this
machine will draw and why. The remedies come from the surveys too, so the wizard
has no opinions of its own to keep in step with the runtime's.

What this module owns: a window, a state file, and the bridge between them.

The offline rule from §7 is structural rather than defended: eight of the ten
pages are skippable, and the two that are not — welcome and finish — ask for
nothing. A machine with no network, no microphone, no speakers, no model and no
GPU walks through all ten and arrives at a companion that works.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

__all__ = ["AlphaFirstRun", "build_model", "run"]

STATE_SCHEMA_VERSION = 2


def build_model(*, root: Path | None = None) -> Any:
    """An :class:`~companion.onboarding.OnboardingModel` wired to real surveys.

    The surveyors are closures rather than direct calls so the model can decide
    *when* to run them: probing three loopback ports and loading a speech
    recogniser at window-construction time would make the welcome page take
    several seconds to appear.
    """
    from companion.onboarding import (
        OnboardingModel, survey_audio, survey_character, survey_local_providers, survey_speech,
    )

    def character() -> Any:
        from companion.character.defaults import default_character_paths
        from companion.character.importer import PackageRegistry
        from companion.presentation import (
            AccessibilityPreferences, PresentationSignals, select_presentation,
        )

        state_root = root or _default_root()
        try:
            from companion.character.three_d.diagnostics import three_d_environment

            environment = three_d_environment()
        except Exception:
            environment = {"windowedThreeDAvailable": False, "graphicalSession": True}
        signals = PresentationSignals(
            gpu_available=bool(environment.get("windowedThreeDAvailable")),
            display_available=bool(environment.get("graphicalSession")),
            available_memory_bytes=_available_memory(),
        )
        recommendation = select_presentation(signals, AccessibilityPreferences())
        registry = PackageRegistry(
            state_root / "characters", built_in_paths=default_character_paths(),
        )
        return survey_character(registry, eligible=recommendation.eligible)

    return OnboardingModel(surveyors={
        "providers": survey_local_providers,
        "speech": survey_speech,
        "audio": survey_audio,
        "character": character,
    })


def _default_root() -> Path:
    override = os.environ.get("BUNNY_COMPANION_ROOT")
    if override:
        return Path(override)
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "bunny-os" / "companion"


def _available_memory() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1]) * 1024
    except OSError:
        return None
    return None


class AlphaFirstRun:
    """Position, persistence and completion. No GTK; the window drives this.

    Separated from the window so that the wizard's *behaviour* — where it
    resumes, what it records, when it is finished — is testable without a
    display. That was the missing half before: every decision the old first run
    made lived inside a GTK callback.
    """

    def __init__(self, state_path: Path, *, model: Any = None, root: Path | None = None) -> None:
        self.state_path = Path(state_path)
        self.completion_path = self.state_path.with_name("first-run-complete")
        self.model = model if model is not None else build_model(root=root)
        self.answers: dict[str, str] = {}

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Resume. A state file that cannot be read starts the wizard over.

        Over, rather than refusing to run: the old implementation raised on an
        invalid state file, and a first-run service that raises at login is a
        machine with no first run and no way to reach one.
        """
        try:
            raw = self.state_path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(value, Mapping):
            return
        answers = value.get("answers")
        self.model.restore(
            step_id=str(value.get("currentStep", "")),
            answers=answers if isinstance(answers, Mapping) else {},
        )

    def save(self) -> None:
        document = {
            "schemaVersion": STATE_SCHEMA_VERSION,
            "currentStep": self.model.step.step_id,
            "completed": self.model.complete,
            "answers": self.model.answers,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".first-run-", dir=self.state_path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.state_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def finish(self) -> None:
        """Mark the wizard done, so the user unit's condition stops matching.

        The marker is a separate file from the state, because the unit's
        ``ConditionPathExists=!`` reads a path and must not have to parse
        anything to decide whether to run.
        """
        self.model.go_to("finish")
        self.model.advance()
        self.save()
        descriptor = os.open(
            self.completion_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, b"schemaVersion=2\ncompleted=true\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @property
    def complete(self) -> bool:
        return self.completion_path.exists()

    # -- movement ------------------------------------------------------------

    def next(self, *, skipped: bool = False) -> Any:
        if self.model.at_last:
            self.finish()
            return self.model.view()
        self.model.advance(skipped=skipped)
        self.save()
        return self.model.view()

    def back(self) -> Any:
        self.model.back()
        self.save()
        return self.model.view()

    def recheck(self) -> Any:
        step = self.model.step
        if step.survey:
            self.model.refresh(step.survey)
        return self.model.view()

    def view(self) -> Any:
        return self.model.view()


def run(state_path: Path, *, root: Path | None = None) -> int:  # pragma: no cover - needs a display
    """Open the first-run window. Returns the application's exit code."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
    except (ImportError, ValueError) as error:
        raise RuntimeError(f"GTK 4 is required for the first-run experience: {error}") from error

    session = AlphaFirstRun(state_path, root=root)
    session.load()

    class Window(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title="Welcome to Bunny OS")
            self.set_default_size(760, 560)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            for side in ("top", "bottom", "start", "end"):
                getattr(outer, f"set_margin_{side}")(28)

            self.progress = Gtk.Label(xalign=0.0)
            self.progress.add_css_class("dim-label")
            self.heading = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
            self.heading.add_css_class("title-1")
            self.body = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
            self.body.set_max_width_chars(72)

            self.thumbnail = Gtk.Picture()
            self.thumbnail.set_size_request(180, 180)
            self.thumbnail.set_visible(False)

            self.detail = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
            self.detail.set_max_width_chars(72)
            self.detail.add_css_class("dim-label")

            self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scroller = Gtk.ScrolledWindow(vexpand=True)
            scroller.set_child(self.rows)

            self.recheck = Gtk.Button(label="Check again")
            self.recheck.connect("clicked", self.on_recheck)
            self.back = Gtk.Button(label="Back")
            self.back.connect("clicked", self.on_back)
            self.skip = Gtk.Button()
            self.skip.connect("clicked", self.on_skip)
            self.next = Gtk.Button()
            self.next.add_css_class("suggested-action")
            self.next.connect("clicked", self.on_next)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            buttons.append(self.recheck)
            spacer = Gtk.Box(hexpand=True)
            buttons.append(spacer)
            buttons.append(self.back)
            buttons.append(self.skip)
            buttons.append(self.next)

            for widget in (self.progress, self.heading, self.body, self.thumbnail,
                           self.detail, scroller, buttons):
                outer.append(widget)
            self.set_child(outer)
            self.connect("close-request", self.on_close)
            self.render()

        # -- drawing -------------------------------------------------------

        def render(self):
            view = session.view()
            step = view.step
            self.progress.set_label(view.progress)
            self.heading.set_label(step.title)
            self.body.set_label(step.body)
            self.detail.set_label(view.detail)
            self.detail.set_visible(bool(view.detail))
            self.back.set_sensitive(not session.model.at_first)
            self.skip.set_visible(view.can_skip)
            if view.can_skip:
                self.skip.set_label(step.skip)
            self.next.set_label(step.action)
            self.recheck.set_visible(bool(step.survey))
            self._draw_rows(view)

        def _draw_rows(self, view):
            child = self.rows.get_first_child()
            while child is not None:
                following = child.get_next_sibling()
                self.rows.remove(child)
                child = following
            self.thumbnail.set_visible(False)
            survey = view.survey
            if survey is None:
                return
            for line in _survey_rows(view.step.step_id, survey):
                label = Gtk.Label(label=line, xalign=0.0, wrap=True, selectable=True)
                self.rows.append(label)
            thumbnail = getattr(survey, "thumbnail_path", "")
            if thumbnail and Path(thumbnail).is_file():
                try:
                    self.thumbnail.set_filename(thumbnail)
                    self.thumbnail.set_visible(True)
                except Exception:
                    self.thumbnail.set_visible(False)

        # -- actions -------------------------------------------------------

        def on_next(self, _button):
            if session.model.at_last:
                session.finish()
                self.close()
                return
            session.next()
            self.render()

        def on_skip(self, _button):
            session.next(skipped=True)
            self.render()

        def on_back(self, _button):
            session.back()
            self.render()

        def on_recheck(self, _button):
            session.recheck()
            self.render()

        def on_close(self, _window):
            session.save()
            return False

    application = Gtk.Application(application_id="art.comrade.BunnyFirstRun")
    application.connect("activate", lambda app: Window(app).present())
    return int(application.run(None))


def _survey_rows(step_id: str, survey: Any) -> tuple[str, ...]:
    """The per-machine detail each page shows under its copy.

    A function rather than a method on each survey: the surveys are shared with
    the diagnostics and the CLI, and a ``gtk_rows`` method on them would put a
    presentation decision inside a measurement.
    """
    if step_id in ("providers", "local_model"):
        rows = []
        for finding in getattr(survey, "findings", ()):
            state = {
                "eligible": "ready", "models-present": "running, models present",
                "running": "running, no models", "installed": "installed, not running",
                "absent": "not installed",
            }.get(finding.layer, finding.layer)
            rows.append(f"{finding.provider_id} — {state}")
            if finding.reason:
                rows.append(f"    {finding.reason}")
            if finding.remedy:
                rows.append(f"    {finding.remedy}")
        return tuple(rows) or ("No local provider adapters are configured.",)
    if step_id == "microphone":
        rows = [f"Microphones found: {len(getattr(survey, 'microphones', ()))}"]
        for device in getattr(survey, "microphones", ())[:8]:
            rows.append(f"    {device.description or device.name}{' (default)' if device.default else ''}")
        rows.append(
            f"Speech recognition: {'available' if getattr(survey, 'available', False) else 'unavailable'}"
        )
        if getattr(survey, "reason", ""):
            rows.append(f"    {survey.reason}")
        return tuple(rows)
    if step_id == "speaker":
        rows = [f"Output devices: {len(getattr(survey, 'outputs', ()))}"]
        for device in getattr(survey, "outputs", ())[:8]:
            rows.append(f"    {device.description or device.name}{' (default)' if device.default else ''}")
        rows.append(f"Local voice: {getattr(survey, 'voice_id', '') or 'none installed'}")
        return tuple(rows)
    if step_id == "character":
        rows = []
        if getattr(survey, "package_id", ""):
            rows.append(f"Character: {getattr(survey, 'package_name', '') or survey.package_id}")
        rows.append(getattr(survey, "description", ""))
        for reason in getattr(survey, "reasons", ())[:4]:
            rows.append(f"    {reason}")
        return tuple(row for row in rows if row)
    return ()
