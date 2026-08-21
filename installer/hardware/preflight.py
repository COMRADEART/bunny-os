# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware classification without turning detection into support claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import platform
from typing import Iterable


STATUSES = frozenset({"supported", "supported_with_limitations", "experimental", "unsupported", "unknown"})


@dataclass(frozen=True)
class HardwareItem:
    category: str
    identifier: str
    status: str
    evidence: tuple[str, ...]
    limitation: str | None = None

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["evidence"] = list(self.evidence)
        return value


def classify(
    *,
    architecture: str,
    ram_bytes: int,
    storage_bytes: int,
    firmware_mode: str,
    secure_boot: str,
    tpm_present: bool,
    pci_devices: Iterable[tuple[str, str, str]] = (),
) -> dict[str, object]:
    items: list[HardwareItem] = []
    arch_status = "supported_with_limitations" if architecture in {"x86_64", "amd64"} else "unsupported"
    items.append(HardwareItem("architecture", architecture, arch_status, ("x86-64 is the only Phase 3 target",)))
    ram_gib = ram_bytes / (1024**3)
    ram_status = "supported_with_limitations" if ram_gib >= 8 else "unsupported" if ram_gib < 4 else "experimental"
    items.append(HardwareItem("memory", f"{ram_gib:.1f} GiB", ram_status, ("capacity detected",), "Local-model suitability is not inferred."))
    storage_gib = storage_bytes / (1024**3)
    storage_status = "supported_with_limitations" if storage_gib >= 64 else "unsupported" if storage_gib < 40 else "experimental"
    items.append(HardwareItem("storage", f"{storage_gib:.1f} GiB", storage_status, ("target capacity detected",)))
    items.append(HardwareItem("firmware", firmware_mode, "supported_with_limitations" if firmware_mode == "uefi" else "unsupported", ("legacy BIOS is not supported",)))
    sb_status = "unknown" if secure_boot == "unknown" else "supported_with_limitations"
    items.append(HardwareItem("secure_boot", secure_boot, sb_status, ("state detection only; derived boot chain unqualified",)))
    items.append(HardwareItem("tpm", "present" if tpm_present else "absent", "experimental" if tpm_present else "unknown", ("TPM unlock remains opt-in and unqualified",)))
    for category, vendor, device in pci_devices:
        vendor_lower = vendor.lower()
        if category == "graphics" and any(name in vendor_lower for name in ("intel", "amd", "red hat", "virtio")):
            status = "supported_with_limitations"
            limitation = "Open driver path selected; physical execution is still untested."
        elif category == "graphics" and "nvidia" in vendor_lower:
            status = "experimental"
            limitation = "Proprietary NVIDIA drivers are not bundled; safe graphics remains available."
        else:
            status = "unknown"
            limitation = "Detection is not hardware qualification."
        items.append(HardwareItem(category, f"{vendor} {device}".strip(), status, ("PCI inventory",), limitation))
    return {
        "schemaVersion": 1,
        "hostArchitecture": platform.machine() or architecture,
        "overall": "unsupported" if any(item.status == "unsupported" for item in items) else "supported_with_limitations",
        "items": [item.to_dict() for item in items],
        "physicalHardwareCertified": False,
    }


#: The smallest display the graphical setup surface is qualified on.
#:
#: Declared here because nothing declared it before, and §39 requires setup to
#: remain usable at 200 % text — which is a question about how many pixels the
#: screen has, not about the stylesheet. Anaconda's own documented floor is
#: 800x600; claiming that for Bunny would be dishonest, because at 200 % text a
#: 600px-tall surface cannot show a destructive warning and its confirmation
#: control at the same time, and §39 forbids hiding destructive-warning text.
#:
#: The story harness measures its overflow findings against this width, so a
#: change here changes what the harness considers off-screen.
MINIMUM_SETUP_DISPLAY = {"width": 1024, "height": 768}


def minimum_requirements() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "setupDisplay": {
            **MINIMUM_SETUP_DISPLAY,
            "note": "The graphical setup surface is qualified at this size and above, "
                    "including at 200% text scaling.",
        },
        "profiles": {
            "base_desktop": {"ramGiB": {"minimum": 4, "recommended": 8}, "storageGiB": {"minimum": 40, "recommended": 64}, "firmware": "UEFI x86-64"},
            "cloud_models": {"ramGiB": {"minimum": 8, "recommended": 16}, "storageGiB": {"minimum": 64, "recommended": 96}, "network": "required only while using configured providers"},
            "small_local_models": {"ramGiB": {"minimum": 16, "recommended": 24}, "storageGiB": {"minimum": 96, "recommended": 128}, "benchmark": "required before capability claim"},
            "medium_local_models": {"ramGiB": {"minimum": 32, "recommended": 64}, "storageGiB": {"minimum": 160, "recommended": 256}, "benchmark": "required before capability claim"},
            "developer": {"ramGiB": {"minimum": 16, "recommended": 32}, "storageGiB": {"minimum": 128, "recommended": 256}},
        },
        "benchmarkClaim": "No local-model throughput benchmark is asserted.",
    }

