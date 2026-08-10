# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and set the output volume — the one action that can prove it worked.

Everything else in this catalogue hands a request to something and is told it
was accepted. This one can ask afterwards. That makes it the action §22's slice
uses to demonstrate a *verified* result and a *verified* undo, and it is why
:attr:`companion.desktop.catalogue.ActionDescriptor.supports_verification` is
true here and almost nowhere else.

**The sink identity is bound into the approval.** §4.5 requires a refusal when
the device changed after approval, and that is only possible if the approval
named a device. So a volume request always carries an ``outputId``: either the
one the caller approved, or the default sink resolved *before* the question was
asked. A machine where headphones were plugged in between the prompt and the
execution has changed the answer to "which speaker", and the honest response is
to ask again rather than to set the volume of whatever is default now.

**Read-back is rounded and says so.** ``pactl`` reports volume in both raw
units and percent, and the percent it prints is itself rounded. A request for
50% can read back as 50% while the underlying value is 49.8%. The descriptor's
limitations say the comparison is at whole-percent resolution, so a match means
"the same to the precision the desktop itself displays" rather than "identical".
Saying which is better than a confirmation nobody can interpret.

There is deliberately no per-application volume control. §4.5 excludes it, and
the reason is that a per-application sink input is a moving target — it exists
only while the application plays something, so an approval naming one is an
approval that can stop being answerable between question and act.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

from ..errors import DesktopCancelled
from .base import (
    AdapterOutcome,
    Availability,
    acknowledged,
    failure,
    unsupported_outcome,
    verified,
)
from .command import capture_command, have, run_command

__all__ = ["AudioControlAdapter", "AudioOutput"]

#: The default sink, in ``pactl``'s own vocabulary. Used only to *resolve* the
#: name of the current default; never passed to a set command, because a request
#: approved against "whatever is default" is a request approved against nothing.
_DEFAULT_SINK_TOKEN = "@DEFAULT_SINK@"

#: ``Volume: front-left: 32768 /  50% / -18.06 dB,   front-right: …``
_VOLUME_PERCENT = re.compile(r"(\d{1,3})%")


@dataclass(frozen=True)
class AudioOutput:
    """One output, as much of it as an approval needs to name."""

    output_id: str
    display_name: str = ""
    percent: int | None = None
    muted: bool | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "outputId": self.output_id,
            "displayName": self.display_name,
            "percent": self.percent,
            "muted": self.muted,
        }


