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
import base64
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping

BEGIN = "---BUNNY-ALPHA-JSON-BEGIN---"
END = "---BUNNY-ALPHA-JSON-END---"

#: Serial consoles interleave, and the probe frames its payload so that they
#: may. A control-character strip first, because the console carries colour.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

#: The probe's chunk framing. Anchored to the end of the line so a kernel
#: message appended to a chunk cannot be mistaken for part of it.
_CHUNK = re.compile(r"BUNNYB64 (\d+) ([A-Za-z0-9+/=]+)\s*$")
_COUNT = re.compile(r"BUNNYB64-COUNT (\d+)\s*$")

#: Must equal ``CHUNK`` in alpha-probe.py. The two are separate programs and
#: one runs inside the guest, so the width cannot be shared as an import; it
#: is only used to notice a torn line, and a mismatch degrades to "cut short"
#: rather than to a wrong record.
_CHUNK_WIDTH = 512


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

    # Numbered base64 chunks first. The probe prints them because a serial
    # console interleaves: a kernel message landed inside a 130 kB JSON object
    # at character 48312 on one offline boot and the whole record was lost.
    # Anything the kernel writes between two chunks fails to match; a chunk torn
    # in half fails to match too, and its *index* is then missing, so this can
    # name the piece it lost rather than decoding something short and calling it
    # a record.
    chunks: dict[int, str] = {}
    declared = -1
    for line in body.splitlines():
        cleaned = _CONTROL.sub("", line)
        count = _COUNT.search(cleaned)
        if count:
            declared = int(count.group(1))
            continue
        found = _CHUNK.search(cleaned)
        if found:
            chunks[int(found.group(1))] = found.group(2)
    if chunks:
        expected = declared if declared >= 0 else max(chunks) + 1
        missing = [index for index in range(expected) if index not in chunks]
        if missing:
            return None, (
                f"the probe's output lost {len(missing)} of {expected} chunk(s) to console "
                f"interleaving: {missing[:8]}"
            )
        # A chunk cut short still matches the pattern — the remaining base64 is
        # valid base64 — so length is checked too. Without this a torn line
        # reaches the decoder and the failure is reported as "did not decode",
        # which says nothing about where it happened.
        short = [
            index for index in range(expected - 1)
            if len(chunks[index]) != _CHUNK_WIDTH
        ]
        if short:
            return None, (
                f"{len(short)} chunk(s) arrived cut short, so a console line was torn: "
                f"{short[:8]}"
            )
        joined = "".join(chunks[index] for index in range(expected))
        try:
            return json.loads(base64.b64decode(joined).decode("utf-8")), ""
        except Exception as error:
            return None, f"the reassembled payload did not decode: {error}"

    # A probe from before the chunk framing. Kept so an older serial log can
    # still be read.
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

    def runtime_enabled_without_companion_window() -> tuple[bool, str]:
        text = str(_at(record, "sections", "units", "userPreset") or "")
        states = [line.strip() for line in text.splitlines() if line.strip()]
        expected = ["enabled", "disabled"]
        return states == expected, (
            "is-enabled runtime/window: "
            f"{states!r}; expected {expected!r}"
        )

    add(
        "session.runtime-enabled-window-not-autostarted",
        "units",
        runtime_enabled_without_companion_window,
    )

    def one_runtime_without_companion_window() -> tuple[bool, str]:
        """One runtime and no legacy GTK window, counted from unit cgroups.

        The GNOME Shell surface is the visible assistant. The GTK client remains
        installed for an explicit Applications-grid launch, but autostarting it
        would put a second Bunny over the desktop character. The runtime may
        briefly have a helper while it is reaped; the window must have none.
        """
        counts = _at(record, "sections", "session", "processCounts") or {}
        if "runtime" not in counts or "window" not in counts:
            return False, "the per-unit process counts were not collected"
        runtime = counts["runtime"]
        window = counts["window"]
        ok = (
            runtime.isdigit() and 1 <= int(runtime) <= 2
            and window == "0"
        )
        return ok, f"runtime processes={runtime}, window processes={window}"

    add(
        "session.runtime-only-no-companion-window",
        "session",
        one_runtime_without_companion_window,
    )

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
    parser.add_argument(
        "--probe-json", type=Path, default=None,
        help="the record read off the guest filesystem; preferred over the console",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", default="alpha-story")
    parser.add_argument("--profile", default="beta")
    parser.add_argument("--source-image", default="")
    parser.add_argument("--offline", default="0")
    parser.add_argument("--commit", default="")
    arguments = parser.parse_args(argv)

    # The guest filesystem is the authoritative channel; the console is the
    # fallback. Both are attempted and the record says which one answered, so a
    # story that only survived on the console is visible as such rather than
    # indistinguishable from one that did not need it.
    probe, failure, channel = None, "", ""
    if arguments.probe_json is not None:
        try:
            probe = json.loads(arguments.probe_json.read_text(encoding="utf-8"))
            channel = "guest-filesystem"
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            failure = f"the record from the guest filesystem did not parse: {error}"
    if probe is None:
        probe, console_failure = extract(arguments.serial)
        if probe is not None:
            channel = "serial-console"
        else:
            failure = "; ".join(part for part in (failure, console_failure) if part)
    offline = arguments.offline == "1"
    document: dict[str, Any] = {
        "schemaVersion": 1,
        "label": arguments.label,
        "commit": arguments.commit,
        "profile": arguments.profile,
        "sourceImage": arguments.source_image,
        "offline": offline,
        "probeExtracted": probe is not None,
        "extractionChannel": channel,
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
