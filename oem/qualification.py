"""OEM hardware qualification kit evaluation.

This is distinct from ``operations/hardware.py``, which classifies *community*
hardware reports into support tiers. This module evaluates a *per-model OEM
qualification run*: a fixed test suite plus a sustained-load campaign, signed by
the qualifying party.

Three refusals are deliberate:

* An image is never approved without validated recovery.
* The word "certified" is never applied without a completed formal process and
  at least two independent repeat runs.
* A performance number is never accepted without a declared methodology.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_RUN = "NOT_RUN"
STATUSES = frozenset({PASS, FAIL, NOT_APPLICABLE, NOT_RUN})

#: The fixed qualification suite. ``optional`` tests may report NOT_APPLICABLE
#: when the hardware genuinely lacks the component; everything else must PASS.
REQUIRED_TESTS: tuple[str, ...] = (
    "installation",
    "encryption",
    "secure-boot",
    "graphics",
    "display",
    "wifi",
    "audio",
    "suspend-resume",
    "storage",
    "updates",
    "rollback",
    "recovery",
    "multi-user",
)

OPTIONAL_TESTS: tuple[str, ...] = (
    "tpm",
    "bluetooth",
    "camera",
    "battery",
    "thermals",
    "bunny-local-ai",
)

ALL_TESTS: tuple[str, ...] = REQUIRED_TESTS + OPTIONAL_TESTS

#: Sustained-load scenarios from the thermal campaign. Each must be executed and
#: its observations recorded, including negative observations.
SUSTAINED_LOAD_SCENARIOS: tuple[str, ...] = (
    "sustained-cpu",
    "sustained-gpu",
    "local-model-inference",
    "simultaneous-compile-and-model",
    "battery-operation",
    "charging",
    "suspend-cycles",
)

#: Observations that must be present for every executed sustained-load scenario.
REQUIRED_OBSERVATIONS: tuple[str, ...] = (
    "thermalThrottling",
    "fanBehaviour",
    "powerUse",
    "crashes",
    "dataCorruption",
    "driverResets",
)

#: A qualification may only be described with this vocabulary. "Certified" is
#: absent on purpose; see ``docs/OEM_PROGRAMME.md``.
QUALIFICATION_LEVELS = ("qualified", "qualified-with-limitations", "not-qualified", "incomplete")

MINIMUM_REPEAT_RUNS = 2


@dataclass(frozen=True)
class QualificationVerdict:
    model: str
    passed: bool
    level: str
    failures: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    notRun: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    recoveryValidated: bool = False
    certificationClaimPermitted: bool = False
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "passed": self.passed,
            "level": self.level,
            "failedTests": list(self.failures),
            "missingTests": list(self.missing),
            "notRunTests": list(self.notRun),
            "limitations": list(self.limitations),
            "recoveryValidated": self.recoveryValidated,
            "certificationClaimPermitted": self.certificationClaimPermitted,
            "notes": list(self.notes),
        }


def _evaluate_tests(
    results: Mapping[str, Any],
    failures: list[str],
    missing: list[str],
    not_run: list[str],
    limitations: list[str],
) -> None:
    unexpected = sorted(set(results) - set(ALL_TESTS))
    if unexpected:
        raise ValueError("unknown qualification test ids: " + ", ".join(unexpected))
    bad = sorted(f"{key}={value!r}" for key, value in results.items() if value not in STATUSES)
    if bad:
        raise ValueError("invalid qualification statuses: " + ", ".join(bad))

    for test in REQUIRED_TESTS:
        status = results.get(test)
        if status is None:
            missing.append(test)
        elif status == FAIL:
            failures.append(test)
        elif status == NOT_RUN:
            not_run.append(test)
        elif status == NOT_APPLICABLE:
            failures.append(test)

    for test in OPTIONAL_TESTS:
        status = results.get(test)
        if status is None:
            missing.append(test)
        elif status == FAIL:
            failures.append(test)
        elif status == NOT_RUN:
            not_run.append(test)
        elif status == NOT_APPLICABLE:
            limitations.append(f"{test} is not applicable to this hardware")


def _evaluate_sustained_load(
    campaign: Any,
    failures: list[str],
    not_run: list[str],
    notes: list[str],
) -> None:
    if not isinstance(campaign, Mapping):
        not_run.extend(f"sustained-load:{name}" for name in SUSTAINED_LOAD_SCENARIOS)
        notes.append("no sustained-load campaign was supplied")
        return
    unexpected = sorted(set(campaign) - set(SUSTAINED_LOAD_SCENARIOS))
    if unexpected:
        raise ValueError("unknown sustained-load scenario ids: " + ", ".join(unexpected))
    for scenario in SUSTAINED_LOAD_SCENARIOS:
        entry = campaign.get(scenario)
        if not isinstance(entry, Mapping):
            not_run.append(f"sustained-load:{scenario}")
            continue
        status = entry.get("status")
        if status not in STATUSES:
            raise ValueError(f"sustained-load scenario {scenario} has invalid status {status!r}")
        if status == FAIL:
            failures.append(f"sustained-load:{scenario}")
            continue
        if status in {NOT_RUN, NOT_APPLICABLE}:
            not_run.append(f"sustained-load:{scenario}")
            continue
        absent = [name for name in REQUIRED_OBSERVATIONS if name not in entry]
        if absent:
            failures.append(f"sustained-load:{scenario} is missing observations: {', '.join(absent)}")


def _evaluate_performance_claims(claims: Any, failures: list[str]) -> None:
    if claims is None:
        return
    if not isinstance(claims, list):
        raise ValueError("performanceClaims must be a list")
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            failures.append(f"performanceClaims[{index}] is not an object")
            continue
        methodology = claim.get("methodology")
        if not isinstance(methodology, str) or len(methodology.strip()) < 32:
            failures.append(
                f"performanceClaims[{index}] has no controlled methodology; "
                "performance numbers are not published without one"
            )
        if claim.get("repeatRuns") is None or not isinstance(claim.get("repeatRuns"), int) or claim["repeatRuns"] < MINIMUM_REPEAT_RUNS:
            failures.append(
                f"performanceClaims[{index}] declares fewer than {MINIMUM_REPEAT_RUNS} repeat runs"
            )


def evaluate_qualification(
    report: Mapping[str, Any],
    *,
    required_tests: Iterable[str] | None = None,
) -> QualificationVerdict:
    """Evaluate one OEM hardware qualification report."""
    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")
    if report.get("schemaVersion") != 1:
        raise ValueError(f"unsupported qualification schemaVersion {report.get('schemaVersion')!r}")

    model = report.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("model is required")

    results = report.get("tests")
    if not isinstance(results, Mapping):
        raise ValueError("tests must be an object mapping test ids to statuses")

    failures: list[str] = []
    missing: list[str] = []
    not_run: list[str] = []
    limitations: list[str] = []
    notes: list[str] = []

    _evaluate_tests(results, failures, missing, not_run, limitations)
    _evaluate_sustained_load(report.get("sustainedLoad"), failures, not_run, notes)
    _evaluate_performance_claims(report.get("performanceClaims"), failures)

    if not report.get("signature"):
        failures.append("qualification report is unsigned")
    if report.get("methodologyReference") in (None, ""):
        failures.append("qualification report does not reference a repeatable methodology")

    declared_limitations = report.get("knownLimitations")
    if isinstance(declared_limitations, list):
        limitations.extend(str(item) for item in declared_limitations)

    recovery_validated = results.get("recovery") == PASS
    if not recovery_validated:
        failures.append("recovery was not validated; an OEM image cannot be approved without it")

    repeat_runs = report.get("repeatRuns")
    repeat_ok = isinstance(repeat_runs, int) and not isinstance(repeat_runs, bool) and repeat_runs >= MINIMUM_REPEAT_RUNS

    blocking = bool(failures or missing or not_run)
    passed = not blocking

    if passed and limitations:
        level = "qualified-with-limitations"
    elif passed:
        level = "qualified"
    elif failures:
        level = "not-qualified"
    else:
        level = "incomplete"

    formal_process = report.get("formalCertificationProcess") is True
    certification_permitted = bool(passed and repeat_ok and formal_process and not limitations)
    if not certification_permitted:
        reason = []
        if not passed:
            reason.append("qualification did not pass")
        if not repeat_ok:
            reason.append(f"fewer than {MINIMUM_REPEAT_RUNS} repeat runs")
        if not formal_process:
            reason.append("no completed formal certification process")
        if limitations:
            reason.append("declared limitations")
        notes.append("certification claim refused: " + "; ".join(reason))

    return QualificationVerdict(
        model=model,
        passed=passed,
        level=level,
        failures=tuple(failures),
        missing=tuple(missing),
        notRun=tuple(not_run),
        limitations=tuple(dict.fromkeys(limitations)),
        recoveryValidated=recovery_validated,
        certificationClaimPermitted=certification_permitted,
        notes=tuple(notes),
    )
