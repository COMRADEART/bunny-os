#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline journal analysis for one dsq-1 boot.

The installed journal is the authoritative service record (the guest ships
no credentials, so live ``systemctl`` queries are impossible by design and
serial output alone was already shown to misname units). This module reads
an extracted journal directory with ``journalctl -D`` and produces the
Stage 3 per-boot record: per-unit event histories, the nine-way disposition
the collector must distinguish, timeline milestones, and excerpts.

Two lessons from the prior pass are enforced here:

* A transient D-Bus activation unit is canonicalised: the per-boot
  connection ID in ``dbus-:1.2-org.gnome.Shell.Screencast@0.service`` never
  becomes part of a unit's identity, and the raw name is preserved.
* An empty failed-unit list is only ever produced by a successful query
  over a complete journal. Any extraction or parse failure yields
  ``None`` fields plus a recorded error, never silence.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

#: v2: user-manager unit events are read from USER_UNIT (v1 read UNIT only
#: and silently missed every user unit — the exact class of collector
#: defect this pass exists to catch); failures are phase-classified
#: against the recorded shutdown initiation so a teardown exit race can
#: never be reported as a boot failure, nor a boot failure hidden by one.
FAILED_UNIT_COLLECTOR_VERSION = "dsq-failed-units-2"

#: Canonicalisation of transient D-Bus activation units: the connection ID
#: (":1.2") varies per boot and must not create a new unit identity.
TRANSIENT_DBUS_RE = re.compile(
    r"^dbus-:\d+\.\d+-(?P<name>[A-Za-z0-9._]+)@(?P<instance>\d+)\.service$")

MAIN_EXIT_RE = re.compile(
    r"Main process exited, code=(?P<code>[a-z-]+), status=(?P<status>[0-9A-Z/]+)")
RESTART_COUNTER_RE = re.compile(r"restart counter is at (?P<count>\d+)")
SKIPPED_RE = re.compile(r"was skipped because (?P<why>.+?)\.?$")

KERNEL_GFX_RE = re.compile(
    r"(drm|virtio[-_]gpu|framebuffer|simpledrm|vgaarb)", re.IGNORECASE)
KERNEL_GFX_BAD_RE = re.compile(
    r"(error|fail|timeout|unable|refused|invalid)", re.IGNORECASE)


class JournalError(RuntimeError):
    pass


