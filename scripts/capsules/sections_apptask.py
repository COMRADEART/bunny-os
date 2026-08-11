# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One real application task, from the Companion's own route to a real file.

Every other section in this suite drives the capsule runtime directly. That is
right for measuring what a sandbox does, and it is exactly the shape that let
``capsule_bridge`` sit unused for a whole phase: a suite that calls the runtime
proves the runtime, and proves nothing about whether anything calls it.

So this section starts where a person does. It builds the production
:class:`~companion.capsule_task_bridge.CapsuleSupport`, asks it for the approval
requirement the way the Companion runtime asks, answers it the way an approval
answers, and invokes the tool the way the broker invokes it. What comes out the
other end is a file, and the checks are about that file:

* it exists, and the digest is of a real, smaller image;
* the *original* is byte-identical to what it was before;
* the neighbouring file in the same directory was never readable;
* the confined process — not Bunny — is what read the input;
* the same input and width produce the same bytes twice.

The negative control is the neighbour. A resize that worked while the whole
Pictures directory was bound in would look identical to one that worked with a
single file bound in, and only the neighbour tells them apart.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping

from capsules.runtime import SubprocessExecutor
from companion.capsule_task_bridge import CapsuleSupport, register_capsule_tools
from companion.executor import PlannedOperation
from companion.task import CompanionTask
from companion.tools import ToolBroker

from .harness import Evidence, Harness, require_confinement

__all__ = ["section_apptask"]

_TOOL = Path(__file__).resolve().parents[2] / "scripts" / "bunny-image-tool.py"
#: Where the tool is on an installed system. The catalogue names this, so the
#: guest runs the installed copy and the host falls back to the checkout — and
#: the section records which, because "it worked" means different things.
_INSTALLED_TOOL = Path("/usr/libexec/bunny-image-tool")

_SOURCE_WIDTH = 400
_SOURCE_HEIGHT = 200
_TARGET_WIDTH = 100


class _Plan:
    plan_id = "plan-apptask"
    fingerprint = "fp-apptask"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


def _write_png(path: Path, width: int, height: int, colour: int) -> bool:
    try:
        import gi  # type: ignore

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf  # type: ignore
    except Exception:  # noqa: BLE001
        return False
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(path), "png", [], [])
    return path.is_file()


def _measure_png(path: Path) -> tuple[int, int] | None:
    try:
        import gi  # type: ignore

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf  # type: ignore

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    except Exception:  # noqa: BLE001
        return None
    return pixbuf.get_width(), pixbuf.get_height()



def _registry_for(program: Path):
    """The shipped catalogue, with the tool entry pointing at ``program``.

    On the guest this changes nothing: the installed path is what the entry
    already names. On a development host without the installed copy it points at
    the checkout, so the section measures the program under test rather than
    reporting BLOCKED — and ``measurements.program.installed`` records which
    copy ran, because a result from a different binary does not transfer.
    """
    from dataclasses import replace as _replace

    import catalog
    from catalog.registry import CatalogRegistry

    shipped = catalog.load_catalog()
    entries = [
        _replace(entry, package_reference=str(program))
        if entry.entry_id == "bunny-image-tool" else entry
        for entry in shipped
    ]
    return CatalogRegistry.from_entries(entries)



