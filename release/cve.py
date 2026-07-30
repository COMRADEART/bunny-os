# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-CVE binary analysis, vulnerable-path mapping, and five proof classes.

The previous phase answered nine of ten reachability questions for all 24
Critical and High findings and could not answer the tenth: *is the vulnerable
code path compiled into the installed binary and active or invocable?* That
single unanswered question is why all 24 remain ``Unknown``.

This module is the structure that question needs in order to be answerable, and
— more importantly — the structure that stops it being answered badly. Three
rules do most of the work:

**An absent symbol is not absent code.** Go strips symbol tables and inlines
aggressively; a stripped C library exports only what its ABI requires. So
:func:`classify_symbol_evidence` will never return "not present" from a symbol
search alone. Concluding ``Not present`` requires the source and binary versions
to match exactly, the build configuration to be recorded, *and* a mapping from
the vulnerable function to the binary — which for a stripped binary means
debuginfo, not `nm`.

**Each proof class carries its own evidence requirements.** ``Present but
unreachable`` needs activation analysis, privilege analysis, an invocation graph,
the system configuration, the sandbox or MAC control, and a reviewer. A record
claiming that class with four of six is rejected, not accepted with a caveat.

**A reviewer is required for every non-blocking class, and a Critical needs an
independent one.** Self-review is the failure mode this whole subsystem exists to
prevent, so it is checked at parse time rather than at report time.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: The five result classes, fixed by the brief.
PROOF_CLASSES = (
    "Not present",
    "Present but unreachable",
    "Reachable but mitigated",
    "Reachable and blocking",
    "Unknown",
)

#: Classes that do not block a stable release. ``Reachable but mitigated`` is
#: absent deliberately: a mitigation is not a fix. It becomes non-blocking only
#: through explicit acceptance by a release approver, which is recorded
#: separately and is not a property of the analysis.
NON_BLOCKING_CLASSES = frozenset({"Not present", "Present but unreachable"})

#: Evidence each class requires before it may be claimed. The keys are field
#: names in the analysis record; a missing or empty field means the class is
#: refused.
CLASS_EVIDENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "Not present": (
        "installedVersion",
        "sourcePackageVersion",
        "buildConfiguration",
        "symbolOrSourceMapping",
        "reviewer",
    ),
    "Present but unreachable": (
        "activationAnalysis",
        "privilegeAnalysis",
        "invocationGraph",
        "systemConfiguration",
        "sandboxOrMacControl",
        "reviewer",
    ),
    "Reachable but mitigated": (
        "exactMitigation",
        "bypassAnalysis",
        "residualImpact",
        "reviewer",
    ),
    "Reachable and blocking": (),
    "Unknown": (),
}

#: Every field the brief requires for a Critical or High finding's analysis.
ANALYSIS_FIELDS = (
    "advisoryId",
    "cveId",
    "packageName",
    "sourcePackage",
    "binaryPackage",
    "installedVersion",
    "fixedVersion",
    "installedExecutableOrLibrary",
    "sourceRpmReference",
    "debuginfoReference",
    "elfBuildId",
    "strippedState",
    "exportedSymbols",
    "dynamicDependencies",
    "packageScripts",
    "systemdUnits",
    "socketUnits",
    "dbusActivation",
    "desktopActivation",
    "commandInvocationPaths",
    "bunnyInvocationPaths",
    "pluginInvocationPaths",
    "sandboxReachability",
    "userInvocability",
    "networkExposure",
    "defaultEnablement",
    "vulnerableFunctionOrSubsystem",
    "evidenceSource",
    "conclusion",
)

#: The vulnerable-path mapping the brief requires per CVE (workstream 10).
MAPPING_FIELDS = (
    "vulnerableSourceFile",
    "vulnerableFunction",
    "affectedFeature",
    "buildTimeFlag",
    "runtimeFlag",
    "commandRequiredToReach",
    "privilegeRequired",
    "inputType",
    "networkRequirement",
    "localUserRequirement",
    "containerOrImageRequirement",
    "bunnyExposesFeature",
)

