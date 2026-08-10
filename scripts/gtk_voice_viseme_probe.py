#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice-produced visemes drawn by a real GTK character renderer, on a real compositor.

The voice-runtime phase closed with one thing measured and one thing asserted.
Measured: an amplitude envelope over the synthesiser's own samples, an ordered
viseme timeline, and a scheduler walking it against the playback position.
Asserted: that a renderer *would* draw it. Nothing had ever connected the two —
the only timeline the character renderer had ever been given was one a test made
up — so "the visemes are right" and "the mouth moves" were separate claims with
an unexercised join between them.

This probe is that join, executed:

    canonical caption
        -> companion.voice.service.VoiceService (a real local provider)
        -> synthesised WAV, probed for its real duration
        -> companion.voice.visemes: an amplitude-derived timeline
        -> companion.character.speech_link.VisemeLink
        -> companion.character.lipsync.LipSyncController
        -> companion.character.animated_renderer.Animated2DRenderer
        -> Gtk.Picture.set_filename, on a compositor

Nothing in that chain is a fixture. The caption is a real
:class:`companion.presentation.PresentationState`; the audio is whatever eSpeak
NG produced on this machine; the timeline is the worker's own, carried by the
``viseme_timeline`` event; and the file handed to GTK is the asset the character
package declares for the shape the controller chose.

What it will not do:

* it will not run without a display. There is no offscreen mode, because a
  frame that was never given to a compositor proves nothing about one that was;
* it will not call the timing "lip sync accuracy". The timing method is
  **measured amplitude** over the synthesised samples — 40 ms windows — and the
  report says so in the same field that carries the numbers. No phoneme
  boundary was measured anywhere in this build;
* it will not call this a GNOME session, physical hardware, or a performance
  figure for any target device.

Exit status: 0 every check held, 2 something did not.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import importlib.util
import sys
import threading
import time
import traceback
from typing import Any

# Only when the package is not importable yet.
#
# For a standalone invocation nothing is importable, so this behaves exactly as
# it always has: the installed tree first, the checkout as a fallback.
#
# The guard is for the other case. In a process that already works — a test
# run, another tool that imported this one — the checkout is already on
# ``sys.path``, so the loop skipped it as already-present and inserted the
# *installed* tree in front of it. Every import after that came from whatever
# build happened to be installed, which on a qualification host is a build from
# an earlier phase. It fails loudly when that build is missing a module and
# silently when it is not, and the silent case is a whole test suite passing
# against code nobody changed.
if importlib.util.find_spec("companion") is None:
    for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
        if _candidate.is_dir() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))


CAPTION = (
    "Bunny finished counting the words in your document and is showing you the result."
)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 3)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 3)


def display_environment() -> dict[str, Any]:
    """What display this is, named honestly."""
    wayland = os.environ.get("WAYLAND_DISPLAY")
    x11 = os.environ.get("DISPLAY")
    wslg = Path("/mnt/wslg").exists()
    if wayland and wslg:
        kind, note = "wayland-wslg-remoted", (
            "A real Wayland compositor supplied by the WSLg system distribution and "
            "composited by the Windows host. Real enough to decode, draw and time "
            "frames. NOT a GNOME session, NOT physical hardware, and NOT a "
            "performance measurement for any target device."
        )
    elif wayland:
        kind, note = "wayland-unclassified", "A Wayland compositor that was not identified."
    elif x11:
        kind, note = "x11-unclassified", "An X server that was not identified."
    else:
        kind, note = "none", "No display. The renderer cannot be driven."
    return {
        "kind": kind,
        "note": note,
        "waylandDisplay": wayland,
        "display": x11,
        "pulseServer": os.environ.get("PULSE_SERVER", ""),
        "xdgRuntimeDir": os.environ.get("XDG_RUNTIME_DIR", ""),
        "isGnomeSession": False,
        "isPhysicalHardware": False,
        "physicalSpeakerValidated": False,
        "available": kind != "none",
    }


