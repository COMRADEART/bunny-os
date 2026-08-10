#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which repository files can reach the constructed artifact, and by what route.

"Is this change build-affecting?" is a question that has been answered by
inspection in this repository, and inspection has been wrong twice.

The first time, the capability applicator commit was recorded as having no build
impact because ``capability/`` is not installed, while six files it changed under
``schemas/`` and ``docs/`` are copied into the image wholesale. Reading one
script and stopping is how that happens, and this tool was written to stop it.

The second time it was this tool that was wrong, and worse: it was wrong
*silently, in the safe-sounding direction*. It collected install routes by
walking ``install-root.py``'s AST for calls named ``copy_tree`` or ``copy_file``
and skipping everything else — and ``companion/`` and ``capability/`` are
installed by neither. They are installed by ``copy_python_package``, a third
helper the collector filtered out **before** it recorded anything, so the call
did not even appear in the "unresolved" list that exists to say the closure is
incomplete. Every file in the voice runtime was therefore classified
``context-only``, and the voice-runtime phase reported its build impact as zero
installed paths when the truth was the whole ``companion`` package.

The repair is structural rather than a fourth helper name in the tuple:

``build/scripts/install_routes.py``
    declares the install set as data, and ``install-root.py`` is driven by it.
    This script reads the same declaration. The predicate that decides "does
    this path reach the image, and where" is one function used by both, so
    there is no longer anything for the installer and the analyser to disagree
    about. A helper renamed, split or inlined moves no route.

``install_routes.audit_installer``
    reads ``install-root.py`` and refuses it if it installs anything the table
    does not describe — a new copy helper, a copy issued outside a route stage,
    a generated file nobody declared. When it refuses, this script exits 2 and
    makes **no claim at all**, because an understated closure is worse than no
    closure: it licenses exactly the "this change does not affect the build"
    sentence it cannot support.

The build context is still read from ``build/Containerfile``. Its ``COPY``
directives are the only repository paths the build can see, and a path absent
from all of them cannot reach the artifact by any route.

Three classifications come out:

``installed``
    Reaches the committed layer at a stated destination. **Build-affecting.**
``context-only``
    Visible to the build, not installed by any declared route. The Containerfile
    deletes ``/tmp/bunny-os`` before committing, so these are *probably* absent
    from the artifact — but "probably" is not the standard, and an empirical
    two-build comparison is required to say so.
``unreachable``
    Absent from every COPY directive. Cannot affect the artifact.

Usage::

    build-input-closure.py --map
    build-input-closure.py --range 0cf81a1..b825dd4
    build-input-closure.py --paths companion/voice/worker.py
    build-input-closure.py --audit
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from install_routes import (  # noqa: E402 - the path above is what makes this importable
    GENERATED_ROUTES,
    INSTALL_ROUTES,
    MODELLED_HELPERS,
    PROFILES,
    InstallRoute,
    audit_installer,
    installed_destination,
)

ROOT = Path(__file__).resolve().parents[2]


class ClosureError(RuntimeError):
    """The closure could not be computed, so no claim may be made from it."""


# --------------------------------------------------------------------------- #
# Build context, from the Containerfile
# --------------------------------------------------------------------------- #

_COPY = re.compile(r"^\s*COPY\s+(?P<body>.+?)\s*$", re.IGNORECASE)


