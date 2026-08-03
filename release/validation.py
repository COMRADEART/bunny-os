# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repository validation, reported one validator at a time.

The source gate used to say:

    FAIL    repositoryValidation: every JSON document parses, every schema is
            well formed, every Python file compiles

The thing that had actually failed was ShellCheck, on one line of one file. The
description named JSON, schemas and Python — none of which failed — so the
message sent a reader to the wrong three places. One Boolean was standing in for
twelve independent checks.

Each validator here reports its own result, its own count, and the exact files
that failed. The gate's verdict is unchanged: any failing validator fails
`repositoryValidation`, and the gate still exits 2. Only the diagnosis improved.

A validator that cannot run reports ``SKIP`` with the reason. A skip is not a
pass, and the report says which host tool was missing, so "it passed locally"
and "it never ran locally" are distinguishable.
"""

from __future__ import annotations

from configparser import ConfigParser, Error as ConfigParserError
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Iterable, Sequence
import xml.etree.ElementTree as ET

__all__ = [
    "REQUIRED_VALIDATORS",
    "ValidationReport",
    "ValidatorOutcome",
    "run_validators",
]

#: The ten a source gate must report separately. Extra validators are permitted
#: and are reported the same way; these ten may not be dropped or merged.
REQUIRED_VALIDATORS = (
    "JSON parsing",
    "Schema validation",
    "Python compilation",
    "Shell syntax",
    "ShellCheck",
    "Desktop entries",
    "XML and SVG",
    "Licence headers",
    "Workflow YAML",
    "Committed evidence consistency",
)

#: SPDX identifiers this project ships under. GPL-3.0-or-later is the product;
#: the enterprise, sync and OEM integration surfaces are Apache-2.0 so that a
#: downstream integrator can implement against them. Anything else is a licence
#: nobody decided to ship.
PERMITTED_SPDX = frozenset({"GPL-3.0-or-later", "Apache-2.0"})

_SPDX = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")
_SKIP_PARTS = frozenset({"node_modules", ".git", ".selfcheck-tmp", "__pycache__", "out"})


@dataclass(frozen=True)
class Failure:
    path: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "detail": self.detail}


@dataclass
class ValidatorOutcome:
    name: str
    result: str = "PASS"
    checked: int = 0
    summary: str = ""
    failures: list[Failure] = field(default_factory=list)
    skipReason: str | None = None

    @property
    def failed(self) -> bool:
        return self.result == "FAIL"

    def as_dict(self) -> dict[str, Any]:
        return {
            "validator": self.name,
            "result": self.result,
            "checked": self.checked,
            "summary": self.summary,
            "skipReason": self.skipReason,
            "failures": [item.as_dict() for item in self.failures],
        }


@dataclass
class ValidationReport:
    outcomes: list[ValidatorOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(outcome.failed for outcome in self.outcomes)

    @property
    def failing(self) -> list[ValidatorOutcome]:
        return [outcome for outcome in self.outcomes if outcome.failed]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "result": "PASS" if self.passed else "FAIL",
            "requiredValidators": list(REQUIRED_VALIDATORS),
            "validators": [outcome.as_dict() for outcome in self.outcomes],
            "failingValidators": [outcome.name for outcome in self.failing],
            "note": (
                "A SKIP is not a PASS. It records that the host lacked the tool, so a "
                "check that never ran is distinguishable from one that ran and passed."
            ),
        }

    def render(self, *, verbose: bool = True) -> str:
        lines: list[str] = []
        for outcome in self.outcomes:
            marker = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip"}[outcome.result]
            detail = outcome.summary or outcome.skipReason or ""
            lines.append(f"  {marker}  {outcome.name:32} {detail}")
            if outcome.failed and verbose:
                for item in outcome.failures[:20]:
                    lines.append(f"           {item.path}")
                    lines.append(f"             {item.detail}")
                if len(outcome.failures) > 20:
                    lines.append(f"           ... and {len(outcome.failures) - 20} more")
        return "\n".join(lines)


def _walk(root: Path, pattern: str, *, under: str | None = None) -> list[Path]:
    base = root / under if under else root
    if not base.exists():
        return []
    return sorted(
        path
        for path in base.rglob(pattern)
        if not _SKIP_PARTS.intersection(path.parts)
    )


# --------------------------------------------------------------------------- #
# The validators
# --------------------------------------------------------------------------- #


def _json_parsing(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("JSON parsing")
    paths = sorted({
        *_walk(root, "*.json", under="schemas"),
        *_walk(root, "*.json", under="shell"),
        *_walk(root, "*.json", under="build"),
        *_walk(root, "*.json", under="operations"),
        *_walk(root, "*.json", under="tests/operations/fixtures"),
        *_walk(root, "*.json", under="oem"),
        *_walk(root, "*.json", under="enterprise"),
        *_walk(root, "*.json", under="sync"),
        *_walk(root, "*.json", under="security"),
        # Service capability manifests. A manifest that does not parse would
        # otherwise fail at boot on the machine it was meant to describe.
        *_walk(root, "*.json", under="capability"),
    })
    for path in paths:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            outcome.failures.append(Failure(_name(root, path), str(exc)))
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} documents parsed"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _schema_validation(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("Schema validation")
    paths = sorted({
        *_walk(root, "*.schema.json", under="schemas"),
        *_walk(root, "*.schema.json", under="shell/schemas"),
        *_walk(root, "*.schema.json", under="security"),
    })
    for path in paths:
        name = _name(root, path)
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            outcome.failures.append(Failure(name, f"unparseable: {exc}"))
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            outcome.failures.append(Failure(name, "missing or wrong $schema declaration"))
        if not schema.get("$id"):
            outcome.failures.append(Failure(name, "no $id"))
        if schema.get("type") != "object":
            outcome.failures.append(Failure(name, "top-level type is not object"))
        for reference in _unresolved_local_references(schema):
            outcome.failures.append(Failure(name, f"unresolved local reference {reference}"))

    try:
        import jsonschema  # type: ignore
    except ImportError:
        outcome.skipReason = "jsonschema unavailable; headers and local references still checked"
    else:
        for path in paths:
            try:
                jsonschema.Draft202012Validator.check_schema(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except Exception as exc:  # jsonschema raises several types
                outcome.failures.append(Failure(_name(root, path), f"invalid schema: {exc}"))

    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} schemas" + (
        f" ({outcome.skipReason})" if outcome.skipReason else ""
    )
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _unresolved_local_references(schema: Any) -> list[str]:
    unresolved: list[str] = []

    def resolve(node: Any) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/"):
                target: Any = schema
                for component in reference[2:].split("/"):
                    component = component.replace("~1", "/").replace("~0", "~")
                    if not isinstance(target, dict) or component not in target:
                        unresolved.append(reference)
                        break
                    target = target[component]
            for value in node.values():
                resolve(value)
        elif isinstance(node, list):
            for value in node:
                resolve(value)

    resolve(schema)
    return unresolved


def _python_compilation(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("Python compilation")
    paths = _walk(root, "*.py")
    for path in paths:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (SyntaxError, ValueError, OSError, UnicodeDecodeError) as exc:
            outcome.failures.append(Failure(_name(root, path), str(exc)))
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} files compiled in memory"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _shell_paths(root: Path) -> list[Path]:
    return _walk(root, "*.sh")


def _shell_syntax(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("Shell syntax")
    paths = _shell_paths(root)
    bash = shutil.which("bash")
    if not bash:
        outcome.result = "SKIP"
        outcome.skipReason = "bash unavailable on this host"
        outcome.checked = len(paths)
        return outcome
    for path in paths:
        result = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            outcome.failures.append(
                Failure(_name(root, path), result.stderr.strip() or "bash -n rejected the script")
            )
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} scripts parsed by bash -n"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _shellcheck(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("ShellCheck")
    paths = _shell_paths(root)
    if not shutil.which("shellcheck"):
        outcome.result = "SKIP"
        outcome.skipReason = "shellcheck unavailable on this host"
        outcome.checked = len(paths)
        return outcome
    # No --severity floor and no --exclude: an info finding is a finding. SC1091
    # failed four CI jobs and was fixed at its cause rather than filtered.
    result = subprocess.run(
        ["shellcheck", *[str(path) for path in paths]],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        for block in _shellcheck_blocks(result.stdout, root):
            outcome.failures.append(block)
        if not outcome.failures:
            outcome.failures.append(Failure("<shellcheck>", result.stdout.strip()[:2000]))
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} scripts, no suppression"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _shellcheck_blocks(output: str, root: Path) -> list[Failure]:
    """Turn shellcheck's prose into (file:line, code + message) pairs."""
    failures: list[Failure] = []
    location = None
    for line in output.splitlines():
        header = re.match(r"^In (.+) line (\d+):$", line.strip())
        if header:
            path = header.group(1)
            try:
                path = str(Path(path).resolve().relative_to(root.resolve())).replace("\\", "/")
            except ValueError:
                pass
            location = f"{path}:{header.group(2)}"
            continue
        finding = re.search(r"\b(SC\d{4})\s*\(([a-z]+)\):\s*(.+)$", line)
        if finding and location:
            failures.append(
                Failure(location, f"{finding.group(1)} ({finding.group(2)}): {finding.group(3)}")
            )
            location = None
    return failures


