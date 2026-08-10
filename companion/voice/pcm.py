# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a WAV file the runtime produced, without trusting anything about it.

Two callers need this and they need it for opposite reasons.

:mod:`companion.voice.providers` needs it to find out whether a synthesiser
*actually produced audio*. That is not the same question as "did it exit zero",
and on the reference target the two genuinely disagree: eSpeak NG 1.52 exits
``0`` when handed empty input and writes no file at all, and exits ``0`` when it
cannot write the file it was told to write, printing ``Can't write to: ...`` to
stderr. A provider that reported success from the exit code would hand the
worker a path to nothing, the worker would record the utterance as *played*, and
a user who heard silence would have no way to tell a broken synthesiser from a
quiet one. So success means *there is audio in the file*, measured here.

:mod:`companion.voice.visemes` needs it to derive mouth shapes from the sound
that will actually come out. Amplitude is the only viseme source in this build
that is a measurement rather than an estimate, and it is a measurement of these
samples.

Nothing here uses :mod:`audioop`: it was removed in Python 3.13 and the
reference target runs 3.14. The RMS loop below is a few lines of :mod:`array`
arithmetic and has no such dependency.

The parser is deliberately narrow — 8- and 16-bit PCM, any channel count, any
rate — and refuses everything else rather than guessing. This file is produced
by a subprocess a moment ago on the same machine, so exotic formats mean
something went wrong, and a lenient parser would turn "something went wrong"
into a plausible-looking waveform.
"""

from __future__ import annotations

import array
from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any
import wave

__all__ = [
    "AudioProbe",
    "PcmError",
    "amplitude_envelope",
    "probe_wav",
]

#: The most audio this will read into memory at once, in frames. At 22.05 kHz
#: that is a little over four minutes — far beyond any caption — and it is a
#: bound rather than an expectation: the file comes from a subprocess, and a
#: subprocess that wrote a gigabyte must not be able to make the service read it.
MAX_FRAMES = 6_000_000


class PcmError(ValueError):
    """A file that is not usable audio, with the reason stated."""


@dataclass(frozen=True)
class AudioProbe:
    """What a WAV file turned out to be."""

    path: str
    channels: int
    sample_width: int
    sample_rate: int
    frame_count: int
    byte_size: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate if self.sample_rate else 0.0

    @property
    def silent(self) -> bool:
        """No frames at all. Distinct from "quiet", which is a level, not a shape."""
        return self.frame_count == 0

    def to_json(self) -> dict[str, Any]:
        return {
            "channels": self.channels,
            "sampleWidth": self.sample_width,
            "sampleRate": self.sample_rate,
            "frameCount": self.frame_count,
            "byteSize": self.byte_size,
            "durationSeconds": round(self.duration_seconds, 6),
        }


def probe_wav(path: str | Path) -> AudioProbe:
    """Open a WAV file and report what is in it. Raises :class:`PcmError` if unusable."""
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise PcmError(f"the synthesiser wrote no file at {target.name}: {exc.strerror or exc}") from exc
    if size == 0:
        raise PcmError(f"{target.name} is empty; the synthesiser produced no audio")
    try:
        with wave.open(str(target), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
    except (wave.Error, EOFError, OSError) as exc:
        raise PcmError(f"{target.name} is not a readable WAV file: {exc}") from exc
    if width not in (1, 2):
        raise PcmError(f"{target.name} is {width * 8}-bit; this runtime reads 8- and 16-bit PCM")
    if channels < 1 or channels > 8:
        raise PcmError(f"{target.name} declares {channels} channels")
    if rate <= 0:
        raise PcmError(f"{target.name} declares a sample rate of {rate}")
    if frames <= 0:
        # The eSpeak NG empty-input case, and the reason this function exists.
        raise PcmError(f"{target.name} contains no audio frames")
    if frames > MAX_FRAMES:
        raise PcmError(f"{target.name} holds {frames} frames, beyond the {MAX_FRAMES} bound")
    return AudioProbe(
        path=str(target),
        channels=channels,
        sample_width=width,
        sample_rate=rate,
        frame_count=frames,
        byte_size=size,
    )


def _samples(raw: bytes, width: int) -> array.array:
    if width == 2:
        values = array.array("h")
        values.frombytes(raw[: len(raw) - (len(raw) % 2)])
        if sys.byteorder == "big":
            # WAV is little-endian. On a big-endian host the array would be read
            # byte-swapped, and the envelope would be noise shaped like audio.
            values.byteswap()
        return values
    values = array.array("b")
    # 8-bit WAV is *unsigned*, centred on 128. Subtracting the offset here means
    # the RMS below measures deviation from silence rather than from zero, which
    # for unsigned data would otherwise report a constant loud signal.
    values.frombytes(bytes((item - 128) & 0xFF for item in raw))
    return values


def amplitude_envelope(
    probe: AudioProbe,
    *,
    window_ms: int = 40,
    maximum_windows: int = 4096,
) -> list[tuple[int, float]]:
    """``(offset_ms, level)`` for each window, with ``level`` normalised to 0..1.

    Root-mean-square rather than peak. A peak detector fires on a single click
    and holds the mouth open through a pause; RMS tracks how loud the window
    *sounds*, which is what a mouth shape is supposed to follow.

    The normalisation is against this utterance's own loudest window, not
    against full scale. Synthesisers differ by more than 20 dB in output level,
    and a fixed reference would give one provider a permanently closed mouth and
    another a permanently open one. The cost is that a genuinely quiet utterance
    is scaled up to look normal — acceptable, because the alternative is a
    character that does not move when the machine is speaking.

    ``window_ms`` at 40 ms is about two and a half frames of a 60 Hz renderer:
    fast enough that the mouth tracks syllables, slow enough that it is not
    flickering on individual glottal pulses.
    """
    if window_ms <= 0:
        raise PcmError("the analysis window must be positive")
    frames_per_window = max(1, int(probe.sample_rate * window_ms / 1000))
    with wave.open(probe.path, "rb") as handle:
        raw = handle.readframes(probe.frame_count)
    values = _samples(raw, probe.sample_width)
    if not values:
        return []
    channels = max(1, probe.channels)
    full_scale = 32768.0 if probe.sample_width == 2 else 128.0
    step = frames_per_window * channels

    levels: list[tuple[int, float]] = []
    total = len(values)
    # A bound on the number of windows, widening the window if the utterance is
    # long. §13 requires a bounded event count and this is where the bound is
    # applied to the *source* rather than by discarding events later.
    if total // step > maximum_windows:
        step = max(channels, (total // maximum_windows) // channels * channels or channels)
        frames_per_window = step // channels

    for index in range(0, total, step):
        window = values[index : index + step]
        if not window:
            break
        accumulator = 0
        for sample in window:
            accumulator += sample * sample
        rms = math.sqrt(accumulator / len(window)) / full_scale
        offset_ms = int((index // channels) * 1000 / probe.sample_rate)
        levels.append((offset_ms, rms))

    peak = max((level for _, level in levels), default=0.0)
    if peak <= 0.0:
        return [(offset, 0.0) for offset, _ in levels]
    return [(offset, min(1.0, level / peak)) for offset, level in levels]