class AudioControlAdapter:
    """Read and set the volume and mute of one named output."""

    adapter_id = "AudioControlAdapter"

    def probe(self) -> Availability:
        if not have("pactl"):
            return Availability(
                False, mechanism="pactl", service="pulseaudio-or-pipewire",
                detail="pactl is not installed, so the mixer cannot be reached",
            )
        # §16 again: installed is not available. `pactl info` fails when no
        # sound server is running, which is the actual question.
        if capture_command("pactl", ["info"], timeout_seconds=4.0) is None:
            return Availability(
                False, mechanism="pactl", service="pulseaudio-or-pipewire",
                detail="pactl is installed and no sound server answered; there is no user audio session",
            )
        if self.default_output() is None:
            return Availability(
                False, mechanism="pactl", service="pulseaudio-or-pipewire",
                detail="a sound server answered and there is no output sink to control",
            )
        return Availability(
            True, mechanism="pactl", service="pulseaudio-or-pipewire",
            detail="a sound server answered and an output sink is present",
        )

    # -- reading -----------------------------------------------------------

    def default_output_id(self) -> str:
        """The name of the current default sink, or an empty string."""
        captured = capture_command("pactl", ["get-default-sink"], timeout_seconds=4.0)
        if captured is None:
            return ""
        name = captured.strip().splitlines()[0].strip() if captured.strip() else ""
        return name if name and name != _DEFAULT_SINK_TOKEN else ""

    def read(self, output_id: str = "") -> AudioOutput | None:
        """The current volume and mute of one sink, or ``None`` if unreadable.

        ``None`` rather than a default, for the same reason
        :meth:`SettingsAdapter.read_do_not_disturb` returns it: "cannot tell"
        and "it is zero" are opposite facts and a caller must be able to see
        which one it has.
        """
        name = output_id or self.default_output_id()
        if not name:
            return None
        volume = capture_command("pactl", ["get-sink-volume", name], timeout_seconds=4.0)
        mute = capture_command("pactl", ["get-sink-mute", name], timeout_seconds=4.0)
        if volume is None:
            return None
        match = _VOLUME_PERCENT.search(volume)
        percent = int(match.group(1)) if match else None
        if percent is not None:
            # pactl reports over 100% for boosted sinks. Clamped for the *record*
            # and not for the device: the number shown to a user matches the
            # range the approval was expressed in.
            percent = max(0, min(100, percent))
        muted: bool | None = None
        if mute is not None:
            muted = "yes" in mute.lower()
        return AudioOutput(
            output_id=name,
            display_name=_display_name(name),
            percent=percent,
            muted=muted,
        )

    def default_output(self) -> AudioOutput | None:
        return self.read("")

    # -- setting -----------------------------------------------------------

    def set_volume(
        self,
        *,
        output_id: str,
        percent: int,
        muted: bool | None = None,
        cancellable: Any = None,
    ) -> AdapterOutcome:
        """Set one sink's volume, then read it back and compare.

        ``output_id`` is required and is never ``@DEFAULT_SINK@``. A request
        approved against "the default" would set the volume of whatever became
        default in the meantime, which is the substitution §4.5 refuses.
        """
        started = time.monotonic()
        availability = self.probe()
        if not availability.available:
            return unsupported_outcome("pactl", availability.detail)
        if not output_id or output_id == _DEFAULT_SINK_TOKEN:
            return failure(
                "pactl",
                "a volume change names the sink it applies to; 'the default' is not a sink an "
                "approval can be bound to",
            )
        if not 0 <= int(percent) <= 100:
            return failure("pactl", f"{percent} is outside the 0-100 range")
        if cancellable is not None:
            cancellable.check("before the volume was changed")

        before = self.read(output_id)
        if before is None:
            # The sink named in the approval is gone. Refused rather than
            # redirected to whatever is default now.
            return failure(
                "pactl",
                f"the output {output_id!r} this was approved against is no longer present; the "
                "volume was not changed and no substitute was chosen",
            )

        outcome = run_command(
            "pactl", ["set-sink-volume", output_id, f"{int(percent)}%"], timeout_seconds=5.0
        )
        if outcome.cancelled:
            raise DesktopCancelled(
                "the volume change was cancelled while pactl was running",
                effect_known=False, effect_prevented=False,
            )
        if not outcome.succeeded:
            return failure("pactl", outcome.stderr or f"pactl exited {outcome.exit_code}")

        if muted is not None:
            mute_outcome = run_command(
                "pactl", ["set-sink-mute", output_id, "1" if muted else "0"], timeout_seconds=5.0
            )
            if not mute_outcome.succeeded:
                # The volume changed and the mute did not. Reported as a failure
                # with the partial effect named, because a result that said
                # "failed" alone would imply nothing happened.
                return failure(
                    "pactl",
                    "the volume was set and the mute state could not be changed; the volume "
                    f"change stands: {mute_outcome.stderr or mute_outcome.exit_code}",
                )

        after = self.read(output_id)
        matched = after is not None and after.percent == int(percent)
        if matched and muted is not None:
            matched = after.muted == muted
        return _timed(
            verified(
                "pactl",
                detail=(
                    "the sink's volume was read back after the change and compared at "
                    "whole-percent resolution"
                ),
                matched=bool(matched),
                observed_value=None if after is None else after.percent,
                previousPercent=before.percent,
                previousMuted=before.muted,
                outputId=output_id,
                outputName=before.display_name,
            ),
            started,
        )


def _display_name(sink: str) -> str:
    """A sink's name as a person would recognise it, from its identifier.

    ``alsa_output.pci-0000_00_1f.3.analog-stereo`` is not a thing to put in an
    approval prompt. The trailing profile is the readable part, and where there
    is nothing readable the identifier is used unchanged rather than replaced
    with a guess — §18 wants the exact target, and "Speakers" for a sink that is
    in fact a monitor would be worse than a long name.
    """
    tail = sink.rsplit(".", 1)[-1] if "." in sink else sink
    words = tail.replace("_", " ").replace("-", " ").strip()
    if not words or words.isdigit():
        return sink
    return words


def _timed(outcome: AdapterOutcome, started: float) -> AdapterOutcome:
    from dataclasses import replace

    return replace(outcome, duration_seconds=max(0.0, time.monotonic() - started))
