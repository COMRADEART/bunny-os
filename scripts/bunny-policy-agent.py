#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed device policy agent.

``systemd/bunny-policy-agent.service`` starts this program. The unit used to
name an ExecStart that nothing installed, so an enrolled device would fail at
the loader with "not executable". This file closes that gap without pretending
a control plane exists.

It never writes ``/etc/bunny-os/managed-settings.json`` (only the broker may)
and never stages an unsigned bundle. DEVICE_POLICY.md step 1 is "verify a
signed organisation bundle". This tree has no production signing path for
those bundles, so verification cannot succeed and nothing is applied.

Exit 2 is the fail-closed answer: systemd records a failed oneshot, no
settings change, no silent pass. The enterprise pilot gate remains BLOCKED.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def _path(env_name: str, default: str) -> Path:
    return Path(os.environ.get(env_name) or default)


def main(argv: list[str] | None = None) -> int:
    del argv
    enrolment = _path("BUNNY_POLICY_ENROLMENT", "/etc/bunny-os/enrolment.json")
    staged = _path("BUNNY_POLICY_STAGED", "/var/lib/bunny-os/policy/staged-policies.json")
    managed = _path("BUNNY_POLICY_MANAGED", "/etc/bunny-os/managed-settings.json")
    if not enrolment.is_file():
        print(
            "bunny-policy-agent: no enrolment record; refusing to run "
            f"(expected {enrolment})",
            file=sys.stderr,
        )
        return 2
    try:
        payload = json.loads(enrolment.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"bunny-policy-agent: enrolment is unreadable: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("bunny-policy-agent: enrolment is not a JSON object", file=sys.stderr)
        return 2

    if staged.is_file() or managed.is_file():
        print(
            "bunny-policy-agent: a staged or managed overlay is present, but this "
            "agent cannot verify a signature and will not apply or refresh it",
            file=sys.stderr,
        )
        return 2

    print(
        "bunny-policy-agent: enrolment is present and no signed policy bundle "
        "can be verified in this build; applying nothing",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
