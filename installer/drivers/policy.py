"""Conservative Fedora-only driver recommendations."""

from __future__ import annotations


def graphics_driver(vendor: str, *, secure_boot: str) -> dict[str, object]:
    normalized = vendor.lower()
    if "intel" in normalized:
        return {"driver": "i915/xe + Mesa", "source": "Fedora image", "status": "supported_with_limitations", "requiresRestart": False}
    if "amd" in normalized or "advanced micro devices" in normalized:
        return {"driver": "amdgpu + Mesa", "source": "Fedora image", "status": "supported_with_limitations", "requiresRestart": False}
    if "virtio" in normalized or "red hat" in normalized:
        return {"driver": "virtio_gpu + Mesa", "source": "Fedora image", "status": "supported_with_limitations", "requiresRestart": False}
    if "nvidia" in normalized:
        return {
            "driver": "nouveau/open path",
            "source": "Fedora image",
            "status": "experimental",
            "requiresRestart": True,
            "secureBoot": secure_boot,
            "proprietaryOffered": False,
            "reason": "Redistribution, exact branch, kernel, Wayland, signing, and rollback are not qualified.",
        }
    return {"driver": "software rendering fallback", "source": "Fedora Mesa", "status": "unknown", "requiresRestart": False}


def firmware_policy() -> dict[str, object]:
    return {
        "allowedSources": ["Fedora signed RPM repositories", "linux-firmware", "fwupd LVFS metadata after explicit action"],
        "arbitraryVendorDownloads": False,
        "offlineIncluded": ["linux-firmware", "CPU microcode selected by Fedora dependency policy"],
        "updatesAutomatic": False,
        "missingFirmwareBlocksInstall": False,
    }