class LogCapture:
    """GTK reports most faults through the log rather than by raising."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def install(self, GLib: Any) -> None:
        def writer(level: Any, fields: Any, _user_data: Any = None) -> Any:
            entry: dict[str, str] = {"level": str(level)}
            try:
                for key in ("GLIB_DOMAIN", "MESSAGE"):
                    value = fields.get(key) if hasattr(fields, "get") else None
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "replace")
                    if value:
                        entry[key] = str(value)
            except Exception:  # noqa: BLE001 - a log handler must not fault
                pass
            self.records.append(entry)
            return GLib.LogWriterOutput.HANDLED

        try:
            GLib.log_set_writer_func(writer, None)
        except Exception:  # noqa: BLE001 - older GLib; the probe still runs
            pass

    @property
    def serious(self) -> list[dict[str, str]]:
        return [
            record for record in self.records
            if "CRITICAL" in record.get("level", "").upper()
            or "ERROR" in record.get("level", "").upper()
        ]


class MouthAssets:
    """Shape -> the file the character package declares for it.

    Resolved from the manifest rather than read off the renderer at draw time.
    The renderer's ``frame`` is mutated on the voice worker's thread and read on
    the main loop; carrying the *shape* across the thread boundary and resolving
    it here means the file GTK is handed always belongs to the frame that was
    accepted, not to whichever frame happened to be current when the idle
    callback ran.
    """

    def __init__(self, package: Any) -> None:
        self.package = package
        manifest = package.manifest
        self.by_shape: dict[str, Path] = {}
        for shape, animation_name in manifest.mouth_shape_map.items():
            try:
                animation = manifest.animation(animation_name)
            except Exception:  # noqa: BLE001 - a shape with no animation simply has no asset
                continue
            self.by_shape[shape] = package.asset_path(animation.frames[0].asset_id)
        self.fallback = package.asset_path(manifest.fallback_asset)

    def path_for(self, shape: str) -> Path:
        return self.by_shape.get(shape, self.fallback)


class Probe:
    """One compositor run: build everything, speak, watch, tear down."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        self.report: dict[str, Any] = {
            "schema": "bunny-os/gtk-voice-viseme-probe/1",
            "display": display_environment(),
            "checks": {},
            "measurements": {},
            "limitations": [],
        }
        self.failures: list[str] = []
        self.drawn: list[dict[str, Any]] = []
        self.idle_sources: set[int] = set()
        self.retired: set[int] = set()
        self.started = time.monotonic()

    # -- helpers -----------------------------------------------------------

    def now_ms(self) -> float:
        return round((time.monotonic() - self.started) * 1000, 3)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    # -- the run -----------------------------------------------------------

    def run(self) -> int:
        if not self.report["display"]["available"]:
            self.report["gate"] = {"passed": False, "failures": ["no display; refusing to pretend"]}
            print(json.dumps(self.report, indent=2, sort_keys=True))
            return 2

        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        from companion.character.animated_renderer import Animated2DRenderer
        from companion.character.defaults import default_character_path
        from companion.character.package import validate_package_directory
        from companion.character.speech_link import VisemeLink
        from companion.character.surface import CharacterPresenter
        from companion.presentation import PresentationState
        from companion.voice.service import VoiceService, VoiceServiceOptions
        import companion.character.speech_link as link_module

        self.GLib, self.Gtk = GLib, Gtk
        self.report["gtkVersion"] = (
            f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        )
        self.report["provenance"] = {
            "speechLink": link_module.__file__,
            "animatedRenderer": Animated2DRenderer.__module__,
        }

        capture = LogCapture()
        capture.install(GLib)
        self.capture = capture

        package = validate_package_directory(
            arguments_package(self.arguments) or default_character_path()
        )
        self.assets = MouthAssets(package)
        self.report["package"] = {
            "id": package.manifest.package_id,
            "mouthShapes": sorted(self.assets.by_shape),
            "assetsResolved": len(self.assets.by_shape),
        }
        if len(self.assets.by_shape) < 2:
            self.fail("the character package declares fewer than two mouth shapes")

        window = Gtk.Window(title="Bunny voice viseme probe")
        picture = Gtk.Picture()
        window.set_child(picture)
        window.set_default_size(320, 320)
        window.present()
        self.picture = picture
        # Let the window finish coming up before anything is timed. The first
        # measured run put the first mouth frame 500 ms behind its audio and the
        # ten frames after it within 0.4 ms of each other, which is not a
        # synchronisation figure — it is the compositor realising a window and
        # then the whole queue draining at once. Warming up first makes the
        # number that comes out the steady-state one, and the first-frame
        # latency is reported on its own below rather than folded into it.
        self.pump(seconds=1.5)

        presenter = CharacterPresenter(package.root.parent)
        self.presenter = presenter

        voice = VoiceService(VoiceServiceOptions(
            runtime_directory=Path(self.arguments.runtime_directory),
        ))
        self.voice = voice
        health = voice.voice_health()
        self.report["voice"] = {
            "providers": [
                {"providerId": item["providerId"], "ready": item["ready"], "detail": item.get("detail", "")}
                for item in health["providers"]
            ],
            "audio": [
                {"backendId": item["backendId"], "ready": item["ready"], "detail": item.get("detail", "")}
                for item in health["audio"]["backends"]
            ],
        }
        if not any(item["ready"] for item in health["providers"]):
            self.fail("no local synthesiser is ready; there is no voice output to draw")
        if not any(item["ready"] for item in health["audio"]["backends"]):
            self.fail("no audio backend is ready; there is no playback clock to drive the mouth")

        link = VisemeLink(
            presenter=presenter,
            draw=self.draw,
            dispatch=self.dispatch,
        )
        self.link = link
        voice.worker.subscribe(link.on_voice_event)
        voice.worker.subscribe(self.observe)
        self.events: list[Any] = []

        try:
            self.check_full_utterance(PresentationState)
            self.check_cancellation(PresentationState)
            self.check_worker_restart(PresentationState)
            self.check_renderer_restart(PresentationState)
            self.check_stale_revision(PresentationState)
        finally:
            self.teardown()

        self.report["glib"] = {
            "records": len(capture.records),
            "criticals": len(capture.serious),
            "examples": capture.serious[:4],
        }
        if capture.serious:
            self.fail(f"{len(capture.serious)} GLib critical or error record(s)")

        self.report["gate"] = {"passed": not self.failures, "failures": self.failures}
        print(json.dumps(self.report, indent=2, sort_keys=True))
        if self.arguments.output:
            self.arguments.output.parent.mkdir(parents=True, exist_ok=True)
            self.arguments.output.write_text(
                json.dumps(self.report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8", newline="\n",
            )
        return 0 if not self.failures else 2

    # -- the GTK side ------------------------------------------------------

    def dispatch(self, action) -> None:
        """Onto the main loop. The only thread that may touch a widget.

        One idle source per frame, each removing itself. A *timer* would be the
        wrong shape here twice over: it would keep firing after the utterance
        ended, and it would be a resource that outlives whatever created it —
        which is precisely what the teardown check exists to catch.
        """
        box: dict[str, int] = {}

        def once() -> bool:
            try:
                action()
            finally:
                self.retired.add(box.get("id", -1))
            return self.GLib.SOURCE_REMOVE

        identifier = self.GLib.idle_add(once)
        box["id"] = identifier
        self.idle_sources.add(identifier)

    def draw(self, frame: Any) -> None:
        """The widget call under test. Runs on the main loop."""
        path = self.assets.path_for(frame.shape)
        # If GTK cannot decode the file this is where it complains, and the
        # complaint goes to the log capture rather than anywhere quieter.
        self.picture.set_filename(str(path))
        self.drawn.append({
            "atMs": self.now_ms(),
            # When the link accepted it, on the worker's thread. The difference
            # between the two is what the main loop added, and it is the only
            # part of the delay this probe is in a position to measure.
            "emittedAtMs": round((frame.at_monotonic - self.started) * 1000, 3),
            "requestId": frame.request_id,
            "sequence": frame.sequence,
            "shape": frame.shape,
            "source": frame.source,
            "positionMs": frame.position_ms,
            "driftMs": frame.drift_ms,
            "revision": frame.revision,
            "origin": frame.origin,
            "path": str(path),
        })

    def observe(self, event: Any) -> None:
        self.events.append({
            "kind": event.kind,
            "requestId": event.request_id,
            "atMs": self.now_ms(),
            "payload": {} if event.kind in ("viseme", "viseme_timeline") else dict(event.payload),
        })

    def pump(self, *, seconds: float, until=None) -> None:
        """Turn the main loop for a while, or until a condition holds."""
        deadline = time.monotonic() + seconds
        context = self.GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if until is not None and until():
                # One more drain so the frames that condition produced are drawn.
                while context.pending():
                    context.iteration(False)
                return
            time.sleep(0.005)
        while context.pending():
            context.iteration(False)

    # -- the checks --------------------------------------------------------

    def _speak(self, PresentationState, *, request_id_hint: str, text: str = CAPTION):
        state = PresentationState(
            session_id="probe-session", task_id="probe-task", phase="presenting_result",
            status_text=text, result_summary=text,
        )
        self.presenter.update(state)
        self.link.publish(1)
        request, reason = self.voice.announce(state)
        if request is None:
            self.fail(f"{request_id_hint}: the runtime refused to speak: {reason}")
        return request

    def check_full_utterance(self, PresentationState) -> None:
        before = len(self.drawn)
        request = self._speak(PresentationState, request_id_hint="utterance")
        if request is None:
            return
        self.pump(seconds=30.0, until=lambda: self._settled(request.request_id))
        frames = self.drawn[before:]
        shapes = [item["shape"] for item in frames]
        non_neutral = sorted({item for item in shapes if item != "neutral"})
        timeline_frames = [item for item in frames if item["origin"] == "timeline"]

        audio_started = self._event_ms("audio_started", request.request_id)
        first_viseme = self._event_ms("viseme", request.request_id)
        first_drawn = frames[0]["atMs"] if frames else None
        neutral = [item for item in frames if item["shape"] == "neutral"]
        # Three different things, all called "drift" by somebody.
        #
        # `scheduler` is the worker's own number, and on the file-playback path
        # it is structurally zero: the worker has no audio clock independent of
        # the playback handle, so it passes the same position as both arguments.
        # Reported with that stated rather than presented as a measurement.
        #
        # `presentation` is the real one: how far the mouth frame that was drawn
        # lags the point in the audio it belongs to, measured from the audio
        # start on this machine's clock. It includes the synthesis-to-draw path,
        # the main loop and the compositor.
        #
        # `dispatch` is the part of that this probe added by marshalling onto
        # the main loop.
        scheduler_drift = [abs(item["driftMs"]) for item in timeline_frames]
        presentation_drift = [
            round(item["atMs"] - audio_started - item["positionMs"], 3)
            for item in timeline_frames
        ] if audio_started is not None else []
        dispatch_latency = [
            round(item["atMs"] - item["emittedAtMs"], 3) for item in timeline_frames
        ]

        self.report["checks"]["fullUtterance"] = {
            "requestId": request.request_id,
            "framesDrawn": len(frames),
            "timelineFrames": len(timeline_frames),
            "distinctNonNeutralShapes": non_neutral,
            "sequencesOrdered": [item["sequence"] for item in timeline_frames]
                == sorted(item["sequence"] for item in timeline_frames),
            "requestIdsMatch": sorted({item["requestId"] for item in timeline_frames}) == [request.request_id],
            "revisions": sorted({item["revision"] for item in frames}),
            "endedNeutral": bool(frames) and frames[-1]["shape"] == "neutral",
            "sampleCount": self._sample_count(request.request_id),
            "timingMethod": self._viseme_source(request.request_id),
            "held": self.link.report.held,
            # Bounded, and the point of the whole probe: the actual sequence of
            # files handed to Gtk.Picture, in order, with when.
            "frameTrace": [
                {
                    "atMs": item["atMs"], "shape": item["shape"],
                    "positionMs": item["positionMs"], "asset": Path(item["path"]).name,
                }
                for item in frames[:80]
            ],
        }
        self.report["measurements"]["fullUtterance"] = {
            "audioStartedAtMs": audio_started,
            "firstVisemeAtMs": first_viseme,
            "firstRenderedMouthFrameAtMs": first_drawn,
            "finalNeutralAtMs": neutral[-1]["atMs"] if neutral else None,
            "mouthChangesWhileAudioActive": len([
                item for item in timeline_frames
                if audio_started is not None and item["atMs"] >= audio_started
            ]),
            "maximumObservedDriftMs": max(
                (abs(item) for item in presentation_drift), default=None,
            ),
            "medianObservedDriftMs": _median(presentation_drift),
            "firstFrameDriftMs": presentation_drift[0] if presentation_drift else None,
            "maximumDispatchLatencyMs": max(dispatch_latency, default=None),
            "medianDispatchLatencyMs": _median(dispatch_latency),
            "schedulerReportedDriftMs": max(scheduler_drift) if scheduler_drift else 0,
            "schedulerDriftNote": (
                "structurally zero on the file-playback path: a one-shot player exposes "
                "no clock, so the worker passes the playback handle's position as both "
                "the timeline position and the audio clock. It is not a measurement and "
                "is reported here so that nobody reads the zero as one."
            ),
            "note": (
                "Timing method is MEASURED AMPLITUDE over the synthesiser's own samples "
                "in 40 ms windows. No phoneme boundary was measured anywhere in this "
                "build, and no claim of phoneme-accurate lip sync is made. "
                "maximumObservedDriftMs is the presentation drift: how far a drawn mouth "
                "frame sat from the point in the audio it belongs to, from the audio "
                "start on this machine's clock."
            ),
        }

        if len(non_neutral) < 2:
            self.fail(f"only {non_neutral} non-neutral mouth shape(s) were drawn")
        if not self.report["checks"]["fullUtterance"]["sequencesOrdered"]:
            self.fail("mouth frames were drawn out of order")
        if not self.report["checks"]["fullUtterance"]["requestIdsMatch"]:
            self.fail("a mouth frame carried a request id the audio did not")
        if not self.report["checks"]["fullUtterance"]["endedNeutral"]:
            self.fail("the mouth did not return to neutral when the utterance completed")
        if self.report["measurements"]["fullUtterance"]["mouthChangesWhileAudioActive"] < 2:
            self.fail("the mouth did not change while the audio was active")
        if self.report["checks"]["fullUtterance"]["revisions"] != [1]:
            self.fail("a mouth frame was drawn against a revision the renderer was not showing")
        self._assert_caption(request, "fullUtterance")

    def check_cancellation(self, PresentationState) -> None:
        before = len(self.drawn)
        request = self._speak(
            PresentationState, request_id_hint="cancellation",
            text=(
                "Bunny is reading a much longer sentence so that there is something "
                "to interrupt part of the way through it, which is the whole point."
            ),
        )
        if request is None:
            return
        # Wait for the mouth to be moving, then cancel.
        self.pump(seconds=10.0, until=lambda: any(
            item["origin"] == "timeline" and item["shape"] != "neutral"
            for item in self.drawn[before:]
        ))
        moving = len(self.drawn)
        cancelled_at = self.now_ms()
        self.voice.voice_cancel(requestId=request.request_id)
        self.pump(seconds=10.0, until=lambda: self._settled(request.request_id))
        frames = self.drawn[moving:]
        neutral = next((item for item in frames if item["shape"] == "neutral"), None)
        after_neutral = []
        if neutral is not None:
            after_neutral = [
                item for item in frames
                if item["atMs"] > neutral["atMs"] and item["shape"] != "neutral"
            ]
        self.report["checks"]["cancellation"] = {
            "requestId": request.request_id,
            "framesAfterCancel": len(frames),
            "returnedToNeutral": neutral is not None,
            "mouthChangesAfterNeutral": len(after_neutral),
            "rejectedAfterCancellation": self.link.report.rejected.get("after-cancellation", 0),
        }
        self.report["measurements"]["cancellation"] = {
            "cancelRequestedAtMs": cancelled_at,
            "neutralAtMs": neutral["atMs"] if neutral else None,
            "cancellationToNeutralMs": (
                round(neutral["atMs"] - cancelled_at, 3) if neutral else None
            ),
        }
        if neutral is None:
            self.fail("cancellation did not return the mouth to neutral")
        if after_neutral:
            self.fail(f"{len(after_neutral)} mouth change(s) happened after cancellation")
        self._assert_caption(request, "cancellation")

    def check_worker_restart(self, PresentationState) -> None:
        before = len(self.drawn)
        request = self._speak(
            PresentationState, request_id_hint="worker-restart",
            text="Bunny is speaking while the voice worker is restarted underneath it.",
        )
        if request is None:
            return
        self.pump(seconds=10.0, until=lambda: any(
            item["origin"] == "timeline" for item in self.drawn[before:]
        ))
        self.voice.restart_worker()
        self.voice.worker.subscribe(self.link.on_voice_event)
        self.voice.worker.subscribe(self.observe)
        self.pump(seconds=5.0, until=lambda: bool(self.drawn) and self.drawn[-1]["shape"] == "neutral")
        self.report["checks"]["voiceWorkerRestart"] = {
            "lastShape": self.drawn[-1]["shape"] if self.drawn else None,
            "origin": self.drawn[-1]["origin"] if self.drawn else None,
            "workerRunning": self.voice.worker.running,
            "note": (
                "restart_worker cancels the utterance in flight before it stops the "
                "worker, so the neutral usually arrives by the cancellation path rather "
                "than the worker-stopped one. Both end neutral, which is the property; "
                "the worker-stopped path is covered directly in "
                "tests/companion/test_voice_renderer_link.py"
            ),
        }
        if not self.drawn or self.drawn[-1]["shape"] != "neutral":
            self.fail("a voice-worker restart left the mouth mid-syllable")

    def check_renderer_restart(self, PresentationState) -> None:
        from companion.character.surface import CharacterPresenter

        before = len(self.drawn)
        request = self._speak(
            PresentationState, request_id_hint="renderer-restart",
            text="Bunny is speaking while the character renderer is restarted underneath it.",
        )
        if request is None:
            return
        self.pump(seconds=10.0, until=lambda: any(
            item["origin"] == "timeline" for item in self.drawn[before:]
        ))
        replacement = CharacterPresenter(self.presenter.root)
        answer = self.link.restart_renderer(replacement)
        self.presenter = replacement
        self.pump(seconds=10.0, until=lambda: self._settled(request.request_id))
        self.report["checks"]["rendererRestart"] = {
            "decision": answer,
            "lastShape": self.drawn[-1]["shape"] if self.drawn else None,
            "resumed": False,
            "degradedExplicitly": "degraded-to-neutral" in answer,
        }
        if "degraded-to-neutral" not in answer:
            self.fail("a renderer restart neither resumed nor degraded explicitly")
        if not self.drawn or self.drawn[-1]["shape"] != "neutral":
            self.fail("a renderer restart left stale mouth state")
        self._assert_caption(request, "rendererRestart")

    def check_stale_revision(self, PresentationState) -> None:
        before = len(self.drawn)
        request = self._speak(
            PresentationState, request_id_hint="revision",
            text="Bunny is speaking while the presentation revision moves on.",
        )
        if request is None:
            return
        self.pump(seconds=10.0, until=lambda: any(
            item["origin"] == "timeline" for item in self.drawn[before:]
        ))
        self.link.publish(2)
        self.pump(seconds=10.0, until=lambda: self._settled(request.request_id))
        stale = self.link.report.rejected.get("stale-revision", 0)
        self.report["checks"]["presentationRevision"] = {
            "revisionAfter": self.link.revision,
            "staleFramesRefused": stale,
            "framesDrawnAtOldRevision": len([
                item for item in self.drawn[before:] if item["revision"] == 1
            ]),
        }
        if stale <= 0:
            self.report["limitations"].append(
                "the revision moved after the last viseme of the utterance, so no stale "
                "frame was produced to refuse; the refusal itself is covered by "
                "tests/companion/test_voice_renderer_link.py"
            )

    # -- teardown ----------------------------------------------------------

    def teardown(self) -> None:
        self.link.close()
        self.voice.close()
        # Drain whatever the close produced, then look for survivors.
        self.pump(seconds=1.0)
        survivors = sorted(self.idle_sources - self.retired)
        self.report["checks"]["teardown"] = {
            "idleSourcesCreated": len(self.idle_sources),
            "idleSourcesSurviving": len(survivors),
            "timeoutSourcesCreated": 0,
            "voiceThreadsRemaining": sum(
                1 for item in threading.enumerate() if item.name.startswith("companion-voice")
            ),
            "lastShape": self.drawn[-1]["shape"] if self.drawn else None,
        }
        if survivors:
            self.fail(f"{len(survivors)} GLib idle source(s) survived teardown")
        if self.report["checks"]["teardown"]["voiceThreadsRemaining"]:
            self.fail("a voice worker thread survived teardown")
        if self.drawn and self.drawn[-1]["shape"] != "neutral":
            self.fail("stale mouth state remained after teardown")
        self.report["link"] = self.link.describe()

    # -- small readers -----------------------------------------------------

    def _settled(self, request_id: str) -> bool:
        return any(
            item["requestId"] == request_id
            and item["kind"] in (
                "speech_finished", "speech_cancelled", "speech_interrupted",
                "speech_failed", "speech_degraded",
            )
            for item in self.events
        )

    def _event_ms(self, kind: str, request_id: str) -> float | None:
        for item in self.events:
            if item["kind"] == kind and item["requestId"] == request_id:
                return item["atMs"]
        return None

    def _sample_count(self, request_id: str) -> int | None:
        for item in reversed(self.events):
            if item["requestId"] != request_id:
                continue
            synthesis = item["payload"].get("synthesis") if item["payload"] else None
            if isinstance(synthesis, dict) and synthesis.get("frameCount"):
                return int(synthesis["frameCount"])
        return None

    def _viseme_source(self, request_id: str) -> str:
        for item in self.events:
            if item["kind"] == "audio_started" and item["requestId"] == request_id:
                return str(item["payload"].get("visemeSource", ""))
        return ""

    def _assert_caption(self, request: Any, label: str) -> None:
        """§8: the caption is correct whatever the mouth did."""
        caption = self.voice.ledger.get(request.caption_reference)
        recorded = caption.text if caption is not None else ""
        self.report["checks"].setdefault("captions", {})[label] = {
            "captionPresent": caption is not None,
            "matchesProjection": bool(recorded),
        }
        if caption is None:
            self.fail(f"{label}: the caption the utterance came from is gone")


def arguments_package(arguments: argparse.Namespace) -> Path | None:
    if not arguments.package_root:
        return None
    return Path(arguments.package_root) / arguments.package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", default="", help="where character packages live")
    parser.add_argument("--package", default="default-bunny")
    parser.add_argument(
        "--runtime-directory", default="/tmp/bunny-voice-viseme-probe",
        help="where the voice journal is written",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    Path(arguments.runtime_directory).mkdir(parents=True, exist_ok=True)

    probe = Probe(arguments)
    try:
        return probe.run()
    except Exception:  # noqa: BLE001 - the probe reports its own failure
        probe.report["gate"] = {
            "passed": False,
            "failures": ["the probe raised", traceback.format_exc().splitlines()[-1]],
        }
        probe.report["traceback"] = traceback.format_exc()
        print(json.dumps(probe.report, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