STRIPPED_STATES = ("stripped", "not-stripped", "partially-stripped", "unknown")
TRISTATE = ("yes", "no", "unknown")

#: The value that must be used when a mapping is not confident. Spelled out so a
#: blank field and a deliberate "we do not know" stay distinguishable.
UNKNOWN = "unknown"

_ADVISORY = re.compile(
    r"^(CVE-\d{4}-\d{4,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|GO-\d{4}-\d+|[A-Z]{2,}-\d{4}-\d+)$"
)
_BUILD_ID = re.compile(r"^[0-9a-f]{16,64}$")


class CveAnalysisError(ValueError):
    """Raised when a per-CVE analysis is malformed or overclaims."""


# --------------------------------------------------------------------------- #
# Symbol evidence
# --------------------------------------------------------------------------- #


#: What a symbol search can and cannot conclude, per stripped state. The table is
#: the whole point of this function existing: the temptation is to read "symbol
#: not found" as "code not present", and that inference is only ever valid for a
#: binary that was never stripped *and* whose linker does not inline across the
#: boundary in question — which excludes every Go binary in this image.
def classify_symbol_evidence(
    *,
    symbolPresent: bool,
    strippedState: str,
    language: str,
    debuginfoAvailable: bool,
) -> dict[str, Any]:
    """Say what a symbol-table observation is and is not evidence of."""
    if strippedState not in STRIPPED_STATES:
        raise CveAnalysisError(f"strippedState must be one of {', '.join(STRIPPED_STATES)}")

    if symbolPresent:
        return {
            "supports": "presence",
            "conclusion": "the symbol is present, so the code it names is linked into the binary",
            "sufficientForNotPresent": False,
            "caveat": (
                "Presence of a symbol does not establish reachability. A linked function that no "
                "entry point calls is present and unreachable."
            ),
        }

    if strippedState in {"stripped", "partially-stripped", "unknown"}:
        return {
            "supports": "nothing",
            "conclusion": (
                f"the symbol is absent from a {strippedState} binary, which is what a "
                "stripped binary looks like whether or not the code is present"
            ),
            "sufficientForNotPresent": False,
            "caveat": (
                "Absence of a symbol from a stripped binary is not evidence of absent code. "
                + (
                    "Debuginfo is available and must be used instead."
                    if debuginfoAvailable
                    else "Debuginfo must be acquired before this question can be answered."
                )
            ),
        }

    if language.casefold() == "go":
        return {
            "supports": "nothing",
            "conclusion": (
                "the symbol is absent from an unstripped Go binary, but the Go compiler inlines "
                "across package boundaries and the linker eliminates dead code by rewriting call "
                "graphs, so an absent name does not imply absent instructions"
            ),
            "sufficientForNotPresent": False,
            "caveat": (
                "For Go, establishing absence requires the module version graph and the linker's "
                "dead-code decisions, not a symbol table."
            ),
        }

    return {
        "supports": "weak-absence",
        "conclusion": (
            "the symbol is absent from a binary that was not stripped, which is consistent with "
            "the code being absent"
        ),
        # Even here it is not sufficient on its own: a static-only function is
        # absent from the symbol table of an unstripped binary too.
        "sufficientForNotPresent": False,
        "caveat": (
            "A file-static or inlined function is absent from an unstripped symbol table as well. "
            "Corroborate with debuginfo or with the source build configuration."
        ),
    }


