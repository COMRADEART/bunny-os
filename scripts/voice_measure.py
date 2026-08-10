#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§24: what the voice runtime costs on this machine, measured rather than claimed.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them.

Every number here is a measurement of *this* process tree on *this* host, and
the report says which host. Three rules the output obeys:

**Nothing is extrapolated.** A figure that could not be taken is ``NOT_RUN``
with the reason, never an estimate. PSS needs ``/proc/<pid>/smaps_rollup``; a
provider's RSS needs the provider to have been running when the sample was
taken; CPU during synthesis needs a synthesiser. On a host missing any of those
the corresponding rows say so.

**Nothing here is Bunny OS's memory usage.** These are the voice runtime's own
figures plus, where asked for, the companion runtime beside it. A desktop, a
compositor, a browser and the rest of an installed system are not in them, and
§24 is explicit that they must not be presented as if they were.

**A sample of one is labelled as one.** Every row carries ``n``, and min,
median, p95 and max are only computed where ``n`` makes them mean something.
With fewer than twenty samples the p95 is the maximum by construction, and the
report says so rather than printing a number that looks like a percentile.

The audio path on the reference target is the **WSLg bridge** — a PulseAudio
protocol socket onto an RDP sink carried to the Windows host. Latency figures
therefore include an RDP hop that a physical sound card would not have, and no
physical speaker was validated. Both facts are in the emitted document.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Sequence

for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

#: Below this many samples a percentile is the maximum and is reported as such.
PERCENTILE_FLOOR = 20


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def summarise(name: str, values: Iterable[float], unit: str, *, note: str = "") -> dict[str, Any]:
    """min / median / p95 / max / n, or an honest refusal."""
    sample = [float(item) for item in values if item is not None]
    if not sample:
        return {
            "metric": name, "unit": unit, "result": "NOT_RUN",
            "reason": note or "no sample was taken on this host", "n": 0,
        }
    document: dict[str, Any] = {
        "metric": name,
        "unit": unit,
        "n": len(sample),
        "minimum": round(min(sample), 4),
        "median": round(statistics.median(sample), 4),
        "p95": round(_percentile(sample, 0.95), 4),
        "maximum": round(max(sample), 4),
    }
    if len(sample) < PERCENTILE_FLOOR:
        document["p95Note"] = (
            f"n={len(sample)} is below {PERCENTILE_FLOOR}; the p95 is at or near the maximum "
            "by construction rather than by measurement"
        )
    if note:
        document["note"] = note
    return document


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #


