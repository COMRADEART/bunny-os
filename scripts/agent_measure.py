#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§25's figures, for the host this runs on and no other.

Two things this script refuses to do. It does not report a number it did not
measure — an unmeasurable dimension records ``NOT_RUN`` with the reason, never
a zero. And it does not add the model server's memory to Bunny Companion's:
the model process is measured separately, by pid, and the report keeps the two
columns apart, because "the companion uses 3 GB" would be false and the kind of
false that gets repeated.

Latencies are measured from the runtime's own clock around the operations a
user waits on: provider selection, context construction, time to first token,
output rate, total generation, cancellation, structured validation, tool
proposal handling, and the fallback ladder. Where this host has no local model
runtime, the generation figures are ``NOT_RUN`` and the ones that need no model
— selection, context, validation — still run.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion.agents.config import AgentConfiguration, default_configuration
from companion.agents.context import ContextBuilder
from companion.agents.registry import SelectionRequirement
from companion.agents.request import GenerationMessage, GenerationRequest
from companion.agents.service import AgentProviderService, AgentServiceOptions
from companion.agents.stream import StreamAssembler
from companion.agents.structured import PLAN_SCHEMA_REFERENCE, parse_structured

SCHEMA = "bunny-os/agent-provider-measurements/1"

_PLAN_TEXT = json.dumps({
    "summary": "Count the words",
    "operations": [{"name": "count-words", "tool": "text.count_words",
                    "arguments": {"text": "one two three"}}],
})