def _journalctl(journal_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["journalctl", "-D", str(journal_dir), "--no-pager", *args],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise JournalError(
            f"journalctl {' '.join(args)}: {result.stderr.strip()[:400]}")
    return result.stdout


def list_boots(journal_dir: Path) -> list[dict]:
    out = _journalctl(journal_dir, "--list-boots", "-o", "json")
    boots = json.loads(out)
    if not isinstance(boots, list) or not boots:
        raise JournalError("journal contains no boots")
    return boots


def canonical_unit(raw: str) -> tuple[str, str | None]:
    """Return (canonical identity, dbus connection id or None)."""
    match = TRANSIENT_DBUS_RE.match(raw)
    if match:
        conn = raw.split("-", 1)[1].split("-", 1)[0]
        return (f"dbus-:*-{match.group('name')}@{match.group('instance')}"
                ".service", conn)
    return raw, None


def analyze_boot(journal_dir: Path, boot_id: str) -> dict[str, Any]:
    """Produce the full Stage 3 analysis for one boot ID."""
    raw = _journalctl(journal_dir, "-b", boot_id, "-o", "json")
    entries = []
    parse_errors = 0
    for line in raw.splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            parse_errors += 1
    if not entries:
        raise JournalError(f"boot {boot_id}: no journal entries")

    def ts(entry: dict) -> float | None:
        value = entry.get("__REALTIME_TIMESTAMP")
        return int(value) / 1e6 if value else None

    def mono(entry: dict) -> float | None:
        value = entry.get("__MONOTONIC_TIMESTAMP")
        return int(value) / 1e6 if value else None

    def msg(entry: dict) -> str:
        message = entry.get("MESSAGE", "")
        if isinstance(message, list):  # binary-safe journal export
            try:
                message = bytes(message).decode("utf-8", "replace")
            except (TypeError, ValueError):
                message = repr(message)
        return message

    # ---------------------------------------------------------- unit events
    # PID 1 speaks about system units with a UNIT field; each user manager
    # (uid != 0, _COMM=systemd) speaks about its user units the same way.
    system_units: dict[str, dict] = {}
    user_units: dict[tuple[str, str], dict] = {}
    sessions_by_uid: dict[str, list[str]] = {}
    shutdown_initiated: float | None = None
    seat0_at: float | None = None
    graphical_at: float | None = None
    health_check_at: float | None = None
    coredumps: list[dict] = []
    kernel_gfx_errors: list[str] = []
    timeline: dict[str, float | None] = {}
    dependency_failures: list[dict] = []

    def unit_state(store: dict, key, raw_name: str) -> dict:
        if key not in store:
            store[key] = {
                "rawNames": [], "events": [], "failures": 0,
                "started": 0, "starting": 0, "finalEvent": None,
                "mainExit": None, "restartCounterMax": 0,
                "skipped": [], "result": None,
                "activeEnterMono": None, "inactiveEnterMono": None,
            }
        if raw_name not in store[key]["rawNames"]:
            store[key]["rawNames"].append(raw_name)
        return store[key]

    def note_unit_event(store: dict, key, raw_name: str, kind: str,
                        entry: dict, detail: str | None = None) -> None:
        state = unit_state(store, key, raw_name)
        state["events"].append(
            {"kind": kind, "monotonic": mono(entry), "detail": detail})
        state["finalEvent"] = kind
        if kind == "started":
            state["started"] += 1
            state["activeEnterMono"] = mono(entry)
        elif kind == "starting":
            state["starting"] += 1
        elif kind == "failed":
            state["failures"] += 1
            state["inactiveEnterMono"] = mono(entry)
            if detail:
                state["result"] = detail
        elif kind == "stopped":
            state["inactiveEnterMono"] = mono(entry)

    for entry in entries:
        message = msg(entry)
        uid = entry.get("_UID")
        pid = entry.get("_PID")
        comm = entry.get("_COMM", "")
        unit_field = entry.get("UNIT")
        user_unit_field = entry.get("USER_UNIT")

        # kernel graphics problems
        if entry.get("_TRANSPORT") == "kernel":
            if KERNEL_GFX_RE.search(message) and KERNEL_GFX_BAD_RE.search(message):
                kernel_gfx_errors.append(message)
            if "Linux version" in message and "kernelStart" not in timeline:
                timeline["kernelStart"] = mono(entry)
            if re.search(r"\[drm\].*(Initialized|feature)", message) \
                    and "graphicsDeviceReady" not in timeline:
                timeline["graphicsDeviceReady"] = mono(entry)
            continue

        is_system_manager = pid == "1" and comm == "systemd"
        is_user_manager = pid != "1" and comm == "systemd" and uid not in (None, "0")

        target_store = None
        target_key: Any = None
        raw_name = None
        if is_system_manager and unit_field:
            target_store, raw_name = system_units, unit_field
            target_key, _conn = canonical_unit(unit_field)
        elif is_user_manager and (user_unit_field or unit_field):
            # a user manager names its units in USER_UNIT; UNIT is only a
            # fallback for entries that carry no USER_UNIT at all
            raw_name = user_unit_field or unit_field
            target_store = user_units
            canon, _conn = canonical_unit(raw_name)
            target_key = (uid, canon)

        if target_store is not None:
            if message.startswith("Starting "):
                note_unit_event(target_store, target_key, raw_name, "starting", entry)
            elif message.startswith(("Started ", "Reached target ", "Mounted ",
                                     "Listening on ", "Finished ")):
                note_unit_event(target_store, target_key, raw_name, "started", entry)
            elif ": Failed with result" in message:
                result = message.split("Failed with result", 1)[1].strip(" '.")
                note_unit_event(target_store, target_key, raw_name, "failed",
                                entry, result)
            elif message.startswith(("Stopped ", "Stopping ")):
                note_unit_event(target_store, target_key, raw_name, "stopped", entry)
            elif "Main process exited" in message:
                match = MAIN_EXIT_RE.search(message)
                if match:
                    unit_state(target_store, target_key, raw_name)["mainExit"] = {
                        "code": match.group("code"),
                        "status": match.group("status")}
            elif "Scheduled restart job" in message:
                match = RESTART_COUNTER_RE.search(message)
                state = unit_state(target_store, target_key, raw_name)
                if match:
                    state["restartCounterMax"] = max(
                        state["restartCounterMax"], int(match.group("count")))
                state["events"].append({"kind": "restart-scheduled",
                                        "monotonic": mono(entry),
                                        "detail": message[-120:]})
            elif "was skipped because" in message:
                match = SKIPPED_RE.search(message)
                unit_state(target_store, target_key, raw_name)["skipped"].append(
                    match.group("why") if match else message[-160:])
            if message.startswith("Dependency failed for"):
                dependency_failures.append(
                    {"unit": raw_name, "scope": "system" if
                     target_store is system_units else f"user-{uid}",
                     "monotonic": mono(entry)})

        # milestones
        if is_system_manager:
            if message.startswith("Reached target") and unit_field == "graphical.target":
                graphical_at = mono(entry)
                timeline["graphicalTarget"] = graphical_at
            elif unit_field == "multi-user.target" and message.startswith("Reached target"):
                timeline["multiUserTarget"] = mono(entry)
            elif unit_field == "dbus-broker.service" and message.startswith("Started"):
                timeline["dbusReady"] = mono(entry)
            elif unit_field == "systemd-logind.service" and message.startswith("Started"):
                timeline["logindReady"] = mono(entry)
            elif unit_field == "NetworkManager.service" and message.startswith("Started"):
                timeline["networkManagerReady"] = mono(entry)
            elif unit_field == "gdm.service":
                if message.startswith("Starting"):
                    timeline["gdmStartRequested"] = mono(entry)
                elif message.startswith("Started"):
                    timeline["gdmActive"] = mono(entry)
            elif unit_field == "avahi-daemon.service" and message.startswith("Starting"):
                timeline["avahiActivation"] = mono(entry)
            elif unit_field == "bunny-health-check.service" \
                    and message.startswith("Finished"):
                health_check_at = mono(entry)
                timeline["healthCheck"] = health_check_at
            elif unit_field == "authselect-apply-changes.service":
                if message.startswith("Starting"):
                    timeline["authselectApplyStart"] = mono(entry)
                elif message.startswith("Finished"):
                    timeline["authselectApplyEnd"] = mono(entry)
            elif unit_field == "chronyd.service":
                # dsq-2: the chronyd ordering correction is an assertion about
                # two timestamps, so both have to exist as timestamps. The
                # dsq-1 analysis recorded the authselect window but nothing
                # about chronyd, which is why the ordering could only be
                # argued from the absence of a failure rather than measured.
                #
                # First-wins on the request: a restart after the window would
                # otherwise overwrite the spawn that the race is about.
                if message.startswith("Starting"):
                    timeline.setdefault("chronydStartRequested", mono(entry))
                elif message.startswith("Started"):
                    timeline.setdefault("chronydActive", mono(entry))
            elif unit_field == "nss-user-lookup.target" and \
                    message.startswith("Reached target"):
                timeline.setdefault("nssUserLookupReached", mono(entry))
            elif unit_field in ("poweroff.target", "shutdown.target") and \
                    message.startswith(("Reached target", "Starting")):
                if shutdown_initiated is None:
                    shutdown_initiated = mono(entry)
            if "systemdStart" not in timeline and comm == "systemd" and \
                    "running in system mode" in message:
                timeline["systemdStart"] = mono(entry)
        if comm == "systemd-logind":
            if message.startswith("Power key pressed") and \
                    shutdown_initiated is None:
                shutdown_initiated = mono(entry)
            if message == "New seat seat0.":
                seat0_at = mono(entry)
                timeline["seat0Created"] = seat0_at
            session_match = re.match(
                r"New session (\S+) of user (\S+)\.", message)
            if session_match:
                sessions_by_uid.setdefault(
                    entry.get("SESSION_UID", ""), []).append(session_match.group(1))
        if comm == "(sd-pam)" or (comm == "systemd" and is_user_manager):
            pass
        if "pam_unix(gdm-launch-environment:session): session opened" in message:
            timeline["greeterSessionOpened"] = mono(entry)
        if "pam_systemd" in message:
            pass
        if entry.get("MESSAGE_ID") == "fc2e22bc6ee647b6b90729ab34a250b1":
            coredumps.append({
                "monotonic": mono(entry),
                "process": entry.get("COREDUMP_COMM"),
                "uid": entry.get("COREDUMP_UID"),
                "signal": entry.get("COREDUMP_SIGNAL_NAME"),
                "message": message[:200]})
        # user sessions from pam
        pam_match = re.search(
            r"session opened for user ([A-Za-z0-9._-]+)\(uid=(\d+)\)", message)
        if pam_match:
            sessions_by_uid.setdefault(pam_match.group(2), []).append(
                f"pam:{pam_match.group(1)}")
        if "PipeWire" in message or comm == "pipewire":
            timeline.setdefault("pipewireFirstSeen", mono(entry))

    # -------------------------------------------------------- dispositions
    def failure_phases(state: dict) -> tuple[int, int]:
        """(boot-phase failures, shutdown-phase failures)."""
        boot_phase = shutdown_phase = 0
        for event in state["events"]:
            if event["kind"] != "failed":
                continue
            when = event["monotonic"] or 0
            if shutdown_initiated is not None and when >= shutdown_initiated:
                shutdown_phase += 1
            else:
                boot_phase += 1
        return boot_phase, shutdown_phase

    def dispose(state: dict, scope: str, uid: str | None) -> str:
        if state["failures"] > 0:
            boot_phase, shutdown_phase = failure_phases(state)
            last_failure = max(
                (e["monotonic"] or 0) for e in state["events"]
                if e["kind"] == "failed")
            recovered_after = any(
                e["kind"] == "started" and (e["monotonic"] or 0) > last_failure
                for e in state["events"])
            if recovered_after:
                return "failed-transiently-and-recovered"
            if boot_phase == 0 and shutdown_phase > 0:
                # every failure of this unit happened at or after the
                # recorded shutdown initiation: a teardown result, kept
                # distinct so it can neither masquerade as a boot failure
                # nor be silently excused
                return "failed-during-shutdown"
            return "currently-failed"
        if state["skipped"] and state["started"] == 0:
            return "skipped-by-condition"
        if state["started"] > 0 or state["starting"] > 0:
            return "activated-and-succeeded"
        return "inactive-no-activation-observed"

    def render(store: dict, scope: str) -> list[dict]:
        rendered = []
        for key, state in sorted(store.items(), key=lambda kv: str(kv[0])):
            uid = key[0] if scope == "user" else None
            unit_name = key[1] if scope == "user" else key
            boot_phase, shutdown_phase = failure_phases(state)
            rendered.append({
                "unit": unit_name,
                "scope": scope,
                "uid": uid,
                "uidHadSession": (uid in sessions_by_uid) if uid else None,
                "rawNames": state["rawNames"],
                "disposition": dispose(state, scope, uid),
                "failures": state["failures"],
                "failuresDuringBoot": boot_phase,
                "failuresDuringShutdown": shutdown_phase,
                "started": state["started"],
                "result": state["result"],
                "mainExit": state["mainExit"],
                "restartCounterMax": state["restartCounterMax"],
                "skipped": state["skipped"],
                "activeEnterMono": state["activeEnterMono"],
                "inactiveEnterMono": state["inactiveEnterMono"],
                "events": state["events"],
            })
        return rendered

    system_rendered = render(system_units, "system")
    user_rendered = render(user_units, "user")

    failed_system = [u for u in system_rendered
                     if u["disposition"] == "currently-failed"]
    shutdown_failed_system = [u for u in system_rendered
                              if u["disposition"] == "failed-during-shutdown"]
    recovered_system = [u for u in system_rendered
                        if u["disposition"] == "failed-transiently-and-recovered"]
    failed_user = [u for u in user_rendered
                   if u["disposition"] == "currently-failed"]
    shutdown_failed_user = [u for u in user_rendered
                            if u["disposition"] == "failed-during-shutdown"]

    return {
        "failedUnitCollectorVersion": FAILED_UNIT_COLLECTOR_VERSION,
        "bootId": boot_id,
        "entryCount": len(entries),
        "parseErrors": parse_errors,
        "wallClock": {"first": ts(entries[0]), "last": ts(entries[-1])},
        "graphicalTargetReachedMono": graphical_at,
        "shutdownInitiatedMono": shutdown_initiated,
        "seat0CreatedMono": seat0_at,
        "healthCheckFinishedMono": health_check_at,
        "timeline": timeline,
        "sessionsByUid": sessions_by_uid,
        "systemUnits": system_rendered,
        "userUnits": user_rendered,
        "failedSystemUnits": sorted(u["unit"] for u in failed_system),
        "shutdownFailedSystemUnits": sorted(
            u["unit"] for u in shutdown_failed_system),
        "recoveredSystemUnits": sorted(u["unit"] for u in recovered_system),
        "failedUserUnits": sorted(
            f"uid={u['uid']}:{u['unit']}" for u in failed_user),
        "shutdownFailedUserUnits": sorted(
            f"uid={u['uid']}:{u['unit']}" for u in shutdown_failed_user),
        "dependencyFailures": dependency_failures,
        "coredumps": coredumps,
        "kernelGraphicsErrors": kernel_gfx_errors[:50],
        "gdm": _gdm_assertions(system_units, timeline, coredumps, entries,
                               msg, mono, shutdown_initiated, failure_phases),
        "firstLogin": _first_login_assertions(user_rendered, sessions_by_uid),
        "chronydOrdering": _chronyd_ordering(system_units, timeline),
    }


def _gdm_assertions(system_units: dict, timeline: dict, coredumps: list,
                    entries: list, msg, mono,
                    shutdown_initiated: float | None,
                    failure_phases) -> dict:
    """Stage 7 readiness assertions, judged from the installed journal.

    Failures and fatal errors are phase-split: a greeter that ran cleanly
    through the whole observation window and stumbled only while being torn
    down is a different finding from one that never came up — and the
    difference must survive into the record, not be reconstructed later."""
    gdm = system_units.get("gdm.service")
    boot_failures = shutdown_failures = 0
    if gdm:
        boot_failures, shutdown_failures = failure_phases(gdm)
    greeter_opened = timeline.get("greeterSessionOpened")
    session_never_registered = None
    fatal_display_errors = []
    for entry in entries:
        message = msg(entry)
        when = mono(entry)
        during_shutdown = (shutdown_initiated is not None and
                           when is not None and when >= shutdown_initiated)
        if "Session never registered, failing" in message \
                and not during_shutdown:
            session_never_registered = when
        if not during_shutdown and re.search(
                r"(gnome-shell|mutter|Xorg|Xwayland).*"
                r"(Fatal|fatal|Failed to open display|"
                r"could not create.*display)", message):
            fatal_display_errors.append(message[:200])
    gdm_coredump = [c for c in coredumps
                    if (c.get("process") or "").startswith(("gdm", "gnome-shell"))]
    return {
        "gdmReachedActive": bool(gdm and gdm["started"] > 0),
        "gdmFailures": gdm["failures"] if gdm else None,
        "gdmBootPhaseFailures": boot_failures if gdm else None,
        "gdmShutdownPhaseFailures": shutdown_failures if gdm else None,
        "gdmRestartCounterMax": gdm["restartCounterMax"] if gdm else None,
        "greeterSessionOpenedMono": greeter_opened,
        "sessionNeverRegisteredMono": session_never_registered,
        "fatalDisplayErrors": fatal_display_errors[:20],
        "gdmCoredumps": gdm_coredump,
    }


#: Uids and account names that are part of the display stack rather than a
#: person logging in. A first login must be none of these.
INFRASTRUCTURE_ACCOUNTS = ("gdm", "gnome-initial-setup")

FIRST_LOGIN_UNITS = ("bunny-config-dir.service", "bunny-first-boot.service")


def _first_login_assertions(user_rendered: list[dict],
                            sessions_by_uid: dict) -> dict:
    """dsq-2 — what the first-login units did, per logged-in uid.

    Read from userUnits, which is built from USER_UNIT. A system-journal
    query cannot answer any of this: these units exist only inside a user
    manager, and a prior collector that read UNIT alone reported the 60/60
    bunny-first-boot failure as an empty list.

    Every field is None when the boot cannot answer it, never a falsy
    default — an absent session and a session whose units all succeeded must
    not render identically.
    """
    logged_in = sorted(
        uid for uid, names in sessions_by_uid.items()
        if uid and uid != "0" and any(
            not any(account in name for account in INFRASTRUCTURE_ACCOUNTS)
            for name in names))

    per_uid: dict[str, dict] = {}
    for uid in logged_in:
        units: dict[str, dict | None] = {}
        for unit_name in FIRST_LOGIN_UNITS:
            found = next((u for u in user_rendered
                          if u["unit"] == unit_name and u["uid"] == uid), None)
            if found is None:
                units[unit_name] = None
                continue
            exit_status = (found.get("mainExit") or {}).get("status")
            units[unit_name] = {
                "disposition": found["disposition"],
                "result": found["result"],
                "mainExitStatus": exit_status,
                "failuresDuringBoot": found["failuresDuringBoot"],
                "restartCounterMax": found["restartCounterMax"],
                "activeEnterMono": found["activeEnterMono"],
                # 226/NAMESPACE is the signature of the corrected defect: the
                # mount namespace could not be built, so ExecStart never ran.
                # Named explicitly because a gate that only counted failures
                # would report the correction as working the moment the unit
                # failed some other way.
                "namespaceFailure": exit_status == "226/NAMESPACE",
            }
        per_uid[uid] = units

    return {
        "loggedInUids": logged_in,
        "sessionCount": len(logged_in),
        "units": per_uid,
        "anyNamespaceFailure": any(
            (entry or {}).get("namespaceFailure")
            for units in per_uid.values() for entry in units.values()),
    }


def _chronyd_ordering(system_units: dict, timeline: dict) -> dict:
    """dsq-2 — the chronyd correction stated as two comparable timestamps.

    `orderedAfterAuthselect` is None, not False, when either timestamp is
    absent: a boot where authselect had nothing to apply proves nothing about
    the ordering and must not be counted as proving it holds.
    """
    chronyd = system_units.get("chronyd.service")
    exit_status = None
    if chronyd and chronyd.get("mainExit"):
        exit_status = chronyd["mainExit"].get("status")

    start = timeline.get("chronydStartRequested")
    apply_end = timeline.get("authselectApplyEnd")
    apply_start = timeline.get("authselectApplyStart")
    ordered = None
    if start is not None and apply_end is not None:
        ordered = start >= apply_end

    inside_window = None
    if start is not None and apply_start is not None and apply_end is not None:
        inside_window = apply_start <= start <= apply_end

    return {
        "chronydStartRequestedMono": start,
        "chronydActiveMono": timeline.get("chronydActive"),
        "nssUserLookupReachedMono": timeline.get("nssUserLookupReached"),
        "authselectApplyStartMono": apply_start,
        "authselectApplyEndMono": apply_end,
        "orderedAfterAuthselect": ordered,
        "startedInsideApplyWindow": inside_window,
        "mainExitStatus": exit_status,
        # 217/USER is the exact failure the ordering correction targets: the
        # account could not be resolved when chronyd spawned.
        "userResolutionFailure": exit_status == "217/USER",
        "observed": chronyd is not None,
    }


def excerpts(journal_dir: Path, boot_id: str, out_dir: Path) -> dict[str, str]:
    """Stage 4 excerpt files, hashed by the caller's manifest pass."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, args in {
        "journal-full-short-monotonic.log": ("-b", boot_id, "-o", "short-monotonic"),
        "journal-gdm.log": ("-b", boot_id, "-o", "short-monotonic",
                            "-u", "gdm.service"),
        "journal-warnings.log": ("-b", boot_id, "-o", "short-monotonic",
                                 "-p", "warning..alert"),
        "journal-avahi.log": ("-b", boot_id, "-o", "short-monotonic",
                              "-u", "avahi-daemon.service",
                              "-u", "avahi-daemon.socket"),
        # dsq-2. `-u` matches system units only, so the first-login units —
        # which exist only in a user manager — produce an empty file under it.
        # That empty file was how a prior collector reported the 60/60
        # bunny-first-boot failure as nothing at all. `--user-unit` is the
        # query that can see them, and these excerpts are the evidence the
        # gate requires instead of a system-journal substitute.
        "journal-first-login-user-units.log": (
            "-b", boot_id, "-o", "short-monotonic",
            "--user-unit", "bunny-first-boot.service",
            "--user-unit", "bunny-config-dir.service",
            "--user-unit", "systemd-tmpfiles-setup.service"),
        "journal-chronyd.log": ("-b", boot_id, "-o", "short-monotonic",
                                "-u", "chronyd.service",
                                "-u", "authselect-apply-changes.service"),
    }.items():
        try:
            (out_dir / name).write_text(_journalctl(journal_dir, *args),
                                        encoding="utf-8")
            written[name] = "written"
        except JournalError as exc:
            written[name] = f"FAILED: {exc}"
    return written
