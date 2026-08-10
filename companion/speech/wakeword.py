# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Wake-word lifecycle boundary, intentionally disabled for this milestone.

The object exists so a future explicitly enabled detector has a service seam
and state contract; it owns no capture backend today. Push-to-talk remains the
only production activation route, and there is no method here that can open a
microphone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = ["WakeWordService", "WakeWordState"]


class WakeWordState(str, Enum):
    DISABLED = "disabled"
    WAITING = "waiting"
    DETECTED = "detected"


@dataclass
class WakeWordService:
    phrase: str = "Hey Bunny"
    state: WakeWordState = WakeWordState.DISABLED

    def enable(self) -> None:
        raise RuntimeError(
            "wake-word listening is not enabled in this milestone; use explicit push-to-talk"
        )

    def disable(self) -> None:
        self.state = WakeWordState.DISABLED

    def describe(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "phrase": self.phrase,
            "available": False,
            "enabled": False,
            "opensMicrophone": False,
            "persistentIndicatorRequiredWhenEnabled": True,
            "reason": "push-to-talk is the only enabled activation mode",
        }
