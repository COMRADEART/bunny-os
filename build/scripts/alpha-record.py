#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lift the probe's JSON out of a serial console and judge it.

Two jobs, and they are separate on purpose. Extracting is mechanical: find the
markers, parse what is between them, and say plainly when there is nothing
there — a boot that never reached the probe produces *no* record rather than an
empty one that reads like a pass.

Judging is the part that decides whether a boot counts, and every judgement is
one named assertion with the evidence it was made from beside it. §42 asks for
gates that record their exact commit and track named quantities; a gate that
answered "ok" would be a gate nobody could argue with.

Exit status: 0 every assertion held, 1 at least one did not, 2 there was no
record to judge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping

BEGIN = "---BUNNY-ALPHA-JSON-BEGIN---"
END = "---BUNNY-ALPHA-JSON-END---"

#: Serial consoles interleave. The probe's own output is one line of JSON, but
#: the kernel may have written a line of its own into the middle of it, so the
#: extraction takes everything between the markers and then finds the JSON.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def extract(serial: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        text = serial.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return None, f"the serial log could not be read: {error}"
    if BEGIN not in text:
        return None, (
            "the probe never ran: no begin marker in the serial log. The guest did not "
            "reach graphical.target, or the injected unit did not start."
        )
    body = text.split(BEGIN, 1)[1]
    if END not in body:
        return None, "the probe started and did not finish: no end marker"
    body = body.split(END, 1)[0]
    for line in body.splitlines():
        candidate = _CONTROL.sub("", line).strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                return json.loads(candidate), ""
            except json.JSONDecodeError:
                continue
    joined = _CONTROL.sub("", " ".join(body.split()))
    start, finish = joined.find("{"), joined.rfind("}")
    if start >= 0 and finish > start:
        try:
            return json.loads(joined[start:finish + 1]), ""
        except json.JSONDecodeError as error:
            return None, f"the probe's output was not valid JSON: {error}"
    return None, "the probe's output held no JSON object"


