#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect what this machine actually is, for the host readiness gate.

Written to be run on the candidate host and nowhere else. It records observations
and refuses to infer: where a value cannot be read, the field is null and the
gate treats that as a refusal rather than a pass.

Two collection rules matter more than the rest.

Serial numbers are hashed, never recorded raw, because the environment report is
committed and a serial is an identifier for a physical object somebody owns. The
hash is stable enough to prove two runs happened on the same machine, which is
the only property the evidence model needs.

The renderer string is classified rather than merely stored. ``llvmpipe`` renders
correctly and looks unremarkable in a report; recording it as an ordinary GPU is
how a software rasteriser ends up cited as GPU qualification.

Usage:

    python collect-environment.py --environment-id FQH-20260803-01 \\
        --operator "name" --role host --output environment.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

SOFTWARE_RASTERISERS = ("llvmpipe", "softpipe", "swrast", "software rasterizer", "lavapipe")


def run(*command: str, timeout: int = 30) -> str | None:
    """Run a command and return its stdout, or None if it cannot answer."""
    if not shutil.which(command[0]):
        return None
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def version_of(binary: str, *args: str) -> str | None:
    out = run(binary, *(args or ("--version",)))
    return out.splitlines()[0].strip() if out else None


def hashed(value: str | None) -> str:
    """A serial identifies a physical object; commit the hash, not the object."""
    return sha256(value.encode()).hexdigest() if value else ""


def detect_hypervisor() -> str | None:
    out = run("systemd-detect-virt")
    if out and out != "none":
        return out
    # WSL does not always answer systemd-detect-virt.
    if "microsoft" in (read("/proc/sys/kernel/osrelease") or "").lower():
        return "wsl"
    return None