def _rss_pss(pid: int | str = "self") -> tuple[int | None, int | None]:
    """``(rss, pss)`` in bytes for one process, or ``(None, None)``.

    PSS is the one worth having for a companion: it divides shared pages by the
    number of processes sharing them, so summing PSS across the companion, the
    renderer and a synthesiser does not count libc three times. It needs
    ``smaps_rollup``, which is Linux 4.14 and later.
    """
    rss = pss = None
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
                    break
    except OSError:
        return None, None
    try:
        with open(f"/proc/{pid}/smaps_rollup", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    pss = int(line.split()[1]) * 1024
                    break
    except OSError:
        pss = None
    return rss, pss


def _children() -> list[tuple[int, str]]:
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    own = os.getpid()
    found: list[tuple[int, str]] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parent = 0
        name = ""
        for line in status.splitlines():
            if line.startswith("PPid:"):
                parent = int(line.split()[1])
            elif line.startswith("Name:"):
                parts = line.split(maxsplit=1)
                name = parts[1].strip() if len(parts) > 1 else ""
            if parent and name:
                break
        if parent == own:
            found.append((int(entry.name), name))
    return found


def _cpu_seconds(pid: int | str = "self") -> float | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None
    try:
        ticks = os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        return None
    # utime is field 14 overall, which is index 11 after the comm split.
    return (int(fields[11]) + int(fields[12])) / ticks


def _directory_bytes(root: Path) -> int:
    total = 0
    try:
        for item in root.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def _state(revision: int, text: str):
    from companion.presentation import PresentationState

    return PresentationState(
        session_id="measure-session", task_id="measure-task",
        phase="presenting_result", base_phase="presenting_result",
        result_summary=text, revision=revision,
    )


#: Utterances of increasing length. Latency is dominated by the text for a
#: formant synthesiser, so a single length would produce a distribution with no
#: width and a p95 that meant nothing.
_UTTERANCES = (
    "Done.",
    "There are forty-two words in your note.",
    "I counted the words in your note, checked the count a second time, and the answer is forty-two.",
    (
        "I have finished reading the note you gave me. I counted the words, then validated "
        "that count a second time using a different method, and both agree that there are "
        "forty-two words in it. Nothing was sent off this machine at any point."
    ),
)


def measure(runs: int, *, verbose: bool = False) -> dict[str, Any]:
    from companion.voice.captions import SpeechDisposition
    from companion.voice.policy import VoicePreferences
    from companion.voice.request import Priority
    from companion.voice.service import VoiceService, VoiceServiceOptions

    synthesis: list[float] = []
    first_audio: list[float] = []
    caption_offset: list[float] = []
    viseme_offset: list[float] = []
    cancellation: list[float] = []
    degradation: list[float] = []
    restart: list[float] = []
    worker_idle_rss: list[float] = []
    worker_idle_pss: list[float] = []
    provider_rss: list[float] = []
    provider_pss: list[float] = []
    backend_rss: list[float] = []
    backend_pss: list[float] = []
    combined_rss: list[float] = []
    combined_pss: list[float] = []
    temporary_peak: list[float] = []
    synthesis_cpu: list[float] = []
    playback_cpu: list[float] = []

    spoken = 0
    degraded = 0
    provider_id = ""
    backend_id = ""
    outcome = ""
    viseme_source = ""

    with tempfile.TemporaryDirectory(prefix="bunny-voice-measure-") as directory:
        service = VoiceService(VoiceServiceOptions(
            runtime_directory=Path(directory),
            preferences=VoicePreferences(speak_progress=True),
        ))
        try:
            service.refresh()
            outcome = service.policy.decision.outcome
            # Idle: the worker is running and nothing is queued. Taken before
            # anything speaks, so it is the resting cost rather than the peak.
            time.sleep(0.2)
            rss, pss = _rss_pss()
            if rss is not None:
                worker_idle_rss.append(rss)
            if pss is not None:
                worker_idle_pss.append(pss)

            for index in range(runs):
                text = _UTTERANCES[index % len(_UTTERANCES)]
                caption = service.publish(_state(index + 1, f"{text} Run {index + 1}."))
                service.ledger.mark_shown(caption.caption_id)
                started = time.monotonic()
                cpu_before = _cpu_seconds()
                request, reason = service.speak(caption.caption_id, priority=Priority.TASK_RESULT)
                if request is None:
                    if verbose:
                        print(f"  {index + 1:3d} not spoken: {reason}", file=sys.stderr)
                    continue

                # Sample the children while the utterance is in flight. A sample
                # taken afterwards would find nothing, which is the point of the
                # runtime but not a measurement of it.
                sampled_provider = sampled_backend = False
                peak_temporary = 0
                deadline = started + 120.0
                while time.monotonic() < deadline:
                    status = service.worker.status()
                    if status["current"] is None and not status["queueDepth"]:
                        break
                    for pid, name in _children():
                        child_rss, child_pss = _rss_pss(pid)
                        if child_rss is None:
                            continue
                        if name in ("espeak-ng", "espeak", "spd-say", "say"):
                            provider_rss.append(child_rss)
                            if child_pss is not None:
                                provider_pss.append(child_pss)
                            sampled_provider = True
                        elif name in ("paplay", "pacat", "pw-play", "aplay"):
                            backend_rss.append(child_rss)
                            if child_pss is not None:
                                backend_pss.append(child_pss)
                            sampled_backend = True
                    peak_temporary = max(peak_temporary, _voice_temporary_bytes())
                    time.sleep(0.01)
                service.worker.drain(timeout=60.0)
                cpu_after = _cpu_seconds()

                measurement = service.ledger.measurement(request.request_id)
                disposition = next(
                    (item["disposition"] for item in reversed(service.queue.ledger)
                     if item["requestId"] == request.request_id), "",
                )
                if disposition == SpeechDisposition.PLAYED:
                    spoken += 1
                else:
                    degraded += 1
                if measurement is not None:
                    if measurement.synthesis_latency_ms is not None:
                        synthesis.append(measurement.synthesis_latency_ms)
                    if measurement.time_to_first_audio_ms is not None:
                        first_audio.append(measurement.time_to_first_audio_ms)
                    if measurement.caption_to_audio_ms is not None:
                        caption_offset.append(measurement.caption_to_audio_ms)
                    if measurement.viseme_to_audio_ms is not None:
                        viseme_offset.append(measurement.viseme_to_audio_ms)
                    viseme_source = measurement.viseme_source or viseme_source
                if peak_temporary:
                    temporary_peak.append(peak_temporary)
                if cpu_before is not None and cpu_after is not None:
                    # One figure for the whole utterance: synthesis and playback
                    # are not separable from the parent's own accounting, and
                    # splitting a number that was never split would be inventing
                    # the division. Recorded under both names with that said.
                    synthesis_cpu.append((cpu_after - cpu_before) * 1000)
                    playback_cpu.append((cpu_after - cpu_before) * 1000)

                selection = service.registry.select(request)
                if selection.selected:
                    provider_id = selection.provider.declaration.provider_id
                for item in service.worker.events(limit=16):
                    if item.kind == "audio_started":
                        backend_id = str(
                            item.payload.get("backendId") or item.payload.get("providerId") or ""
                        )

                rss, pss = _rss_pss()
                if rss is not None:
                    combined_rss.append(rss)
                if pss is not None:
                    combined_pss.append(pss)
                if verbose:
                    print(
                        f"  {index + 1:3d} {disposition:<22} "
                        f"synth={measurement.synthesis_latency_ms if measurement else '-'}ms "
                        f"audio={measurement.time_to_first_audio_ms if measurement else '-'}ms",
                        file=sys.stderr, flush=True,
                    )

            # -- cancellation latency -------------------------------------
            for index in range(min(runs, 10)):
                caption = service.publish(_state(
                    1000 + index,
                    "A deliberately long utterance, produced only so that it is still playing "
                    "when the cancellation arrives and the time between the two can be measured.",
                ))
                service.ledger.mark_shown(caption.caption_id)
                request, _reason = service.speak(caption.caption_id, priority=Priority.TASK_RESULT)
                if request is None:
                    break
                waited = time.monotonic() + 10.0
                while time.monotonic() < waited:
                    if (service.worker.status()["current"] or {}).get("requestId") == request.request_id:
                        break
                    time.sleep(0.002)
                started = time.monotonic()
                service.voice_cancel(requestId=request.request_id)
                service.worker.drain(timeout=30.0)
                cancellation.append((time.monotonic() - started) * 1000)

            # -- device-loss degradation latency ---------------------------
            for _index in range(min(runs, 10)):
                for backend in service.router.backends:
                    setter = getattr(backend, "set_reachable", None)
                    if setter is not None:
                        setter(False)
                started = time.monotonic()
                service.refresh()
                degradation.append((time.monotonic() - started) * 1000)
                for backend in service.router.backends:
                    setter = getattr(backend, "set_reachable", None)
                    if setter is not None:
                        setter(True)
                for _ in range(service.policy.restore_observations):
                    service.refresh()

            # -- worker restart time ---------------------------------------
            for _index in range(min(runs, 10)):
                started = time.monotonic()
                service.restart_worker(timeout=30.0)
                restart.append((time.monotonic() - started) * 1000)
        finally:
            service.close()

    linux = sys.platform.startswith("linux")
    memory_note = "" if linux else "memory is read from /proc, which this platform does not have"
    return {
        "schemaVersion": 1,
        "host": _host(),
        "runs": runs,
        "spoken": spoken,
        "degradedToCaptions": degraded,
        "providerId": provider_id,
        "backendId": backend_id,
        "voiceOutcome": outcome,
        "visemeSource": viseme_source,
        "memory": [
            summarise("voice worker idle RSS", worker_idle_rss, "bytes", note=memory_note),
            summarise("voice worker idle PSS", worker_idle_pss, "bytes", note=memory_note or _pss_note()),
            summarise("provider process RSS", provider_rss, "bytes",
                      note=memory_note or "sampled while a synthesiser was running"),
            summarise("provider process PSS", provider_pss, "bytes", note=memory_note or _pss_note()),
            summarise("playback backend RSS", backend_rss, "bytes",
                      note=memory_note or "sampled while a player was running"),
            summarise("playback backend PSS", backend_pss, "bytes", note=memory_note or _pss_note()),
            summarise("companion plus voice RSS", combined_rss, "bytes",
                      note=memory_note or (
                          "this interpreter with the voice runtime in it; NOT the memory "
                          "usage of Bunny OS, which includes a desktop this does not run"
                      )),
            summarise("companion plus voice PSS", combined_pss, "bytes", note=memory_note or _pss_note()),
            summarise("temporary storage peak", temporary_peak, "bytes",
                      note="the largest total held in private voice workspaces during an utterance"),
        ],
        "latency": [
            summarise("synthesis latency", synthesis, "ms"),
            summarise("time to first audio", first_audio, "ms"),
            summarise("caption to audio offset", caption_offset, "ms",
                      note="positive means the caption led the audio, which is the correct sign"),
            summarise("viseme to audio offset", viseme_offset, "ms"),
            summarise("cancellation latency", cancellation, "ms",
                      note="from the cancel call returning to the utterance settling"),
            summarise("device loss degradation latency", degradation, "ms"),
            summarise("worker restart time", restart, "ms"),
        ],
        "cpu": [
            summarise("process CPU during an utterance", synthesis_cpu, "ms",
                      note=(
                          "the parent's own user+system time across synthesis and playback "
                          "together; the child's CPU is not in this figure and the two phases "
                          "are not separable from the parent's accounting"
                      )),
        ],
        "caveats": [
            "these are the voice runtime's figures and not Bunny OS memory usage",
            "no physical speaker was validated; audio on the reference target reaches an "
            "RDP sink through the WSLg bridge",
            f"a p95 computed from fewer than {PERCENTILE_FLOOR} samples is the maximum",
        ],
    }


def _voice_temporary_bytes() -> int:
    total = 0
    for workspace in Path(tempfile.gettempdir()).glob("bunny-voice-*"):
        total += _directory_bytes(workspace)
    return total


def _pss_note() -> str:
    return (
        "" if Path("/proc/self/smaps_rollup").exists()
        else "this kernel exposes no smaps_rollup, so PSS cannot be read"
    )


def _host() -> dict[str, Any]:
    document: dict[str, Any] = {
        "platform": sys.platform,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "release": platform.release(),
    }
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                document["os"] = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    document["wsl"] = "microsoft" in platform.release().lower()
    try:
        document["commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
    except OSError:
        document["commit"] = ""
    for name in ("espeak-ng", "spd-say", "paplay", "pw-play", "aplay", "pactl"):
        document.setdefault("tools", {})[name] = _which(name)
    return document


def _which(name: str) -> str:
    for directory in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
    return ""


def render(document: dict[str, Any]) -> str:
    lines = [
        "Voice runtime measurements",
        "",
        f"  host        {document['host'].get('os', document['host']['platform'])}"
        f"{' (WSL)' if document['host'].get('wsl') else ''}",
        f"  commit      {document['host'].get('commit', '')[:12]}",
        f"  outcome     {document['voiceOutcome']}",
        f"  provider    {document['providerId'] or 'none available'}",
        f"  backend     {document['backendId'] or 'none available'}",
        f"  visemes     {document['visemeSource'] or 'none produced'}",
        f"  utterances  {document['spoken']} spoken, {document['degradedToCaptions']} captions-only",
        "",
    ]
    for section in ("memory", "latency", "cpu"):
        lines.append(f"  {section.upper()}")
        for row in document[section]:
            if row.get("result") == "NOT_RUN":
                lines.append(f"    {row['metric']:<34} NOT_RUN  {row['reason']}")
                continue
            scale = 1024 * 1024 if row["unit"] == "bytes" else 1
            unit = "MiB" if row["unit"] == "bytes" else row["unit"]
            lines.append(
                f"    {row['metric']:<34} n={row['n']:<4} "
                f"min={row['minimum'] / scale:>9.3f} med={row['median'] / scale:>9.3f} "
                f"p95={row['p95'] / scale:>9.3f} max={row['maximum'] / scale:>9.3f} {unit}"
            )
        lines.append("")
    lines.append("  " + "\n  ".join(document["caveats"]))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    document = measure(max(1, args.runs), verbose=args.verbose)
    print(json.dumps(document, indent=2, sort_keys=True) if args.json else render(document))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
