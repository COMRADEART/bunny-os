#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which repository files can reach the constructed artifact, and by what route.

"Is this change build-affecting?" is a question that has been answered by
inspection in this repository, and inspection has now been wrong at least once:
the capability applicator commit was recorded as having no build impact because
``capability/`` is not installed, while three files it changed under ``schemas/``
and three under ``docs/`` are copied into the image wholesale by
``install-root.py``. Reading one script and stopping is how that happens.

So this computes the closure mechanically, from the two files that actually
decide it:

``build/Containerfile``
    Its ``COPY`` directives define the **build context** — the only repository
    paths the build can see at all. A path absent from every COPY cannot reach
    the artifact by any route, and that is the strongest statement available.

``build/scripts/install-root.py``
    Its ``copy_tree`` and ``copy_file`` calls define the **install set** — the
    paths that end up in the committed layer. Parsed from the AST rather than by
    regular expression, so a call this script cannot understand is reported as
    an unresolved route rather than silently dropped.

The distinction between the two is the whole point. A file in the build context
but not the install set is *probably* not in the artifact — the Containerfile
deletes ``/tmp/bunny-os`` before committing — but "probably" is not the standard
the reproducibility process holds, so those paths are reported separately as
requiring an empirical check rather than being folded into either answer.

Three classifications come out:

``installed``
    Reaches the committed layer at a stated destination. **Build-affecting.**
``context-only``
    Visible to the build, not installed by any route this script can see.
    Requires an empirical two-build comparison to call it non-affecting.
    Visible to the build, not installed by any declared route. The Containerfile
    deletes ``/tmp/bunny-os`` before committing, so these are *probably* absent
    from the artifact — but "probably" is not the standard, and an empirical
    two-build comparison is required to say so.
``unreachable``
    Absent from every COPY directive. Cannot affect the artifact.

Usage::

    build-input-closure.py --map
    build-input-closure.py --range 96ca61f..ff751ab
    build-input-closure.py --paths schemas/execution-plan.schema.json
    build-input-closure.py --range 0cf81a1..b825dd4
    build-input-closure.py --paths companion/voice/worker.py
    build-input-closure.py --audit
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]

#: Directory names ``copy_tree`` skips. Kept in step with install-root.py; a
#: mismatch here would report a file as installed that never is.
_COPY_TREE_EXCLUDES = {"__pycache__", "node_modules", "target"}

#: Paths the Containerfile writes into the image outside install-root.py, and
#: the repository input each is derived from. These are the routes that a reader
#: of install-root.py alone would miss, which is exactly the failure this script
#: exists to prevent.
_INDIRECT_ROUTES = (
    {
        "destination": "OCI config label org.opencontainers.image.revision",
        "derivedFrom": "the git commit being built (BUNNY_SOURCE_COMMIT)",
        "note": (
            "every commit changes the OCI configuration digest, whatever its content. "
            "The repository's comparison process accounts for this; it is recorded here "
            "so that an unchanged layer digest is never mistaken for an unchanged image."
        ),
    },
    {
        "destination": "/usr/lib/bunny-os/release.json",
        "derivedFrom": "the git commit being built (sourceCommit field)",
        "note": "written by install-root.py from --source-commit; changes on every commit",
    },
    {
        "destination": "/usr/lib/bunny-os/packages.txt",
        "derivedFrom": "rpm -qa inside the container",
        "note": "derived from the package snapshot, not from repository sources",
    },
)

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
        sources = parts[:-1]
        for item in sources:
        for item in parts[:-1]:
            if item in (".", "./") or item.startswith(".."):
                unresolved.append(line.strip())
                continue
            roots.append(item.rstrip("/"))
    return sorted(set(roots)), unresolved


# --------------------------------------------------------------------------- #
# Install set, from install-root.py
# --------------------------------------------------------------------------- #