def collect_graphics() -> dict:
    cards = sorted(str(p) for p in Path("/dev/dri").glob("card*")) if Path("/dev/dri").is_dir() else []
    renders = sorted(str(p) for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []

    glx = run("glxinfo", "-B") or ""
    renderer = next(
        (line.split(":", 1)[1].strip() for line in glx.splitlines() if "OpenGL renderer string" in line),
        None,
    )
    mesa = next(
        (line.split(":", 1)[1].strip() for line in glx.splitlines() if "OpenGL core profile version" in line),
        None,
    ) or next(
        (line.split(":", 1)[1].strip() for line in glx.splitlines() if "OpenGL version string" in line),
        None,
    )

    vulkan_out = run("vulkaninfo", "--summary") or ""
    vulkan = next(
        (line.split("=", 1)[1].strip() for line in vulkan_out.splitlines() if "deviceName" in line),
        None,
    )

    pci = run("bash", "-lc", "lspci -nnk | grep -A3 -iE 'vga|3d|display' | head -20")
    driver = None
    if pci:
        match = re.search(r"Kernel driver in use:\s*(\S+)", pci)
        driver = match.group(1) if match else None

    return {
        "drmCardNodes": cards,
        "drmRenderNodes": renders,
        "pciIdentity": (pci.splitlines()[0] if pci else None),
        "kernelDriver": driver,
        "mesaVersion": mesa,
        "openglRenderer": renderer,
        "vulkanDevice": vulkan,
        "softwareRasteriser": any(n in (renderer or "").lower() for n in SOFTWARE_RASTERISERS),
    }


def collect_displays() -> dict:
    """Connected DRM connectors. Nested windows are deliberately not counted."""
    outputs: list[dict] = []
    sysfs = Path("/sys/class/drm")
    if sysfs.is_dir():
        for connector in sorted(sysfs.glob("card*-*")):
            status = read(str(connector / "status"))
            if status is None:
                continue
            modes = read(str(connector / "modes")) or ""
            outputs.append(
                {
                    "connector": connector.name,
                    "status": status,
                    "preferredMode": modes.splitlines()[0] if modes else None,
                }
            )
    connected = [o for o in outputs if o["status"] == "connected"]
    modes = {o["preferredMode"] for o in connected if o["preferredMode"]}
    return {
        "connectedOutputs": len(connected),
        "outputs": outputs,
        "mixedResolution": (len(modes) > 1) if len(connected) >= 2 else None,
    }


def collect_tpm() -> dict:
    caps = run("tpm2_getcap", "properties-fixed") or ""
    manufacturer = None
    match = re.search(r'value:\s*"?([A-Za-z0-9]+)"?', caps) if caps else None
    if match:
        manufacturer = match.group(1)

    devices = [p for p in ("/dev/tpm0", "/dev/tpmrm0") if Path(p).exists()]
    version = read("/sys/class/tpm/tpm0/tpm_version_major")
    present = bool(devices)

    # An emulated TPM proves the software path, never the machine.
    swtpm_running = bool(run("bash", "-lc", "pgrep -x swtpm >/dev/null && echo yes"))
    physical = present and not swtpm_running and detect_hypervisor() is None

    return {
        "present": present,
        "version": f"{version}.0" if version else ("2.0" if caps else None),
        "manufacturer": manufacturer,
        "physical": physical,
    }


def user_unit_active(unit: str) -> bool:
    return run("systemctl", "--user", "is-active", unit) == "active"


def collect(environment_id: str, operator: str, role: str) -> dict:
    osrel = {}
    for line in (read("/etc/os-release") or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            osrel[key] = value.strip('"')

    lscpu = run("lscpu") or ""
    cpu_model = next((l.split(":", 1)[1].strip() for l in lscpu.splitlines() if l.startswith("Model name")), "unknown")
    flags = next((l.split(":", 1)[1] for l in lscpu.splitlines() if l.startswith("Flags")), "")
    virt_flag = "vmx" if " vmx" in flags else ("svm" if " svm" in flags else None)

    meminfo = read("/proc/meminfo") or ""
    total_kb = next((int(l.split()[1]) for l in meminfo.splitlines() if l.startswith("MemTotal")), 0)

    evidence_root = os.environ.get("BUNNY_EVIDENCE_ROOT", "/var/lib/bunny-qualification")
    target = Path(evidence_root) if Path(evidence_root).exists() else Path.home()
    usage = shutil.disk_usage(target)

    sb = run("mokutil", "--sb-state") or ""
    if "enabled" in sb.lower():
        secure_boot = "enabled"
    elif "disabled" in sb.lower():
        secure_boot = "disabled"
    elif sb:
        secure_boot = "unsupported"
    else:
        secure_boot = "unknown"

    session_type = os.environ.get("XDG_SESSION_TYPE") or "unknown"
    if session_type not in {"wayland", "x11", "tty"}:
        session_type = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "unknown"

    portal_backends = []
    for backend in ("xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk"):
        if shutil.which(backend) or Path(f"/usr/libexec/{backend}").exists():
            portal_backends.append(backend)

    input_methods = [name for name in ("ibus", "fcitx5") if shutil.which(name)]
    engines = (run("ibus", "list-engine") or "").splitlines()[:40]

    cryptsetup = version_of("cryptsetup")
    luks2 = bool(cryptsetup) and bool(run("bash", "-lc", "cryptsetup --help | grep -q luks2 && echo yes"))

    tooling = {}
    for binary in ("git", "cargo", "rustc", "gcc", "meson", "ninja", "podman",
                   "qemu-system-x86_64", "virsh", "python3", "swtpm", "tpm2_getcap",
                   "Xwayland", "pipewire", "wireplumber", "orca", "spd-say", "syft", "grype"):
        tooling[binary] = version_of(binary) if shutil.which(binary) else None

    return {
        "schemaVersion": 1,
        "environmentId": environment_id,
        "role": role,
        "collectedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "operator": operator,
        "host": {
            "hostname": run("hostname") or "unknown",
            "manufacturer": read("/sys/class/dmi/id/sys_vendor") or "unknown",
            "model": read("/sys/class/dmi/id/product_name") or "unknown",
            "serialHash": hashed(read("/sys/class/dmi/id/product_serial")),
            "bareMetal": detect_hypervisor() is None,
            "hypervisorDetected": detect_hypervisor(),
        },
        "os": {
            "name": osrel.get("NAME", "unknown"),
            "versionId": osrel.get("VERSION_ID", "unknown"),
            "kernel": read("/proc/sys/kernel/osrelease") or "unknown",
            "isoDigest": os.environ.get("BUNNY_FEDORA_ISO_DIGEST"),
            "installedOn": os.environ.get("BUNNY_HOST_INSTALLED_ON"),
        },
        "boot": {
            "mode": "uefi" if Path("/sys/firmware/efi").exists() else "bios",
            "secureBoot": secure_boot,
            "platformSize": int(read("/sys/firmware/efi/fw_platform_size") or 0) or None,
        },
        "cpu": {"model": cpu_model, "logicalCores": os.cpu_count() or 0, "virtualisationFlag": virt_flag},
        "memory": {"totalBytes": total_kb * 1024},
        "storage": {
            "availableBytesForEvidence": usage.free,
            "devices": [
                {"name": line.split()[0], "size": line.split()[-1]}
                for line in (run("lsblk", "-dn", "-o", "NAME,SIZE") or "").splitlines()
                if line.strip()
            ],
        },
        "graphics": collect_graphics(),
        "displays": collect_displays(),
        "tpm": collect_tpm(),
        "virtualisation": {
            "kvmAvailable": Path("/dev/kvm").exists(),
            "virtHostValidate": run("virt-host-validate"),
            "qemuVersion": version_of("qemu-system-x86_64"),
            "libvirtVersion": version_of("virsh"),
        },
        "selinux": {"mode": (run("getenforce") or "unknown")},
        "session": {
            "type": session_type,
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
            "pipewire": user_unit_active("pipewire"),
            "wireplumber": user_unit_active("wireplumber"),
            "portal": user_unit_active("xdg-desktop-portal"),
            "portalBackends": portal_backends,
        },
        "audio": {"devices": (run("bash", "-lc", "pactl list short sinks 2>/dev/null | cut -f2") or "").splitlines()},
        "accessibility": {
            "orcaInstalled": bool(shutil.which("orca")),
            "orcaVersion": version_of("orca"),
            "speechDispatcherInstalled": bool(shutil.which("spd-say")),
            "speechDispatcherVersion": version_of("spd-say"),
            "atspiPresent": bool(run("pkg-config", "--exists", "atspi-2") is not None and shutil.which("pkg-config")),
        },
        "inputMethod": {
            "available": input_methods,
            "ibusVersion": version_of("ibus", "version"),
            "fcitx5Version": version_of("fcitx5"),
            "engines": engines,
        },
        "crypto": {
            "cryptsetupVersion": cryptsetup,
            "luks2Supported": luks2,
            "argon2idAvailable": bool(run("bash", "-lc", "cryptsetup benchmark 2>/dev/null | grep -qi argon2id && echo yes")),
        },
        "tooling": tooling,
        "git": {
            "version": version_of("git") or "unknown",
            "autocrlf": run("git", "config", "--get", "core.autocrlf"),
            "byteRoundtripTestsPass": None,
        },
        "clock": {
            "synchronised": "synchronized: yes" in (run("timedatectl") or "").lower()
            or "System clock synchronized: yes" in (run("timedatectl") or ""),
            "timezone": next(
                (l.split(":", 1)[1].strip() for l in (run("timedatectl") or "").splitlines() if "Time zone" in l),
                None,
            ),
            "systemTime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--role", default="host", choices=("host", "vm-qualification", "physical-target"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = collect(args.environment_id, args.operator, args.role)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    print(f"wrote {args.output}")
    print(f"  host:     {report['host']['manufacturer']} {report['host']['model']}")
    print(f"  bareMetal:{report['host']['bareMetal']}  hypervisor={report['host']['hypervisorDetected']}")
    print(f"  renderer: {report['graphics']['openglRenderer']}")
    print(f"  software rasteriser: {report['graphics']['softwareRasteriser']}")
    print(f"  connected outputs:   {report['displays']['connectedOutputs']}")
    print("\nThis is an observation of the host. It qualifies nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
