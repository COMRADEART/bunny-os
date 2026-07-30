#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-CVE reachability pipeline: findings, acquisition, symbols, packages.

The bounded review in the previous phase answered nine of ten questions for all
24 Critical and High findings and left the tenth open. This pipeline is the
apparatus the tenth question needs.

Every command fails closed. In particular ``analyse-symbols`` and
``generate-packages`` do not invent the evidence they are missing: an analysis
record generated from the committed scan alone carries ``unknown`` in every field
that requires a binary, and ``Unknown`` as its conclusion. That is the accurate
state of the analysis on a machine that has neither the image nor the debuginfo.

Commands::

    reachability.py generate-findings      # per-CVE records from committed evidence
    reachability.py acquire-plan           # exact acquisition commands, per package
    reachability.py validate-acquisition   # manifest checksums, versions, trust
    reachability.py analyse-symbols        # ELF/symbol analysis, or state what is missing
    reachability.py generate-packages      # one review bundle per unresolved advisory
    reachability.py disposition            # the aggregate verdict
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release.acquisition import (  # noqa: E402
    AcquisitionError,
    acquisition_plan,
    evaluate_manifest,
    parse_nevra,
)
from release.cve import (  # noqa: E402
    ANALYSIS_FIELDS,
    MAPPING_FIELDS,
    UNKNOWN,
    CveAnalysisError,
    classify_symbol_evidence,
    evaluate_document,
)
from release.reviews import completed_review_identifiers  # noqa: E402

DATA = ROOT / "operations/data"
SECURITY = ROOT / "security/reachability"
FINDINGS = SECURITY / "findings"
SOURCES = SECURITY / "sources"
REPORTS = SECURITY / "reports"
PACKAGES = SECURITY / "packages"
OUT = ROOT / "build/out/qualification"

BLOCKING_SEVERITIES = ("Critical", "High")

#: The Go binaries the base image installs, measured in
#: evidence/reachability/beta-minimised-binaries.txt. Any of the three may carry
#: a vendored module, and the scan does not say which.
CANDIDATE_CARRIERS = (
    "podman-5.8.4-1.fc44.x86_64 at /usr/sbin/podman",
    "skopeo-1.22.2-2.fc44.x86_64 at /usr/sbin/skopeo",
    "bootc-1.16.4-1.fc44.x86_64 at /usr/sbin/bootc",
)

