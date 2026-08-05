# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Power source, battery state, thermal headroom and active cooling."""

from __future__ import annotations

from pathlib import Path

from ..model import Observation, PowerFacts, ThermalFacts, absent, measured, unknown
from .sources import Deadline, iter_directory, read_first_line, read_int, sanitize

__all__ = ["probe_power", "probe_thermal"]

_SUPPLY_ROOT = "/sys/class/power_supply"
_THERMAL_ROOT = "/sys/class/thermal"

#: Governors that mean the platform has already decided to trade performance
#: for energy. Bunny OS respects that decision rather than competing with it.
_SAVING_GOVERNORS = frozenset({"powersave", "conservative"})
_SAVING_PROFILES = frozenset({"low-power", "quiet", "power-saver"})


def probe_power(deadline: Deadline) -> PowerFacts:
    supplies = iter_directory(_SUPPLY_ROOT, limit=32)
    if not Path(_SUPPLY_ROOT).is_dir():
        return PowerFacts(
            supply=unknown(_SUPPLY_ROOT, "not present; this is normal on servers and in containers"),
            battery_present=unknown(_SUPPLY_ROOT),
            battery_percent=unknown(_SUPPLY_ROOT),
            power_saving=_power_saving(),
        )

    mains_online: bool | None = None
    battery_percent: int | None = None
    battery_status = ""
    battery_seen = False

    for entry in supplies:
        kind = (read_first_line(entry / "type") or "").strip()
        if kind == "Mains":
            online = read_int(entry / "online")
            if online is not None:
                mains_online = bool(online) if mains_online is None else (mains_online or bool(online))
        elif kind == "Battery":
            battery_seen = True
            if battery_percent is None:
                capacity = read_int(entry / "capacity")
                if capacity is not None and 0 <= capacity <= 100:
                    battery_percent = capacity
            if not battery_status:
                battery_status = sanitize(read_first_line(entry / "status") or "", limit=24)

    if mains_online is True:
        supply = measured("ac", _SUPPLY_ROOT, "a mains supply reports online")
    elif battery_seen and (mains_online is False or battery_status.lower() == "discharging"):
        supply = measured("battery", _SUPPLY_ROOT, f"battery status {battery_status.lower() or 'unknown'}")
    elif not supplies:
        # An empty power_supply class is a real observation: no battery, no
        # mains reporting. Desktops and servers look like this and it is not a
        # failure to detect anything.
        supply = absent(_SUPPLY_ROOT, "no power supplies are exposed; treated as permanently powered")
    else:
        supply = unknown(_SUPPLY_ROOT, "supplies present but neither mains state nor battery status was readable")

    return PowerFacts(
        supply=supply,
        battery_present=measured(battery_seen, _SUPPLY_ROOT),
        battery_percent=(
            measured(battery_percent, _SUPPLY_ROOT)
            if battery_percent is not None
            else (absent(_SUPPLY_ROOT, "no battery") if not battery_seen else unknown(_SUPPLY_ROOT, "battery present but capacity unreadable"))
        ),
        power_saving=_power_saving(),
    )


def _power_saving() -> Observation:
    profile = read_first_line("/sys/firmware/acpi/platform_profile")
    if profile:
        return measured(profile.strip().lower() in _SAVING_PROFILES, "acpi platform_profile", sanitize(profile, limit=24))
    governor = read_first_line("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if governor:
        return measured(governor.strip().lower() in _SAVING_GOVERNORS, "cpufreq scaling_governor", sanitize(governor, limit=24))
    return unknown("acpi/cpufreq", "neither a platform profile nor a cpufreq governor is exposed")


def probe_thermal(deadline: Deadline) -> ThermalFacts:
    zones = [entry for entry in iter_directory(_THERMAL_ROOT, limit=64) if entry.name.startswith("thermal_zone")]
    temperatures: list[int] = []
    for zone in zones:
        milli = read_int(zone / "temp")
        # Sensors that are unplugged or unread report implausible values rather
        # than failing to open. A reading outside this range is discarded rather
        # than allowed to become the reported maximum.
        if milli is not None and -40_000 < milli < 150_000:
            temperatures.append(milli)

    if temperatures:
        max_celsius = measured(round(max(temperatures) / 1000.0, 1), f"{_THERMAL_ROOT}/thermal_zone*/temp")
    elif zones:
        max_celsius = unknown(_THERMAL_ROOT, "thermal zones present but no plausible reading")
    else:
        max_celsius = absent(_THERMAL_ROOT, "no thermal zones are exposed")

    devices = [entry for entry in iter_directory(_THERMAL_ROOT, limit=64) if entry.name.startswith("cooling_device")]
    engaged: list[float] = []
    for device in devices:
        current = read_int(device / "cur_state")
        maximum = read_int(device / "max_state")
        if current is not None and maximum and maximum > 0 and current >= 0:
            engaged.append(min(1.0, current / maximum))

    if engaged:
        peak = max(engaged)
        cooling_state = measured(round(peak, 3), f"{_THERMAL_ROOT}/cooling_device*", "fraction of maximum cooling effort")
        # Any engaged cooling device means the platform is actively shedding
        # heat. That is the live signal; a temperature reading alone is not,
        # because the threshold at which a given board throttles is not exposed.
        throttled = measured(peak > 0.0, f"{_THERMAL_ROOT}/cooling_device*")
    elif devices:
        cooling_state = unknown(_THERMAL_ROOT, "cooling devices present but states unreadable")
        throttled = unknown(_THERMAL_ROOT)
    else:
        cooling_state = absent(_THERMAL_ROOT, "no cooling devices are exposed")
        throttled = absent(_THERMAL_ROOT, "no cooling devices to report throttling")

    return ThermalFacts(max_celsius=max_celsius, throttled=throttled, cooling_state=cooling_state)
