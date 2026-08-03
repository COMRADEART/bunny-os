#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decide whether a machine may be used to qualify Bunny OS.

The gate exists because the previous attempt at V4 was made on a host that could
not measure two of the eight mandatory gates, and nothing in the tooling said so
until somebody went looking. A host that cannot measure a thing must refuse the
work rather than produce a result that looks like a measurement.

Every condition here is mandatory. There is no warning tier, because a warning is
how a missing mandatory condition turns into a footnote in a report nobody reads
twice. A condition is either observed to hold or the host is BLOCKED.

Three refusals in particular are worth stating plainly, because each one has an
attractive-looking substitute that must never be accepted:

* a software rasteriser is not a GPU — llvmpipe renders correctly and proves
  nothing about the hardware path;
* two nested windows are not two displays — only connected DRM connectors count;
* an emulated TPM is not a TPM — swtpm proves the software path, not the machine.

Usage:

    python host-readiness-gate.py --environment path/to/environment.json
    python host-readiness-gate.py --environment env.json --output readiness.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Callable

SOFTWARE_RASTERISERS = ("llvmpipe", "softpipe", "swrast", "software rasterizer", "lavapipe")

# Devices that report a plausible-looking GPU name while the real render path is
# translated or emulated. WSL is the case that prompted this: it advertises
# "Microsoft Direct3D12 (NVIDIA GeForce ...)" as a Vulkan device while OpenGL
# falls back to llvmpipe and /dev/dri does not exist. A name check alone accepts
# it, which is the llvmpipe mistake wearing a better disguise.
PARAVIRTUAL_RENDERERS = ("direct3d12", "d3d12", "swiftshader", "virgl", "venus", "vmware")

# Minimums. Deliberately modest: the gate refuses hosts that cannot measure, not
# hosts that are merely slow.
MIN_LOGICAL_CORES = 8
MIN_MEMORY_BYTES = 16 * 1024**3
MIN_EVIDENCE_BYTES = 400 * 1024**3
MIN_CONNECTED_OUTPUTS = 2


class Condition:
    def __init__(
        self,
        identifier: str,
        description: str,
        check: Callable[[dict], tuple[bool, Any, str | None]],
    ) -> None:
        self.id = identifier
        self.description = description
        self.check = check

    def evaluate(self, env: dict) -> dict:
        try:
            satisfied, observed, refusal = self.check(env)
        except (KeyError, TypeError, IndexError) as exc:
            # A missing field is a refusal, never a pass. An environment report
            # that cannot answer the question has not answered it.
            satisfied, observed, refusal = False, None, f"environment report incomplete: {exc}"
        return {
            "id": self.id,
            "description": self.description,
            "mandatory": True,
            "satisfied": bool(satisfied),
            "observed": observed if isinstance(observed, (str, int, float, bool, type(None))) else str(observed),
            "refusal": None if satisfied else (refusal or "condition not satisfied"),
        }


def _renderer_is_software(graphics: dict) -> bool:
    if graphics.get("softwareRasteriser"):
        return True
    renderer = (graphics.get("openglRenderer") or "").lower()
    return any(name in renderer for name in SOFTWARE_RASTERISERS)


def _hardware_renderer_observed(graphics: dict) -> bool:
    """A renderer must be observed, not merely not-known-to-be-software.

    The first version of this asked only whether the renderer was a software
    rasteriser, and a missing renderer answered no — so a host where glxinfo was
    absent or failed satisfied the mandatory GPU condition by saying nothing.
    An absent observation is not a passing one.
    """
    renderer = (graphics.get("openglRenderer") or "").strip()
    return bool(renderer) and not _renderer_is_software(graphics)


def _renderer_is_translated(name: str | None) -> bool:
    """True for translation layers and emulated devices, whatever they are named."""
    lowered = (name or "").lower()
    return any(marker in lowered for marker in PARAVIRTUAL_RENDERERS + SOFTWARE_RASTERISERS)