#: Installed packages whose binaries are analysis targets, with their measured
#: NEVRAs. toolbox is absent after minimisation and is recorded as such rather
#: than omitted.
ANALYSIS_TARGETS = (
    {"installedNevra": "podman-5.8.4-1.fc44.x86_64", "binaryPath": "/usr/sbin/podman", "language": "go"},
    {"installedNevra": "skopeo-1.22.2-2.fc44.x86_64", "binaryPath": "/usr/sbin/skopeo", "language": "go"},
    {"installedNevra": "bootc-1.16.4-1.fc44.x86_64", "binaryPath": "/usr/sbin/bootc", "language": "rust"},
    {"installedNevra": "kernel-core-7.1.5-200.fc44.x86_64", "binaryPath": "/usr/lib/modules/7.1.5-200.fc44.x86_64/vmlinuz", "language": "c"},
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional(path: Path, default: Any) -> Any:
    try:
        return load(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        return "0" * 40


def blocking_findings() -> list[dict[str, Any]]:
    document = load(DATA / "vulnerability-disposition.json")
    return [
        finding
        for finding in document.get("findings", [])
        if finding.get("scannerSeverity") in BLOCKING_SEVERITIES
    ]


def reachability_answers() -> dict[str, dict[str, Any]]:
    document = load(DATA / "vulnerability-disposition.json")
    return {item["advisoryId"]: item for item in document.get("reachability", [])}


def carrier_locations() -> dict[tuple[str, str], list[str]]:
    """Where the scanner found each vulnerable module. Measured, not inferred."""
    path = ROOT / "evidence/vulnerability/beta-grype.json"
    document = load(path)
    locations: dict[tuple[str, str], list[str]] = {}
    for match in document.get("matches", []):
        vulnerability = match.get("vulnerability", {})
        artifact = match.get("artifact", {})
        key = (str(vulnerability.get("id")), str(artifact.get("name")))
        paths = sorted(
            {
                str(location.get("path", ""))
                for location in artifact.get("locations", [])
                if location.get("path")
            }
        )
        if paths:
            locations.setdefault(key, paths)
    return locations


def _desktop_entries_reference_container_runtime() -> tuple[str, list[str]]:
    """Grep the shipped desktop entries for a container-runtime invocation."""
    hits: list[str] = []
    for path in sorted(ROOT.rglob("*.desktop")):
        if "node_modules" in path.parts or "out" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover
            continue
        for token in ("podman", "skopeo", "bootc", "toolbox", "docker"):
            if re.search(rf"^Exec=.*\b{token}\b", text, re.MULTILINE):
                hits.append(f"{path.relative_to(ROOT)}: {token}")
    return ("yes" if hits else "no"), hits


# --------------------------------------------------------------------------- #
# generate-findings
# --------------------------------------------------------------------------- #


def generate_findings() -> int:
    """Write one analysis record per Critical/High advisory from committed evidence."""
    findings = blocking_findings()
    answers = reachability_answers()
    locations = carrier_locations()
    desktop_state, desktop_hits = _desktop_entries_reference_container_runtime()
    commit = source_commit()

    for directory in (FINDINGS, SOURCES, REPORTS, PACKAGES):
        directory.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for finding in findings:
        advisory = finding["advisoryId"]
        package = finding["package"]
        answer = answers.get(advisory, {}).get("answers", {})
        carriers = locations.get((advisory, package), [])
        kernel = package == "linux-kernel"

        record: dict[str, Any] = {
            "schemaVersion": 1,
            "advisoryId": advisory,
            "cveId": advisory if advisory.startswith("CVE-") else UNKNOWN,
            "packageName": package,
            # The scan records an ostree object digest, not a package name. For
            # the kernel the version string *is* the package NEVRA, so that one
            # is known; for the vendored Go modules it is not.
            "sourcePackage": "kernel" if kernel else UNKNOWN,
            "binaryPackage": "kernel-core-7.1.5-200.fc44.x86_64" if kernel else UNKNOWN,
            "installedVersion": finding["installedVersion"],
            "fixedVersion": finding.get("fixedVersion"),
            "installedExecutableOrLibrary": carriers[0] if carriers else UNKNOWN,
            "carrierObjects": carriers,
            "candidateCarriers": [] if kernel else list(CANDIDATE_CARRIERS),
            "sourceRpmReference": UNKNOWN,
            "debuginfoReference": UNKNOWN,
            "debugsourceReference": UNKNOWN,
            "elfBuildId": UNKNOWN,
            "strippedState": UNKNOWN,
            "language": "c" if kernel else ("rust" if "bootc" in package else "go"),
            "exportedSymbols": [],
            "dynamicDependencies": [],
            "packageScripts": UNKNOWN,
            # Measured in evidence/reachability/beta-facts.txt.
            "systemdUnits": (
                ["(kernel: no unit carries the vulnerable code)"]
                if kernel
                else [
                    "podman.service (present, not enabled)",
                    "podman.socket (present, not in sockets.target.wants)",
                    "bootc-fetch-apply-updates.timer (present, not enabled)",
                ]
            ),
            "socketUnits": (
                []
                if kernel
                else ["podman.socket — ListenStream=%t/podman/podman.sock, unix, absent from sockets.target.wants"]
            ),
            "dbusActivation": UNKNOWN,
            "desktopActivation": desktop_state,
            "desktopActivationEvidence": desktop_hits or [
                f"grep '^Exec=.*(podman|skopeo|bootc|toolbox|docker)' over every shipped .desktop at {commit[:12]}: no match"
            ],
            "commandInvocationPaths": (
                ["kernel code is reached through syscalls, not a command"]
                if kernel
                else [
                    "/usr/sbin/podman — mode 0755 root:root, no setuid; on PATH for any user",
                    "/usr/sbin/skopeo — mode 0755 root:root, no setuid",
                    "/usr/sbin/bootc — mode 0755 root:root, no setuid",
                ]
            ),
            "bunnyInvocationPaths": [
                "none — the privileged broker exposes typed fixed backends and has no generic exec "
                "path; no backend invokes a container runtime"
            ],
            "pluginInvocationPaths": ["none — plugins reach the system only through the broker"],
            "sandboxReachability": answer.get("sandboxLimitsExposure", {}).get("answer", UNKNOWN),
            "userInvocability": answer.get("unprivilegedInvocation", {}).get("answer", UNKNOWN),
            "networkExposure": finding.get("networkExposure", UNKNOWN),
            "defaultEnablement": answer.get("runsByDefault", {}).get("answer", UNKNOWN),
            # Not invented. Naming a function without the advisory's own
            # description of it would be a guess dressed as evidence.
            "vulnerableFunctionOrSubsystem": UNKNOWN,
            "mapping": {name: UNKNOWN for name in MAPPING_FIELDS}
            | {
                "privilegeRequired": finding.get("privilegeLevel", UNKNOWN),
                "networkRequirement": finding.get("networkExposure", UNKNOWN),
                "localUserRequirement": "no" if kernel else "yes",
                "bunnyExposesFeature": "no",
            },
            "evidenceSource": (
                "evidence/vulnerability/beta-grype.json (carrier object), "
                "evidence/reachability/beta-facts.txt (unit state), "
                "evidence/reachability/beta-permissions.txt (modes), "
                "evidence/reachability/beta-minimised-binaries.txt (installed NEVRAs)"
            ),
            "conclusion": "Unknown",
            "reviewer": None,
            "independentReviewReference": None,
            "sourceCommit": commit,
            "generatedAt": _now(),
            "notes": _notes_for(advisory, package, carriers, kernel),
        }

        missing = [name for name in ANALYSIS_FIELDS if name not in record]
        if missing:  # pragma: no cover - guards the generator against drift
            raise SystemExit(f"{advisory}: generator omitted required fields: {', '.join(missing)}")

        write_json(FINDINGS / f"{advisory}.json", record)
        written.append(advisory)

    # Only the blocking set's carriers. The scan records locations for every
    # match at every severity, and summarising over all of them would report
    # 74 advisories against the kernel object when 1 of them is in scope here.
    blocking_keys = {(finding["advisoryId"], finding["package"]) for finding in findings}
    blocking_locations = {key: paths for key, paths in locations.items() if key in blocking_keys}

    index = {
        "schemaVersion": 1,
        "sourceCommit": commit,
        "generatedAt": _now(),
        "advisoryCount": len(written),
        "advisories": sorted(written),
        "distinctCarrierObjects": sorted({path for paths in blocking_locations.values() for path in paths}),
        "note": (
            "Every record concludes 'Unknown'. Nine of the ten bounded reachability questions are "
            "answered from measured evidence; the tenth needs the binary, its debuginfo and the "
            "advisory's own description of the vulnerable function, none of which is in this "
            "repository."
        ),
    }
    write_json(FINDINGS / "index.json", index)
    print(f"wrote {len(written)} per-CVE analysis records to {FINDINGS.relative_to(ROOT)}")
    print(f"distinct carrier objects: {len(index['distinctCarrierObjects'])}")
    for path in index["distinctCarrierObjects"]:
        sharing = sorted(
            advisory for (advisory, _), paths in blocking_locations.items() if path in paths
        )
        print(f"  {path[-24:]}")
        print(f"      carries {len(sharing)} of the 24 blocking advisories: {', '.join(sharing)}")
    return 0


def _notes_for(advisory: str, package: str, carriers: list[str], kernel: bool) -> str:
    if kernel:
        return (
            "Grype's kernel classifier compares the installed version against an upstream stable "
            "series. CVE-2020-27815 is a 2020 JFS bug whose stated fixed version, 4.9.249, is six "
            "major versions behind the installed 7.1.5. That is consistent with a classifier "
            "artefact and is recorded as Unknown rather than Remediated, because the remediation "
            "path is 'confirm against the Fedora kernel changelog' and nobody has. Being almost "
            "certainly fine is not evidence."
        )
    lines = [
        "The scan records the carrier as an ostree object, not an installed path: the "
        "fedora-bootc base ships an object store and every finding's location is an object in a "
        "lower layer.",
    ]
    if carriers:
        lines.append(f"Carrier object: {carriers[0]}.")
    lines.append(
        "Mapping that object to one of the three installed Go binaries requires the image: "
        "`ostree ls` or `find /usr -samefile` inside a booted or mounted deployment. Until that "
        "is done the carrier is one of: " + "; ".join(CANDIDATE_CARRIERS) + "."
    )
    if package == "golang.org/x/text":
        lines.append(
            "This advisory's carrier object is the one the previous phase identified as toolbox, "
            "which package minimisation removed: `rpm -q toolbox` reports not installed and "
            "/usr/bin/toolbox is absent from the minimised image. The object survives in a base "
            "layer because dnf remove cannot remove an object from a lower layer's store. If the "
            "carrier attribution is confirmed, this finding's invocation analysis differs from the "
            "other 23 — there is no installed executable to invoke. It remains Unknown because the "
            "attribution is not confirmed and question 7 is unanswered either way."
        )
    return " ".join(lines)


def _now() -> str:
    stamp = os.environ.get("BUNNY_EVALUATION_TIME")
    if stamp:
        return stamp
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# acquire-plan / validate-acquisition
# --------------------------------------------------------------------------- #


def acquire_plan() -> int:
    plan = acquisition_plan(ANALYSIS_TARGETS)
    payload = {
        "schemaVersion": 1,
        "sourceCommit": source_commit(),
        "generatedAt": _now(),
        "targetCount": len(plan),
        "targets": plan,
        "constraints": [
            "Fedora infrastructure only; no third-party binary source is accepted.",
            "Every download's SHA-256 and the resolving repomd.xml digest must be recorded.",
            "The NEVRA must equal the installed NEVRA, not merely the same upstream version.",
            "RPMs are stored outside this repository. Only the manifest is committed.",
        ],
        "note": (
            "A plan, not an execution. The environments that run these gates have no network "
            "access to Fedora infrastructure, and a plan can be reviewed before it is run."
        ),
    }
    write_json(SOURCES / "acquisition-plan.json", payload)
    write_text(SOURCES / "ACQUISITION.md", _render_acquisition_markdown(payload))
    print(f"wrote {(SOURCES / 'acquisition-plan.json').relative_to(ROOT)} for {len(plan)} target(s)")
    for target in plan:
        print(f"  {target['installedNevra']} -> {target['binaryPath']}")
    return 0


def _render_acquisition_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "<!--",
        "SPDX-FileCopyrightText: 2026 ComradeArt",
        "SPDX-License-Identifier: GPL-3.0-or-later",
        "-->",
        "",
        "# Source and debuginfo acquisition",
        "",
        f"Source commit: `{payload['sourceCommit']}`",
        "",
        "Generated by `python scripts/reachability.py acquire-plan`. Edit the generator, not this",
        "file.",
        "",
        "## Constraints",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["constraints"])
    lines.extend(["", "## Targets", ""])
    for target in payload["targets"]:
        lines.extend(
            [
                f"### `{target['installedNevra']}`",
                "",
                f"Binary: `{target['binaryPath']}`",
                "",
                "```sh",
            ]
        )
        lines.extend(target["commands"])
        lines.extend(["```", "", "Verification:", ""])
        lines.extend(f"- {item}" for item in target["verification"])
        lines.append("")
    lines.extend(
        [
            "## Why nothing is committed",
            "",
            "A single podman debuginfo package is larger than this entire source tree. The",
            "manifest and its checksums are the committed evidence; the artifacts live at",
            "`$BUNNY_CVE_CACHE` outside the repository. `release/acquisition.py` refuses a record",
            "whose `storedOutsideRepository` is not `true`.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_acquisition() -> int:
    path = SOURCES / "acquisition-manifest.json"
    document = load_optional(path, None)
    if document is None:
        print(
            f"BLOCKED: {path.relative_to(ROOT)} does not exist. No source, binary or debuginfo "
            "package has been acquired, so no symbol analysis can be performed."
        )
        print("run: python scripts/reachability.py acquire-plan, then execute the plan on a Fedora host")
        return 2
    try:
        result = evaluate_manifest(document)
    except AcquisitionError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    write_json(OUT / "cve-acquisition.json", result)
    print(f"acquisition: {len(result['completeTargets'])} of {result['targetCount']} target(s) complete")
    for reason in result["rejected"]:
        print(f"  REJECTED {reason}")
    for target in result["targets"]:
        if target["missingKinds"]:
            print(f"  {target['installedNevra']}: missing {', '.join(target['missingKinds'])}")
    if result["result"] != "PASS":
        print("BLOCKED: acquisition incomplete")
        return 2
    print("acquisition complete and verified")
    return 0


# --------------------------------------------------------------------------- #
# analyse-symbols
# --------------------------------------------------------------------------- #


_ELF_TOOLS = ("eu-readelf", "readelf", "objdump", "nm", "eu-unstrip", "rpm", "file")


def analyse_symbols(sysroot: Path | None) -> int:
    """Run, or explain why it cannot run, the ELF and symbol analysis.

    On a host with the binaries and the tooling this collects build IDs, stripped
    state, dynamic dependencies and dynamic symbols. On a host without them it
    records precisely what is absent. What it never does is treat a missing tool
    or a missing symbol as a negative result.
    """
    available = {tool: shutil.which(tool) for tool in _ELF_TOOLS}
    missing_tools = sorted(tool for tool, path in available.items() if not path)

    rows: list[dict[str, Any]] = []
    for target in ANALYSIS_TARGETS:
        binary = Path(target["binaryPath"])
        if sysroot is not None:
            binary = sysroot / str(target["binaryPath"]).lstrip("/")
        present = binary.is_file()
        row: dict[str, Any] = {
            "installedNevra": target["installedNevra"],
            "binaryPath": str(target["binaryPath"]),
            "resolvedPath": str(binary),
            "binaryPresent": present,
            "language": target["language"],
            "elfBuildId": UNKNOWN,
            "strippedState": UNKNOWN,
            "dynamicDependencies": [],
            "dynamicSymbolCount": None,
            "symbolTablePresent": None,
            "debuginfoResolved": False,
            "collectionErrors": [],
        }
        if not present:
            row["collectionErrors"].append(
                f"{binary} does not exist on this host; the image must be mounted or booted"
            )
        elif missing_tools:
            row["collectionErrors"].append(
                f"binary present but these tools are absent: {', '.join(missing_tools)}"
            )
        else:
            row.update(_collect_elf_facts(binary))
        rows.append(row)

    collected = [row for row in rows if not row["collectionErrors"]]
    payload = {
        "schemaVersion": 1,
        "sourceCommit": source_commit(),
        "generatedAt": _now(),
        "host": os.name,
        "toolsAvailable": {tool: bool(path) for tool, path in available.items()},
        "missingTools": missing_tools,
        "targets": rows,
        "collectedTargets": [row["installedNevra"] for row in collected],
        "uncollectedTargets": [row["installedNevra"] for row in rows if row["collectionErrors"]],
        "result": "PASS" if len(collected) == len(rows) and rows else "BLOCKED",
        "discipline": (
            "An absent symbol is not absent code. Every conclusion drawn from this data must go "
            "through release.cve.classify_symbol_evidence, which refuses to support a 'Not present' "
            "conclusion from a symbol observation on a stripped or Go binary."
        ),
    }
    write_json(REPORTS / "symbol-analysis.json", payload)
    write_json(OUT / "cve-symbol-analysis.json", payload)

    print(f"symbol analysis: {len(collected)} of {len(rows)} target(s) collected")
    if missing_tools:
        print(f"  missing tooling: {', '.join(missing_tools)}")
    for row in rows:
        state = "collected" if not row["collectionErrors"] else "NOT COLLECTED"
        print(f"  {state:14} {row['installedNevra']}")
        for error in row["collectionErrors"]:
            print(f"      {error}")

    # Demonstrate the discipline on the data actually held, so the refusal is
    # exercised rather than merely documented.
    verdict = classify_symbol_evidence(
        symbolPresent=False,
        strippedState="unknown",
        language="go",
        debuginfoAvailable=(SOURCES / "acquisition-manifest.json").is_file(),
    )
    print(f"  symbol-absence verdict: supports {verdict['supports']!r}")
    print(f"      {verdict['caveat']}")

    if payload["result"] != "PASS":
        print(
            "BLOCKED: symbol analysis incomplete. This is the state of the analysis, not a "
            "failure of the tooling: no conclusion may be drawn from data that was not collected."
        )
        return 2
    print("symbol analysis collected for every target")
    return 0


def _collect_elf_facts(binary: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"collectionErrors": []}
    readelf = shutil.which("eu-readelf") or shutil.which("readelf")

    def run(argv: list[str]) -> str:
        try:
            result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
            facts["collectionErrors"].append(f"{' '.join(argv[:2])}: {exc}")
            return ""
        return result.stdout

    notes = run([readelf, "-n", str(binary)]) if readelf else ""
    match = re.search(r"Build ID:\s*([0-9a-f]+)", notes)
    facts["elfBuildId"] = match.group(1) if match else UNKNOWN

    described = run([shutil.which("file") or "file", "-b", str(binary)])
    if "not stripped" in described:
        facts["strippedState"] = "not-stripped"
    elif "stripped" in described:
        facts["strippedState"] = "stripped"
    else:
        facts["strippedState"] = UNKNOWN

    dynamic = run([readelf, "-d", str(binary)]) if readelf else ""
    facts["dynamicDependencies"] = sorted(set(re.findall(r"NEEDED.*?\[([^\]]+)\]", dynamic)))

    dynsym = run([readelf, "--dyn-syms", str(binary)]) if readelf else ""
    facts["dynamicSymbolCount"] = len([line for line in dynsym.splitlines() if re.match(r"\s*\d+:", line)])
    symtab = run([readelf, "-S", str(binary)]) if readelf else ""
    facts["symbolTablePresent"] = ".symtab" in symtab
    return facts


# --------------------------------------------------------------------------- #
# generate-packages
# --------------------------------------------------------------------------- #

_BUNDLE_FILES = (
    "summary.md",
    "finding.json",
    "installed-package.json",
    "source-package.json",
    "binary-analysis.json",
    "activation-analysis.json",
    "sandbox-analysis.json",
    "evidence-manifest.json",
    "review-questions.md",
)


def generate_packages() -> int:
    """One nine-file review bundle per unresolved Critical or High advisory."""
    if not (FINDINGS / "index.json").is_file():
        print("BLOCKED: run `python scripts/reachability.py generate-findings` first")
        return 2
    index = load(FINDINGS / "index.json")
    symbols = load_optional(REPORTS / "symbol-analysis.json", {"targets": []})
    acquisition = load_optional(SOURCES / "acquisition-manifest.json", None)
    commit = source_commit()

    written: list[str] = []
    for advisory in index["advisories"]:
        record = load(FINDINGS / f"{advisory}.json")
        if record["conclusion"] not in {"Unknown", "Reachable and blocking", "Reachable but mitigated"}:
            continue
        directory = PACKAGES / advisory
        directory.mkdir(parents=True, exist_ok=True)

        write_json(directory / "finding.json", record)
        write_json(directory / "installed-package.json", _installed_package_block(record))
        write_json(directory / "source-package.json", _source_package_block(record, acquisition))
        write_json(directory / "binary-analysis.json", _binary_analysis_block(record, symbols))
        write_json(directory / "activation-analysis.json", _activation_block(record))
        write_json(directory / "sandbox-analysis.json", _sandbox_block(record))
        write_json(directory / "evidence-manifest.json", _evidence_manifest(record, commit))
        write_text(directory / "summary.md", _bundle_summary(record))
        write_text(directory / "review-questions.md", _bundle_questions(record))

        absent = [name for name in _BUNDLE_FILES if not (directory / name).is_file()]
        if absent:  # pragma: no cover
            raise SystemExit(f"{advisory}: bundle missing {', '.join(absent)}")
        written.append(advisory)

    manifest = {
        "schemaVersion": 1,
        "sourceCommit": commit,
        "generatedAt": _now(),
        "bundleCount": len(written),
        "bundles": sorted(written),
        "filesPerBundle": list(_BUNDLE_FILES),
        "note": (
            "Each bundle is self-contained: a reviewer needs the bundle and the repository at the "
            "named commit, and no access to undocumented local state."
        ),
    }
    write_json(PACKAGES / "index.json", manifest)
    print(f"wrote {len(written)} review bundle(s) of {len(_BUNDLE_FILES)} files to {PACKAGES.relative_to(ROOT)}")
    return 0


def _installed_package_block(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "advisoryId": record["advisoryId"],
        "module": record["packageName"],
        "moduleVersion": record["installedVersion"],
        "fixedVersion": record["fixedVersion"],
        "binaryPackage": record["binaryPackage"],
        "carrierObjects": record["carrierObjects"],
        "candidateCarriers": record["candidateCarriers"],
        "installedNevrasMeasured": [target["installedNevra"] for target in ANALYSIS_TARGETS],
        "carrierAttributionConfirmed": False,
        "howToConfirm": [
            "mount or boot the beta deployment built from the pinned base digest",
            "for each of /usr/sbin/podman, /usr/sbin/skopeo, /usr/sbin/bootc: "
            "`find /sysroot/ostree/repo/objects -samefile <binary>`",
            "or `ostree ls -R <commit> /usr/sbin` and compare object checksums",
        ],
    }


def _source_package_block(record: dict[str, Any], acquisition: Any) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "advisoryId": record["advisoryId"],
        "sourcePackage": record["sourcePackage"],
        "sourceRpmReference": record["sourceRpmReference"],
        "debuginfoReference": record["debuginfoReference"],
        "debugsourceReference": record["debugsourceReference"],
        "acquisitionManifestPresent": acquisition is not None,
        "acquisitionPlan": "security/reachability/sources/acquisition-plan.json",
        "vendoredModuleNote": (
            "The module is vendored into a Go binary, so the source of record is the module at the "
            "installed version inside the RPM's vendor tree, not a separately packaged library. "
            "The source RPM is the only artifact that pins which module version Fedora built."
        ),
    }


def _binary_analysis_block(record: dict[str, Any], symbols: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "advisoryId": record["advisoryId"],
        "elfBuildId": record["elfBuildId"],
        "strippedState": record["strippedState"],
        "language": record["language"],
        "exportedSymbols": record["exportedSymbols"],
        "dynamicDependencies": record["dynamicDependencies"],
        "vulnerableFunctionOrSubsystem": record["vulnerableFunctionOrSubsystem"],
        "collectedTargets": symbols.get("collectedTargets", []),
        "uncollectedTargets": symbols.get("uncollectedTargets", []),
        "symbolDiscipline": (
            "An absent symbol is not absent code. For a Go binary the compiler inlines across "
            "package boundaries and the linker rewrites call graphs, so neither the presence nor "
            "the absence of a module-level name settles whether the vulnerable instructions were "
            "emitted. Establishing 'Not present' requires debuginfo and the source build "
            "configuration."
        ),
    }


def _activation_block(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "advisoryId": record["advisoryId"],
        "systemdUnits": record["systemdUnits"],
        "socketUnits": record["socketUnits"],
        "dbusActivation": record["dbusActivation"],
        "desktopActivation": record["desktopActivation"],
        "desktopActivationEvidence": record["desktopActivationEvidence"],
        "defaultEnablement": record["defaultEnablement"],
        "commandInvocationPaths": record["commandInvocationPaths"],
        "bunnyInvocationPaths": record["bunnyInvocationPaths"],
        "pluginInvocationPaths": record["pluginInvocationPaths"],
        "userInvocability": record["userInvocability"],
        "measuredEvidence": "evidence/reachability/beta-facts.txt, beta-permissions.txt",
        "outstanding": [
            "D-Bus activation was not enumerated; `busctl --list` inside a booted deployment would "
            "settle it",
        ],
    }


def _sandbox_block(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "advisoryId": record["advisoryId"],
        "selinux": "selinux-policy-targeted, enforcing",
        "sandboxReachability": record["sandboxReachability"],
        "bunnyUnitHardening": "Bunny units carry systemd sandboxing directives",
        "brokerModel": (
            "The privileged broker exposes typed fixed backends. There is no generic exec path, so "
            "a plugin cannot reach a container runtime through it."
        ),
        "residualExposure": (
            "A local user may invoke the binaries directly; SELinux confines what a rootless "
            "invocation can do but does not remove the code. Confinement reduces blast radius and "
            "is not a reachability answer."
        ),
        "limits": [
            "No SELinux denial testing was performed against a deliberate invocation.",
            "No measurement of what a confined rootless podman can reach was made.",
        ],
    }


def _evidence_manifest(record: dict[str, Any], commit: str) -> dict[str, Any]:
    import hashlib

    files = [
        "evidence/vulnerability/beta-grype.json",
        "evidence/reachability/beta-facts.txt",
        "evidence/reachability/beta-permissions.txt",
        "evidence/reachability/beta-binaries.txt",
        "evidence/reachability/beta-minimised-binaries.txt",
        "operations/data/vulnerability-disposition.json",
        "docs/adr/ADR-027-base-image-security-decision.md",
        "SECURITY_REACHABILITY_REVIEW.md",
    ]
    entries = []
    for relative in files:
        target = ROOT / relative
        if not target.is_file():
            entries.append({"path": relative, "present": False, "sha256": None})
            continue
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        entries.append(
            {
                "path": relative,
                "present": True,
                "sha256": digest.hexdigest(),
                "sizeBytes": target.stat().st_size,
            }
        )
    return {
        "schemaVersion": 1,
        "advisoryId": record["advisoryId"],
        "sourceCommit": commit,
        "generatedAt": _now(),
        "baseImageDigest": "sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4",
        "files": entries,
        "note": (
            "Digests are recomputed from the files on disk at generation time. A reviewer can "
            "verify the bundle describes the repository at the named commit."
        ),
    }


def _bundle_summary(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {record['advisoryId']} — {record['packageName']} {record['installedVersion']}",
            "",
            f"Source commit: `{record['sourceCommit']}`  ",
            f"Current conclusion: **{record['conclusion']}** (blocking)",
            "",
            "## What is established",
            "",
            "| Question | Answer | Basis |",
            "|---|---|---|",
            "| Is the vulnerable module in the image? | yes | scanner match against the built archive |",
            f"| Does it run by default? | {record['defaultEnablement']} | no unit is enabled; no preset enables one |",
            f"| Can an unprivileged user invoke the carrier? | {record['userInvocability']} | mode 0755, no setuid |",
            "| Can Bunny or a plugin invoke it? | no | typed fixed broker backends, no generic exec path |",
            f"| Does sandboxing limit exposure? | {record['sandboxReachability']} | SELinux targeted, enforcing |",
            "| Can the package be removed? | no | bootc requires podman and skopeo; rpm-ostree requires skopeo |",
            "| **Is the vulnerable code path compiled in and active?** | **unknown** | **not determined** |",
            "",
            "## What is not established",
            "",
            f"- The carrier binary. The scan records an ostree object: `{record['installedExecutableOrLibrary']}`.",
            f"- The vulnerable function or subsystem: `{record['vulnerableFunctionOrSubsystem']}`.",
            f"- The ELF build ID: `{record['elfBuildId']}`.",
            f"- The stripped state: `{record['strippedState']}`.",
            "- Whether debuginfo maps the vulnerable function into the shipped build.",
            "",
            "## Notes",
            "",
            record["notes"],
            "",
            "## Fixed version",
            "",
            f"`{record['fixedVersion']}`. Fedora 44 ships no build carrying it: `dnf check-update`",
            "returns nothing for the carrier packages, and a base rebuild on 2026-07-29 did not",
            "move the position.",
            "",
        ]
    )


def _bundle_questions(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Review questions — {record['advisoryId']}",
            "",
            "Answer each with the evidence you used. An unanswered question is not a negative",
            "answer, and a `Not present` conclusion drawn from a symbol table alone will be",
            "rejected by `release/cve.py`.",
            "",
            "## 1. Carrier attribution",
            "",
            f"Which installed binary carries `{record['packageName']} {record['installedVersion']}`?",
            "The scan records only an ostree object digest. Candidates:",
            "",
        ]
        + [f"- `{candidate}`" for candidate in record["candidateCarriers"]]
        + [
            "",
            "## 2. The vulnerable function",
            "",
            "Name the vulnerable source file and function from the advisory, and the feature it",
            "belongs to. If the advisory does not identify one, say so.",
            "",
            "## 3. Presence in the shipped build",
            "",
            "Is the vulnerable code compiled into the installed binary? Required evidence:",
            "",
            "- the installed NEVRA and the source RPM at the *same* version and release;",
            "- the build configuration Fedora used, including build tags;",
            "- a mapping from the vulnerable function to the binary, via debuginfo or debugsource.",
            "",
            "Go's linker eliminates dead code and the compiler inlines across package boundaries.",
            "Neither a present nor an absent module-level symbol settles this.",
            "",
            "## 4. Reachability",
            "",
            "If present, is there a supported or attacker-controlled path that reaches it? State:",
            "",
            "- the command required, and the privilege it needs;",
            "- the input type, and whether it can come from a network or an untrusted file;",
            "- whether any enabled unit, socket, D-Bus name or desktop entry reaches it;",
            "- whether Bunny OS exposes the feature at all.",
            "",
            "## 5. Mitigation",
            "",
            "If reachable, does SELinux targeted policy or systemd sandboxing materially reduce the",
            "exploit? Name the control, analyse the bypass, and state the residual impact.",
            "",
            "## 6. Conclusion",
            "",
            "One of: `Not present`, `Present but unreachable`, `Reachable but mitigated`,",
            "`Reachable and blocking`, `Unknown`.",
            "",
            "`Unknown` is an acceptable and often correct answer. It remains blocking, which is the",
            "current state, so concluding `Unknown` costs the project nothing it has not already",
            "lost. A wrong `Not present` on a Critical finding would clear a blocker it should not.",
            "",
        ]
    )