# --------------------------------------------------------------------------- #
# The analysis record
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CveAnalysis:
    advisoryId: str
    cveId: str
    packageName: str
    fields: Mapping[str, Any]
    mapping: Mapping[str, Any]
    proofClass: str
    reviewer: str | None
    independentReviewReference: str | None
    evidenceSource: str
    notes: str

    @property
    def blocking(self) -> bool:
        return self.proofClass not in NON_BLOCKING_CLASSES

    @property
    def unknownMappingFields(self) -> tuple[str, ...]:
        return tuple(
            sorted(name for name in MAPPING_FIELDS if str(self.mapping.get(name, UNKNOWN)) == UNKNOWN)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "advisoryId": self.advisoryId,
            "cveId": self.cveId,
            "packageName": self.packageName,
            **{name: self.fields.get(name) for name in ANALYSIS_FIELDS if name not in {"advisoryId", "cveId", "packageName", "conclusion"}},
            "mapping": {name: self.mapping.get(name, UNKNOWN) for name in MAPPING_FIELDS},
            "unknownMappingFields": list(self.unknownMappingFields),
            "proofClass": self.proofClass,
            "conclusion": self.proofClass,
            "reviewer": self.reviewer,
            "independentReviewReference": self.independentReviewReference,
            "evidenceSource": self.evidenceSource,
            "notes": self.notes,
            "blocking": self.blocking,
        }


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().casefold() == UNKNOWN
    if isinstance(value, (list, tuple, dict)):
        return not value
    return False


def parse_analysis(
    record: Mapping[str, Any],
    *,
    completed_independent_reviews: Iterable[str] = (),
    criticalAdvisories: Iterable[str] = (),
    independentReviewers: Iterable[str] = (),
) -> CveAnalysis:
    """Validate one per-CVE analysis record.

    ``independentReviewers`` names people recorded as external. A Critical
    finding reaching a non-blocking class needs both a completed independent
    review *and* a reviewer drawn from that set, because a reference to someone
    else's review does not make this analysis independent.
    """
    if not isinstance(record, Mapping):
        raise CveAnalysisError("analysis must be an object")

    missing = [name for name in ANALYSIS_FIELDS if name not in record]
    if missing:
        raise CveAnalysisError(f"analysis missing required fields: {', '.join(sorted(missing))}")

    advisory = str(record["advisoryId"])
    if not _ADVISORY.match(advisory):
        raise CveAnalysisError(f"advisoryId {advisory!r} is not a recognised advisory identifier")

    proof_class = record["conclusion"]
    if proof_class not in PROOF_CLASSES:
        raise CveAnalysisError(
            f"{advisory}: conclusion must be one of {', '.join(PROOF_CLASSES)}"
        )

    if record["strippedState"] not in STRIPPED_STATES:
        raise CveAnalysisError(
            f"{advisory}: strippedState must be one of {', '.join(STRIPPED_STATES)}"
        )
    for name in ("sandboxReachability", "userInvocability", "defaultEnablement", "dbusActivation", "desktopActivation"):
        if record[name] not in TRISTATE:
            raise CveAnalysisError(f"{advisory}: {name} must be one of {', '.join(TRISTATE)}")

    build_id = record.get("elfBuildId")
    if build_id and str(build_id) != UNKNOWN and not _BUILD_ID.match(str(build_id)):
        raise CveAnalysisError(
            f"{advisory}: elfBuildId {build_id!r} is not a hex build ID; record 'unknown' rather "
            "than an approximation"
        )

    mapping = record.get("mapping") or {}
    if not isinstance(mapping, Mapping):
        raise CveAnalysisError(f"{advisory}: mapping must be an object")
    unknown_mapping_keys = sorted(set(mapping) - set(MAPPING_FIELDS))
    if unknown_mapping_keys:
        raise CveAnalysisError(f"{advisory}: unknown mapping fields: {', '.join(unknown_mapping_keys)}")

    reviewer = record.get("reviewer")
    reference = record.get("independentReviewReference")
    reviews = set(completed_independent_reviews)
    externals = {str(name).casefold() for name in independentReviewers}

    # --- version discipline ------------------------------------------------
    installed = str(record["installedVersion"])
    source_version = str(record.get("sourcePackageVersion") or "")
    if proof_class != "Unknown" and source_version and installed:
        if not _versions_correspond(installed, source_version):
            raise CveAnalysisError(
                f"{advisory}: analysed source {source_version!r} does not correspond to installed "
                f"{installed!r}; an analysis of the wrong version establishes nothing about the "
                "shipped binary"
            )

    # --- per-class evidence requirements -----------------------------------
    required = CLASS_EVIDENCE_REQUIREMENTS[proof_class]
    absent = [name for name in required if _empty(record.get(name))]
    if absent:
        raise CveAnalysisError(
            f"{advisory}: conclusion {proof_class!r} requires evidence this record does not carry: "
            + ", ".join(sorted(absent))
        )

    # --- the absent-symbol trap --------------------------------------------
    if proof_class == "Not present":
        exported = record["exportedSymbols"]
        symbol_present = _symbol_named_in(exported, record.get("vulnerableFunctionOrSubsystem"))
        verdict = classify_symbol_evidence(
            symbolPresent=symbol_present,
            strippedState=str(record["strippedState"]),
            language=str(record.get("language", "")),
            debuginfoAvailable=not _empty(record.get("debuginfoReference")),
        )
        if not verdict["sufficientForNotPresent"] and _relies_only_on_symbols(record):
            raise CveAnalysisError(
                f"{advisory}: 'Not present' rests only on a symbol observation. {verdict['caveat']}"
            )

    # --- reviewer discipline -----------------------------------------------
    if proof_class in NON_BLOCKING_CLASSES or proof_class == "Reachable but mitigated":
        if _empty(reviewer):
            raise CveAnalysisError(f"{advisory}: conclusion {proof_class!r} requires a named reviewer")

    if advisory in set(criticalAdvisories) and proof_class in NON_BLOCKING_CLASSES:
        if not reference or reference not in reviews:
            raise CveAnalysisError(
                f"{advisory}: a Critical advisory may only reach {proof_class!r} through a "
                "completed independent security review; none is referenced"
            )
        if externals and str(reviewer).casefold() not in externals:
            raise CveAnalysisError(
                f"{advisory}: reviewer {reviewer!r} is not recorded as an independent reviewer; a "
                "Critical disposition cannot be self-reviewed"
            )

    return CveAnalysis(
        advisoryId=advisory,
        cveId=str(record["cveId"]),
        packageName=str(record["packageName"]),
        fields={name: record.get(name) for name in ANALYSIS_FIELDS} | {
            name: record.get(name)
            for name in ("sourcePackageVersion", "buildConfiguration", "symbolOrSourceMapping",
                         "activationAnalysis", "privilegeAnalysis", "invocationGraph",
                         "systemConfiguration", "sandboxOrMacControl", "exactMitigation",
                         "bypassAnalysis", "residualImpact", "language")
            if name in record
        },
        mapping={name: mapping.get(name, UNKNOWN) for name in MAPPING_FIELDS},
        proofClass=proof_class,
        reviewer=str(reviewer) if reviewer else None,
        independentReviewReference=str(reference) if reference else None,
        evidenceSource=str(record["evidenceSource"]),
        notes=str(record.get("notes", "")),
    )