CONDITIONS: list[Condition] = [
    Condition(
        "role-is-host",
        "the report describes a measurement host",
        lambda e: (
            e["role"] == "host",
            e["role"],
            f"role is {e['role']}; this gate evaluates the measurement host only",
        ),
    ),
    Condition(
        "bare-metal",
        "Fedora runs on bare metal",
        lambda e: (
            bool(e["host"]["bareMetal"]) and not e["host"].get("hypervisorDetected"),
            e["host"].get("hypervisorDetected") or "bare metal",
            f"host is virtualised ({e['host'].get('hypervisorDetected')}); "
            "a qualification host must not run inside WSL, VirtualBox, VMware or a nested VM",
        ),
    ),
    Condition(
        "fedora",
        "the operating system is Fedora",
        lambda e: (
            "fedora" in e["os"]["name"].lower(),
            e["os"]["name"],
            f"operating system is {e['os']['name']}, not Fedora",
        ),
    ),
    Condition(
        "uefi-boot",
        "the host booted in UEFI mode",
        lambda e: (
            e["boot"]["mode"] == "uefi",
            e["boot"]["mode"],
            f"boot mode is {e['boot']['mode']}; UEFI is required",
        ),
    ),
    Condition(
        "selinux-enforcing",
        "SELinux is enforcing",
        lambda e: (
            e["selinux"]["mode"] == "Enforcing",
            e["selinux"]["mode"],
            f"SELinux is {e['selinux']['mode']}, not Enforcing",
        ),
    ),
    Condition(
        "wayland-session",
        "the host session is Wayland",
        lambda e: (
            e["session"]["type"] == "wayland",
            e["session"]["type"],
            f"host session is {e['session']['type']}; Wayland is required",
        ),
    ),
    Condition(
        "drm-card-node",
        "a DRM card node exists",
        lambda e: (
            bool(e["graphics"]["drmCardNodes"]),
            ", ".join(e["graphics"]["drmCardNodes"]) or None,
            "/dev/dri is absent; without KMS there is no page-flip, no vblank and no connector",
        ),
    ),
    Condition(
        "drm-render-node",
        "a DRM render node exists",
        lambda e: (
            bool(e["graphics"]["drmRenderNodes"]),
            ", ".join(e["graphics"]["drmRenderNodes"]) or None,
            "no /dev/dri/renderD* node; GPU rendering cannot be measured",
        ),
    ),
    Condition(
        "hardware-renderer",
        "an OpenGL renderer was observed and is hardware, not a software rasteriser",
        lambda e: (
            _hardware_renderer_observed(e["graphics"]),
            e["graphics"].get("openglRenderer"),
            (
                "no OpenGL renderer was observed; an absent observation is not a passing one"
                if not (e["graphics"].get("openglRenderer") or "").strip()
                else f"renderer is {e['graphics'].get('openglRenderer')}, a software rasteriser; "
                "it renders correctly and proves nothing about the hardware path"
            ),
        ),
    ),
    Condition(
        "vulkan-device",
        "a hardware Vulkan device is present, backed by a real DRM device",
        lambda e: (
            bool(e["graphics"].get("vulkanDevice"))
            and bool(e["graphics"]["drmCardNodes"])
            and not _renderer_is_translated(e["graphics"].get("vulkanDevice")),
            e["graphics"].get("vulkanDevice"),
            (
                f"Vulkan device {e['graphics'].get('vulkanDevice')!r} is translated or emulated; "
                "a paravirtualised device name is not a hardware render path"
                if _renderer_is_translated(e["graphics"].get("vulkanDevice"))
                else "no Vulkan device backed by a DRM card node"
            ),
        ),
    ),
    Condition(
        "two-connected-outputs",
        "at least two displays are physically connected",
        lambda e: (
            e["displays"]["connectedOutputs"] >= MIN_CONNECTED_OUTPUTS,
            e["displays"]["connectedOutputs"],
            f"{e['displays']['connectedOutputs']} connected output(s); "
            f"{MIN_CONNECTED_OUTPUTS} are required, and nested windows are not outputs",
        ),
    ),
    Condition(
        "physical-tpm-2",
        "a physical TPM 2.0 is present",
        lambda e: (
            e["tpm"]["present"] and e["tpm"]["physical"] and (e["tpm"].get("version") or "").startswith("2"),
            f"present={e['tpm']['present']} physical={e['tpm']['physical']} version={e['tpm'].get('version')}",
            "no physical TPM 2.0; an emulated TPM proves the software path, not the machine",
        ),
    ),
    Condition(
        "secure-boot-observed",
        "the Secure Boot state was observed",
        lambda e: (
            e["boot"]["secureBoot"] in {"enabled", "disabled"},
            e["boot"]["secureBoot"],
            f"Secure Boot state is {e['boot']['secureBoot']}; it must be explicitly observed, "
            "even when disabled",
        ),
    ),
    Condition(
        "kvm-available",
        "KVM is usable: /dev/kvm exists and virt-host-validate qemu passes",
        lambda e: (
            bool(e["virtualisation"]["kvmAvailable"])
            and e["virtualisation"].get("virtHostValidateExitCode") == 0,
            f"kvm={e['virtualisation']['kvmAvailable']} "
            f"virt-host-validate exit={e['virtualisation'].get('virtHostValidateExitCode')}",
            (
                "/dev/kvm is unavailable; Programs E, F and G run in disposable guests"
                if not e["virtualisation"]["kvmAvailable"]
                else "virt-host-validate qemu was not run; a present /dev/kvm node is not "
                "a working hypervisor and not run is not a pass"
                if e["virtualisation"].get("virtHostValidateExitCode") is None
                else "virt-host-validate qemu exited "
                f"{e['virtualisation'].get('virtHostValidateExitCode')}; the node exists but "
                "the host cannot actually run guests"
            ),
        ),
    ),
    Condition(
        "pipewire-active",
        "PipeWire is running",
        lambda e: (e["session"]["pipewire"], e["session"]["pipewire"], "PipeWire is not active"),
    ),
    Condition(
        "wireplumber-active",
        "WirePlumber is running",
        lambda e: (e["session"]["wireplumber"], e["session"]["wireplumber"], "WirePlumber is not active"),
    ),
    Condition(
        "portal-active",
        "xdg-desktop-portal is running",
        lambda e: (
            e["session"]["portal"],
            ", ".join(e["session"].get("portalBackends") or []) or e["session"]["portal"],
            "xdg-desktop-portal is inactive; screen sharing and screenshots cannot be measured",
        ),
    ),
    Condition(
        "orca-installed",
        "Orca is installed",
        lambda e: (
            e["accessibility"]["orcaInstalled"],
            e["accessibility"].get("orcaVersion"),
            "Orca is not installed; accessibility cannot be measured, and labels are not Orca evidence",
        ),
    ),
    Condition(
        "speech-dispatcher-installed",
        "speech-dispatcher is installed",
        lambda e: (
            e["accessibility"]["speechDispatcherInstalled"],
            e["accessibility"].get("speechDispatcherVersion"),
            "speech-dispatcher is not installed; spoken output cannot be captured",
        ),
    ),
    Condition(
        "input-method-available",
        "IBus or Fcitx 5 is available",
        lambda e: (
            bool(e["inputMethod"]["available"]),
            ", ".join(e["inputMethod"]["available"]) or None,
            "neither IBus nor Fcitx 5 is available; CJK input cannot be measured",
        ),
    ),
    Condition(
        "luks2-supported",
        "cryptsetup supports LUKS2",
        lambda e: (
            e["crypto"]["luks2Supported"],
            e["crypto"].get("cryptsetupVersion"),
            "cryptsetup does not report LUKS2 support",
        ),
    ),
    Condition(
        "cpu-cores",
        f"at least {MIN_LOGICAL_CORES} logical cores",
        lambda e: (
            e["cpu"]["logicalCores"] >= MIN_LOGICAL_CORES,
            e["cpu"]["logicalCores"],
            f"{e['cpu']['logicalCores']} logical cores; {MIN_LOGICAL_CORES} required",
        ),
    ),
    Condition(
        "memory",
        "sufficient RAM for the guest matrices",
        lambda e: (
            e["memory"]["totalBytes"] >= MIN_MEMORY_BYTES,
            e["memory"]["totalBytes"],
            f"{e['memory']['totalBytes'] / 1024**3:.1f} GiB RAM; "
            f"{MIN_MEMORY_BYTES / 1024**3:.0f} GiB is the reduced-matrix minimum",
        ),
    ),
    Condition(
        "evidence-storage",
        "sufficient storage for guests, overlays and retained evidence",
        lambda e: (
            e["storage"]["availableBytesForEvidence"] >= MIN_EVIDENCE_BYTES,
            e["storage"]["availableBytesForEvidence"],
            f"{e['storage']['availableBytesForEvidence'] / 1024**3:.0f} GiB available; "
            f"{MIN_EVIDENCE_BYTES / 1024**3:.0f} GiB required",
        ),
    ),
    Condition(
        "clock-synchronised",
        "the system clock is synchronised",
        lambda e: (
            e["clock"]["synchronised"],
            e["clock"].get("systemTime"),
            "the system clock is not synchronised; evidence timestamps would not be trustworthy",
        ),
    ),
    Condition(
        "git-byte-roundtrip",
        "the evidence byte round-trip guard passes",
        lambda e: (
            e["git"]["byteRoundtripTestsPass"] is True,
            e["git"]["byteRoundtripTestsPass"],
            "tests/evidence did not pass; attested bytes may not round-trip this checkout",
        ),
    ),
]


