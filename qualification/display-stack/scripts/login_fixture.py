#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 7 — the qualification-only login fixture.

The product image ships with no account and no default credential, and must
keep shipping that way. But the first-login defect this pass corrects can only
be observed by actually logging in: bunny-config-dir.service and
bunny-first-boot.service are user units that never run without a user session.

So the account is injected, per run, into the run's own copy-on-write overlay.
Nothing here touches the source disk, the archive, or the repository:

  * one account, created in the overlay's ostree deployment /etc;
  * a random password generated for this run and never written down — not to
    the record, not to the repository, not to the log;
  * GDM automatic login, so the session starts without a credential crossing
    the serial console or a screenshot;
  * a genuinely empty home, because a home that already contained
    ~/.config/bunny-os would test nothing.

The overlay is discarded when the run ends, which is what expires the
credential. Every record this fixture touches is stamped so that no reader can
mistake the account for product behaviour.

Injecting into the deployment's /etc is deliberate. A bootc system's /etc is
per-deployment and writable, so an account added there behaves like one added
on the running system; adding it to /usr/lib/passwd would change the immutable
base and make the fixture a change to the artifact under test.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import subprocess

#: Never a name a product image would plausibly carry, so that an account
#: leaking into an artifact is obvious on sight rather than plausible.
TEST_USER = "dsq-test"
TEST_UID = 4242
TEST_GID = 4242
TEST_GECOS = "dsq-2 qualification fixture account (test-injected)"

#: Stamped into every record that used the fixture.
PROVENANCE = {
    "account": TEST_USER,
    "uid": TEST_UID,
    "testInjected": True,
    "partOfBunnyArtifact": False,
    "injectedInto": "per-run copy-on-write overlay",
    "sourceDiskModified": False,
    "credential": "random per run, not retained, not recorded, not printed",
    "expiry": "the overlay is destroyed when the run ends",
    "note": ("The Bunny OS image ships no account and no default credential. "
             "This account exists only inside one qualification run's "
             "writable overlay and is not product behaviour."),
}


class FixtureError(Exception):
    pass


def _guestfish(overlay: Path, root: str, *commands: str) -> str:
    argv = ["guestfish", "-a", str(overlay), "run", ":", "mount", root, "/"]
    for command in commands:
        argv += [":", *command.split("\x00")]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise FixtureError(f"guestfish failed: {result.stderr.strip()[:400]}")
    return result.stdout


