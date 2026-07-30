# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny OS privileged broker.

The package deliberately uses only the Python standard library.  OS authority
is represented by a finite method table in protocol.py and fixed backends in
backend.py; no caller-supplied command is ever executed.
"""

CONTRACT_VERSION = "1.0.0"
BROKER_VERSION = "0.1.0"
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024

