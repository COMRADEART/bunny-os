# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The companion store root is one path, named one way, in two places.

The defect these tests pin: the runtime unit's ``StateDirectory=bunny-companion``
made systemd set ``$STATE_DIRECTORY`` to ``~/.local/state/bunny-companion`` --
which the service's ``_state_root`` reads as its first non-override branch --
while the supported CLI's ``default_root`` wrote ``~/.local/state/bunny-os/companion``.
Both honour ``BUNNY_COMPANION_ROOT`` first, so the two diverged only on the
default, which is the only path the supported settings surface uses. Settings
written through ``bunny-os companion settings set`` therefore never reached the
service, and an ordinary question was answered by the deterministic executor
with a canned sentence even when a healthy, preferred local provider was
configured and saw the real model.

The fix aligns the unit's ``StateDirectory`` with the code's ``bunny-os/companion``
convention. The socket directory (``RuntimeDirectory=bunny-companion`` under
``$XDG_RUNTIME_DIR``) is a different name on purpose -- it matches the runtime
socket path the schema and the window unit connect to -- and must not move.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "systemd" / "user"
SUFFIX = Path("bunny-os") / "companion"


def _directives(text: str, name: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            values.append(value.strip())
    return values


class CompanionStateRootAlignment(unittest.TestCase):
    def test_the_unit_state_directory_matches_the_cli_default_suffix(self):
        from companion.cli import default_root

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUNNY_COMPANION_ROOT", None)
            os.environ.pop("XDG_STATE_HOME", None)
            cli_root = default_root()
        # default_root() is <state base>/bunny-os/companion under no override;
        # the last two segments are the suffix the unit must reproduce.
        self.assertEqual(Path(*cli_root.parts[-2:]), SUFFIX,
                         "default_root() must end in bunny-os/companion")
        for unit in ("bunny-companion.service", "bunny-companion-window.service"):
            text = (UNITS / unit).read_text(encoding="utf-8")
            # StateDirectory is a systemd (POSIX) unit directive; compare against
            # the POSIX form so the assertion is stable on non-Linux dev hosts
            # (on Linux as_posix() == str(), so nothing about the target changes).
            self.assertEqual(
                _directives(text, "StateDirectory"), [SUFFIX.as_posix()],
                f"{unit} StateDirectory must align with the CLI default root",
            )

    def test_the_socket_runtime_directory_stays_bunny_companion(self):
        # RuntimeDirectory is the socket dir ($XDG_RUNTIME_DIR/bunny-companion),
        # which the schema and the window unit address; it is NOT the state root
        # and must not follow the StateDirectory rename.
        text = (UNITS / "bunny-companion.service").read_text(encoding="utf-8")
        self.assertEqual(
            _directives(text, "RuntimeDirectory"), ["bunny-companion"],
            "RuntimeDirectory is the socket directory; it is not the state root",
        )


if __name__ == "__main__":
    unittest.main()