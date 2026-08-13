"""A unit cannot create the directory its own sandbox is built from.

systemd sets up a unit's mount namespace *before* it runs ExecStart. So a
`ReadWritePaths=` naming a path that does not yet exist fails the unit at step
NAMESPACE, and it fails whether or not the program would have created the path
first — the program never runs.

That is not a hypothetical. Measured on the first Bunny installation medium ever
to reach userspace:

    bunny-live-session.service: Failed to set up mount namespacing:
        /run/bunny-installer: No such file or directory
    bunny-live-session.service: Failed at step NAMESPACE spawning
        /usr/libexec/bunny-live-session: No such file or directory
    bunny-live-session.service: Main process exited, code=exited,
        status=226/NAMESPACE

The program it could not spawn begins by creating that very directory. And
bunny-installer-backend.service carried the same fault against /run/bunny-setup,
which nothing in the repository creates at all — invisible only because the unit
it depends on had already failed.

The rule these tests enforce: a unit that wants a path under /run writable must
declare RuntimeDirectory= for it, which systemd creates before the namespace.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "systemd"

# Paths under /run that exist before any Bunny unit starts, because systemd or
# another package owns them. A unit may name these in ReadWritePaths.
PRE_EXISTING_RUN_PATHS = {
    "/run", "/run/systemd", "/run/log", "/run/lock", "/run/user", "/run/udev",
    "/run/dbus", "/run/utmp",
}


def unit_files() -> list[Path]:
    return sorted(UNITS.glob("*.service")) + sorted(UNITS.glob("*.socket"))


def directives(text: str, name: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            values.extend(value.split())
    return values


class RuntimeDirectoryTests(unittest.TestCase):
    def test_every_writable_run_path_is_declared_as_a_runtime_directory(self) -> None:
        offenders: list[str] = []
        for path in unit_files():
            text = path.read_text(encoding="utf-8")
            runtime = {f"/run/{name}" for name in directives(text, "RuntimeDirectory")}
            for wanted in directives(text, "ReadWritePaths"):
                bare = wanted.lstrip("-+!")
                if not bare.startswith("/run/"):
                    continue
                if bare in PRE_EXISTING_RUN_PATHS or wanted.startswith("-"):
                    continue
                # A path *below* a declared runtime directory is created with it.
                if any(bare == entry or bare.startswith(entry + "/") for entry in runtime):
                    continue
                offenders.append(f"{path.name}: ReadWritePaths={wanted}")
        self.assertEqual(
            offenders, [],
            "these units name a /run path in ReadWritePaths without declaring a "
            "RuntimeDirectory for it. systemd builds the mount namespace before "
            "ExecStart, so the unit fails 226/NAMESPACE if the path is absent — "
            "even if its own program would have created it:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_two_units_this_rule_came_from(self) -> None:
        session = (UNITS / "bunny-live-session.service").read_text(encoding="utf-8")
        self.assertIn("bunny-installer", directives(session, "RuntimeDirectory"))
        self.assertNotIn("/run/bunny-installer", directives(session, "ReadWritePaths"))

        backend = (UNITS / "bunny-installer-backend.service").read_text(encoding="utf-8")
        runtime = directives(backend, "RuntimeDirectory")
        self.assertIn("bunny-installer", runtime)
        self.assertIn("bunny-setup", runtime)

    def test_the_session_directory_outlives_the_oneshot_that_makes_it(self) -> None:
        # bunny-live-session.service is Type=oneshot and the backend reads the
        # marker file it leaves behind. Without preservation systemd removes the
        # directory when the unit's processes exit, taking the marker with it.
        session = (UNITS / "bunny-live-session.service").read_text(encoding="utf-8")
        self.assertEqual(directives(session, "RuntimeDirectoryPreserve"), ["yes"])

    def test_the_detector_would_notice_a_regression(self) -> None:
        # The negative control: the rule must fail on the shape it was written
        # for, or it is a test that can only pass.
        broken = "[Service]\nProtectSystem=strict\nReadWritePaths=/run/bunny-new\n"
        runtime = {f"/run/{name}" for name in directives(broken, "RuntimeDirectory")}
        wanted = directives(broken, "ReadWritePaths")[0]
        self.assertNotIn(wanted, runtime)
        self.assertTrue(wanted.startswith("/run/"))
        self.assertNotIn(wanted, PRE_EXISTING_RUN_PATHS)


if __name__ == "__main__":
    unittest.main()
