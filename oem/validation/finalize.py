# SPDX-License-Identifier: Apache-2.0
"""Factory finalisation evaluation for ``bunny-oem finalize``.

``docs/OEM_MODE.md`` already states the intended contract: sealing removes the
OEM account, history, SSH keys, network credentials, test files, logs containing
identifiers, and installer session material, then verifies the first-run marker.
This module turns that prose into a closed set of checks with a fail-closed
evaluator.

Two rules matter more than the individual checks:

* ``UNKNOWN`` is a failure. A check that could not be performed is never treated
  as a pass, matching the repository's existing ``NOT_RUN``-is-blocking stance.
* Every check must be present. A missing check id is a failure, so adding a new
  check cannot silently weaken an older evidence file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
NOT_RUN = "NOT_RUN"

ACCEPTABLE = frozenset({PASS})
STATUSES = frozenset({PASS, FAIL, UNKNOWN, NOT_RUN})


@dataclass(frozen=True)
class FactoryCheck:
    checkId: str
    description: str
    blocking: bool = True


#: Every condition that must hold before a device may leave the factory. Order is
#: the order reported to the operator.
FACTORY_STATE_CHECKS: tuple[FactoryCheck, ...] = (
    FactoryCheck("factory-accounts-removed", "No temporary factory or OEM account remains in /etc/passwd or /etc/shadow"),
    FactoryCheck("factory-groups-removed", "No factory group membership grants residual administrative access"),
    FactoryCheck("factory-autologin-disabled", "No GDM autologin or passwordless session remains configured"),
    FactoryCheck("factory-wifi-profiles-removed", "No factory NetworkManager connection profile or PSK remains"),
    FactoryCheck("factory-ssh-keys-removed", "No factory authorized_keys entry or provisioning SSH key remains"),
    FactoryCheck("test-credentials-removed", "No test provider credential, token, or Secret Service item remains"),
    FactoryCheck("factory-sudo-rules-removed", "No factory sudoers or polkit rule grants unrestricted local root"),
    FactoryCheck("identifier-logs-removed", "No temporary log, journal export, or diagnostic bundle containing device identifiers remains"),
    FactoryCheck("shell-history-cleared", "No shell history remains for root or any factory account"),
    FactoryCheck("installer-session-removed", "No installer transaction journal, answer file, or session artefact remains"),
    FactoryCheck("machine-id-regenerated", "/etc/machine-id is empty or newly generated so first boot derives a fresh value"),
    FactoryCheck("host-keys-regenerated", "SSH host keys are absent or regenerated rather than cloned across units"),
    FactoryCheck("device-identity-absent-or-fresh", "No factory device identity key remains; identity is created on first customer boot"),
    FactoryCheck("enrolment-state-absent", "No enrolment token, certificate, or organisation binding remains from factory testing"),
    FactoryCheck("sync-state-absent", "No sync account, device key, or cached encrypted object remains"),
    FactoryCheck("first-user-setup-incomplete", "The first-run marker records setup as incomplete so the customer creates the first account"),
    FactoryCheck("recovery-verified", "Recovery media or partition boots and its image signature verifies"),
    FactoryCheck("image-signatures-verified", "The installed OS image and every OEM extension verify against their declared trust roots"),
    FactoryCheck("secure-boot-state-recorded", "Secure Boot state is recorded honestly, including 'disabled' or 'unknown'"),
    FactoryCheck("tpm-state-recorded", "TPM presence and state are recorded honestly, including 'absent'"),
    FactoryCheck("burn-in-completed", "Burn-in and storage validation completed without unrecovered error"),
    FactoryCheck("diagnostic-serials-not-retained", "No retained diagnostic record contains a hardware serial or per-unit identifier"),
)

CHECK_IDS = tuple(check.checkId for check in FACTORY_STATE_CHECKS)
_CHECKS_BY_ID = {check.checkId: check for check in FACTORY_STATE_CHECKS}


@dataclass(frozen=True)
class FinalisationVerdict:
    """Whether one device may be handed to a customer."""

    deviceRecordId: str
    sealed: bool
    failures: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    passed: tuple[str, ...] = ()

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(sorted({*self.failures, *self.missing, *self.unknown}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "deviceRecordId": self.deviceRecordId,
            "sealed": self.sealed,
            "failedChecks": list(self.failures),
            "missingChecks": list(self.missing),
            "unknownChecks": list(self.unknown),
            "passedChecks": list(self.passed),
            "blockers": list(self.blockers),
        }


def evaluate_finalisation(
    record: Mapping[str, Any],
    *,
    required_checks: Iterable[str] | None = None,
) -> FinalisationVerdict:
    """Evaluate a factory finalisation record.

    ``record`` has the shape ``{"schemaVersion": 1, "deviceRecordId": str,
    "checks": {checkId: status}}``. Unknown check ids are rejected so a typo
    cannot masquerade as a passing check.
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    if record.get("schemaVersion") != 1:
        raise ValueError(f"unsupported factory record schemaVersion {record.get('schemaVersion')!r}")

    device_record_id = record.get("deviceRecordId")
    if not isinstance(device_record_id, str) or not device_record_id:
        raise ValueError("deviceRecordId is required")

    checks = record.get("checks")
    if not isinstance(checks, Mapping):
        raise ValueError("checks must be an object mapping check ids to statuses")

    expected = tuple(required_checks) if required_checks is not None else CHECK_IDS
    unexpected = sorted(set(checks) - set(_CHECKS_BY_ID))
    if unexpected:
        raise ValueError("unknown factory check ids: " + ", ".join(unexpected))

    bad_status = sorted(
        f"{key}={value!r}" for key, value in checks.items() if value not in STATUSES
    )
    if bad_status:
        raise ValueError("invalid factory check statuses: " + ", ".join(bad_status))

    failures: list[str] = []
    missing: list[str] = []
    unknown: list[str] = []
    passed: list[str] = []

    for check_id in expected:
        check = _CHECKS_BY_ID.get(check_id)
        if check is None:
            raise ValueError(f"unknown required check id {check_id!r}")
        status = checks.get(check_id)
        if status is None:
            missing.append(check_id)
        elif status == PASS:
            passed.append(check_id)
        elif status == FAIL:
            failures.append(check_id)
        else:
            unknown.append(check_id)

    sealed = not failures and not missing and not unknown
    return FinalisationVerdict(
        deviceRecordId=device_record_id,
        sealed=sealed,
        failures=tuple(failures),
        missing=tuple(missing),
        unknown=tuple(unknown),
        passed=tuple(passed),
    )


def describe_checks() -> list[dict[str, Any]]:
    """Return the check catalogue for documentation and operator display.

    ``offlineInspectable`` tells an operator which checks ``bunny-oem inspect``
    can settle from a filesystem tree and which need a running system or a
    signed burn-in report, so the five that always report UNKNOWN offline are
    not mistaken for a broken probe.
    """
    from oem.inspection import INSPECTABLE_CHECKS, REQUIRES_LIVE_ATTESTATION

    return [
        {
            "checkId": check.checkId,
            "description": check.description,
            "blocking": check.blocking,
            "offlineInspectable": check.checkId in INSPECTABLE_CHECKS,
            "requiresLiveAttestation": REQUIRES_LIVE_ATTESTATION.get(check.checkId),
        }
        for check in FACTORY_STATE_CHECKS
    ]
