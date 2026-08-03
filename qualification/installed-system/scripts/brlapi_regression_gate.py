#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The BrlAPI regression gate: three installations, three distinct keys.

Stage 9 asks a narrow question — does the corrected archive mint a per-install
BrlAPI key with the right ownership and mode, and does it keep the value out of
the logs and out of the repository? — and this decides it from the collected
records rather than from a summary someone wrote by hand.

The distinctness check is the one that matters most. A key baked into the image
would satisfy "present, 0640, root-owned" on every installation and be useless:
every Bunny system would share one authorisation key. Three installations
producing three different digests is what establishes it is generated per
install.

Types are normalised before comparison. The collector records uid, gid and mode
as strings, and an earlier version of this check compared uid against the
integer 0, which is never equal to "0" — so it reported a correctly root-owned
key as not root-owned and blocked a passing regression. A gate that fails
closed on its own type confusion is still a wrong gate.

Physical braille hardware is NOT_RUN and this gate never claims otherwise: key
generation and service integration are not device support.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import sys

REQUIRED_INSTALLATIONS = 3
REQUIRED_MODE = 0o640


def as_int(value, base: int = 10) -> int | None:
    """The collector writes numbers as strings; compare them as numbers."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        if text.startswith("0o"):
            return int(text, 8)
        return int(text, base)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path(
        "qualification/installed-system/evidence-isq2"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    paths = sorted(glob.glob(str(args.evidence_root / "ISQ-*brlapi*" /
                                 "brlapi.json")))
    records = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]

    problems: list[str] = []
    if len(records) < REQUIRED_INSTALLATIONS:
        problems.append(
            f"{len(records)} installations collected, "
            f"{REQUIRED_INSTALLATIONS} required")

    digests: list[str] = []
    for path, record in zip(paths, records):
        name = Path(path).parent.name
        key = record.get("key") or {}
        if record.get("result") != "PASS":
            problems.append(f"{name}: result is {record.get('result')}")
        if not key.get("present"):
            problems.append(f"{name}: no key was created")
            continue

        mode = as_int(key.get("mode"))
        if mode != REQUIRED_MODE:
            problems.append(
                f"{name}: key mode is {key.get('mode')}, expected 0640")
        if mode is not None and mode & 0o007:
            problems.append(
                f"{name}: key mode {key.get('mode')} is readable by others")

        uid = as_int(key.get("uid"))
        if uid != 0:
            problems.append(f"{name}: key is owned by uid {key.get('uid')}, "
                            "expected root")

        digest = key.get("sha256")
        if not digest:
            problems.append(f"{name}: the record carries no key digest")
        else:
            digests.append(digest)

        for field in ("value", "key", "secret"):
            if isinstance(key.get(field), str):
                problems.append(
                    f"{name}: the record carries a {field} field; a key "
                    "record must carry the digest and never the value")

        classification = record.get("classification") or {}
        if classification.get("physicalBrailleDevice") != "NOT_RUN":
            problems.append(
                f"{name}: physicalBrailleDevice is "
                f"{classification.get('physicalBrailleDevice')}; no braille "
                "device was attached and key generation is not device support")

    if digests and len(set(digests)) != len(digests):
        problems.append(
            "key digests are not distinct across installations — a shared key "
            "would satisfy every other check here and still leave every "
            "system using the same authorisation key")

    verdict = {
        "installations": len(records),
        "keysPresent": len(digests),
        "distinctKeys": len(set(digests)),
        "requiredMode": "0640",
        "physicalBrailleDevice": "NOT_RUN",
        "problems": problems,
        "verdict": "PASS" if not problems else "BLOCKED",
    }
    for problem in problems:
        print(f"  problem: {problem}")
    print(json.dumps(verdict, indent=2))
    if args.output:
        args.output.write_text(json.dumps(verdict, indent=2) + "\n",
                               encoding="utf-8")
        print(f"verdict written to {args.output}")
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
