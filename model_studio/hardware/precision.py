# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one place that decides what numeric type training runs in.

There is exactly one implementation of this decision in Bunny, and it is this
function. Not because duplication is untidy, but because the two copies would
disagree on the one input that matters: *whether bfloat16 is actually supported*.
The tempting shortcut is

    if cuda_available: dtype = bfloat16

and it is wrong on every card before Ampere. A Turing or Pascal GPU reports
``torch.cuda.is_available() == True`` and then produces NaNs, or a kernel error
at the first backward pass, depending on which operation gets there first. The
failure surfaces minutes into a run, and looks like a bad dataset.

So the decision is a pure function of an :class:`~model_studio.hardware.probe.
Accelerator` — which carries capability as a *tri-state*, not a boolean — and
the rule for the third state is the one that makes this safe:

    bfloat16 is selected only when support was positively established.

``UNKNOWN`` is not "probably fine". A machine whose capability could not be
queried gets float32, which is slower and always correct, and the reason says
so. The inverse rule — assume the fast thing and let it crash — is how a
training subsystem earns a reputation for being flaky on hardware nobody on the
team owns.

The second rule is about explicit requests. A configuration that asks for
``bf16`` on a card that cannot do it does not get quietly downgraded to
``fp16``: :attr:`PrecisionDecision.honoured` is false, and preflight turns that
into a blocking reason. A silent downgrade changes the numerics of a run whose
results someone is about to compare against another run, and neither report
would mention it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .probe import SUPPORTED, UNKNOWN, Accelerator

__all__ = ["DTYPES", "PrecisionDecision", "select_precision"]

#: Every numeric type this project trains in. ``fp32`` is the floor: it is the
#: only one that is correct everywhere, so it is what an unresolvable machine
#: gets.
DTYPES: tuple[str, ...] = ("bf16", "fp16", "fp32")


@dataclass(frozen=True)
class PrecisionDecision:
    """What training will run in, and why.

    ``honoured`` is false when ``requested`` named a dtype this accelerator
    cannot do. ``dtype`` then holds what the machine *can* do, so a caller that
    wants to show "you asked for bf16; this card can only do fp16" has both
    halves — but a caller that just runs the plan must refuse, and preflight
    does.
    """

    dtype: str
    reason: str
    requested: str = "auto"
    honoured: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "dtype": self.dtype,
            "reason": self.reason,
            "requested": self.requested,
            "honoured": self.honoured,
        }


def _automatic(accelerator: Accelerator) -> PrecisionDecision:
    """The rule table, with ``UNKNOWN`` never resolving upward."""
    if accelerator.kind == "cuda":
        if accelerator.bf16 == SUPPORTED:
            return PrecisionDecision(
                "bf16",
                f"CUDA device {accelerator.name!r} reports bfloat16 support",
            )
        if accelerator.fp16 == SUPPORTED:
            detail = (
                "does not support bfloat16"
                if accelerator.bf16 != UNKNOWN
                else "could not be queried for bfloat16 support"
            )
            return PrecisionDecision(
                "fp16",
                f"CUDA device {accelerator.name!r} {detail}; float16 is supported",
            )
        return PrecisionDecision(
            "fp32",
            f"CUDA device {accelerator.name!r} established neither bfloat16 nor "
            "float16 support; float32 is the only correct choice",
        )

    if accelerator.kind == "mps":
        # Apple Silicon: the supported half-precision type is float16. bfloat16
        # exists on newer chips and newer torch, so it is taken when the probe
        # positively established it and never assumed from "this is an M-series".
        if accelerator.bf16 == SUPPORTED:
            return PrecisionDecision(
                "bf16", "Metal backend reports bfloat16 support",
            )
        if accelerator.fp16 == SUPPORTED:
            return PrecisionDecision(
                "fp16", "Metal backend supports float16; bfloat16 was not established",
            )
        return PrecisionDecision(
            "fp32", "Metal backend established no half-precision support",
        )

    return PrecisionDecision(
        "fp32",
        "no accelerator; CPU training runs in float32 because half precision on "
        "CPU is neither faster nor uniformly implemented",
    )


def select_precision(accelerator: Accelerator, *, requested: str = "auto") -> PrecisionDecision:
    """The canonical precision decision. Every trainer calls this one.

    ``requested`` is ``"auto"`` or a member of :data:`DTYPES`. An explicit
    request is honoured only where support was positively established;
    ``fp32`` is honoured everywhere, because every backend can do it.
    """
    if requested not in ("auto", *DTYPES):
        raise ValueError(f"unknown precision {requested!r}; expected auto or one of {DTYPES}")

    automatic = _automatic(accelerator)
    if requested == "auto":
        return automatic

    if requested == "fp32":
        return PrecisionDecision(
            "fp32", "float32 was requested and is available on every backend",
            requested=requested,
        )

    support = accelerator.bf16 if requested == "bf16" else accelerator.fp16
    if support == SUPPORTED:
        return PrecisionDecision(
            requested,
            f"{requested} was requested and {accelerator.name!r} supports it",
            requested=requested,
        )

    state = "does not support it" if support != UNKNOWN else "could not be queried for it"
    return PrecisionDecision(
        automatic.dtype,
        f"{requested} was requested but {accelerator.name!r} {state}; "
        f"this machine can run {automatic.dtype}",
        requested=requested,
        honoured=False,
    )