def build_context_roots(containerfile: Path) -> tuple[list[str], list[str]]:
    """Repository paths the build can see, and any COPY this cannot resolve.

    A ``COPY .`` or ``COPY --from=`` is returned as unresolved rather than
    guessed at: the first would make every path reachable and the second copies
    from another stage, and quietly assuming either would produce a closure that
    understates what the build sees.
    """
    roots: list[str] = []
    unresolved: list[str] = []
    text = containerfile.read_text(encoding="utf-8")
    # Join line continuations before matching, so a wrapped COPY is one directive.
    text = re.sub(r"\\\s*\n\s*", " ", text)
    for line in text.splitlines():
        match = _COPY.match(line)
        if match is None:
            continue
        body = match.group("body")
        if body.startswith("--"):
            unresolved.append(line.strip())
            continue
        parts = body.split()
        if len(parts) < 2:
            unresolved.append(line.strip())
            continue
        for item in parts[:-1]:
            if item in (".", "./") or item.startswith(".."):
                unresolved.append(line.strip())
                continue
            roots.append(item.rstrip("/"))
    return sorted(set(roots)), unresolved


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(
    path: str,
    roots: Iterable[str],
    routes: Sequence[InstallRoute] = INSTALL_ROUTES,
) -> dict[str, Any]:
    """Where one repository-relative path can reach, and how.

    Every route is offered the path through the shared predicate. A path that
    several routes carry — ``capability/services/*.json`` is installed as
    manifest data and would also be caught by a package route if it were Python
    — reports all of them, because "which copy of this file does the image use"
    is a question a reader must be able to see the whole of.
    """
    normalised = path.replace("\\", "/").lstrip("./")

    reachable = any(
        normalised == root or normalised.startswith(root + "/")
        for root in roots
    )

    matched: list[dict[str, Any]] = []
    for route in routes:
        destination = installed_destination(route, normalised)
        if destination is None:
            continue
        matched.append({
            "routeId": route.id,
            "kind": route.kind,
            "sourcePath": route.source,
            "destination": route.destination,
            "installedAs": destination,
            "mode": oct(route.mode),
            "profiles": sorted(route.profiles) if route.profiles is not None else list(PROFILES),
        })

    if matched and not reachable:
        # A route names this path and the build context does not contain it, so
        # the copy inside the container has nothing to copy. Reporting this as
        # "installed" would be the analyser's original defect running the other
        # way round: it told the truth about routes and not about reach, and a
        # package added to install_routes.py without a matching COPY in the
        # Containerfile was silently absent from the image while every check
        # said it was there. Named separately so it cannot be read as either
        # "installed" or "not built from".
        classification = "route-without-context"
    elif matched:
        classification = "installed"
    elif reachable:
        classification = "context-only"
    else:
        classification = "unreachable"

    return {
        "path": normalised,
        "classification": classification,
        "inBuildContext": reachable,
        "profiles": sorted({
            profile for item in matched for profile in item["profiles"]
        }),
        "routes": matched,
    }