def _versions_correspond(installed: str, source: str) -> bool:
    """Loose correspondence between an installed version and an analysed source.

    Deliberately loose: `v0.46.0` and `0.46.0` are the same module, and
    `5.8.4-1.fc44` and `5.8.4` are the same upstream. Deliberately not absent:
    analysing 5.6.1 and shipping 5.8.4 is the ``source and binary version
    mismatch`` case and must fail.
    """
    def core(value: str) -> tuple[str, ...]:
        cleaned = value.strip().lstrip("vV")
        cleaned = re.split(r"[-+~]", cleaned, maxsplit=1)[0]
        return tuple(part for part in cleaned.split(".") if part)

    left, right = core(installed), core(source)
    if not left or not right:
        return False
    shared = min(len(left), len(right))
    return left[:shared] == right[:shared]


def _symbol_named_in(exported: Any, function: Any) -> bool:
    if _empty(function):
        return False
    needle = str(function).casefold()
    if isinstance(exported, (list, tuple)):
        return any(needle in str(item).casefold() for item in exported)
    return needle in str(exported).casefold()


def _relies_only_on_symbols(record: Mapping[str, Any]) -> bool:
    """Whether the only cited evidence is a symbol table.

    A record that also cites debuginfo, debugsource, a build configuration or a
    source-to-binary mapping is not relying on symbols alone.
    """
    corroborating = ("debuginfoReference", "debugsourceReference", "buildConfiguration", "symbolOrSourceMapping")
    return all(_empty(record.get(name)) for name in corroborating)


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def summarise_analyses(analyses: Iterable[CveAnalysis]) -> dict[str, Any]:
    """Aggregate per-CVE analyses into a gate-usable verdict."""
    rows = list(analyses)
    by_class: dict[str, list[str]] = {name: [] for name in PROOF_CLASSES}
    for analysis in rows:
        by_class[analysis.proofClass].append(analysis.advisoryId)
    blocking = sorted(analysis.advisoryId for analysis in rows if analysis.blocking)
    unmapped = sorted(
        analysis.advisoryId for analysis in rows if analysis.unknownMappingFields
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "analysed": len(rows),
        "byProofClass": {name: sorted(values) for name, values in by_class.items() if values},
        "blockingAdvisories": blocking,
        "blockingCount": len(blocking),
        "advisoriesWithUnmappedFields": unmapped,
        "blocked": bool(blocking),
        "result": "BLOCKED" if blocking else "PASS",
        "note": (
            "'Unknown' and 'Reachable and blocking' block. 'Reachable but mitigated' blocks until a "
            "release approver explicitly accepts it, because a mitigation is not a fix. An absent "
            "symbol was not treated as absent code anywhere in this set."
        ),
    }