SCHEMA = Path(__file__).resolve().parents[1] / "host-environment.schema.json"


class SchemaError(Exception):
    """The environment report is not a valid environment report."""


def validate_environment(env: object, *, schema_path: Path = SCHEMA) -> None:
    """Reject a malformed report at the boundary, before any condition reads it.

    The conditions index and call methods on the report freely, so a document
    with the right keys and the wrong types can raise from inside a lambda. That
    used to surface as a traceback, which is the one outcome a gate must never
    produce: a crash is not a refusal, and a caller cannot tell them apart.

    Validating the whole document first means a malformed report is refused for
    being malformed, with the offending field named. Catching more exception
    types inside the wrapper would have hidden the same problem one layer down.
    """
    try:
        import jsonschema
    except ImportError as exc:
        # Fail closed. A gate that cannot check its input has not checked it.
        raise SchemaError(
            "jsonschema is unavailable, so the environment report cannot be validated. "
            "Install it (python -m pip install jsonschema) rather than skipping the check."
        ) from exc

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"{schema_path.name} could not be read: {exc}") from exc

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(env), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<document root>"
        detail = f"{location}: {first.message}"
        if len(errors) > 1:
            detail += f" (and {len(errors) - 1} further schema violation(s))"
        raise SchemaError(detail)