def changed_paths(revision_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", revision_range],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ClosureError(f"git diff {revision_range} failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def installer_audit() -> list[str]:
    installer = ROOT / "build/scripts/install-root.py"
    if not installer.is_file():
        return ["build/scripts/install-root.py is missing"]
    return audit_installer(installer)


def build_closure(paths: list[str]) -> dict[str, Any]:
    containerfile = ROOT / "build/Containerfile"
    installer = ROOT / "build/scripts/install-root.py"
    if not containerfile.is_file() or not installer.is_file():
        raise ClosureError("the Containerfile or install-root.py is missing; no closure can be computed")

    complaints = installer_audit()
    if complaints:
        raise ClosureError(
            "install-root.py installs something build/scripts/install_routes.py does "
            "not model, so the install set this script would report is not the install "
            "set the build produces:\n  " + "\n  ".join(complaints)
        )

    roots, copy_unresolved = build_context_roots(containerfile)
    if copy_unresolved:
        raise ClosureError(
            "the Containerfile has COPY directives this script cannot resolve, so the "
            "build context is not fully known:\n  " + "\n  ".join(copy_unresolved)
        )

    classified = [classify(item, roots) for item in paths]
    installed = [item for item in classified if item["classification"] == "installed"]
    context_only = [item for item in classified if item["classification"] == "context-only"]
    unreachable = [item for item in classified if item["classification"] == "unreachable"]

    return {
        "schemaVersion": 2,
        "buildContextRoots": roots,
        "unresolvedCopyDirectives": copy_unresolved,
        "installerAuditComplaints": complaints,
        "declaredRouteCount": len(INSTALL_ROUTES),
        "modelledHelpers": dict(sorted(MODELLED_HELPERS.items())),
        "generatedRoutes": [dict(item) for item in GENERATED_ROUTES],
        "closureComplete": True,
        "summary": {
            "examined": len(classified),
            "installed": len(installed),
            "contextOnly": len(context_only),
            "unreachable": len(unreachable),
            "buildAffecting": bool(installed),
            "affectedProfiles": sorted({
                profile for item in installed for profile in item["profiles"]
            }),
        },
        "installed": installed,
        "contextOnly": context_only,
        "unreachable": unreachable,
        "interpretation": {
            "installed": "reaches the committed layer; the change IS build-affecting",
            "contextOnly": (
                "visible to the build but installed by no declared route. The "
                "Containerfile deletes /tmp/bunny-os before committing, so these are "
                "probably absent from the artifact — but 'probably' is not the standard, "
                "and an empirical two-build comparison is required to say so."
            ),
            "unreachable": "absent from every COPY directive; cannot affect the artifact by any route",
            "caveat": (
                "Every commit changes the OCI configuration digest through the revision "
                "label and /usr/lib/bunny-os/release.json. An unchanged layer digest is "
                "not an unchanged image."
            ),
        },
    }


def render(document: dict[str, Any]) -> str:
    lines = ["Build-input closure", ""]
    lines.append(f"  build context roots: {', '.join(document['buildContextRoots'])}")
    lines.append(f"  declared install routes: {document['declaredRouteCount']}")
    summary = document["summary"]
    lines.extend([
        "",
        f"  examined {summary['examined']} path(s): "
        f"{summary['installed']} installed, {summary['contextOnly']} context-only, "
        f"{summary['unreachable']} unreachable",
        "",
        f"  BUILD-AFFECTING: {'YES' if summary['buildAffecting'] else 'no installed path found'}",
    ])
    if summary["affectedProfiles"]:
        lines.append(f"  profiles affected: {', '.join(summary['affectedProfiles'])}")
    if document["installed"]:
        lines.extend(["", "  Installed into the artifact:"])
        for item in document["installed"]:
            lines.append(f"    {item['path']}")
            for route in item["routes"]:
                lines.append(f"      -> {route['installedAs']}  [{route['routeId']}, {route['kind']}]")
    if document["contextOnly"]:
        lines.extend(["", "  In the build context, not installed by a declared route:"])
        lines.extend(f"    {item['path']}" for item in document["contextOnly"])
    if document["unreachable"]:
        lines.extend(["", "  Unreachable from the build:"])
        lines.extend(f"    {item['path']}" for item in document["unreachable"][:40])
        if len(document["unreachable"]) > 40:
            lines.append(f"    ... and {len(document['unreachable']) - 40} more")
    lines.extend(["", "  " + document["interpretation"]["caveat"]])
    return "\n".join(lines)


def route_map() -> dict[str, Any]:
    roots, copy_unresolved = build_context_roots(ROOT / "build/Containerfile")
    return {
        "schemaVersion": 2,
        "buildContextRoots": roots,
        "unresolvedCopyDirectives": copy_unresolved,
        "installRoutes": [route.to_json() for route in INSTALL_ROUTES],
        "generatedRoutes": [dict(item) for item in GENERATED_ROUTES],
        "modelledHelpers": dict(sorted(MODELLED_HELPERS.items())),
        "installerAuditComplaints": installer_audit(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--range", help="a git revision range, e.g. 0cf81a1..b825dd4")
    group.add_argument("--paths", nargs="+", help="repository-relative paths to classify")
    group.add_argument("--map", action="store_true", help="print the whole install route table")
    group.add_argument(
        "--audit", action="store_true",
        help="check that install-root.py installs nothing the route table does not model",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--output", type=Path, help="write JSON to this path as well")
    args = parser.parse_args()

    def emit(document: dict[str, Any], text: str) -> None:
        print(json.dumps(document, indent=2, sort_keys=True) if args.json else text)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            )

    try:
        if args.audit:
            complaints = installer_audit()
            document = {
                "schemaVersion": 2,
                "installerAuditComplaints": complaints,
                "modelled": bool(not complaints),
                "modelledHelpers": dict(sorted(MODELLED_HELPERS.items())),
            }
            text = (
                "install-root.py installs only what build/scripts/install_routes.py models"
                if not complaints
                else "BLOCKED: install-root.py installs something the route table does not "
                     "model:\n  " + "\n  ".join(complaints)
            )
            emit(document, text)
            return 0 if not complaints else 2

        if args.map:
            document = route_map()
            lines = ["Build context roots:"]
            lines.extend(f"  {item}" for item in document["buildContextRoots"])
            lines.append("\nInstall routes (repository path -> installed path):")
            for route in document["installRoutes"]:
                lines.append(
                    f"  {route['source']:52} -> {route['destination']}  "
                    f"[{route['kind']}, {route['mode']}]"
                )
            lines.append("\nGenerated routes (not copies of a repository file):")
            for item in document["generatedRoutes"]:
                lines.append(f"  {item['destination']}")
                lines.append(f"    from: {item['derivedFrom']}")
            if document["installerAuditComplaints"]:
                lines.append("\nBLOCKED: the installer does something this table does not model:")
                lines.extend(f"  {item}" for item in document["installerAuditComplaints"])
            emit(document, "\n".join(lines))
            return 2 if document["installerAuditComplaints"] else 0

        paths = changed_paths(args.range) if args.range else list(args.paths)
        document = build_closure(paths)
        if args.range:
            document["revisionRange"] = args.range
        emit(document, render(document))
        # Exit 1 when the change is build-affecting, so a gate can branch on it.
        return 1 if document["summary"]["buildAffecting"] else 0
    except ClosureError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