def _read(overlay: Path, root: str, path: str) -> str:
    result = subprocess.run(
        ["guestfish", "--ro", "-a", str(overlay), "run", ":",
         "mount-ro", root, "/", ":", "cat", path],
        capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise FixtureError(f"cannot read {path}: {result.stderr.strip()[:300]}")
    return result.stdout


def _hash_password(password: str) -> str:
    """A yescrypt/SHA-512 crypt string for the guest's shadow file.

    Generated on the host with the guest's own algorithm rather than by
    running a program inside the image, so the fixture needs no boot to
    install a credential it is about to throw away.
    """
    import crypt  # deprecated in 3.13 but present on the builder
    salt = crypt.mksalt(crypt.METHOD_SHA512)
    return crypt.crypt(password, salt)


def inject(overlay: Path, root: str, deploy: str,
           second_login: bool = False) -> dict:
    """Create the test account in one run's overlay. Returns provenance.

    `deploy` is the ostree deployment root inside the guest, e.g.
    /ostree/deploy/default/deploy/<checksum>.0 — the same path the dsq-1
    diagnostic drop-in used.
    """
    etc = f"{deploy}/etc"
    password = secrets.token_urlsafe(24)
    hashed = _hash_password(password)
    del password  # never leaves this function

    passwd = _read(overlay, root, f"{etc}/passwd")
    group = _read(overlay, root, f"{etc}/group")
    shadow = _read(overlay, root, f"{etc}/shadow")

    for name, text in (("passwd", passwd), ("group", group)):
        if re.search(rf"^{TEST_USER}:", text, re.MULTILINE):
            raise FixtureError(
                f"{TEST_USER} already present in {name}; the source disk must "
                "ship no test account, and an overlay is used once")

    # /var/home, because a bootc system keeps /home a symlink into /var.
    home = f"/var/home/{TEST_USER}"
    passwd_line = (f"{TEST_USER}:x:{TEST_UID}:{TEST_GID}:{TEST_GECOS}:"
                   f"{home}:/bin/bash")
    group_line = f"{TEST_USER}:x:{TEST_GID}:"
    # Last-changed day 20000 with no ageing: an expiring credential would make
    # a run fail for a reason unrelated to what it measures.
    shadow_line = f"{TEST_USER}:{hashed}:20000:0:99999:7:::"

    commands = [
        f"write\x00{etc}/passwd\x00{passwd.rstrip(chr(10))}\n{passwd_line}\n",
        f"write\x00{etc}/group\x00{group.rstrip(chr(10))}\n{group_line}\n",
        f"write\x00{etc}/shadow\x00{shadow.rstrip(chr(10))}\n{shadow_line}\n",
        f"chmod\x000600\x00{etc}/shadow",
    ]

    # The home is created empty and owned by the account. Empty is the point:
    # the correction has to produce ~/.config/bunny-os on a home that has
    # nothing in it, and a home seeded from /etc/skel or from a previous run
    # would hide exactly the failure this pass exists to close.
    commands += [
        f"mkdir-p\x00{home}",
        f"chown\x00{TEST_UID}\x00{TEST_GID}\x00{home}",
        f"chmod\x000700\x00{home}",
    ]

    # GDM automatic login. This is what makes the session start without a
    # password crossing the serial log or a screenshot.
    gdm_conf = (
        "# dsq-2 qualification fixture — test-injected, not product config.\n"
        "[daemon]\n"
        "AutomaticLoginEnable=true\n"
        f"AutomaticLogin={TEST_USER}\n"
    )
    if second_login:
        # A second login must be a second *session*, not a resumed one. With
        # automatic login the clean way to get one is a reboot, so the second
        # boot keeps the same configuration and the run drives the reboot.
        gdm_conf += "# second-login run: the harness reboots to log in again\n"
    commands += [
        f"mkdir-p\x00{etc}/gdm",
        f"write\x00{etc}/gdm/custom.conf\x00{gdm_conf}",
    ]

    _guestfish(overlay, root, *commands)

    provenance = dict(PROVENANCE)
    provenance["home"] = home
    provenance["automaticLogin"] = True
    provenance["secondLoginPlanned"] = second_login
    provenance["injectedPaths"] = [f"{etc}/passwd", f"{etc}/group",
                                   f"{etc}/shadow", f"{etc}/gdm/custom.conf",
                                   home]
    return provenance


def verify_absent_from_artifact(source_disk: Path, root: str,
                                deploy: str) -> list[str]:
    """The fixture is only honest if the artifact it runs against has no such
    account. Checked against the source disk, before any overlay exists."""
    problems = []
    for path in (f"{deploy}/etc/passwd", f"{deploy}/etc/shadow",
                 "/usr/lib/passwd"):
        try:
            text = _read(source_disk, root, path)
        except FixtureError:
            continue
        if re.search(rf"^{TEST_USER}:", text, re.MULTILINE):
            problems.append(
                f"{path} in the source artifact contains {TEST_USER}: the "
                "fixture account has leaked into the image under test")
    try:
        gdm = _read(source_disk, root, f"{deploy}/etc/gdm/custom.conf")
    except FixtureError:
        gdm = ""
    if "AutomaticLoginEnable=true" in gdm:
        problems.append(
            "the source artifact enables GDM automatic login; that is fixture "
            "configuration and must not ship")
    return problems


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-provenance", action="store_true")
    args = parser.parse_args()
    if args.print_provenance:
        print(json.dumps(PROVENANCE, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
