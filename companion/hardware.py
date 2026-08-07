# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What this machine has, and — asked separately — what actually works on it.

§20's list is two lists wearing one hat, and the second half of the section says
so: record the hardware, and **do not use hardware facts alone to infer** that a
local model is installed, that the portal is operational, that a file-manager
service is activatable, that a speech model is installed, or that a URI handler
is usable. Probe operational capability separately.

That is not a stylistic preference. Each of those five has a configuration where
the hardware fact holds and the capability does not, and each of those
configurations is common:

======================  ================================================
32 GiB of RAM           and no weights anywhere on the disk
a Wayland session       and no ``xdg-desktop-portal`` running in it
a file manager package  whose D-Bus name nothing will activate
a working microphone    and no Vosk model
a browser installed     and no handler registered for ``https``
======================  ================================================

So this module has two halves and they do not talk to each other.
:func:`hardware_facts` reads ``/proc`` and ``/sys`` and reports what is there.
:func:`operational_probes` asks the things that answer. The record joins them,
and every probe carries the sentence that says what was asked and what replied.

Nothing here is expensive: the facts are file reads, and the probes delegate to
the surveys and adapters that already exist rather than opening a second
connection to anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import platform
import shutil
from typing import Any, Mapping, Sequence

__all__ = [
    "HardwareFacts",
    "OperationalProbe",
    "capability_record",
    "hardware_facts",
    "operational_probes",
]

_SYS = Path("/sys")
_PROC = Path("/proc")

#: PCI vendor ids worth naming. Anything else is reported by its raw id rather
#: than as "unknown", because the raw id is what a bug report needs.
_VENDORS = {
    "0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA",
    "0x1af4": "virtio", "0x1234": "QEMU", "0x15ad": "VMware", "0x1414": "Microsoft",
}


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in _read(_PROC / "meminfo").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * 1024
    return values


@dataclass(frozen=True)
class HardwareFacts:
    """What is present. No claim about whether any of it works."""

    architecture: str = "unknown"
    kernel: str = ""
    cpu_model: str = "unknown"
    cpu_count: int = 0
    memory_total_bytes: int = 0
    memory_available_bytes: int = 0
    gpus: tuple[Mapping[str, Any], ...] = ()
    dri_nodes: tuple[str, ...] = ()
    display_protocol: str = "none"
    display_server: str = ""
    audio_outputs: int = 0
    audio_inputs: int = 0
    sound_cards: tuple[str, ...] = ()
    battery_present: bool = False
    battery_percent: float | None = None
    on_battery: bool = False
    thermal_zones: tuple[Mapping[str, Any], ...] = ()
    network_interfaces: tuple[Mapping[str, str], ...] = ()
    virtualized: bool = False
    virtualization_detail: str = ""

    @property
    def has_dri(self) -> bool:
        return bool(self.dri_nodes)

    @property
    def network_up(self) -> bool:
        return any(
            item.get("operstate") == "up" and item.get("name") != "lo"
            for item in self.network_interfaces
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "kernel": self.kernel,
            "cpu": {"model": self.cpu_model, "count": self.cpu_count},
            "memory": {
                "totalBytes": self.memory_total_bytes,
                "availableBytes": self.memory_available_bytes,
            },
            "gpus": [dict(item) for item in self.gpus],
            "driNodes": list(self.dri_nodes),
            "hasDri": self.has_dri,
            "display": {"protocol": self.display_protocol, "server": self.display_server},
            "audio": {
                "outputs": self.audio_outputs,
                "inputs": self.audio_inputs,
                "soundCards": list(self.sound_cards),
            },
            "battery": {
                "present": self.battery_present,
                "percent": self.battery_percent,
                "onBattery": self.on_battery,
            },
            "thermalZones": [dict(item) for item in self.thermal_zones],
            "network": {
                "interfaces": [dict(item) for item in self.network_interfaces],
                "up": self.network_up,
            },
            "virtualized": self.virtualized,
            "virtualizationDetail": self.virtualization_detail,
        }