# --------------------------------------------------------------------------- #
# disposition
# --------------------------------------------------------------------------- #


def _completed_reviews() -> tuple[str, ...]:
    document = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    return completed_review_identifiers(document)


def _independent_reviewers() -> set[str]:
    document = load_optional(DATA / "independent-reviews.json", {"schemaVersion": 1, "reviews": []})
    return {
        str(item["reviewer"])
        for item in document.get("reviews", [])
        if isinstance(item, dict) and item.get("state") == "delivered" and item.get("reviewer")
    }


def collect_analyses() -> tuple[dict[str, Any], list[str], list[str]]:
    findings = blocking_findings()
    expected = [finding["advisoryId"] for finding in findings]
    critical = [f["advisoryId"] for f in findings if f["scannerSeverity"] == "Critical"]
    analyses = []
    for advisory in expected:
        path = FINDINGS / f"{advisory}.json"
        if path.is_file():
            analyses.append(load(path))
    return {"schemaVersion": 1, "analyses": analyses}, expected, critical


def disposition() -> int:
    document, expected, critical = collect_analyses()
    try:
        result = evaluate_document(
            document,
            completed_independent_reviews=_completed_reviews(),
            criticalAdvisories=critical,
            independentReviewers=_independent_reviewers(),
            expectedAdvisories=expected,
        )
    except CveAnalysisError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    write_json(OUT / "cve-reachability-disposition.json", result)
    write_json(REPORTS / "disposition.json", result)

    print(f"per-CVE analyses: {result['analysed']} of {len(expected)} Critical/High advisories")
    for name, advisories in sorted(result["byProofClass"].items()):
        print(f"  {name:26} {len(advisories)}")
    if result["uncoveredAdvisories"]:
        print("  UNCOVERED: " + ", ".join(result["uncoveredAdvisories"]))
    if result["blocked"]:
        print(f"BLOCKED: {result['blockingCount']} advisory(ies) block a stable release")
        return 2
    print("every Critical and High advisory has an acceptable, reviewed disposition")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="reachability")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "generate-findings",
        "acquire-plan",
        "validate-acquisition",
        "generate-packages",
        "disposition",
    ):
        commands.add_parser(name)
    symbols = commands.add_parser("analyse-symbols")
    symbols.add_argument(
        "--sysroot",
        type=Path,
        help="root of a mounted Bunny OS deployment; omit to look at this host",
    )

    args = parser.parse_args()
    if args.command == "generate-findings":
        return generate_findings()
    if args.command == "acquire-plan":
        return acquire_plan()
    if args.command == "validate-acquisition":
        return validate_acquisition()
    if args.command == "analyse-symbols":
        return analyse_symbols(args.sysroot)
    if args.command == "generate-packages":
        return generate_packages()
    if args.command == "disposition":
        return disposition()
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
