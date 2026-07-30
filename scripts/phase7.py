#!/usr/bin/env python3
"""Repository-native Bunny OS Phase 7 commands.

Gate structure mirrors Phase 5. A *source* gate can pass on any development host
because it checks source, schemas, documents, and tests. Every *pilot* gate is
fail-closed and depends on a published, signed stable release that does not
exist, so those gates report NO-GO rather than printing success.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from enterprise.fleet import RingConfiguration, eligible_device_count, parse_ring
from enterprise.pilot import PILOT_ENTRY_GATES, evaluate_pilot
from enterprise.tenancy import ISOLATION_REQUIREMENTS, evaluate_isolation

DATA = ROOT / "operations/data"

PHASE7_DOCS = (
    "docs/PHASE_7_BASELINE.md",
    "docs/OEM_PROGRAMME.md",
    "docs/OEM_PROFILES.md",
    "docs/FACTORY_PROVISIONING.md",
    "docs/DEVICE_IDENTITY.md",
    "docs/DEVICE_ATTESTATION.md",
    "docs/ENTERPRISE_ENROLMENT.md",
    "docs/DEVICE_POLICY.md",
    "docs/FLEET_UPDATES.md",
    "docs/REMOTE_ADMINISTRATION.md",
    "docs/REMOTE_WIPE.md",
    "docs/ENTERPRISE_APPLICATIONS.md",
    "docs/FLEET_PRIVACY.md",
    "docs/ENTERPRISE_AUDIT.md",
    "docs/ENCRYPTED_SYNC.md",
    "docs/SYNC_CRYPTOGRAPHY.md",
    "docs/SYNC_RECOVERY.md",
    "docs/DEVICE_PAIRING.md",
    "docs/DATA_DELETION.md",
    "docs/AIR_GAPPED_MANAGEMENT.md",
    "docs/KIOSK_MODE.md",
    "docs/DEVICE_DECOMMISSIONING.md",
    "docs/PILOT_PROGRAMME.md",
    "docs/SUSTAINABILITY.md",
    "docs/ENTERPRISE_THREAT_MODEL.md",
    "docs/adr/ADR-020-end-to-end-encrypted-sync.md",
    "docs/adr/ADR-021-device-identity.md",
    "docs/adr/ADR-022-enterprise-policy-agent.md",
    "docs/adr/ADR-023-fleet-control-plane.md",
    "docs/adr/ADR-024-multi-tenant-isolation.md",
    "docs/adr/ADR-025-oem-profile-trust.md",
    "docs/adr/ADR-026-remote-administration-boundary.md",
    "PHASE_7_REPORT.md",
    "OEM_READINESS_REPORT.md",
    "FACTORY_PROVISIONING_SECURITY_REVIEW.md",
    "ENTERPRISE_ARCHITECTURE_REPORT.md",
    "FLEET_SECURITY_REVIEW.md",
    "MULTITENANCY_TEST_REPORT.md",
    "ENCRYPTED_SYNC_SECURITY_REVIEW.md",
    "ENCRYPTED_SYNC_PRIVACY_REVIEW.md",
    "AIR_GAPPED_MANAGEMENT_REPORT.md",
    "PILOT_READINESS_REPORT.md",
    "SUSTAINABILITY_REPORT.md",
    "PHASE_7_SECURITY_REVIEW.md",
    "PHASE_7_PRIVACY_REVIEW.md",
    "THIRD_PARTY_NOTICES.md",
    "LICENSE_COMPLIANCE_REPORT.md",
)

PHASE7_DEMOS = (
    "README.md",
    "build-oem-image.md",
    "factory-provisioning.md",
    "enrol-device.md",
    "apply-policy.md",
    "update-ring.md",
    "deploy-application.md",
    "offline-policy.md",
    "device-pairing.md",
    "encrypted-sync.md",
    "device-revocation.md",
    "remote-wipe-simulation.md",
    "decommission-device.md",
    "security-demo.md",
    "privacy-demo.md",
    "demo-10-minutes.md",
    "demo-30-minutes.md",
    "demo-60-minutes.md",
)

PHASE7_SCHEMAS = (
    "schemas/oem-profile.schema.json",
    "schemas/oem-qualification.schema.json",
    "schemas/device-identity.schema.json",
    "schemas/device-attestation.schema.json",
    "schemas/enrolment-message.schema.json",
    "schemas/device-policy.schema.json",
    "schemas/fleet-health.schema.json",
    "schemas/fleet-audit.schema.json",
    "schemas/organisation-catalogue.schema.json",
    "schemas/sync-envelope.schema.json",
    "schemas/offline-policy-bundle.schema.json",
)

BASELINE_FIELDS = (
    "stable version",
    "supported architectures",
    "current hardware tiers",
    "oem readiness",
    "device identity readiness",
    "multi-device data model",
    "enterprise-management gaps",
    "cloud-service gaps",
    "privacy risks",
    "security risks",
    "legal and licensing risks",
    "operational capacity",
    "estimated maintenance burden",
    "phase 7 blockers",
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def audit() -> int:
    missing = [name for name in PHASE7_DOCS if not (ROOT / name).is_file()]
    demo_root = ROOT / "demos/07-oem-enterprise-sync"
    missing.extend(
        f"demos/07-oem-enterprise-sync/{name}" for name in PHASE7_DEMOS if not (demo_root / name).is_file()
    )
    missing.extend(name for name in PHASE7_SCHEMAS if not (ROOT / name).is_file())
    if missing:
        print("Phase 7 audit BLOCKED; missing:")
        print("\n".join(missing))
        return 2
    print(
        f"phase7-audit: {len(PHASE7_DOCS)} documents, {len(PHASE7_DEMOS)} demonstrations, "
        f"and {len(PHASE7_SCHEMAS)} schemas present"
    )
    return 0


def baseline() -> int:
    path = ROOT / "docs/PHASE_7_BASELINE.md"
    if not path.is_file():
        print("missing docs/PHASE_7_BASELINE.md")
        return 2
    text = path.read_text(encoding="utf-8").casefold()
    missing = [field for field in BASELINE_FIELDS if field not in text]
    if missing:
        print("Phase 7 baseline missing fields: " + ", ".join(missing))
        return 2
    print(f"Phase 7 baseline contains all {len(BASELINE_FIELDS)} mandatory fields")
    return 0


def source_gate() -> int:
    """Structural checks over the Phase 7 evidence data and separation rules."""
    readiness = load(DATA / "phase7-readiness.json")
    if readiness.get("schemaVersion") != 1:
        raise SystemExit("phase7-readiness.json schemaVersion is invalid")
    unknown = sorted(set(readiness.get("entryGates", {})) - set(PILOT_ENTRY_GATES))
    if unknown:
        raise SystemExit("phase7-readiness.json declares unknown entry gates: " + ", ".join(unknown))
    missing = sorted(set(PILOT_ENTRY_GATES) - set(readiness.get("entryGates", {})))
    if missing:
        raise SystemExit("phase7-readiness.json is missing entry gates: " + ", ".join(missing))
    if readiness.get("recommendation") != "NO-GO":
        raise SystemExit(
            "phase7-readiness.json claims a recommendation other than NO-GO; a pilot recommendation "
            "requires a published stable release and completed reviews"
        )

    isolation = load(DATA / "phase7-multitenancy.json")
    verdict = evaluate_isolation(isolation["controls"])
    if not verdict.isolated:
        print(
            "multi-tenant isolation evidence incomplete: "
            + ", ".join([*verdict.missingEvidence, *verdict.failedControls])
        )
        return 2

    keys = load(DATA / "phase7-key-separation.json")
    namespaces = keys.get("namespaces", {})
    required = {"osUpdate", "releaseArtifact", "oemProfile", "fleetControl", "syncDevice"}
    if set(namespaces) != required:
        raise SystemExit("phase7-key-separation.json must declare exactly: " + ", ".join(sorted(required)))
    prefixes = [value.get("prefix") for value in namespaces.values()]
    if len(set(prefixes)) != len(prefixes):
        raise SystemExit("signing key namespaces must not share a prefix")
    for name, value in namespaces.items():
        if value.get("privateKeyInRepository") is not False:
            raise SystemExit(f"{name} declares a private key in the repository")

    print(
        f"Phase 7 source gate passed: {len(ISOLATION_REQUIREMENTS)} isolation controls evidenced, "
        f"{len(namespaces)} separated signing namespaces, pilot recommendation NO-GO recorded. "
        "This is not a pilot approval."
    )
    return 0


def fleet_simulation(devices: int) -> int:
    """Deterministic ring rollout simulation over synthetic device counts."""
    if devices < 1:
        raise SystemExit("device count must be at least 1")
    stages = [
        parse_ring({"schemaVersion": 1, "ring": "internal-test", "rolloutPercentage": 100}),
        parse_ring({"schemaVersion": 1, "ring": "early-validation", "rolloutPercentage": 10}),
        parse_ring({"schemaVersion": 1, "ring": "general-deployment", "rolloutPercentage": 50}),
        parse_ring({"schemaVersion": 1, "ring": "general-deployment", "rolloutPercentage": 100}),
        parse_ring({"schemaVersion": 1, "ring": "general-deployment", "rolloutPercentage": 100, "paused": True}),
        parse_ring({"schemaVersion": 1, "ring": "general-deployment", "rolloutPercentage": 0, "withdrawn": True}),
    ]
    rows = []
    for index, configuration in enumerate(stages, start=1):
        offered = eligible_device_count(devices, configuration)
        rows.append({
            "step": index,
            "ring": configuration.ring,
            "rolloutPercentage": configuration.rolloutPercentage,
            "paused": configuration.paused,
            "withdrawn": configuration.withdrawn,
            "devicesOffered": offered,
            "signatureVerificationRequired": configuration.signatureVerificationRequired,
        })
    output = ROOT / "build/out/phase7/fleet-simulation.json"
    atomic_json(output, {
        "schemaVersion": 1,
        "deviceCount": devices,
        "steps": rows,
        "simulated": True,
        "note": (
            "Simulated rollout arithmetic only. No device, image, signature, or network operation "
            "occurred. Simulation is never production-readiness evidence."
        ),
    })
    for row in rows:
        print(
            f"step {row['step']}: ring={row['ring']} rollout={row['rolloutPercentage']}% "
            f"paused={row['paused']} withdrawn={row['withdrawn']} offered={row['devicesOffered']}"
        )
    print(f"wrote {output}; this is a simulation and not production readiness evidence")
    return 0


def pilot_readiness() -> int:
    evidence = load(DATA / "phase7-readiness.json")
    readiness = evaluate_pilot(
        {"pilot": "internal-pilot", **evidence["pilotDefinition"]},
        evidence["entryGates"],
    )
    payload = readiness.as_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    if readiness.ready:
        print("pilot readiness reports GO; confirm independently before enrolling any real device")
        return 0
    print(
        "pilot readiness: NO-GO. Unmet gates: "
        + ", ".join([*readiness.failedGates, *readiness.missingGates])
    )
    return 2


def pilot_gate(kind: str) -> int:
    evidence = load(DATA / "phase7-readiness.json")
    gates = evidence["entryGates"]
    required = {
        "oem": (
            "stableReleasePublished", "signedStableArtifacts", "reproducibleBuildEvidence",
            "oemRecoveryValidation", "phase7SecurityReview",
        ),
        "enterprise": (
            "stableReleasePublished", "signedStableArtifacts", "postReleaseSecurityReview",
            "postReleasePrivacyReview", "multiTenancyIsolationTests", "phase7SecurityReview",
            "phase7PrivacyReview", "supportCapacityConfirmed",
        ),
        "sync": (
            "stableReleasePublished", "signedStableArtifacts", "syncCryptographyIndependentReview",
            "phase7SecurityReview", "phase7PrivacyReview", "supportCapacityConfirmed",
        ),
    }[kind]
    unmet = [name for name in required if gates.get(name) is not True]
    if unmet:
        print(f"{kind} pilot gate BLOCKED. Unmet gates:")
        for name in unmet:
            note = evidence.get("entryGateNotes", {}).get(name, "no note recorded")
            print(f"  - {name}: {note}")
        print(
            f"Do not begin a {kind} pilot, manufacture devices, deploy fleets, or launch a hosted "
            "service while any gate above is unmet."
        )
        return 2
    print(f"{kind} pilot gate passed; a controlled pilot may be proposed for separate approval")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("audit", "baseline", "source-gate", "pilot-readiness"):
        commands.add_parser(name)
    simulation = commands.add_parser("fleet-simulation")
    simulation.add_argument("--devices", type=int, default=500)
    gate = commands.add_parser("pilot-gate")
    gate.add_argument("--kind", choices=("oem", "enterprise", "sync"), required=True)
    args = parser.parse_args()
    if args.command == "audit":
        return audit()
    if args.command == "baseline":
        return baseline()
    if args.command == "source-gate":
        return source_gate()
    if args.command == "fleet-simulation":
        return fleet_simulation(args.devices)
    if args.command == "pilot-readiness":
        return pilot_readiness()
    if args.command == "pilot-gate":
        return pilot_gate(args.kind)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
