#!/usr/bin/python3
"""Launch only a manifest-verified Bunny deployment, or explain the placeholder."""

import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    try:
        manifest = json.loads(Path("/usr/share/bunny-os/bunny-artifact.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    executable = Path("/opt/bunny/current/bunny-desktop")
    if manifest.get("status") == "verified" and executable.is_file() and os.access(executable, os.X_OK):
        os.execv(str(executable), [str(executable), *sys.argv[1:]])
    message = "This Phase 1 developer image contains an explicit Bunny 0.2.0 package placeholder. Supply and verify a signed upstream Linux release artifact before Bunny Desktop can run."
    if Path("/usr/bin/zenity").exists():
        subprocess.run(["/usr/bin/zenity", "--warning", "--title=Bunny artifact unavailable", f"--text={message}"], check=False)
    else:
        print(message, file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

