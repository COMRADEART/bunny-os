# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Grade a recorded run from the command line.

    python3 -m qualification.grader.cli build/out/phase3/login/g16 --user alex

Exists so that the harness and a person use the *same* grader. Phase 4's
grading lived in a heredoc inside ``build/scripts/vm-login-story.sh``, which
meant it could only run at the end of a sixteen-minute VM run, could not be
tested, and could not be replayed over a recorded run without editing the shell
script. Every one of those is a reason a wrong check survives.

**On writing.** :mod:`core`, :mod:`models` and :mod:`rules` never write
anything, and ``tests/test_side_effect_safety.py`` asserts it. This module
does write — the verdict has to go somewhere — and the boundary is deliberate:
it writes only the file it was asked to write, and never the evidence it read.
``--output -`` prints to stdout and writes nothing at all, which is the mode a
replay over committed evidence should use.

Exit status:

    0   PASS
    6   FAIL
    7   NOT_RUN

``6`` is inherited from the shell harness this replaces, so a caller that
tested for it keeps working. ``7`` is new, because "nothing was measured" used
to share an exit status with "everything measured was fine".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import grade, load_evidence, load_expectation
from .models import Expectation, Outcome

EXIT_STATUS = {Outcome.PASS: 0, Outcome.FAIL: 6, Outcome.NOT_RUN: 7}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qualification.grader.cli",
        description="Grade a recorded VM journey. Reads evidence; runs no machine.",
    )
    parser.add_argument("run", type=Path, help="the recorded run directory")
    parser.add_argument("--user", default=None, help="the account the session was opened for")
    parser.add_argument(
        "--expect-journey",
        choices=("granted", "denied", "none"),
        default=None,
        help=(
            "what the run was asked to do. Overrides expectation.json. "
            "'none' declares that no journey was requested, which is different "
            "from not declaring at all."
        ),
    )
    parser.add_argument(
        "--expect-interaction",
        choices=("yes", "no"),
        default=None,
        help="whether an in-session driver was supposed to run",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="where to write the verdict JSON; '-' prints it and writes nothing",
    )
    parser.add_argument(
        "--merge-into",
        type=Path,
        default=None,
        help=(
            "an existing result.json to carry forward alongside the verdict, so a "
            "reader that expected the old fields still finds them"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    run: Path = arguments.run

    if not run.is_dir():
        print(f"no such run directory: {run}", file=sys.stderr)
        return 2

    expectation = load_expectation(run)
    if arguments.expect_journey is not None or arguments.expect_interaction is not None:
        # An explicit flag beats the file, and *declares* the run either way —
        # a caller who names what the run was for has declared it, whether or
        # not the run wrote a sidecar.
        expectation = Expectation(
            declared=True,
            journey=(
                None
                if arguments.expect_journey in (None, "none")
                else arguments.expect_journey
            )
            if arguments.expect_journey is not None
            else expectation.journey,
            interaction=(
                arguments.expect_interaction == "yes"
                if arguments.expect_interaction is not None
                else expectation.interaction
            ),
            graphical_session=expectation.graphical_session,
            label=expectation.label or run.name,
        )

    verdict = grade(load_evidence(run, user=arguments.user), expectation)
    document = verdict.to_json()

    if arguments.merge_into and arguments.merge_into.is_file():
        try:
            previous = json.loads(arguments.merge_into.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
        if isinstance(previous, dict):
            # The verdict wins on every key it owns; everything the collector
            # recorded and the grader does not model is carried through rather
            # than dropped.
            merged = dict(previous)
            merged.update(document)
            # ...except `schemaVersion`, which both sides own and which means
            # different things to each. A blind merge silently rewrote the
            # collector's `schemaVersion: 2` to the grader's `1`, so a reader
            # checking the record's shape would have been told it was an older
            # format than it is. The collector's version describes the file; the
            # grader's describes the verdict inside it, and they are versioned
            # independently because they change for different reasons.
            if "schemaVersion" in previous:
                merged["schemaVersion"] = previous["schemaVersion"]
                merged["graderSchemaVersion"] = document.get("schemaVersion")
            document = merged

    rendered = json.dumps(document, indent=1, sort_keys=True)
    if arguments.output == "-":
        print(rendered)
    else:
        destination = Path(arguments.output) if arguments.output else run / "verdict.json"
        destination.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)

    print(verdict.explanation, file=sys.stderr)
    return EXIT_STATUS[verdict.outcome]


if __name__ == "__main__":
    raise SystemExit(main())
