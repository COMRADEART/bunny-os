#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import sys

system = Path("/usr/lib/bunny-os/python")
sys.path.insert(0, str(system if system.exists() else Path(__file__).resolve().parents[2]))

from companion.cli import main

raise SystemExit(main("bunny-companion-service"))