def _source_relative(node: ast.AST) -> str | None:
    """Resolve ``source / "a/b"`` into ``"a/b"``. Returns None if it is not that."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = node.left, node.right
        if isinstance(left, ast.Name) and left.id == "source" and isinstance(right, ast.Constant):
            if isinstance(right.value, str):
                return right.value
        # source / "a" / "b"
        inner = _source_relative(left)
        if inner is not None and isinstance(right, ast.Constant) and isinstance(right.value, str):
            return f"{inner}/{right.value}"
    return None


def _path_literal(node: ast.AST) -> str | None:
    """Resolve ``Path("/usr/...")`` into ``"/usr/..."``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path":
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    if isinstance(node, ast.JoinedStr):
        # f"/usr/libexec/{name}" — a loop over a name list. Reported as a route
        # with a wildcard destination rather than dropped.
        pieces = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
            else:
                pieces.append("*")
        return "".join(pieces)
    return None


def declared_routes(tree: ast.Module) -> list[dict[str, Any]]:
    """Routes the installer declares in ``INSTALL_ROUTES``.

    A destination computed inside a loop cannot be resolved from the AST, and an
    analyser that reported such a path as "not installed" would be worse than no
    analyser — it would license exactly the mistake this tool exists to catch.
    So the installer declares those routes in a table it is itself driven by,
    and this reads the table. A declaration the installer obeys cannot drift
    from what the installer does.
    """
    routes: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [item.id for item in node.targets if isinstance(item, ast.Name)]
        if "INSTALL_ROUTES" not in targets:
            continue
        try:
            table = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
        for entry in table:
            if not isinstance(entry, dict) or "sourceGlob" not in entry:
                continue
            routes.append({
                "kind": "glob",
                "sourcePath": entry["sourceGlob"],
                "strip": entry.get("strip", ""),
                "destination": entry["destination"],
                "exclude": tuple(entry.get("exclude", ())),
                "excludeStems": tuple(entry.get("excludeStems", ())),
                "line": node.lineno,
            })
    return routes