def _gpus() -> tuple[tuple[Mapping[str, Any], ...], tuple[str, ...]]:
    cards: list[Mapping[str, Any]] = []
    drm = _SYS / "class/drm"
    try:
        entries = sorted(drm.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.startswith("card") or "-" in entry.name:
            continue
        device = entry / "device"
        vendor = _read(device / "vendor")
        driver = ""
        try:
            driver = (device / "driver").resolve().name
        except OSError:
            driver = ""
        cards.append({
            "node": entry.name,
            "vendorId": vendor,
            "vendor": _VENDORS.get(vendor, vendor or "unknown"),
            "deviceId": _read(device / "device"),
            "driver": driver,
        })
    nodes: list[str] = []
    dri = Path("/dev/dri")
    try:
        nodes = sorted(item.name for item in dri.iterdir())
    except OSError:
        nodes = []
    return tuple(cards), tuple(nodes)


def _display() -> tuple[str, str]:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland", os.environ.get("XDG_CURRENT_DESKTOP", "")
    if os.environ.get("DISPLAY"):
        return "x11", os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "none", ""


def _sound() -> tuple[int, int, tuple[str, ...]]:
    """Counted from ``/proc/asound``, which needs no sound server to be running.

    Deliberately not from ``pactl``: this half of the module reports *hardware*,
    and a machine whose sound server is down still has the card. The server is
    asked in :func:`operational_probes`, where a failure means something.
    """
    cards: list[str] = []
    base = _PROC / "asound"
    try:
        for entry in sorted(base.iterdir()):
            if entry.name.startswith("card") and entry.name[4:].isdigit():
                cards.append(_read(entry / "id") or entry.name)
    except OSError:
        pass
    outputs = inputs = 0
    for line in _read(base / "pcm").splitlines():
        lowered = line.lower()
        if "playback" in lowered:
            outputs += 1
        if "capture" in lowered:
            inputs += 1
    return outputs, inputs, tuple(cards)


def _battery() -> tuple[bool, float | None, bool]:
    base = _SYS / "class/power_supply"
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return False, None, False
    percent: float | None = None
    present = False
    on_battery = False
    for entry in entries:
        kind = _read(entry / "type")
        if kind == "Battery":
            present = True
            capacity = _read(entry / "capacity")
            if capacity.isdigit():
                percent = float(capacity)
            if _read(entry / "status") == "Discharging":
                on_battery = True
        elif kind == "Mains" and _read(entry / "online") == "0":
            on_battery = True
    return present, percent, on_battery and present


def _thermal() -> tuple[Mapping[str, Any], ...]:
    zones: list[Mapping[str, Any]] = []
    base = _SYS / "class/thermal"
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return ()
    for entry in entries:
        if not entry.name.startswith("thermal_zone"):
            continue
        raw = _read(entry / "temp")
        celsius: float | None = None
        if raw.lstrip("-").isdigit():
            celsius = int(raw) / 1000.0
        zones.append({
            "zone": entry.name,
            "type": _read(entry / "type") or "unknown",
            "celsius": celsius,
        })
        if len(zones) >= 16:
            break
    return tuple(zones)


def _network() -> tuple[Mapping[str, str], ...]:
    interfaces: list[Mapping[str, str]] = []
    base = _SYS / "class/net"
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return ()
    for entry in entries:
        interfaces.append({
            "name": entry.name,
            "operstate": _read(entry / "operstate") or "unknown",
            "wireless": "yes" if (entry / "wireless").exists() or (entry / "phy80211").exists() else "no",
        })
        if len(interfaces) >= 32:
            break
    return tuple(interfaces)


def _virtualization() -> tuple[bool, str]:
    """``systemd-detect-virt``, and a hypervisor flag as the fallback.

    Worth recording because a VM boot is not a hardware boot, and §4 and §21
    both forbid presenting one as the other. A record that carries the answer
    makes the mistake visible instead of arguable.
    """
    detector = shutil.which("systemd-detect-virt")
    if detector:
        try:
            import subprocess

            result = subprocess.run(
                [detector], capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, Exception):  # pragma: no cover - defensive
            result = None
        if result is not None:
            value = result.stdout.strip()
            if value and value != "none":
                return True, value
            if value == "none":
                return False, "none"
    if "hypervisor" in _read(_PROC / "cpuinfo").lower():
        return True, "cpu hypervisor flag"
    return False, "not detected"


def hardware_facts() -> HardwareFacts:
    """Every §20 fact, read from the machine. Never raises."""
    memory = _meminfo()
    cpu_model = "unknown"
    for line in _read(_PROC / "cpuinfo").splitlines():
        if line.lower().startswith("model name") and ":" in line:
            cpu_model = line.split(":", 1)[1].strip()
            break
    gpus, nodes = _gpus()
    protocol, server = _display()
    outputs, inputs, cards = _sound()
    present, percent, on_battery = _battery()
    virtualized, virtualization_detail = _virtualization()
    machine = platform.machine().lower()
    return HardwareFacts(
        architecture={"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine or "unknown"),
        kernel=platform.release(),
        cpu_model=cpu_model or platform.processor() or "unknown",
        cpu_count=os.cpu_count() or 0,
        memory_total_bytes=memory.get("MemTotal", 0),
        memory_available_bytes=memory.get("MemAvailable", 0),
        gpus=gpus,
        dri_nodes=nodes,
        display_protocol=protocol,
        display_server=server,
        audio_outputs=outputs,
        audio_inputs=inputs,
        sound_cards=cards,
        battery_present=present,
        battery_percent=percent,
        on_battery=on_battery,
        thermal_zones=_thermal(),
        network_interfaces=_network(),
        virtualized=virtualized,
        virtualization_detail=virtualization_detail,
    )


@dataclass(frozen=True)
class OperationalProbe:
    """One capability, asked of the thing that provides it.

    ``inferred_from`` names the hardware fact a naive implementation would have
    used instead. It is carried so the record can be read as evidence that the
    inference was *not* made — an empty probe list with a full hardware list is
    exactly the shape §20 forbids.
    """

    capability: str
    available: bool
    detail: str
    inferred_from: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "available": self.available,
            "detail": self.detail,
            "wouldHaveBeenInferredFrom": self.inferred_from,
        }


#: The five §20 names the phase brief calls out, plus the two the companion
#: needs for its own start-up. Every entry has a probe function below and a
#: hardware fact it must not be inferred from.
_NEVER_INFER: Mapping[str, str] = {
    "local-model": "system memory and GPU presence",
    "portal": "a Wayland or X11 session being present",
    "file-manager": "a file manager package being installed",
    "speech-model": "a microphone being present",
    "uri-handler": "a browser being installed",
    "audio-output": "a sound card existing in /proc/asound",
    "three-d-renderer": "/dev/dri existing",
}


def operational_probes(
    *,
    facts: HardwareFacts | None = None,
    provider_survey: Any = None,
    speech_survey: Any = None,
    audio_survey: Any = None,
    desktop_report: Any = None,
    three_d: Any = None,
) -> tuple[OperationalProbe, ...]:
    """Ask each capability. Every argument is injectable so tests need no machine.

    ``None`` means "go and find out", and each discovery is guarded: a probe
    that raises produces an unavailable result with the exception as its detail,
    because a capability record that failed to be produced is worse than one
    that records a failure.
    """
    facts = facts or hardware_facts()
    probes: list[OperationalProbe] = []

    def add(capability: str, available: bool, detail: str) -> None:
        probes.append(OperationalProbe(
            capability=capability, available=bool(available), detail=detail,
            inferred_from=_NEVER_INFER.get(capability, ""),
        ))

    # -- local model ---------------------------------------------------------
    if provider_survey is None:
        try:
            from .onboarding.providers import survey_local_providers

            provider_survey = survey_local_providers()
        except Exception as error:
            provider_survey = None
            add("local-model", False, f"the provider survey did not run: {error}")
    if provider_survey is not None:
        add(
            "local-model", bool(getattr(provider_survey, "any_eligible", False)),
            getattr(provider_survey, "summary", "") or "surveyed",
        )

    # -- speech model --------------------------------------------------------
    if speech_survey is None:
        try:
            from .onboarding.speech import survey_speech

            speech_survey = survey_speech()
        except Exception as error:
            speech_survey = None
            add("speech-model", False, f"the speech survey did not run: {error}")
    if speech_survey is not None:
        add(
            "speech-model", bool(getattr(speech_survey, "model_present", False)),
            getattr(speech_survey, "reason", "") or "a recognition model is installed",
        )

    # -- audio output --------------------------------------------------------
    if audio_survey is None:
        try:
            from .onboarding.audio import survey_audio

            audio_survey = survey_audio()
        except Exception as error:
            audio_survey = None
            add("audio-output", False, f"the audio survey did not run: {error}")
    if audio_survey is not None:
        add(
            "audio-output", bool(getattr(audio_survey, "output_available", False)),
            getattr(audio_survey, "output_detail", "") or "enumerated",
        )

    # -- portal, file manager, URI handler -----------------------------------
    #
    # ``probe_environment`` takes the adapter set it is to ask. Calling it with
    # none raised ``missing 1 required positional argument``, the exception was
    # caught, and all three capabilities were reported unavailable with the
    # TypeError as their reason — on a machine where the portal was running.
    # Found on the first booted image, where the record said "the desktop
    # environment probe did not run" three times and read like a finding.
    adapters = None
    if desktop_report is None:
        try:
            from .desktop.environment import DesktopAdapters, probe_environment

            adapters = DesktopAdapters()
            desktop_report = probe_environment(adapters)
        except Exception as error:
            desktop_report = None
            for capability in ("portal", "file-manager", "uri-handler"):
                add(capability, False, f"the desktop environment probe did not run: {error}")
        finally:
            # Released here. The probe opens bus connections, and a capability
            # record that leaked one per call would show up in the §42 resource
            # deltas as a leak in whatever ran it.
            if adapters is not None:
                try:
                    adapters.close()
                except Exception:
                    pass
    if desktop_report is not None:
        for capability, action_id in (
            ("portal", "desktop.open_uri"),
            ("file-manager", "desktop.reveal_file"),
            ("uri-handler", "desktop.open_uri"),
        ):
            try:
                permitted = bool(desktop_report.permits(action_id))
                reason = str(desktop_report.reason(action_id) or "")
            except Exception as error:
                permitted, reason = False, str(error)
            add(capability, permitted, reason or f"{action_id} is available")

    # -- 3D renderer ---------------------------------------------------------
    if three_d is None:
        three_d = _three_d_probe(facts)
    add("three-d-renderer", bool(three_d[0]), str(three_d[1]))
    return tuple(probes)


def _three_d_probe(facts: HardwareFacts) -> tuple[bool, str]:
    """Can a graphics context be created? Asked of the driver, not of ``/dev/dri``.

    The reference host proves why: Fedora 44 under WSL2 has no ``/dev/dri`` at
    all and still creates an EGL surfaceless context on llvmpipe. Inferring from
    the device node would report no 3D on a machine that renders.
    """
    try:
        from .character.three_d.diagnostics import three_d_environment
    except Exception as error:
        return False, f"the 3D renderer is not importable: {error}"
    try:
        environment = three_d_environment()
    except Exception as error:
        return False, f"the 3D environment check failed: {error}"
    available = bool(environment.get("threeDAvailable"))
    reasons = "; ".join(str(item) for item in environment.get("reasons", ()) if item)
    if available and not facts.has_dri:
        reasons = (reasons + "; " if reasons else "") + (
            "no /dev/dri node exists, so a context here would be software-rasterised"
        )
    return available, reasons or "the 3D environment was described"


def capability_record(**kwargs: Any) -> dict[str, Any]:
    """The §20 record: the facts, the probes, and the rule that separates them."""
    facts = kwargs.pop("facts", None) or hardware_facts()
    probes = operational_probes(facts=facts, **kwargs)
    return {
        "schemaVersion": 1,
        "hardware": facts.to_json(),
        "operational": [probe.to_json() for probe in probes],
        "rule": (
            "Hardware facts and operational capability are measured separately. "
            "No entry under 'operational' is derived from an entry under 'hardware'."
        ),
    }