def evaluate(env: dict, *, now: str) -> dict:
    conditions = [condition.evaluate(env) for condition in CONDITIONS]
    satisfied = sum(1 for c in conditions if c["satisfied"])
    return {
        "schemaVersion": 1,
        "environmentId": env.get("environmentId", "unknown"),
        "evaluatedAt": now,
        "result": "READY" if satisfied == len(conditions) else "BLOCKED",
        "mandatoryTotal": len(conditions),
        "mandatorySatisfied": satisfied,
        "conditions": conditions,
    }


def render(result: dict) -> str:
    lines = [
        f"host readiness: {result['result']}",
        f"  environment: {result['environmentId']}",
        f"  mandatory conditions satisfied: {result['mandatorySatisfied']} of {result['mandatoryTotal']}",
        "",
    ]
    for condition in result["conditions"]:
        mark = "ok     " if condition["satisfied"] else "BLOCKED"
        lines.append(f"  {mark} {condition['id']:28} {condition['description']}")
        if not condition["satisfied"]:
            lines.append(f"          BLOCKED: {condition['refusal']}")
    if result["result"] == "BLOCKED":
        lines += [
            "",
            "This host may not be used to qualify Bunny OS. A host that cannot measure a",
            "requirement must refuse the work rather than produce a result that resembles a",
            "measurement.",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="write the readiness result as JSON")
    args = parser.parse_args()

    try:
        env = json.loads(args.environment.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"BLOCKED: {args.environment} does not exist")
        return 2
    except json.JSONDecodeError as exc:
        print(f"BLOCKED: {args.environment} is not valid JSON: {exc}")
        return 2

    try:
        validate_environment(env)
    except SchemaError as exc:
        print(f"BLOCKED: {args.environment} is not a valid environment report.")
        print(f"         {exc}")
        return 2

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = evaluate(env, now=now)
    print(render(result))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {args.output}")

    return 0 if result["result"] == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