def install_routes(installer: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every ``copy_tree``/``copy_file``/declared route, and what resisted parsing."""
    tree = ast.parse(installer.read_text(encoding="utf-8"), filename=str(installer))
    routes: list[dict[str, Any]] = list(declared_routes(tree))
    unresolved: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in ("copy_tree", "copy_file"):
            continue
        if len(node.args) < 2:
            unresolved.append(f"line {node.lineno}: {node.func.id} with too few arguments")
            continue
        relative = _source_relative(node.args[0])
        destination = _path_literal(node.args[1])
        if relative is None or destination is None:
            unresolved.append(
                f"line {node.lineno}: {node.func.id}("
                f"{ast.unparse(node.args[0])}, {ast.unparse(node.args[1])})"
            )
            continue
        routes.append({
            "kind": "tree" if node.func.id == "copy_tree" else "file",
            "sourcePath": relative,
            "destination": destination,
            "line": node.lineno,
        })

    # A route whose source is a variable (the script's own script_names loop)
    # is genuinely unresolvable from the AST alone. Those appear in `unresolved`
    # and the caller is told the closure is incomplete.
    return sorted(routes, key=lambda item: (item["sourcePath"], item["line"])), unresolved


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(
    path: str, roots: Iterable[str], routes: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Where one repository-relative path can reach, and how."""
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
        source = route["sourcePath"]
        if route["kind"] == "glob":
            # A declared route. fnmatch with ** semantics: PurePath.match does
            # not handle ** the way glob does, so the comparison is done on the
            # literal prefix and the suffix separately.
            prefix, _, suffix = source.partition("**/")
            if suffix:
                if not normalised.startswith(prefix):
                    continue
                if not PurePosixPath(normalised).match(suffix):
                    continue
            elif not PurePosixPath(normalised).match(source):
                continue
            strip = route.get("strip", "")
            remainder = normalised[len(strip):].lstrip("/") if strip else normalised
            parts = PurePosixPath(remainder).parts
            if set(route.get("exclude", ())).intersection(parts):
                continue
            if PurePosixPath(normalised).stem in route.get("excludeStems", ()):
                continue
            matched.append({
                **route,
                "installedAs": f"{route['destination'].rstrip('/')}/{remainder}",
            })
            continue
        if route["kind"] == "file":
            if normalised == source:
                matched.append({**route, "installedAs": route["destination"]})
            continue
        if normalised == source or normalised.startswith(source + "/"):
            remainder = normalised[len(source):].lstrip("/")
            if any(part in _COPY_TREE_EXCLUDES for part in remainder.split("/")):
                continue
            matched.append({
                **route,
                "installedAs": f"{route['destination'].rstrip('/')}/{remainder}" if remainder else route["destination"],
            })
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

    if matched:
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

    roots, copy_unresolved = build_context_roots(containerfile)
    routes, route_unresolved = install_routes(installer)
    classified = [classify(item, roots, routes) for item in paths]

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
        "schemaVersion": 1,
        "buildContextRoots": roots,
        "unresolvedCopyDirectives": copy_unresolved,
        "unresolvedInstallCalls": route_unresolved,
        "indirectRoutes": list(_INDIRECT_ROUTES),
        "closureComplete": not copy_unresolved,
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
                "visible to the build but installed by no route this script can see. "
                "The Containerfile deletes /tmp/bunny-os before committing, so these are "
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
    if document["unresolvedCopyDirectives"]:
        lines.append("  UNRESOLVED COPY directives (the closure is incomplete):")
        lines.extend(f"    {item}" for item in document["unresolvedCopyDirectives"])
    if document["unresolvedInstallCalls"]:
        lines.append(f"  install calls this script could not resolve: {len(document['unresolvedInstallCalls'])}")
        lines.extend(f"    {item}" for item in document["unresolvedInstallCalls"][:8])
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
    if document["installed"]:
        lines.extend(["", "  Installed into the artifact:"])
        for item in document["installed"]:
            for route in item["routes"]:
                lines.append(f"    {item['path']}")
                lines.append(f"      -> {route['installedAs']}  (install-root.py:{route['line']})")
    if document["contextOnly"]:
        lines.extend(["", "  In the build context, not installed by a visible route:"])
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
    lines.extend([
        "",
        "  " + document["interpretation"]["caveat"],
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--range", help="a git revision range, e.g. 96ca61f..ff751ab")
    group.add_argument("--paths", nargs="+", help="repository-relative paths to classify")
    group.add_argument("--map", action="store_true", help="print the whole install route table")
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

    try:
        if args.map:
            roots, copy_unresolved = build_context_roots(ROOT / "build/Containerfile")
            routes, route_unresolved = install_routes(ROOT / "build/scripts/install-root.py")
            document = {
                "schemaVersion": 1,
                "buildContextRoots": roots,
                "unresolvedCopyDirectives": copy_unresolved,
                "installRoutes": routes,
                "unresolvedInstallCalls": route_unresolved,
                "indirectRoutes": list(_INDIRECT_ROUTES),
            }
            if args.json:
                print(json.dumps(document, indent=2, sort_keys=True))
            else:
                print("Build context roots:")
                for item in roots:
                    print(f"  {item}")
                print("\nInstall routes (repository path -> installed path):")
                for route in routes:
                    print(f"  {route['sourcePath']:52} -> {route['destination']}  [{route['kind']}]")
                if route_unresolved:
                    print("\nCalls this script could not resolve:")
                    for item in route_unresolved:
                        print(f"  {item}")
                print("\nIndirect routes (not visible in install-root.py alone):")
                for item in _INDIRECT_ROUTES:
                    print(f"  {item['destination']}")
                    print(f"    from: {item['derivedFrom']}")
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return 0
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
        print(json.dumps(document, indent=2, sort_keys=True) if args.json else render(document))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        emit(document, render(document))
        # Exit 1 when the change is build-affecting, so a gate can branch on it.
        return 1 if document["summary"]["buildAffecting"] else 0
    except ClosureError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