def _at(record: Mapping[str, Any], *path: str) -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def assertions(record: Mapping[str, Any], *, offline: bool) -> list[dict[str, Any]]:
    """Every named check, each with what it read.

    Written as data rather than as ``assert`` statements so that a failing gate
    prints all of its failures rather than the first one, and so that the report
    can quote the evidence beside the verdict.
    """
    checks: list[tuple[str, str, Callable[[], tuple[bool, str]]]] = []

    def add(identifier: str, section: str, judge: Callable[[], tuple[bool, str]]) -> None:
        checks.append((identifier, section, judge))

    # -- §4 boot --------------------------------------------------------------
    def boot_reached() -> tuple[bool, str]:
        stamps = _at(record, "sections", "boot", "unitTimestamps") or {}
        value = stamps.get("graphical.target:ActiveEnterTimestampMonotonic", "0")
        reached = value.isdigit() and int(value) > 0
        return reached, f"graphical.target ActiveEnterTimestampMonotonic={value}"

    add("boot.graphical-target-reached", "boot", boot_reached)

    def boot_is_a_vm() -> tuple[bool, str]:
        detected = str(_at(record, "sections", "boot", "virtualisation") or "")
        # Recorded as a *fact*, and asserted true, because §4 forbids reporting
        # anything but a VM or real hardware as boot evidence and this harness
        # is the VM case. A record that claimed hardware would be the lie.
        return detected not in ("", "none"), f"systemd-detect-virt={detected!r}"

    add("boot.is-a-virtual-machine", "boot", boot_is_a_vm)

    # -- §11 and §12 session --------------------------------------------------
    def runtime_active() -> tuple[bool, str]:
        unit = _at(record, "sections", "units", "user", "bunny-companion.service") or {}
        state = unit.get("ActiveState", "unknown")
        return state == "active", f"bunny-companion.service ActiveState={state}"

    add("session.runtime-started", "units", runtime_active)

    def runtime_not_looping() -> tuple[bool, str]:
        unit = _at(record, "sections", "units", "user", "bunny-companion.service") or {}
        if "NRestarts" not in unit:
            return False, "bunny-companion.service reported no NRestarts; nothing was measured"
        restarts = unit["NRestarts"]
        count = int(restarts) if str(restarts).isdigit() else -1
        return 0 <= count <= 1, f"bunny-companion.service NRestarts={restarts}"

    add("session.runtime-not-restart-looping", "units", runtime_not_looping)

    def window_unit_known() -> tuple[bool, str]:
        unit = _at(record, "sections", "units", "user", "bunny-companion-window.service") or {}
        load = unit.get("LoadState", "unknown")
        return load == "loaded", f"bunny-companion-window.service LoadState={load}"

    add("session.window-unit-installed", "units", window_unit_known)

    def enabled_by_preset() -> tuple[bool, str]:
        text = str(_at(record, "sections", "units", "userPreset") or "")
        enabled = text.count("enabled") >= 2
        return enabled, f"is-enabled: {text.strip()!r}"

    add("session.both-units-enabled", "units", enabled_by_preset)

    def one_runtime_one_window() -> tuple[bool, str]:
        """One process per unit, counted from the unit's own cgroup.

        Not from ``pgrep``: a pattern that matches ``bunny-companion-window``
        also matches the shell running the pgrep and the runuser running that,
        and the first version of this reported three of each on a system where
        neither unit was enabled.

        The runtime is one process. The window is one process *plus whatever
        GTK and Mesa start for it*, which on a session with a compositor is
        several threads in one task group and can legitimately be more than
        one task; the bound is there to catch a second *window*, so it is
        generous rather than exact.
        """
        counts = _at(record, "sections", "session", "processCounts") or {}
        if "runtime" not in counts or "window" not in counts:
            return False, "the per-unit task counts were not collected"
        runtime = counts["runtime"]
        window = counts["window"]
        ok = (
            runtime.isdigit() and int(runtime) <= 2
            and window.isdigit() and int(window) <= 8
        )
        return ok, f"runtime tasks={runtime}, window tasks={window}"

    add("session.no-duplicate-process", "session", one_runtime_one_window)

    def no_terminal() -> tuple[bool, str]:
        counts = _at(record, "sections", "session", "processCounts") or {}
        if "terminals" not in counts:
            return False, "the terminal count was not collected; nothing was measured"
        terminals = counts["terminals"]
        return terminals == "0", f"gnome-terminal-server processes={terminals}"

    add("session.no-terminal-opened", "session", no_terminal)

    # -- §6 provenance --------------------------------------------------------
    def every_subsystem_installed() -> tuple[bool, str]:
        modules = _at(record, "sections", "provenance", "modules") or {}
        if not modules:
            return False, "no provenance was collected"
        bad = [name for name, item in modules.items() if not item.get("installed")]
        return not bad, (
            f"{len(modules) - len(bad)}/{len(modules)} imported from /usr/lib/bunny-os/python"
            + (f"; not installed: {', '.join(sorted(bad))}" if bad else "")
        )

    add("provenance.every-subsystem-from-the-image", "provenance", every_subsystem_installed)

    def no_developer_paths() -> tuple[bool, str]:
        provenance = _at(record, "sections", "provenance")
        if not isinstance(provenance, Mapping) or "rejections" not in provenance:
            return False, "no provenance was collected, so no rejection list exists to be empty"
        rejections = provenance["rejections"] or []
        return not rejections, f"{len(rejections)} rejection(s): {'; '.join(rejections[:4])}"

    add("provenance.no-checkout-or-pythonpath", "provenance", no_developer_paths)

    # -- §20 capability -------------------------------------------------------
    def capability_separates() -> tuple[bool, str]:
        record_value = _at(record, "sections", "capability") or {}
        has_hardware = bool(record_value.get("hardware"))
        probes = record_value.get("operational") or []
        return has_hardware and bool(probes), (
            f"hardware present={has_hardware}, operational probes={len(probes)}"
        )

    add("capability.facts-and-probes-both-present", "capability", capability_separates)

    # -- §13, §28 network -----------------------------------------------------
    def no_outbound() -> tuple[bool, str]:
        count = _at(record, "sections", "network", "outboundCount")
        connections = _at(record, "sections", "network", "outboundConnections") or []
        ok = count == 0
        return ok, f"{count} established non-loopback connection(s): {connections[:3]}"

    add("network.no-unexplained-outbound", "network", no_outbound)

    if offline:
        def route_absent() -> tuple[bool, str]:
            route = str(_at(record, "sections", "network", "defaultRoute") or "")
            return route.strip() == "", f"default route={route.strip()!r}"

        add("network.offline-has-no-default-route", "network", route_absent)

    # -- §8, §9, §32, §33 surveys --------------------------------------------
    def onboarding_complete_offline() -> tuple[bool, str]:
        value = _at(record, "sections", "surveys", "onboarding") or {}
        steps = value.get("steps") or []
        required = [s for s in steps if _at(s, "step", "required")]
        askers = [s for s in required if _at(s, "step", "survey")]
        return bool(steps) and not askers, (
            f"{len(steps)} steps, {len(required)} required, {len(askers)} of those ask for something"
        )

    add("onboarding.offline-completable", "surveys", onboarding_complete_offline)

    def diagnostics_answered() -> tuple[bool, str]:
        value = _at(record, "sections", "surveys", "diagnose") or {}
        sections = _at(value, "report", "sections") or []
        return bool(sections), f"{len(sections)} diagnostic section(s)"

    add("recovery.diagnostics-answered", "surveys", diagnostics_answered)

    def provider_state_is_explicit() -> tuple[bool, str]:
        value = _at(record, "sections", "surveys", "diagnose") or {}
        for section in _at(value, "report", "sections") or []:
            if section.get("sectionId") == "providers":
                detail = str(section.get("detail") or "")
                return bool(detail), f"provider line: {detail[:120]!r}"
        return False, "no provider section in the diagnostic report"

    add("providers.state-is-stated", "surveys", provider_state_is_explicit)

    def character_decided() -> tuple[bool, str]:
        value = _at(record, "sections", "surveys", "characterPolicy") or {}
        decision = value.get("decision") or {}
        rung = decision.get("rung")
        return bool(rung), f"rung={rung}, summary={str(decision.get('summary'))[:100]!r}"

    add("character.policy-decided", "surveys", character_decided)

    # -- §39 identity ---------------------------------------------------------
    def identity_says_alpha() -> tuple[bool, str]:
        release = _at(record, "sections", "identity", "release") or {}
        os_release = _at(record, "sections", "identity", "osRelease") or {}
        channel = release.get("releaseChannel")
        pretty = os_release.get("PRETTY_NAME", "")
        build = release.get("buildId", "")
        ok = channel in ("alpha", "development") and "Bunny OS" in str(pretty) and bool(build)
        return ok, f"channel={channel!r}, PRETTY_NAME={pretty!r}, buildId={build!r}"

    add("identity.one-build-identity", "identity", identity_says_alpha)

    results: list[dict[str, Any]] = []
    for identifier, section, judge in checks:
        try:
            held, evidence = judge()
        except Exception as error:  # pragma: no cover - a judge never takes the gate with it
            held, evidence = False, f"the assertion raised: {type(error).__name__}: {error}"
        results.append({
            "assertion": identifier, "section": section, "held": bool(held), "evidence": evidence,
        })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alpha-record")
    parser.add_argument("--serial", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", default="alpha-story")
    parser.add_argument("--profile", default="beta")
    parser.add_argument("--source-image", default="")
    parser.add_argument("--offline", default="0")
    parser.add_argument("--commit", default="")
    arguments = parser.parse_args(argv)

    probe, failure = extract(arguments.serial)
    offline = arguments.offline == "1"
    document: dict[str, Any] = {
        "schemaVersion": 1,
        "label": arguments.label,
        "commit": arguments.commit,
        "profile": arguments.profile,
        "sourceImage": arguments.source_image,
        "offline": offline,
        "probeExtracted": probe is not None,
        "extractionFailure": failure,
    }
    if probe is None:
        document["allHeld"] = False
        document["assertions"] = []
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        print(f"NO RECORD: {failure}", file=sys.stderr)
        return 2

    results = assertions(probe, offline=offline)
    document["assertions"] = results
    document["allHeld"] = all(item["held"] for item in results)
    document["heldCount"] = sum(1 for item in results if item["held"])
    document["assertionCount"] = len(results)
    document["probe"] = probe
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    for item in results:
        print(f"  [{'ok' if item['held'] else '!!'}] {item['assertion']}: {item['evidence']}")
    print(f"{document['heldCount']}/{document['assertionCount']} assertions held")
    return 0 if document["allHeld"] else 1


if __name__ == "__main__":
    sys.exit(main())
