# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chrome flags for **host demo screenshots only**.

``--no-sandbox`` is required in some CI/cloud containers where the agent
cannot create a user namespace. It is a development-host compromise.

Do **not** copy these flags into Bunny Shell, the Companion window, a
desktop file, or any product browser launcher. A test greps those trees
and fails if ``--no-sandbox`` appears outside ``demos/``.
"""

from __future__ import annotations

# DEMO-ONLY. Never import this name from product browser launchers.
DEMO_ONLY_CHROME_NO_SANDBOX = "--no-sandbox"

DEMO_ONLY_CHROME_FLAGS = (
    DEMO_ONLY_CHROME_NO_SANDBOX,
    "--disable-gpu",
    "--disable-extensions",
    "--disable-component-update",
    "--disable-background-networking",
    "--no-first-run",
    "--no-default-browser-check",
    "--guest",
)