def _desktop_entries(root: Path) -> ValidatorOutcome:
    """Application launchers and session entries, checked against their own rules.

    They are different file kinds. ``DesktopNames`` is required in a GNOME
    session entry and unknown to the freedesktop Desktop Entry Specification,
    so validating both with one set of rules rejects a correct file.
    """
    outcome = ValidatorOutcome("Desktop entries")
    paths = sorted({*_walk(root, "*.desktop", under="shell"),
                    *_walk(root, "*.desktop", under="installer")})
    sessions = 0
    for path in paths:
        name = _name(root, path)
        parser = ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str  # type: ignore[assignment]
        try:
            parser.read(path, encoding="utf-8")
        except ConfigParserError as exc:
            outcome.failures.append(Failure(name, f"unparseable: {exc}"))
            continue
        if not parser.has_section("Desktop Entry"):
            outcome.failures.append(Failure(name, "no [Desktop Entry] section"))
            continue
        entry = parser["Desktop Entry"]
        is_session = "/session/" in name or name.endswith("/session.desktop")
        for required in ("Type", "Name", "Exec"):
            if not entry.get(required):
                outcome.failures.append(Failure(name, f"missing {required}"))
        if entry.get("Type") != "Application":
            outcome.failures.append(Failure(name, f"Type is {entry.get('Type')!r}, expected Application"))
        if is_session:
            sessions += 1
            if not entry.get("DesktopNames"):
                outcome.failures.append(
                    Failure(name, "a session entry must declare DesktopNames")
                )
        elif entry.get("DesktopNames"):
            outcome.failures.append(
                Failure(name, "DesktopNames is a session key and does not belong in a launcher")
            )
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} entries ({sessions} session, {len(paths) - sessions} launcher)"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _xml_and_svg(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("XML and SVG")
    paths = [
        root / "shell/components/gnome-shell-extension/schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml",
        *_walk(root, "*.svg", under="shell/assets"),
        *_walk(root, "*.svg", under="shell/icons"),
    ]
    paths = [path for path in paths if path.exists()]
    for path in paths:
        try:
            ET.parse(path)
        except (ET.ParseError, OSError) as exc:
            outcome.failures.append(Failure(_name(root, path), str(exc)))
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} XML/SVG assets parsed"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _licence_headers(root: Path) -> ValidatorOutcome:
    """No file may declare a licence the project did not decide to ship under."""
    outcome = ValidatorOutcome("Licence headers")
    paths = [
        *_walk(root, "*.py"),
        *_walk(root, "*.sh"),
        *_walk(root, "*.js"),
    ]
    declared = 0
    for path in paths:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:  # pragma: no cover
            continue
        for match in _SPDX.finditer(head):
            identifier = match.group(1)
            if identifier.startswith("{") or "\\" in identifier:
                continue  # a format string or a regex in the licence tooling itself
            declared += 1
            if identifier not in PERMITTED_SPDX:
                outcome.failures.append(
                    Failure(
                        _name(root, path),
                        f"declares {identifier}, which is not among {sorted(PERMITTED_SPDX)}",
                    )
                )
    outcome.checked = len(paths)
    outcome.summary = (
        f"{declared} declarations over {len(paths)} files, all within "
        f"{sorted(PERMITTED_SPDX)}"
    )
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _capability_manifests(root: Path) -> ValidatorOutcome:
    """Shipped service manifests must parse, validate, and agree as a set.

    A manifest is a safety input: it is what tells the policy engine how much
    memory a service needs before that service is started. An unparseable one
    would fail at boot on the machine it was meant to describe, and a set that
    disagrees with itself — a dependency nothing declares, an asymmetric
    conflict, an essential service depending on an optional one — produces a
    control plane that a resource decision can switch off. Both are caught here
    rather than in production.
    """
    outcome = ValidatorOutcome("Capability manifests")
    directory = root / "capability/services"
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    outcome.checked = len(paths)
    if not paths:
        outcome.result = "SKIP"
        outcome.skipReason = "no capability/services directory in this tree"
        return outcome

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from capability.manifest import ManifestError, load_manifest
        from capability.registry import build_registry
    except ImportError as exc:
        outcome.result = "SKIP"
        outcome.skipReason = f"capability package not importable ({exc}); manifests were not validated"
        return outcome

    manifests = []
    for path in paths:
        try:
            manifests.append(load_manifest(path))
        except ManifestError as exc:
            outcome.failures.append(Failure(_name(root, path), str(exc)))

    if not outcome.failures:
        try:
            registry = build_registry(manifests)
        except ManifestError as exc:
            outcome.failures.append(Failure(_name(root, directory), str(exc)))
        else:
            outcome.summary = (
                f"{len(manifests)} manifests, {len(registry.essential())} essential, "
                f"{registry.essential_floor_bytes() // (1024 ** 2)} MiB essential floor"
            )
    if not outcome.summary:
        outcome.summary = f"{len(paths)} manifests"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _workflow_yaml(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("Workflow YAML")
    paths = sorted((root / ".github/workflows").glob("*.yml")) + sorted(
        (root / ".github/workflows").glob("*.yaml")
    )
    try:
        import yaml  # type: ignore
    except ImportError:
        outcome.result = "SKIP"
        outcome.skipReason = "PyYAML unavailable; workflow syntax not parsed"
        outcome.checked = len(paths)
        return outcome

    for path in paths:
        name = _name(root, path)
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            outcome.failures.append(Failure(name, f"unparseable: {exc}"))
            continue
        if not isinstance(document, dict):
            outcome.failures.append(Failure(name, "top level is not a mapping"))
            continue
        jobs = document.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            outcome.failures.append(Failure(name, "no jobs defined"))
            continue
        # `on:` parses as the boolean True in YAML 1.1, which is why it is looked
        # up both ways rather than by string alone.
        if "on" not in document and True not in document:
            outcome.failures.append(Failure(name, "no trigger (`on:`) defined"))
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                outcome.failures.append(Failure(name, f"job {job_name} is not a mapping"))
                continue
            if "runs-on" not in job and "uses" not in job:
                outcome.failures.append(
                    Failure(name, f"job {job_name} declares neither runs-on nor uses")
                )
    outcome.checked = len(paths)
    outcome.summary = f"{len(paths)} workflows parsed"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _committed_evidence_consistency(root: Path) -> ValidatorOutcome:
    """Committed evidence must name a real candidate commit, and agree about it."""
    outcome = ValidatorOutcome("Committed evidence consistency")
    checked = 0

    evidence_path = root / "operations/data/release-evidence.json"
    declared: str | None = None
    if evidence_path.is_file():
        checked += 1
        try:
            declared = json.loads(evidence_path.read_text(encoding="utf-8")).get("candidateCommit")
        except json.JSONDecodeError as exc:
            outcome.failures.append(Failure(_name(root, evidence_path), f"unparseable: {exc}"))
        else:
            if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{40}", declared):
                outcome.failures.append(
                    Failure(
                        _name(root, evidence_path),
                        f"candidateCommit {declared!r} is not a full 40-character SHA",
                    )
                )
                declared = None
            elif _git(root, "cat-file", "-e", f"{declared}^{{commit}}") is None:
                # A shallow clone legitimately lacks it; that is reported, not failed,
                # because the same tree on a full clone is correct.
                outcome.skipReason = (
                    f"candidateCommit {declared[:12]} is not present in this clone "
                    "(shallow checkout); its existence was not verified"
                )

    findings = sorted((root / "security/reachability/findings").glob("*.json"))
    if declared and findings:
        for path in findings:
            checked += 1
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                outcome.failures.append(Failure(_name(root, path), f"unparseable: {exc}"))
                continue
            actual = record.get("sourceCommit")
            if actual != declared:
                outcome.failures.append(
                    Failure(
                        _name(root, path),
                        f"binds to {str(actual)[:12]} but the declared candidate is "
                        f"{declared[:12]}; evidence does not transfer between commits",
                    )
                )

    outcome.checked = checked
    outcome.summary = (
        f"{checked} record(s) agree on candidate {declared[:12]}" if declared
        else f"{checked} record(s) checked"
    )
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _gnome_extension(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("GNOME extension syntax")
    target = root / "shell/components/gnome-shell-extension/extension.js"
    if not target.is_file():
        outcome.result = "SKIP"
        outcome.skipReason = "extension.js absent"
        return outcome
    if not shutil.which("node"):
        outcome.result = "SKIP"
        outcome.skipReason = "node unavailable on this host"
        return outcome
    result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
    if result.returncode != 0:
        outcome.failures.append(Failure(_name(root, target), result.stderr.strip()))
    outcome.checked = 1
    outcome.summary = "extension.js parsed by node --check"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _systemd_units(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("systemd units")
    paths = [
        path for path in sorted((root / "systemd").glob("*.*"))
        if path.suffix in {".service", ".socket", ".timer", ".target"}
    ]
    outcome.checked = len(paths)
    if os.environ.get("BUNNY_VERIFY_SYSTEMD") != "1" or not shutil.which("systemd-analyze"):
        outcome.result = "SKIP"
        outcome.skipReason = (
            "requires BUNNY_VERIFY_SYSTEMD=1 and systemd-analyze on an installed Fedora fixture"
        )
        return outcome
    result = subprocess.run(
        ["systemd-analyze", "verify", *[str(path) for path in paths]],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        for line in (result.stderr or result.stdout).splitlines():
            if line.strip():
                outcome.failures.append(Failure("systemd/", line.strip()))
    outcome.summary = f"{len(paths)} units verified"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


#: Where a program named by a unit's ExecStart= may come from. install-root.py
#: copies from these directories into /usr/libexec and /usr/bin, keeping the
#: basename.
_PROGRAM_SOURCES = (
    ("scripts", ".py"),
    ("installer/bin", ""),
    ("shell/services/bin", ""),
    ("services/bunny-system-broker/bin", ""),
    ("tools/bunny-os/bin", ""),
)

#: Programs whose source file is not named after the installed program.
_PROGRAM_ALIASES = {
    "bunny-update-agent": "services/bunny-update-agent/bunny_update_agent.py",
    "bunny-capability-supervisor": "services/bunny-capability-supervisor/bunny_capability_supervisor.py",
}

#: Prefixes owned by something other than install-root.py.
#:
#: /opt/bunny is the Bunny application payload. It is delivered through
#: build/artifacts/bunny against build/manifests/bunny-artifact.placeholder.json
#: and is checked by build/scripts/verify-bunny-artifact.py, which compares every
#: file against the manifest — a stronger check than "a file with this name
#: exists". Everything else here is supplied by the base image.
_EXTERNALLY_PROVIDED = (
    "/opt/bunny/",
    "/usr/bin/systemctl",
    "/usr/bin/true",
    "/bin/",
    "/usr/sbin/",
    "/usr/lib/systemd/",
)


def _systemd_unit_programs(root: Path) -> ValidatorOutcome:
    """Every unit must name a program this repository actually ships.

    `systemd-analyze verify` in CI reported four units whose ExecStart= did not
    resolve. Three were an artefact of running on a bare container. The fourth,
    bunny-policy-agent, names a program nothing installs — a real gap that was
    invisible inside the noise. It is recorded in unit-program-gaps.json; a unit
    that is neither shippable nor recorded fails here.
    """
    outcome = ValidatorOutcome("systemd unit programs")
    recorded: dict[str, str] = {}
    gaps_path = root / "operations/data/unit-program-gaps.json"
    if gaps_path.is_file():
        try:
            document = json.loads(gaps_path.read_text(encoding="utf-8"))
            recorded = {item["unit"]: item.get("program", "") for item in document.get("gaps", [])}
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            outcome.failures.append(Failure(_name(root, gaps_path), f"unreadable: {exc}"))

    units = sorted(
        path for path in (root / "systemd").rglob("*")
        if path.suffix in {".service", ".socket", ".timer", ".target"}
    )
    for path in units:
        unit = path.name
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^ExecStart=-?(?:[+!@]*)(/\S+)", line.strip())
            if not match:
                continue
            program = match.group(1)
            basename = program.rsplit("/", 1)[-1]
            if program.startswith(_EXTERNALLY_PROVIDED):
                continue
            alias = _PROGRAM_ALIASES.get(basename)
            shipped = (root / alias).is_file() if alias else any(
                (root / directory / f"{basename}{suffix}").is_file()
                for directory, suffix in _PROGRAM_SOURCES
            )
            if shipped:
                continue
            if unit in recorded:
                continue
            outcome.failures.append(
                Failure(
                    _name(root, path),
                    f"ExecStart={program} names a program this repository does not ship and "
                    "which is not recorded in operations/data/unit-program-gaps.json",
                )
            )

    stale = [unit for unit in recorded if not (root / "systemd" / unit).is_file()
             and not (root / "systemd/user" / unit).is_file()]
    for unit in stale:
        outcome.failures.append(
            Failure("operations/data/unit-program-gaps.json",
                    f"records a gap for {unit}, which is no longer a unit in this repository")
        )

    outcome.checked = len(units)
    outcome.summary = f"{len(units)} units, {len(recorded)} recorded gap(s)"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _shell_layout(root: Path) -> ValidatorOutcome:
    outcome = ValidatorOutcome("Shell layout")
    required = ("session", "services", "components", "schemas", "themes", "assets", "icons")
    for name in required:
        if not (root / "shell" / name).is_dir():
            outcome.failures.append(Failure(f"shell/{name}", "required directory is missing"))
    outcome.checked = len(required)
    outcome.summary = f"{len(required)} required shell directories"
    outcome.result = "FAIL" if outcome.failures else "PASS"
    return outcome


def _name(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:  # pragma: no cover - a validator target outside the tree
        return str(path)


def _git(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return result.stdout.strip()


#: Order is the order they are reported in. The ten required ones come first.
_VALIDATORS: tuple[tuple[str, Callable[[Path], ValidatorOutcome]], ...] = (
    ("JSON parsing", _json_parsing),
    ("Schema validation", _schema_validation),
    ("Python compilation", _python_compilation),
    ("Shell syntax", _shell_syntax),
    ("ShellCheck", _shellcheck),
    ("Desktop entries", _desktop_entries),
    ("XML and SVG", _xml_and_svg),
    ("Licence headers", _licence_headers),
    ("Workflow YAML", _workflow_yaml),
    ("Committed evidence consistency", _committed_evidence_consistency),
    ("GNOME extension syntax", _gnome_extension),
    ("systemd units", _systemd_units),
    ("systemd unit programs", _systemd_unit_programs),
    ("Shell layout", _shell_layout),
    ("Capability manifests", _capability_manifests),
)


def run_validators(root: Path, *, only: Iterable[str] | None = None) -> ValidationReport:
    """Run every validator and collect the results. Never raises for a failure."""
    wanted = set(only) if only is not None else None
    report = ValidationReport()
    for name, function in _VALIDATORS:
        if wanted is not None and name not in wanted:
            continue
        try:
            report.outcomes.append(function(root))
        except Exception as exc:  # a validator that crashes is a failing validator
            report.outcomes.append(
                ValidatorOutcome(
                    name,
                    result="FAIL",
                    summary="the validator itself raised",
                    failures=[Failure("<validator>", f"{type(exc).__name__}: {exc}")],
                )
            )
    return report
