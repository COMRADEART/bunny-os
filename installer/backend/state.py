# SPDX-License-Identifier: GPL-3.0-or-later
"""Installer lifecycle with explicit safe cancellation boundaries."""

from __future__ import annotations

from dataclasses import dataclass


STAGES = (
    "Preparing",
    "Validating storage",
    "Partitioning",
    "Encrypting",
    "Creating filesystems",
    "Deploying Bunny OS",
    "Installing bootloader",
    "Creating user",
    "Installing recovery",
    "Configuring hardware",
    "Final verification",
    "Complete",
)
WRITE_BOUNDARY = STAGES.index("Partitioning")


@dataclass
class InstallationState:
    status: str = "initialized"
    stage_index: int = 0
    operation: str = "Waiting for a validated plan"
    warning: str | None = None
    failure: str | None = None

    @property
    def stage(self) -> str:
        return STAGES[min(self.stage_index, len(STAGES) - 1)]

    @property
    def percent(self) -> int:
        return round((self.stage_index / (len(STAGES) - 1)) * 100)

    @property
    def may_cancel(self) -> bool:
        return self.status in {"initialized", "planned", "installing"} and self.stage_index < WRITE_BOUNDARY

    @property
    def destructive_write_started(self) -> bool:
        return self.stage_index >= WRITE_BOUNDARY

    def start(self) -> None:
        if self.status != "planned":
            raise ValueError("installation can start only from a validated plan")
        self.status = "installing"
        self.stage_index = 0
        self.operation = "Preparing the validated installation request"

    def advance(self, operation: str) -> None:
        if self.status != "installing":
            raise ValueError("installation is not running")
        if self.stage_index >= len(STAGES) - 1:
            raise ValueError("installation is already complete")
        self.stage_index += 1
        self.operation = operation[:256]
        if self.stage == "Complete":
            self.status = "complete"

    def cancel(self) -> None:
        if not self.may_cancel:
            raise ValueError("cancellation is not safe at the current boundary")
        self.status = "cancelled"
        self.operation = "Cancelled before destructive writes"

    def fail(self, code: str) -> None:
        self.status = "failed"
        self.failure = code[:128]
        self.operation = "Stopped at a safe boundary where possible"

    def public(self) -> dict[str, object]:
        return {
            "status": self.status,
            "stage": self.stage,
            "overallProgress": self.percent,
            "currentOperation": self.operation,
            "warning": self.warning,
            "failure": self.failure,
            "mayCancel": self.may_cancel,
            "destructiveWriteStarted": self.destructive_write_started,
            "estimatedCompletionTime": None,
        }