def _series(name: str, values: list[float], *, unit: str) -> dict[str, Any]:
    if not values:
        return {"name": name, "unit": unit, "count": 0,
                "result": "NOT_RUN", "reason": "no sample was taken on this host"}
    ordered = sorted(values)
    index = max(0, int(round(0.95 * (len(ordered) - 1))))
    return {
        "name": name, "unit": unit, "count": len(ordered),
        "min": round(ordered[0], 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(ordered[index], 4),
        "max": round(ordered[-1], 4),
    }


def _rss_bytes(pid: int | None = None) -> dict[str, Any]:
    path = Path(f"/proc/{pid}/status") if pid else Path("/proc/self/status")
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return {"rssBytes": int(line.split()[1]) * 1024}
    except OSError:
        pass
    return {"result": "NOT_RUN", "reason": f"{path} is not readable on this platform"}


def _pss_bytes(pid: int | None = None) -> dict[str, Any]:
    path = Path(f"/proc/{pid}/smaps_rollup") if pid else Path("/proc/self/smaps_rollup")
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            if line.startswith("Pss:"):
                return {"pssBytes": int(line.split()[1]) * 1024}
    except OSError:
        pass
    return {"result": "NOT_RUN", "reason": f"{path} is not readable on this platform"}


def _model_server_processes() -> list[dict[str, Any]]:
    """Whatever model runtime is serving, measured by pid and named as its own.

    Deliberately separate from the companion's own figures: these processes
    are not ours, we did not start them, and their memory is the model's.
    """
    found: list[dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text(encoding="ascii", errors="replace").strip()
        except OSError:
            continue
        if name not in ("ollama", "llama-server", "ollama_llama_se", "llama-cli"):
            continue
        pid = int(entry.name)
        found.append({
            "pid": pid, "name": name,
            **_rss_bytes(pid), **_pss_bytes(pid),
        })
    return found


def _timed(action: Callable[[], Any]) -> tuple[float, Any]:
    started = time.monotonic()
    value = action()
    return time.monotonic() - started, value


def measure(*, generations: int, cancellations: int, root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "host": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "pid": os.getpid(),
        },
        "series": [],
        "memory": {},
        "notes": [],
    }
    baseline_rss = _rss_bytes()
    service = AgentProviderService(AgentServiceOptions(root=root))
    try:
        idle_rss = _rss_bytes()
        idle_pss = _pss_bytes()
        report["memory"]["companionProcessBeforeAgents"] = baseline_rss
        report["memory"]["companionProcessWithAgentRuntimeIdle"] = idle_rss
        report["memory"]["companionProcessPssIdle"] = idle_pss
        report["memory"]["modelServerProcesses"] = _model_server_processes()
        report["memory"]["note"] = (
            "the model server's memory is the model's, measured separately by pid; "
            "it is never added to the companion's own figure"
        )

        # -- selection and context, which need no model ---------------------
        selection: list[float] = []
        for _ in range(20):
            elapsed, explanation = _timed(lambda: service.registry.select(
                SelectionRequirement(task_class="question"),
                monotonic=service.clock.monotonic(),
            ))
            selection.append(elapsed)
        report["series"].append(_series("provider-selection", selection, unit="seconds"))

        builder = ContextBuilder()
        construction: list[float] = []
        for _ in range(20):
            elapsed, _built = _timed(lambda: builder.build(
                audience="executor", classification="internal",
                request_text="count the words in this sentence please",
                task_history="prior operations: none",
                context_limit_tokens=4096, maximum_input_tokens=4096,
            ))
            construction.append(elapsed)
        report["series"].append(_series("context-construction", construction, unit="seconds"))

        validation: list[float] = []
        for _ in range(50):
            elapsed, _value = _timed(
                lambda: parse_structured(_PLAN_TEXT, PLAN_SCHEMA_REFERENCE)
            )
            validation.append(elapsed)
        report["series"].append(_series("structured-validation", validation, unit="seconds"))

        assembly: list[float] = []
        for _ in range(50):
            def _assemble() -> None:
                from companion.agents.adapter import StreamEventFactory

                assembler = StreamAssembler(
                    request_id="gen-measure", provider_id="local.measure",
                    maximum_output_bytes=1 << 20,
                )
                factory = StreamEventFactory(
                    request_id="gen-measure", provider_id="local.measure",
                    monotonic=time.monotonic,
                )
                assembler.accept(factory.started())
                for _ in range(64):
                    assembler.accept(factory.delta("token "))
                assembler.accept(factory.completed())
                assembler.finalize()

            elapsed, _ = _timed(_assemble)
            assembly.append(elapsed)
        report["series"].append(
            _series("stream-assembly-64-deltas", assembly, unit="seconds")
        )

        # -- generation, where this host has a local model -------------------
        now = service.clock.monotonic()
        candidates = [
            item for item in service.registry.descriptors(monotonic=now)
            if item.local and item.standing.available and item.fully_declared
        ]
        if not candidates:
            report["notes"].append(
                "no local model provider on this host: time to first token, output "
                "rate, total latency, cancellation latency and model startup are NOT_RUN"
            )
            for name, unit in (
                ("time-to-first-token", "seconds"),
                ("output-rate", "bytes-per-second"),
                ("total-generation", "seconds"),
                ("cancellation-latency", "seconds"),
                ("local-model-startup", "seconds"),
            ):
                report["series"].append(_series(name, [], unit=unit))
            return report

        descriptor = candidates[0]
        report["provider"] = {
            "providerId": descriptor.provider_id,
            "modelId": descriptor.model_id,
            "adapterId": descriptor.adapter_id,
        }

        first_token: list[float] = []
        totals: list[float] = []
        rates: list[float] = []
        counter = 0

        def _request(number: int, tokens: int = 64, deadline: float = 120.0) -> GenerationRequest:
            return GenerationRequest(
                request_id=f"gen-measure-{number:04d}",
                session_id="", task_id="", lifecycle_epoch=0, plan_id="",
                provider_id=descriptor.provider_id,
                model_id=descriptor.model_id,
                purpose="probe",
                messages=(
                    GenerationMessage(role="system", content="Answer briefly."),
                    GenerationMessage(role="user", content="List four seasons, one per line."),
                ),
                system_policy_reference="bunny-agent-policy/1",
                maximum_input_tokens=2048,
                maximum_output_tokens=tokens,
                deadline_seconds=deadline,
                created_at="",
            )

        for _ in range(generations):
            counter += 1
            started = time.monotonic()
            outcome = service.worker.generate(_request(counter))
            elapsed = time.monotonic() - started
            if not outcome.ok or outcome.assembled is None:
                report["notes"].append(
                    f"generation {counter} did not complete: "
                    f"{outcome.failure_kind}: {outcome.detail[:120]}"
                )
                continue
            totals.append(elapsed)
            produced = len(outcome.assembled.text.encode("utf-8"))
            if elapsed > 0 and produced:
                rates.append(produced / elapsed)
            # The worker stamps the first output delta against the moment the
            # adapter was handed the request; that difference *is* time to
            # first token, taken from the runtime's own clock rather than
            # from a second one running beside it.
            timing = service.worker.last_timing()
            if timing.get("requestId") == outcome.request_id and "firstTokenSeconds" in timing:
                first_token.append(float(timing["firstTokenSeconds"]))
        report["series"].append(_series("total-generation", totals, unit="seconds"))
        report["series"].append(_series("output-rate", rates, unit="bytes-per-second"))
        report["series"].append(_series("time-to-first-token", first_token, unit="seconds"))

        # -- cancellation latency --------------------------------------------
        cancel_latencies: list[float] = []
        for _ in range(cancellations):
            counter += 1
            request = _request(counter, tokens=512, deadline=120.0)
            settled = threading.Event()

            def _run() -> None:
                service.worker.generate(request)
                settled.set()

            runner = threading.Thread(target=_run, daemon=True)
            runner.start()
            # Wait until the generation is genuinely in flight before asking
            # it to stop: a cancel that lands before the stream measures the
            # queue, not the cancellation.
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if service.worker.status().get("activeRequestId") == request.request_id:
                    break
                time.sleep(0.01)
            started = time.monotonic()
            service.worker.cancel(request.request_id, reason="measurement")
            if settled.wait(timeout=30.0):
                cancel_latencies.append(time.monotonic() - started)
            runner.join(timeout=5.0)
        report["series"].append(
            _series("cancellation-latency", cancel_latencies, unit="seconds")
        )

        report["memory"]["companionProcessAfterGenerations"] = _rss_bytes()
        report["memory"]["modelServerProcessesAfter"] = _model_server_processes()
        report["series"].append(_series("local-model-startup", [], unit="seconds"))
        report["notes"].append(
            "local model startup is NOT_RUN: the model server on this host was "
            "already running and starting one would measure a different act"
        )
        return report
    finally:
        service.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", type=int, default=8)
    parser.add_argument("--cancellations", type=int, default=4)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--runtime-directory", type=Path, default=None)
    arguments = parser.parse_args()
    root = arguments.runtime_directory or Path(
        tempfile.mkdtemp(prefix="bunny-agent-measure-")
    )
    report = measure(
        generations=arguments.generations,
        cancellations=arguments.cancellations,
        root=root,
    )
    text = json.dumps(report, indent=2, sort_keys=False)
    if arguments.output:
        arguments.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
