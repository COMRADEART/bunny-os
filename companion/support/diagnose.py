# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One screen that says what is wrong, and the four buttons that usually fix it.

§18's list is nine things to show and six things to do. The showing is the easy
half; what makes this a recovery surface rather than a status page is that it
runs when the runtime does not. Every reading below comes from systemd, the
filesystem or a survey — never from the companion protocol — because the
question being asked is often "why is there no companion to ask".

The four actions worth calling out, and why they are the four:

``restart``
    covers the largest class: a runtime that died and was not restarted because
    it had already burned its ``StartLimitBurst``.
``disable 3D for next launch``
    covers the second largest, and is the reason safe mode exists at all. A
    character package or a driver that crashes the renderer takes the window
    with it, and there is no way to reach a setting through a window that
    crashes.
``reset presentation``
    covers a machine stuck on a rung it should have left — a preference written
    during a bad session, a degradation that never lifted.
``start text-only``
    covers everything else, because a text-only companion needs no graphics, no
    audio and no character package, and a user who can reach one can read the
    diagnostics and export them.

Sanitised failures, and only sanitised ones: the journal lines pass through
:func:`companion.privacy.redact_diagnostic_text` on the way in, which is the same
redaction the runtime applies to its own fault records. §37 lists what must never
appear — keys, audio, clipboard contents, private query strings — and the honest
way to keep them out of a bundle is to keep them out of the reading that builds
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from ..privacy import redact_diagnostic_text
from . import companion_runtime_dir, companion_state_root
from .safemode import read_safe_mode

__all__ = [
    "COMPANION_UNITS",
    "RECOVERY_ACTIONS",
    "DiagnosticReport",
    "DiagnosticSection",
    "RecoveryAction",
    "diagnose",
    "unit_status",
]

#: The user units this phase's companion consists of, in dependency order.
COMPANION_UNITS: tuple[str, ...] = (
    "bunny-companion.service",
    "bunny-companion-window.service",
)

_ENV = {"PATH": "/usr/sbin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
_MAX_JOURNAL_LINES = 40


@dataclass(frozen=True)
class DiagnosticSection:
    """One row of the recovery screen: a name, a verdict, and the reason."""

    section_id: str
    title: str
    ok: bool
    detail: str
    #: Extra key/value rows shown under the section when it is expanded.
    facts: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "sectionId": self.section_id,
            "title": self.title,
            "ok": self.ok,
            "detail": self.detail,
            "facts": dict(self.facts),
        }


@dataclass(frozen=True)
class RecoveryAction:
    """Something the user can press, and exactly what it will do."""

    action_id: str
    label: str
    effect: str
    #: ``True`` when it changes something. A destructive action is never the
    #: default focus in the window.
    changes_state: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "actionId": self.action_id,
            "label": self.label,
            "effect": self.effect,
            "changesState": self.changes_state,
        }


RECOVERY_ACTIONS: tuple[RecoveryAction, ...] = (
    RecoveryAction(
        "restart", "Restart Bunny",
        "Stops and starts the companion runtime. Tasks that were running are recovered; "
        "nothing is deleted.",
    ),
    RecoveryAction(
        "disable-3d", "Disable 3D for the next start",
        "The next start uses the 2D character. Your selected character is not changed.",
    ),
    RecoveryAction(
        "reset-presentation", "Reset how Bunny appears",
        "Clears presentation preferences so the machine's own capability decides again. "
        "Your character choice, tasks and settings are untouched.",
    ),
    RecoveryAction(
        "safe-mode", "Start in Safe Mode",
        "The next start turns off 3D, the microphone, remote providers and desktop actions. "
        "Typed conversation and diagnostics still work.",
    ),
    RecoveryAction(
        "text-only", "Start text-only",
        "Starts a companion window with no character and no audio. Use this when the "
        "graphical character will not draw.",
    ),
    RecoveryAction(
        "export", "Export diagnostics",
        "Writes a file you can read before sending it to anyone. Nothing is uploaded.",
        changes_state=False,
    ),
)


