#!/usr/bin/env python3
"""Enumerate the compositor's protocols with a real client.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Compilation is not evidence. This runs `wayland-info`, an independent protocol
client, against the running compositor and reports what it actually saw.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    NestedShell,
    OBSERVED,
    UNAVAILABLE,
    UNSUPPORTED,
    banner,
    preconditions,
    which,
    write_report,
)


IMPLEMENTED = "implemented"
INHERITED = "inherited from framework"
PARTIAL = "partially implemented"
NOT_IMPLEMENTED = "not implemented"
INTENTIONAL = "intentionally unsupported"


#: The protocols the phase requires an answer for, with the global name a
#: client would bind, the expected status, and why.
MATRIX: list[tuple[str, str | None, str, str]] = [
    ("wl_compositor", "wl_compositor", INHERITED, "Core. Provided by smithay's compositor module."),
    ("wl_shm", "wl_shm", INHERITED, "Core shared-memory buffers."),
    ("wl_seat", "wl_seat", INHERITED, "Core input seat."),
    ("wl_output", "wl_output", IMPLEMENTED, "Bunny creates and configures the output globals."),
    ("xdg_wm_base", "xdg_wm_base", IMPLEMENTED, "Bunny implements the window-management policy on top."),
    ("xdg_activation", "xdg_activation_v1", IMPLEMENTED, "Honoured as attention, never as a focus grant."),
    ("xdg_decoration", "zxdg_decoration_manager_v1", IMPLEMENTED, "Server-side decorations are requested."),
    ("xdg_output", "zxdg_output_manager_v1", INHERITED, "Enabled via OutputManagerState::new_with_xdg_output."),
    ("presentation-time", "wp_presentation", INHERITED, "Clock is CLOCK_MONOTONIC."),
    ("viewporter", "wp_viewporter", INHERITED, "Surface scaling and cropping."),
    ("fractional-scale", "wp_fractional_scale_manager_v1", INHERITED, "Needed for 4K at 200% and mixed-DPI layouts."),
    ("relative-pointer", "zwp_relative_pointer_manager_v1", INHERITED, "Required by games and 3D applications."),
    (
        "pointer-constraints",
        "zwp_pointer_constraints_v1",
        NOT_IMPLEMENTED,
        "Available in smithay but not wired up in V3. Pointer lock and confinement do not work; "
        "applications that need them will misbehave.",
    ),
    ("text-input", "zwp_text_input_manager_v3", INHERITED, "The client half of input methods."),
    (
        "input-method",
        "zwp_input_method_v2",
        NOT_IMPLEMENTED,
        "The compositor half needs popup placement policy V3 did not write. Without it there is no "
        "on-screen keyboard and no CJK input method, which is an accessibility and "
        "internationalisation gap, not a cosmetic one.",
    ),
    ("idle-inhibit", "zwp_idle_inhibit_manager_v1", IMPLEMENTED, "Tracked so a video player can hold the screen on."),
    (
        "linux-dmabuf",
        "zwp_linux_dmabuf_v1",
        NOT_IMPLEMENTED,
        "Needs a GPU device to advertise formats against. The nested software renderer on this "
        "host has none, so clients fall back to wl_shm. Required for hardware video decode.",
    ),
    (
        "screencopy",
        "zwlr_screencopy_manager_v1",
        INTENTIONAL,
        "smithay 0.7 implements no screencopy protocol at all. This is the blocker behind the "
        "screencast portal, and it is a framework gap rather than a Bunny decision.",
    ),
    ("layer-shell", "zwlr_layer_shell_v1", IMPLEMENTED, "Every piece of Bunny chrome depends on it."),
    ("session-lock", "ext_session_lock_manager_v1", IMPLEMENTED, "The lock screen's surface role."),
    (
        "foreign-toplevel-management",
        "ext_foreign_toplevel_list_v1",
        NOT_IMPLEMENTED,
        "Available in smithay. Not enabled in V3: it lets any client enumerate every window, so it "
        "wants a security-context restriction before it is turned on.",
    ),
    (
        "data-control",
        "zwlr_data_control_manager_v1",
        INTENTIONAL,
        "Deliberately off. It grants unrestricted clipboard read to any client that binds it, "
        "which is a clipboard-stealing capability with no consent step.",
    ),
]


def parse_globals(text: str) -> dict[str, int]:
    found = {}
    for match in re.finditer(r"interface:\s*'([^']+)',\s*version:\s*(\d+)", text):
        found[match.group(1)] = int(match.group(2))
    return found


def main() -> int:
    banner()
    problems = preconditions()
    if not which("wayland-info"):
        problems.append("wayland-info is not installed")
    if problems:
        write_report(
            "protocol-support.json",
            {"schemaVersion": 1, "evidence": UNAVAILABLE, "problems": problems, "protocols": []},
        )
        print(f"cannot measure: {problems}", file=sys.stderr)
        return 2

    with NestedShell("bunny-protocol", seconds=45) as shell:
        result = shell.run_client(["wayland-info"], timeout=40)
        advertised = parse_globals(result.stdout)

    # A failed measurement must never be reported as protocol absence. Without
    # this check an exited compositor produces a report claiming every protocol
    # is missing, which is the most damaging kind of false evidence this phase
    # can generate.
    if result.returncode != 0 or not advertised:
        write_report(
            "protocol-support.json",
            {
                "schemaVersion": 1,
                "evidence": UNAVAILABLE,
                "problems": [
                    f"wayland-info exited {result.returncode} and returned "
                    f"{len(advertised)} globals; the measurement did not happen"
                ],
                "clientStderr": result.stderr[-2000:],
                "clientStdoutPreview": result.stdout[:500],
                "clientStdoutLength": len(result.stdout),
                "compositorLogTail": shell.log_text()[-1500:],
                "protocols": [],
            },
        )
        print("wayland-info did not produce a global list; nothing measured", file=sys.stderr)
        return 2

    rows = []
    contradictions = []
    for name, global_name, status, note in MATRIX:
        seen = global_name in advertised if global_name else False
        version = advertised.get(global_name) if global_name else None
        claimed_working = status in (IMPLEMENTED, INHERITED, PARTIAL)
        if claimed_working and not seen:
            contradictions.append(f"{name} is claimed {status} but was not advertised")
        if not claimed_working and seen:
            contradictions.append(f"{name} is claimed {status} but WAS advertised")
        rows.append(
            {
                "protocol": name,
                "global": global_name,
                "status": status,
                "advertisedToClient": seen,
                "version": version,
                "evidence": OBSERVED if seen else (UNSUPPORTED if status == INTENTIONAL else OBSERVED),
                "note": note,
            }
        )

    payload = {
        "schemaVersion": 1,
        "verifiedBy": "wayland-info run against the running compositor",
        "globalsAdvertised": advertised,
        "globalCount": len(advertised),
        "protocols": rows,
        "contradictions": contradictions,
        "noUnsupportedProtocolReportedAsSupported": not contradictions,
    }
    write_report("protocol-support.json", payload)
    print(f"{len(advertised)} globals advertised; {len(rows)} protocols assessed")
    for issue in contradictions:
        print(f"  CONTRADICTION: {issue}")
    return 0 if not contradictions else 1


if __name__ == "__main__":
    raise SystemExit(main())
