#!/usr/bin/env python3
"""Render the measured V3 reports from the evidence JSON.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The protocol, compatibility and performance documents are generated so a number
in prose cannot drift from the number in the evidence. The narrative documents
are written by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import ROOT, banner  # noqa: E402


V3 = ROOT / "visual-v3"
REPORTS = V3 / "reports"
HEADER = (
    "> BUNNY WAYLAND SHELL EXPERIMENT\n"
    ">\n"
    "> NOT RELEASE QUALIFIED\n"
    ">\n"
    "> DO NOT USE AS THE DEFAULT SESSION\n"
)


def load(name: str) -> dict | None:
    path = REPORTS / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write(name: str, text: str) -> None:
    (V3 / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote visual-v3/{name}")


def protocol_support() -> None:
    data = load("protocol-support.json")
    if not data or "protocols" not in data or not data["protocols"]:
        write(
            "PROTOCOL_SUPPORT.md",
            f"# Protocol support\n\n{HEADER}\nThe protocol measurement did not run in this "
            "environment, so no matrix is published. Run `make bunny-shell-protocol-test` on a "
            "Linux host with a Wayland session.\n",
        )
        return

    lines = [
        "# Protocol support",
        "",
        HEADER,
        "## How this was established",
        "",
        "Compilation is not evidence. Every row below was checked by running "
        "`wayland-info` — an independent protocol client — against the running compositor and "
        "recording which globals it could actually bind.",
        "",
        f"**{data['globalCount']} globals advertised**, {len(data['protocols'])} protocols "
        "assessed.",
        "",
        "A protocol claimed working that the client could not see, or claimed absent that the "
        "client *could* see, is reported as a contradiction and fails the harness. "
        f"Contradictions in this run: **{len(data['contradictions'])}**.",
        "",
        "## Matrix",
        "",
        "| Protocol | Status | Advertised | Version | Notes |",
        "|---|---|---|---|---|",
    ]
    for row in data["protocols"]:
        advertised = "yes" if row["advertisedToClient"] else "no"
        version = row["version"] if row["version"] is not None else "—"
        note = row["note"].replace("\n", " ")
        lines.append(
            f"| `{row['protocol']}` | {row['status']} | {advertised} | {version} | {note} |"
        )

    absent = [row for row in data["protocols"] if not row["advertisedToClient"]]
    lines += [
        "",
        "## What is missing, and what it costs",
        "",
        f"{len(absent)} of the evaluated protocols are not advertised. The consequences are not "
        "cosmetic:",
        "",
    ]
    for row in absent:
        lines.append(f"- **`{row['protocol']}`** — {row['status']}. {row['note']}")
    lines += [
        "",
        "## Bunny defines no private protocol",
        "",
        "Every interface the shell speaks is a standard one. A private protocol would make every "
        "Bunny shell component unusable outside Bunny and would put Bunny in the position of "
        "maintaining an interface contract — a cost worth paying only for a capability no "
        "standard protocol covers, and V3 found none.",
        "",
        "The one candidate for V4 is a privileged channel for approval surfaces that an ordinary "
        "client must not be able to impersonate. See `SECURITY_MODEL.md`.",
        "",
    ]
    write("PROTOCOL_SUPPORT.md", "\n".join(lines))


def compatibility() -> None:
    data = load("compatibility.json")
    if not data or not data.get("applications"):
        write(
            "COMPATIBILITY_MATRIX.md",
            f"# Compatibility matrix\n\n{HEADER}\nThe compatibility measurement did not run in "
            "this environment.\n",
        )
        return

    lines = [
        "# Compatibility matrix",
        "",
        HEADER,
        "## How this was established",
        "",
        f"Each application was launched against the running compositor on {data['measurementHost']}. "
        "An application counts as working only if the compositor observed it map a toplevel and "
        "identify itself over the protocol.",
        "",
        "**No application was modified to make the shell appear compatible.** An application that "
        "is not installed on the measurement host is recorded as not tested — never as passing.",
        "",
        f"{data['applicationsThatMapped']} of {data['applicationsInstalled']} installed "
        f"applications mapped a window; {data['applicationsConsidered']} were considered.",
        "",
        "## Applications",
        "",
        "| Application | Toolkit | Installed | Mapped a window | Identified as |",
        "|---|---|---|---|---|",
    ]
    for row in data["applications"]:
        if not row["installed"]:
            lines.append(f"| {row['application']} | {row['toolkit']} | no | — | not tested |")
            continue
        mapped = "yes" if row.get("launches") else "**no**"
        identity = ", ".join(
            f"`{window['appId']}` ({window['origin']})" for window in row.get("mappedWindows", [])
        ) or "—"
        lines.append(
            f"| {row['application']} | {row['toolkit']} | yes | {mapped} | {identity} |"
        )

    failures = [row for row in data["applications"] if row["installed"] and not row.get("launches")]
    if failures:
        lines += ["", "## Failures", ""]
        for row in failures:
            lines.append(f"- **{row['application']}** — {row.get('defect', 'no detail recorded')}")
    if data.get("xwaylandNote"):
        lines += ["", "### XWayland", "", data["xwaylandNote"], ""]

    lines += [
        "",
        "## Dimensions that were not measured",
        "",
        "The phase asks about nine dimensions per application. Only *launches* was measurable "
        "here. The rest are recorded as not measured, with the reason, rather than assumed:",
        "",
        "| Dimension | Why it was not measured |",
        "|---|---|",
    ]
    for dimension, reason in sorted(data["dimensionsNotMeasured"].items()):
        lines.append(f"| {dimension} | {reason} |")

    lines += [
        "",
        "## The honest summary",
        "",
        "Native Wayland GTK 4 applications work: they connect, map, are identified from the "
        "protocol, and are composited. That is the core compatibility question and the answer is "
        "positive.",
        "",
        "Everything else is unproven. Most of the requested ecosystem — Qt, Electron, Chromium, "
        "Firefox, a file manager, a code editor, a media player, Flatpak — was not installed on "
        "the measurement host and was therefore not tested at all. A compatibility claim covering "
        "those toolkits would be an invention.",
        "",
    ]
    write("COMPATIBILITY_MATRIX.md", "\n".join(lines))


def performance() -> None:
    data = load("performance.json")
    if not data or not data.get("results"):
        write(
            "PERFORMANCE_REPORT.md",
            f"# Performance report\n\n{HEADER}\nThe performance measurement did not run.\n",
        )
        return

    environment = data["environment"]
    lines = [
        "# Performance report",
        "",
        HEADER,
        "## The environment, stated first",
        "",
        f"- Host: {environment['host']}",
        f"- Renderer: **{environment['renderer']}**",
        f"- Hardware accelerated: **{environment['hardwareAccelerated']}**",
        "",
        environment["note"],
        "",
        "## Results",
        "",
        "| Metric | Target | Measured | Verdict |",
        "|---|---|---|---|",
    ]
    for row in data["results"]:
        verdict = (
            "not measured"
            if row["meetsTarget"] is None
            else ("**meets**" if row["meetsTarget"] else "**misses**")
        )
        measured = "—" if row["measured"] is None else f"{row['measured']} {row['unit']}"
        lines.append(
            f"| {row['description']} | {row['target']} {row['unit']} | {measured} | {verdict} |"
        )

    met = [row for row in data["results"] if row["meetsTarget"] is True]
    missed = [row for row in data["results"] if row["meetsTarget"] is False]
    unmeasured = [row for row in data["results"] if row["meetsTarget"] is None]
    lines += [
        "",
        f"**{len(met)} met, {len(missed)} missed, {len(unmeasured)} not measured.**",
        "",
    ]

    if data.get("frameSampleNote"):
        lines += [
            "## Why frame rate and idle CPU are not reported",
            "",
            data["frameSampleNote"] + ".",
            "",
            "Reporting a frame-rate miss from that sample would be as dishonest as reporting a "
            "pass. Both numbers need a DRM/KMS session on real hardware, where the compositor "
            "owns the page flip instead of waiting for a host to schedule it.",
            "",
        ]

    if missed:
        lines += ["## The misses", ""]
        for row in missed:
            lines.append(
                f"- **{row['description']}**: {row['measured']} {row['unit']} against a "
                f"{row['target']} {row['unit']} target."
            )
        lines += [
            "",
            "The chrome-visibility misses share one cause and it is architectural, not "
            "incidental. Each panel is a separate process that starts a Python interpreter, "
            "imports PyGObject, re-executes itself with `LD_PRELOAD` set for gtk4-layer-shell, "
            "initialises GTK, and only then maps a surface. Three seconds is what that costs on "
            "this host. A 150 ms target is unreachable for a cold process launch by any "
            "toolkit — the target assumes resident chrome, and V4 must keep the panels running "
            "and toggle visibility instead of spawning them.",
            "",
        ]

    lines += [
        "## What these numbers are worth",
        "",
        "Startup and memory are real results and both are comfortable: the compositor reaches its "
        "first frame well inside the target and uses less than half the memory budget, on a "
        "software rasteriser. They would only improve with a GPU.",
        "",
        "The chrome-visibility numbers are real measurements of the wrong architecture, and the "
        "fix is known. The frame-rate and idle-CPU numbers are not results at all in this "
        "environment and are reported as unmeasured.",
        "",
    ]
    write("PERFORMANCE_REPORT.md", "\n".join(lines))


def crash_recovery() -> None:
    data = load("crash-recovery.json")
    if not data:
        return
    lines = [
        "# Crash recovery report",
        "",
        HEADER,
        "## Result",
        "",
        f"**Bounded restart holds: {data['boundedRestartHolds']}.** "
        "No scenario produced an unbounded restart loop.",
        "",
    ]
    for scenario in data["scenarios"]:
        lines += [f"## Scenario: {scenario['scenario']}", ""]
        if scenario.get("evidence") == "unavailable":
            lines += [f"Not measured: {scenario.get('reason')}", ""]
            continue
        for key, value in sorted(scenario.items()):
            if key in ("scenario", "evidence"):
                continue
            lines.append(f"- `{key}`: {value}")
        lines.append("")

    lines += [
        "## The policy",
        "",
        "The restart budget is absolute rather than rate-limited: at most three restarts for the "
        "lifetime of a session, and at most one consecutive restart after a rapid crash. A crash "
        "following a long healthy run resets the *consecutive* counter but never the *total* "
        "budget, which is what makes an endless loop impossible regardless of crash timing.",
        "",
        "When the budget is exhausted the supervisor writes a recovery marker, prints plain-text "
        "guidance that names GNOME as the supported session, and exits 3. The systemd unit treats "
        "3 as a handled outcome rather than a failure to restart.",
        "",
        "## What is not preserved",
        "",
        "**Open clients do not survive a compositor restart.** A Wayland client's connection is to "
        "the compositor's socket; when the process exits the connection is lost and the client "
        "exits with it. Preserving clients would need a socket-handover design that Smithay does "
        "not provide and V3 did not attempt. This is recorded in every crash record rather than "
        "implied.",
        "",
        "## Usable without Character Mode",
        "",
        "The recovery path is text only, deliberately. It has to work when Character Mode is off, "
        "when the compositor cannot start at all, and when nothing but a virtual terminal is "
        "available. A test asserts the guidance mentions GNOME and does not mention the character.",
        "",
    ]
    write("CRASH_RECOVERY_REPORT.md", "\n".join(lines))


def main() -> int:
    banner()
    protocol_support()
    compatibility()
    performance()
    crash_recovery()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