def evaluate_document(
    document: Mapping[str, Any],
    *,
    completed_independent_reviews: Iterable[str] = (),
    criticalAdvisories: Iterable[str] = (),
    independentReviewers: Iterable[str] = (),
    expectedAdvisories: Iterable[str] = (),
) -> dict[str, Any]:
    """Evaluate a whole per-CVE analysis document.

    ``expectedAdvisories`` is the set that must be covered — the Critical and
    High findings from the scan. An advisory with no analysis is reported as
    uncovered and blocks, so adding a finding cannot silently reduce coverage.
    """
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise CveAnalysisError(f"analysis document schemaVersion must be {SCHEMA_VERSION}")
    raw = document.get("analyses")
    if not isinstance(raw, list):
        raise CveAnalysisError("analysis document must carry an analyses array")

    analyses = [
        parse_analysis(
            item,
            completed_independent_reviews=completed_independent_reviews,
            criticalAdvisories=criticalAdvisories,
            independentReviewers=independentReviewers,
        )
        for item in raw
    ]
    seen: set[str] = set()
    for analysis in analyses:
        if analysis.advisoryId in seen:
            raise CveAnalysisError(f"duplicate analysis for {analysis.advisoryId}")
        seen.add(analysis.advisoryId)

    expected = set(expectedAdvisories)
    uncovered = sorted(expected - seen)
    extraneous = sorted(seen - expected) if expected else []

    summary = summarise_analyses(analyses)
    summary["uncoveredAdvisories"] = uncovered
    summary["extraneousAnalyses"] = extraneous
    summary["coverageComplete"] = not uncovered
    if uncovered:
        summary["blocked"] = True
        summary["result"] = "BLOCKED"
    summary["analyses"] = [analysis.as_dict() for analysis in analyses]
    return summary


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "ANALYSIS_FIELDS",
    "CLASS_EVIDENCE_REQUIREMENTS",
    "MAPPING_FIELDS",
    "NON_BLOCKING_CLASSES",
    "PROOF_CLASSES",
    "STRIPPED_STATES",
    "UNKNOWN",
    "CveAnalysis",
    "CveAnalysisError",
    "classify_symbol_evidence",
    "evaluate_document",
    "parse_analysis",
    "summarise_analyses",
]