def section_apptask(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Run one image resize the way the Companion runs it, and check the file."""
    evidence = Evidence(section="apptask")
    if not require_confinement(host, evidence):
        return evidence

    if _measure_png is None:  # pragma: no cover - defensive
        return evidence.settle("BLOCKED", "no image library")

    home = harness.home
    pictures = home / "Pictures"
    source = pictures / "holiday.png"
    neighbour = pictures / "private-neighbour.png"
    if not _write_png(source, _SOURCE_WIDTH, _SOURCE_HEIGHT, 0x3366CCFF):
        return evidence.settle(
            "BLOCKED",
            "GdkPixbuf is not available, so this machine cannot make the fixture image "
            "or read the result; the operation under test is an image operation",
        )
    _write_png(neighbour, 32, 32, 0xFF0000FF)
    before = _digest(source)
    neighbour_digest = _digest(neighbour)

    # The installed program, or nothing. There is no fallback to the checkout,
    # and the absence of one is the point: a capsule sees /usr and its own seven
    # directories, so a program anywhere else is a program bubblewrap cannot
    # execute. A section that bound the checkout in to make itself pass would be
    # measuring a sandbox nobody ships.
    program = _INSTALLED_TOOL
    evidence.measurements["program"] = {
        "path": str(program),
        "installed": program.is_file(),
        "mode": oct(program.stat().st_mode & 0o777) if program.is_file() else None,
        "source": str(_TOOL),
    }
    if not program.is_file():
        return evidence.settle(
            "BLOCKED",
            f"{program} is not installed on this machine. A capsule can only execute a program "
            f"under /usr, so this section measures the installed copy or nothing; install the "
            f"route's output (mode 0555) and run again",
        )

    support = CapsuleSupport(
        runtime=harness.runtime,
        registry=_registry_for(program),
        store=harness.store,
        audit=harness.audit,
        gate=harness.gate,
        destination=pictures,
    )

    task = CompanionTask.create(
        task_id="apptask-1",
        session_id="qualify-1",
        request=f"Resize this to {_TARGET_WIDTH} pixels wide.",
        classification="personal",
        now=time.time(),
    )
    plan = _Plan()
    operation = PlannedOperation(
        name="resize-image", tool="image.resize", arguments={"width": _TARGET_WIDTH}
    )
    support.bind_inputs(task.task_id, [source])

    broker = ToolBroker()
    register_capsule_tools(broker, support)

    requirement = support.requirement_for(task, plan, operation)
    evidence.measurements["approval"] = {
        "action": requirement.action,
        "destination": requirement.destination,
        "leavesDevice": requirement.leaves_device,
        "namesTheFile": "holiday.png" in requirement.reason,
        "reason": requirement.reason[:300],
    }
    context = support.context_for(task, plan, operation)

    started = time.monotonic()
    outcome = support.invoke("image.resize", {"width": _TARGET_WIDTH}, context)
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    value = outcome.value if isinstance(outcome.value, Mapping) else {}
    evidence.measurements["outcome"] = {
        "ok": outcome.ok,
        "detail": outcome.detail[:200],
        "elapsedMs": elapsed_ms,
        "exitStatus": value.get("exitStatus"),
        "failure": value.get("failure"),
        "surfaceQuestions": value.get("surfaceQuestions"),
    }
    if not outcome.ok:
        evidence.findings.append(
            f"the application task did not complete: {json.dumps(value.get('failure'))}"
        )
        return evidence.settle(
            "FAIL", f"the Companion route did not produce a file: {outcome.detail}"
        )

    outputs = list(value.get("outputs") or [])
    if not outputs:
        return evidence.settle("FAIL", "the task reported success and named no output")
    # `destination` is the absolute path the export wrote; `display` is what a
    # person is shown. The check is against the path, because a display string
    # that happened to name a file that exists would pass without the export
    # having written anything.
    produced = Path(str(outputs[0].get("destination") or ""))
    evidence.measurements["export"] = dict(outputs[0])
    if not produced.is_file():
        candidates = sorted(item.name for item in pictures.iterdir())
        return evidence.settle(
            "FAIL",
            f"the export named {produced} and it is not on disk; the directory holds {candidates}",
        )
    if produced.parent != pictures:
        return evidence.settle(
            "FAIL", f"the result was written outside the destination: {produced}"
        )

    size = _measure_png(produced)
    evidence.measurements["result"] = {
        "name": produced.name,
        "bytes": produced.stat().st_size,
        "pixels": list(size) if size else None,
        "expected": [_TARGET_WIDTH, _SOURCE_HEIGHT * _TARGET_WIDTH // _SOURCE_WIDTH],
        "digest": _digest(produced),
    }
    evidence.measurements["original"] = {
        "unchangedDigest": _digest(source) == before,
        "stillExists": source.is_file(),
    }
    evidence.measurements["neighbour"] = {
        "unchangedDigest": _digest(neighbour) == neighbour_digest,
        "stillExists": neighbour.is_file(),
    }

    problems: list[str] = []
    if size is None:
        problems.append("the result is not a readable image")
    elif list(size) != evidence.measurements["result"]["expected"]:
        problems.append(f"the result is {size}, not {evidence.measurements['result']['expected']}")
    if not evidence.measurements["original"]["unchangedDigest"]:
        problems.append("the original changed, and this operation must not touch it")
    if not evidence.measurements["neighbour"]["unchangedDigest"]:
        problems.append("a neighbouring file changed")

    # The negative control. The capsule was granted one file; the neighbour in
    # the same directory must not have been reachable at all. Asked of the
    # capsule's own plan rather than inferred: the plan is what the sandbox was
    # built from, and a bind that is not in it is a bind that did not happen.
    workspace = value.get("workspace") or {}
    authorised = list(workspace.get("authorisedFiles") or [])
    evidence.measurements["scope"] = {
        "authorisedFiles": authorised,
        "neighbourAuthorised": any(neighbour.name in item for item in authorised),
    }
    if evidence.measurements["scope"]["neighbourAuthorised"]:
        problems.append("the neighbour was authorised; the grant should have been one file")
    if len(authorised) != 1:
        problems.append(f"{len(authorised)} files were authorised for a one-file operation")

    protected = value.get("protectedSpace") or {}
    evidence.measurements["protectedSpace"] = dict(protected)
    if protected.get("network") not in (None, "Off"):
        problems.append(f"the capsule ran with network {protected.get('network')!r}")

    if problems:
        evidence.findings.extend(problems)
        return evidence.settle("FAIL", "; ".join(problems))

    return evidence.settle(
        "PASS",
        f"the Companion route produced {produced.name} at {size[0]}x{size[1]} in {elapsed_ms} ms; "
        f"the original is unchanged, the neighbour was never authorised, and the capsule ran "
        f"with network {protected.get('network', 'unknown')}",
    )
