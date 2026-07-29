"""Local-only hardware and OS capability discovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any

from . import CONTRACT_VERSION


_VENDORS = {"0x8086": "intel", "0x1002": "amd", "0x10de": "nvidia", "0x1af4": "virtio", "0x1234": "qemu"}
_ENV = {"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _architecture() -> str:
    value = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(value, "unknown")


def _memory() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in _read(Path("/proc/meminfo")).splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        number = raw.strip().split()[0]
        if number.isdigit():
            values[key] = int(number) * 1024
    return {"totalBytes": values.get("MemTotal", 0), "availableBytes": values.get("MemAvailable", 0)}


def _cpu() -> dict[str, Any]:
    content = _read(Path("/proc/cpuinfo"))
    flags: set[str] = set()
    model = platform.processor() or "unknown"
    for line in content.splitlines():
        if line.lower().startswith(("flags", "features")) and ":" in line:
            flags.update(line.split(":", 1)[1].split())
        if model == "unknown" and line.lower().startswith("model name") and ":" in line:
            model = line.split(":", 1)[1].strip()
    relevant = sorted(flags.intersection({"avx", "avx2", "avx512f", "sse4_2", "aes", "fma", "neon", "asimd", "hypervisor"}))
    return {"model": model, "logicalCpus": os.cpu_count() or 0, "features": relevant}


def _secure_boot() -> tuple[bool, str]:
    variables = list(Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"))
    if not variables:
        return False, "not-detected"
    try:
        data = variables[0].read_bytes()
        return len(data) >= 5 and data[4] == 1, "efi-variable"
    except OSError:
        return False, "unreadable"


def _gpus() -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        device = card / "device"
        vendor_id = _read(device / "vendor", "unknown")
        device_id = _read(device / "device", "unknown")
        driver_link = device / "driver"
        driver = ""
        try:
            driver = driver_link.resolve(strict=True).name
        except OSError:
            pass
        render_nodes = sorted(item.name for item in (device / "drm").glob("renderD*"))
        state = "driver-active" if driver and render_nodes else ("driver-available" if driver else "detected")
        evidence = [f"pci-vendor={vendor_id}", f"pci-device={device_id}"]
        if driver:
            evidence.append(f"driver={driver}")
        if render_nodes:
            evidence.append("render-node-present")
        values.append({
            "name": f"{_VENDORS.get(vendor_id.lower(), 'unknown')}:{device_id}",
            "vendor": _VENDORS.get(vendor_id.lower(), "unknown"),
            "device": device_id,
            "driver": driver or None,
            "state": state,
            "evidence": evidence,
        })
    return values


def _fixed_probe(argv: list[str], timeout: int = 5) -> bool:
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_ENV,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _graphics_apis() -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    vulkan = shutil.which("vulkaninfo")
    vulkan_verified = bool(vulkan and _fixed_probe([vulkan, "--summary"]))
    values.append({
        "name": "vulkan",
        "state": "runtime-verified" if vulkan_verified else ("driver-available" if vulkan else "unknown"),
        "evidence": [f"vulkaninfo={'present' if vulkan else 'absent'}", f"probe-success={str(vulkan_verified).lower()}"],
    })
    egl = Path("/usr/lib64/libEGL.so.1").exists() or Path("/usr/lib/libEGL.so.1").exists()
    values.append({"name": "egl", "state": "driver-available" if egl else "unknown", "evidence": [f"loader={'present' if egl else 'absent'}", "runtime-probe-not-run"]})
    return values


def _sandbox() -> list[dict[str, Any]]:
    backends: list[dict[str, Any]] = []
    max_user_ns = int(_read(Path("/proc/sys/user/max_user_namespaces"), "0") or "0")
    bwrap = shutil.which("bwrap")
    bwrap_verified = bool(bwrap and max_user_ns > 0 and _fixed_probe([bwrap, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr", "/usr/bin/true"]))
    backends.append({
        "name": "bubblewrap",
        "state": "runtime-verified" if bwrap_verified else ("driver-available" if bwrap else "unsupported"),
        "evidence": [f"binary={'present' if bwrap else 'absent'}", f"max-user-namespaces={max_user_ns}", f"probe-success={str(bwrap_verified).lower()}"],
    })
    landlock = Path("/sys/kernel/security/landlock").exists()
    backends.append({"name": "landlock", "state": "detected" if landlock else "unknown", "evidence": [f"securityfs={'present' if landlock else 'not-observed'}"]})
    podman = shutil.which("podman")
    backends.append({"name": "rootless-oci", "state": "driver-available" if podman else "unsupported", "evidence": [f"podman={'present' if podman else 'absent'}"]})
    return backends


def _virtualization(cpu: dict[str, Any]) -> dict[str, Any]:
    product = _read(Path("/sys/class/dmi/id/product_name"), "unknown")
    vendor = _read(Path("/sys/class/dmi/id/sys_vendor"), "unknown")
    detected = "hypervisor" in cpu["features"] or any(word in f"{vendor} {product}".lower() for word in ("qemu", "kvm", "virtualbox", "vmware", "hyper-v"))
    return {"detected": detected, "vendor": vendor, "product": product}


def _battery() -> dict[str, Any]:
    batteries = list(Path("/sys/class/power_supply").glob("BAT*"))
    if not batteries:
        return {"present": False}
    first = batteries[0]
    capacity = _read(first / "capacity")
    return {"present": True, "state": _read(first / "status", "unknown"), "capacityPercent": int(capacity) if capacity.isdigit() else None}


def _network() -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in sorted(Path("/sys/class/net").glob("*")):
        result.append({"name": item.name, "state": _read(item / "operstate", "unknown"), "kind": "loopback" if item.name == "lo" else "network"})
    return result


def _storage() -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    for item in sorted(Path("/sys/class/block").glob("*")):
        if item.name.startswith(("loop", "ram", "zram")):
            continue
        sectors = _read(item / "size", "0")
        removable = _read(item / "removable", "0") == "1"
        rotational = _read(item / "queue/rotational", "0") == "1"
        devices.append({
            "name": item.name,
            "sizeBytes": int(sectors) * 512 if sectors.isdigit() else 0,
            "removable": removable,
            "rotational": rotational,
            "state": "detected",
        })
    usage = shutil.disk_usage("/")
    return {"root": {"totalBytes": usage.total, "usedBytes": usage.used, "freeBytes": usage.free}, "devices": devices}


def _model_suitability(memory: dict[str, int], gpus: list[dict[str, Any]]) -> dict[str, Any]:
    gib = memory["totalBytes"] / (1024 ** 3) if memory["totalBytes"] else 0
    active_gpu = any(gpu["state"] in {"driver-active", "runtime-verified"} for gpu in gpus)
    if gib >= 32 and active_gpu:
        tier = "candidate-20b-moe"
    elif gib >= 16:
        tier = "candidate-small-local"
    else:
        tier = "classification-only-or-hosted"
    return {
        "assessment": tier,
        "verified": False,
        "reasons": [f"system-memory-gib={gib:.1f}", f"active-gpu={str(active_gpu).lower()}", "runtime-benchmark-not-run"],
    }


def inventory() -> dict[str, Any]:
    release = _json(Path("/usr/lib/bunny-os/release.json"))
    artifact = _json(Path("/usr/share/bunny-os/bunny-artifact.json"))
    memory = _memory()
    cpu = _cpu()
    gpus = _gpus()
    graphics_apis = _graphics_apis()
    sandbox = _sandbox()
    secure_boot, secure_boot_evidence = _secure_boot()
    tpm = Path("/sys/class/tpm/tpm0").exists()
    architecture = _architecture()
    os_version = str(release.get("osVersion", "0.1.0"))
    image_version = str(release.get("imageVersion", "unknown"))
    contract_capabilities = {
        "kind": "capabilities",
        "contractVersion": CONTRACT_VERSION,
        "osVersion": os_version,
        "imageVersion": image_version,
        "architecture": architecture,
        "secureBoot": secure_boot,
        "tpmAvailable": tpm,
        "sandboxBackends": sandbox,
        "gpuCapabilities": [{"name": gpu["name"], "state": gpu["state"], "evidence": gpu["evidence"]} for gpu in gpus],
        "updateBackend": "bootc",
        "recoveryAvailable": Path("/usr/lib/systemd/system/bunny-recovery.target").exists(),
        "privilegedBrokerVersion": "0.1.0",
        "bunnyProtocolVersions": [3],
        "desktopIntegration": {
            "packaging": "versioned-opt" if artifact.get("status") == "verified" else "placeholder",
            "artifactStatus": artifact.get("status", "absent"),
            "launcher": "art.comrade.Bunny.desktop",
            "urlScheme": "bunny",
            "notifications": "freedesktop",
            "fileDialogs": "xdg-desktop-portal",
        },
    }
    return {
        "schemaVersion": 1,
        "contractCapabilities": contract_capabilities,
        "cpu": cpu,
        "memory": memory,
        "storage": _storage(),
        "gpu": gpus,
        "graphicsApis": graphics_apis,
        "virtualization": _virtualization(cpu),
        "battery": _battery(),
        "networkInterfaces": _network(),
        "secureBoot": {"enabled": secure_boot, "evidence": secure_boot_evidence, "tested": False},
        "tpm": {"available": tpm, "usedByBunny": False},
        "sandbox": sandbox,
        "container": {"podmanAvailable": shutil.which("podman") is not None},
        "hardwareAcceleration": {"detected": any(gpu["state"] == "driver-active" for gpu in gpus), "runtimeVerified": any(item["state"] == "runtime-verified" for item in graphics_apis)},
        "localModelSuitability": _model_suitability(memory, gpus),
        "privacy": {"transmitted": False},
    }


def human(value: dict[str, Any]) -> str:
    caps = value["contractCapabilities"]
    gpu = ", ".join(f"{item['name']} ({item['state']})" for item in value["gpu"]) or "none detected"
    mem_gib = value["memory"]["totalBytes"] / (1024 ** 3) if value["memory"]["totalBytes"] else 0
    return "\n".join([
        f"Bunny OS {caps['osVersion']} image {caps['imageVersion']}",
        f"Architecture: {caps['architecture']}",
        f"CPU: {value['cpu']['model']} ({value['cpu']['logicalCpus']} logical)",
        f"Memory: {mem_gib:.1f} GiB",
        f"GPU: {gpu}",
        f"Secure Boot detected enabled: {str(caps['secureBoot']).lower()} (not qualification evidence)",
        f"TPM available: {str(caps['tpmAvailable']).lower()}",
        f"Local model assessment: {value['localModelSuitability']['assessment']} (benchmark unverified)",
        "Inventory remains local and is not transmitted.",
    ])