def _systemctl(*arguments: str, timeout: float = 10.0) -> tuple[int, str]:
    binary = shutil.which("systemctl")
    if not binary:
        return 127, "systemctl is not available on this machine"
    try:
        result = subprocess.run(
            [binary, "--user", *arguments],
            env={**_ENV, **{k: v for k, v in os.environ.items() if k in (
                "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "HOME", "USER",
            )}},
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 126, redact_diagnostic_text(str(error))
    return result.returncode, (result.stdout or result.stderr or "").strip()


def unit_status(unit: str) -> dict[str, Any]:
    """``ActiveState``, ``SubState``, ``Result`` and the restart count.

    Four properties in one call rather than four ``is-active`` invocations: the
    restart count is the one that distinguishes "not running" from "restarting
    for the fourth time", and §12 makes that distinction load-bearing.
    """
    code, output = _systemctl(
        "show", unit, "--property=ActiveState", "--property=SubState",
        "--property=Result", "--property=NRestarts", "--property=LoadState",
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip()
    restarts = values.get("NRestarts", "0")
    return {
        "unit": unit,
        "queried": code == 0,
        "loadState": values.get("LoadState", "unknown"),
        "activeState": values.get("ActiveState", "unknown"),
        "subState": values.get("SubState", "unknown"),
        "result": values.get("Result", "unknown"),
        "restarts": int(restarts) if restarts.isdigit() else 0,
        "detail": "" if code == 0 else redact_diagnostic_text(output),
    }


def recent_failures(unit: str = "bunny-companion.service", *, lines: int = _MAX_JOURNAL_LINES) -> tuple[str, ...]:
    """Recent journal lines at priority warning or above, redacted and bounded.

    Priority-filtered rather than tail-of-everything: a bundle full of routine
    start-up chatter buries the one line that matters, and every line included
    is a line that had to be read for secrets.
    """
    binary = shutil.which("journalctl")
    if not binary:
        return ("journalctl is not available on this machine",)
    try:
        result = subprocess.run(
            [binary, "--user", "-u", unit, "-p", "warning", "-n", str(max(1, min(lines, 200))),
             "--no-pager", "-o", "cat"],
            env={**_ENV, **{k: v for k, v in os.environ.items() if k in (
                "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "HOME", "USER",
            )}},
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return (redact_diagnostic_text(f"the journal could not be read: {error}"),)
    if result.returncode != 0:
        return (redact_diagnostic_text(result.stderr or f"journalctl exited {result.returncode}"),)
    return tuple(
        redact_diagnostic_text(line) for line in result.stdout.splitlines()[-lines:] if line.strip()
    )


@dataclass(frozen=True)
class DiagnosticReport:
    """Everything §18 asks to be shown, plus what may be pressed."""

    sections: tuple[DiagnosticSection, ...] = ()
    actions: tuple[RecoveryAction, ...] = RECOVERY_ACTIONS
    failures: tuple[str, ...] = ()
    identity: Mapping[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return all(section.ok for section in self.sections)

    @property
    def summary(self) -> str:
        broken = [section.title for section in self.sections if not section.ok]
        if not broken:
            return "Bunny is healthy. Everything this page checks is working."
        if len(broken) == 1:
            return f"One thing is not working: {broken[0]}."
        return f"{len(broken)} things are not working: {', '.join(broken)}."

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "healthy": self.healthy,
            "summary": self.summary,
            "identity": dict(self.identity),
            "sections": [section.to_json() for section in self.sections],
            "actions": [action.to_json() for action in self.actions],
            "recentFailures": list(self.failures),
            "secretsIncluded": False,
        }

    def lines(self) -> tuple[str, ...]:
        """The report as text, for the CLI and for a screen reader."""
        rows = [self.summary, ""]
        for section in self.sections:
            rows.append(f"[{'ok' if section.ok else '!!'}] {section.title}: {section.detail}")
        if self.failures:
            rows.extend(["", "Recent problems (redacted):"])
            rows.extend(f"  {line}" for line in self.failures)
        return tuple(rows)


def diagnose(
    *,
    root: Path | None = None,
    provider_survey: Any = None,
    speech_survey: Any = None,
    audio_survey: Any = None,
    desktop_report: Any = None,
    units: Sequence[str] = COMPANION_UNITS,
    include_failures: bool = True,
) -> DiagnosticReport:
    """Build the recovery report. Every reading is guarded; this never raises.

    That guarantee is the whole contract. A diagnostic that can fail is a
    diagnostic that is unavailable precisely on the machines that need it.
    """
    root = root or companion_state_root()
    sections: list[DiagnosticSection] = []

    # -- the units -----------------------------------------------------------
    for unit in units:
        status = unit_status(unit)
        active = status["activeState"] == "active"
        missing = status["loadState"] in ("not-found", "masked")
        detail = (
            f"{status['activeState']}/{status['subState']}"
            + (f", {status['restarts']} restarts" if status["restarts"] else "")
            + (f", result {status['result']}" if status["result"] not in ("success", "unknown") else "")
        )
        if missing:
            detail = f"the unit is {status['loadState']}"
        sections.append(DiagnosticSection(
            section_id=f"unit:{unit}", title=unit, ok=active, detail=detail, facts=status,
        ))

    # -- the socket ----------------------------------------------------------
    socket_dir = companion_runtime_dir()
    socket = socket_dir / "runtime.sock"
    candidates = []
    try:
        candidates = [item.name for item in socket_dir.iterdir()]
    except OSError:
        candidates = []
    has_socket = socket.exists() or any(name.endswith(".sock") for name in candidates)
    sections.append(DiagnosticSection(
        "socket", "Runtime socket", has_socket,
        f"{socket_dir} contains {', '.join(candidates) or 'nothing'}",
        {"path": str(socket_dir), "entries": candidates},
    ))

    # -- the store -----------------------------------------------------------
    store_ok = root.is_dir()
    sections.append(DiagnosticSection(
        "store", "Task store", store_ok,
        f"{root} exists" if store_ok else f"{root} does not exist",
        {"path": str(root)},
    ))

    # -- safe mode -----------------------------------------------------------
    safe = read_safe_mode(root)
    sections.append(DiagnosticSection(
        "safe-mode", "Safe mode",
        # Safe mode being on is not a fault; it is a state. It is reported ok so
        # that a user in safe mode does not read this page as "something else is
        # also broken".
        True,
        safe.lines()[0], safe.to_json(),
    ))

    # -- presentation and renderer -------------------------------------------
    sections.append(_renderer_section())
    sections.append(_character_section(root))

    # -- providers, audio, microphone, speech --------------------------------
    sections.append(_provider_section(provider_survey))
    audio_section, speech_section, microphone_section = _audio_sections(audio_survey, speech_survey)
    sections.extend((audio_section, microphone_section, speech_section))

    # -- desktop actions -----------------------------------------------------
    sections.append(_desktop_section(desktop_report))

    failures: tuple[str, ...] = ()
    if include_failures:
        try:
            failures = recent_failures()
        except Exception as error:  # pragma: no cover - defensive
            failures = (redact_diagnostic_text(str(error)),)

    identity: Mapping[str, Any] = {}
    try:
        from ..identity import build_identity

        identity = build_identity().to_json()
    except Exception:
        identity = {}
    return DiagnosticReport(sections=tuple(sections), failures=failures, identity=identity)


def _renderer_section() -> DiagnosticSection:
    try:
        from ..character.three_d.diagnostics import three_d_environment

        environment = three_d_environment()
    except Exception as error:
        return DiagnosticSection(
            "renderer", "3D renderer", False,
            redact_diagnostic_text(f"the 3D environment could not be described: {error}"),
        )
    available = bool(environment.get("threeDAvailable"))
    return DiagnosticSection(
        "renderer", "3D renderer", True,
        (
            "available" if available else "not available"
        ) + ": " + "; ".join(str(item) for item in environment.get("reasons", ()) if item),
        environment,
    )


def _character_section(root: Path) -> DiagnosticSection:
    try:
        from ..character.defaults import default_character_paths
        from ..character.importer import PackageRegistry
        from ..character.policy import read_policy_state

        registry = PackageRegistry(root / "characters", built_in_paths=default_character_paths())
        selected = registry.selected()
        state = read_policy_state(registry)
    except Exception as error:
        return DiagnosticSection(
            "character", "Selected character", False,
            redact_diagnostic_text(f"the character registry could not be read: {error}"),
        )
    if selected is None:
        return DiagnosticSection(
            "character", "Selected character", False,
            "no character package is installed; Bunny uses the text-only presentation",
        )
    return DiagnosticSection(
        "character", "Selected character", True,
        f"{selected.package_id} {selected.package_version}",
        {
            "packageId": selected.package_id,
            "packageVersion": selected.package_version,
            "packageDigest": selected.package_digest,
            "trustState": getattr(selected.trust_state, "value", str(selected.trust_state)),
            "chosenBy": "policy" if state.applied_digest == selected.package_digest else "user",
        },
    )


def _provider_section(survey: Any) -> DiagnosticSection:
    if survey is None:
        try:
            from ..onboarding.providers import survey_local_providers

            survey = survey_local_providers()
        except Exception as error:
            return DiagnosticSection(
                "providers", "AI providers", False,
                redact_diagnostic_text(f"the provider survey did not run: {error}"),
            )
    return DiagnosticSection(
        "providers", "AI providers",
        # No eligible provider is not a fault of Bunny's — §32 requires the
        # no-model machine to be a supported configuration — so this is reported
        # ok, with the summary saying plainly that nothing is eligible.
        True, survey.summary, survey.to_json(),
    )


def _audio_sections(audio: Any, speech: Any) -> tuple[DiagnosticSection, DiagnosticSection, DiagnosticSection]:
    if audio is None:
        try:
            from ..onboarding.audio import survey_audio

            audio = survey_audio()
        except Exception as error:
            audio = None
            audio_section = DiagnosticSection(
                "audio", "Audio output", False,
                redact_diagnostic_text(f"the audio survey did not run: {error}"),
            )
    if audio is not None:
        audio_section = DiagnosticSection(
            "audio", "Audio output", True, audio.summary, audio.to_json(),
        )
    if speech is None:
        try:
            from ..onboarding.speech import survey_speech

            speech = survey_speech()
        except Exception as error:
            speech = None
            microphone = DiagnosticSection(
                "microphone", "Microphone", False,
                redact_diagnostic_text(f"the speech survey did not run: {error}"),
            )
            recognizer = DiagnosticSection(
                "speech", "Speech recognition", False,
                redact_diagnostic_text(f"the speech survey did not run: {error}"),
            )
    if speech is not None:
        microphone = DiagnosticSection(
            "microphone", "Microphone", True,
            f"{len(speech.microphones)} device(s): {speech.capture_detail}",
            {"devices": [device.to_json() for device in speech.microphones]},
        )
        recognizer = DiagnosticSection(
            "speech", "Speech recognition", True,
            speech.remedy, speech.to_json(),
        )
    return audio_section, recognizer, microphone


def _desktop_section(report: Any) -> DiagnosticSection:
    adapters = None
    if report is None:
        # Owned and released here. The probe opens D-Bus connections and helper
        # processes; a diagnostic that left them behind would show up in the
        # very resource-delta measurement §42 uses to decide whether the
        # companion leaks.
        try:
            from ..desktop.environment import DesktopAdapters, probe_environment

            adapters = DesktopAdapters()
            report = probe_environment(adapters)
        except Exception as error:
            return DiagnosticSection(
                "desktop-actions", "Desktop actions", False,
                redact_diagnostic_text(f"the desktop environment probe did not run: {error}"),
            )
        finally:
            if adapters is not None:
                try:
                    adapters.close()
                except Exception:
                    pass
    try:
        value = report.to_json()
    except Exception as error:
        return DiagnosticSection(
            "desktop-actions", "Desktop actions", False, redact_diagnostic_text(str(error)),
        )
    posture = str(value.get("posture", "unknown"))
    available = value.get("available", []) or []
    return DiagnosticSection(
        "desktop-actions", "Desktop actions", True,
        f"{posture}: {len(available)} action(s) available", value,
    )
