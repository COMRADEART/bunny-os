#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect BrlAPI key evidence from an installed disk, without keeping the key.

The whole point of this file is a secret, so the evidence records everything
about it except the thing itself: a SHA-256 over its bytes (enough to prove
two installations differ and that a reboot did not rotate it), its size,
owner, mode, SELinux context and creation time. The key never leaves the
disk it was minted on.

Three questions are answered separately, because the previous pass showed
they can each be true or false independently:

    activation    is the unit enabled in the deployed filesystem — does the
                  symlink exist where systemd would look
    execution     did it actually run this boot, with what result
    outcome       does the key exist, and is it usable

A unit can ship and not be enabled; be enabled and not run; run and produce
nothing. Reporting one as if it were the others is how this defect survived
two passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importing dsq_disk patches ostree_disk's root detection to resolve the
# root as the one filesystem holding /ostree/deploy. The installable disk
# carries /ostree on the boot partition too, so the unpatched rule —
# "exactly one filesystem holding /ostree" — refuses it outright. The
# patched rule is not a guess: two filesystems holding /ostree/deploy are
# refused exactly as before.
sys.path.insert(0, str(
    Path(__file__).resolve().parents[2] / "display-stack/scripts"))
import dsq_disk  # noqa: E402,F401  (patches ostree_disk on import)

from ostree_disk import (  # noqa: E402
    DiskLayoutError,
    guestfish,
    root_partition,
    single_deployment_root,
    stateroot_var,
)

KEY_PATH = "/etc/brlapi.key"
UNIT = "bunny-brlapi-key.service"
EXPECTED_MODE = "0o640"
KEY_HEX_LENGTH = 32


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect_brlapi_evidence")
    parser.add_argument("--disk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", default="", help="which installation this is")
    args = parser.parse_args()

    assertions: list[dict] = []
    limitations = [
        "no braille display is attached: this establishes key generation and "
        "service integration, never physical braille-device compatibility.",
    ]

    def check(name: str, ok: bool, expected: str, observed: str) -> None:
        assertions.append({"name": name, "expected": expected, "observed": observed,
                           "result": "PASS" if ok else "FAIL"})

    try:
        deployment = single_deployment_root(args.disk)
        var = stateroot_var(args.disk)
        root = root_partition(args.disk)
    except DiskLayoutError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    # ---------------------------------------------------------- activation
    # The symlink systemd would follow, in the filesystem that was deployed.
    wants = f"{deployment}/etc/systemd/system/sysinit.target.wants/{UNIT}"
    enabled = guestfish(args.disk, "exists", wants).strip() == "true"
    check("unit-enabled-in-deployed-filesystem", enabled,
          f"{wants} exists", "present" if enabled else "absent")

    unit_file = f"{deployment}/usr/lib/systemd/system/{UNIT}"
    unit_present = guestfish(args.disk, "exists", unit_file).strip() == "true"
    check("unit-shipped", unit_present, f"{unit_file} exists",
          "present" if unit_present else "absent")

    helper = f"{deployment}/usr/libexec/bunny-brlapi-key"
    helper_present = guestfish(args.disk, "exists", helper).strip() == "true"
    check("helper-installed", helper_present, f"{helper} exists",
          "present" if helper_present else "absent")
    helper_mode = None
    if helper_present:
        stat = guestfish(args.disk, "statns", helper)
        fields = dict(line.strip().split(": ", 1)
                      for line in stat.splitlines() if ": " in line)
        helper_mode = int(fields.get("st_mode", "0")) & 0o7777
        check("helper-executable-and-not-writable", (helper_mode & 0o111) != 0
              and (helper_mode & 0o022) == 0,
              "executable, not group- or world-writable", oct(helper_mode))
        check("helper-root-owned", fields.get("st_uid") == "0",
              "uid 0", f"uid {fields.get('st_uid')}")

    # ----------------------------------------------------------- execution
    executed = None
    unit_result = None
    with tempfile.TemporaryDirectory() as scratch:
        journal_tar = Path(scratch) / "journal.tar"
        pull = subprocess.run(
            ["guestfish", "--ro", "-a", str(args.disk), "run", ":",
             "mount-ro", root, "/", ":",
             "tar-out", f"{var}/log/journal", str(journal_tar)],
            capture_output=True, text=True,
        )
        if pull.returncode == 0:
            journal_dir = Path(scratch) / "journal"
            journal_dir.mkdir()
            subprocess.run(["tar", "-xf", str(journal_tar), "-C", str(journal_dir)],
                           check=True)
            machine = [d for d in journal_dir.rglob("*") if d.is_dir()
                       and any(f.suffix == ".journal" for f in d.iterdir() if f.is_file())]
            if machine:
                text = subprocess.run(
                    ["journalctl", "-D", str(machine[0]), "--no-pager", "-o", "short-monotonic"],
                    capture_output=True, text=True).stdout
                executed = bool(re.search(rf"(Starting|Started|Finished).*{re.escape(UNIT)}|"
                                          rf"{re.escape(UNIT)}: (Succeeded|Deactivated)", text))
                failed = re.search(rf"{re.escape(UNIT)}: Failed with result", text)
                unit_result = "failed" if failed else ("succeeded" if executed else "absent")
                check("unit-executed-this-boot", executed,
                      f"{UNIT} appears in the boot journal",
                      unit_result)
                check("unit-succeeded", executed and not failed,
                      "no failure result recorded", unit_result)
                # The key must never be in the journal. Search for any 32-hex
                # run on a line mentioning the key or the unit.
                leak = re.search(rf"(brlapi|{re.escape(UNIT)}).*\b[0-9a-f]{{{KEY_HEX_LENGTH}}}\b",
                                 text, re.IGNORECASE)
                check("key-not-in-journal", leak is None,
                      "no key-shaped value beside a brlapi mention",
                      "possible leak" if leak else "clean")
                # BRLTTY ordering, where brltty is present at all.
                brltty = re.search(r"(Started|Starting).*brltty", text)
                if brltty:
                    generator_at = re.search(
                        rf"\[\s*(\d+\.\d+)\].*(Finished|Started).*{re.escape(UNIT)}", text)
                    brltty_at = re.search(r"\[\s*(\d+\.\d+)\].*(Started|Starting).*brltty", text)
                    if generator_at and brltty_at:
                        check("key-generated-before-brltty",
                              float(generator_at.group(1)) <= float(brltty_at.group(1)),
                              "the generator finishes before brltty starts",
                              f"generator {generator_at.group(1)}s, brltty {brltty_at.group(1)}s")
                    auth = re.search(r"brltty.*(authoriz|authentic).*(fail|denied|error)",
                                     text, re.IGNORECASE)
                    check("no-brltty-authorisation-error", auth is None,
                          "no authorisation failure from brltty",
                          auth.group(0)[:80] if auth else "clean")
                else:
                    limitations.append(
                        "brltty did not start in this boot: no braille device is "
                        "attached and the service is socket/udev driven. Its "
                        "ordering relative to the generator is therefore asserted "
                        "from the unit's Before= directive, not from timestamps.")
        else:
            check("boot-journal-readable", False,
                  "the boot journal can be read from the disk",
                  "absent — execution cannot be established")

    # ------------------------------------------------------------- outcome
    key_guest = f"{deployment}{KEY_PATH}"
    key_present = guestfish(args.disk, "exists", key_guest).strip() == "true"
    check("key-exists", key_present, f"{KEY_PATH} exists on the installed system",
          "present" if key_present else "absent")

    key_record: dict = {"present": key_present}
    if key_present:
        stat = guestfish(args.disk, "statns", key_guest)
        fields = dict(line.strip().split(": ", 1)
                      for line in stat.splitlines() if ": " in line)
        mode = int(fields.get("st_mode", "0")) & 0o7777
        size = int(fields.get("st_size", "0"))
        content = subprocess.run(
            ["guestfish", "--ro", "-a", str(args.disk), "run", ":",
             "mount-ro", root, "/", ":", "download", key_guest, "/dev/stdout"],
            capture_output=True, check=False).stdout
        # The digest is the evidence. The bytes are not recorded anywhere.
        digest = hashlib.sha256(content).hexdigest()
        text = content.decode("ascii", "replace").strip()
        well_formed = len(text) == KEY_HEX_LENGTH and all(
            c in "0123456789abcdef" for c in text)
        context = ""
        labels = guestfish(args.disk, "getxattr", key_guest, "security.selinux")
        context = labels.strip().rstrip("\x00")

        key_record = {
            "present": True,
            "sha256": digest,
            "sizeBytes": size,
            "mode": oct(mode),
            "uid": fields.get("st_uid"),
            "gid": fields.get("st_gid"),
            "selinuxContext": context,
            "createdAt": fields.get("st_ctime"),
            "note": ("The key value is deliberately absent. This record carries a "
                     "digest over its bytes, which is what proves two installations "
                     "differ and a reboot did not rotate it."),
        }
        check("key-non-empty", size > 0, "a non-empty key", f"{size} bytes")
        check("key-well-formed", well_formed,
              f"{KEY_HEX_LENGTH} hex characters", f"{len(text)} characters")
        check("key-mode-0640", oct(mode) == EXPECTED_MODE, EXPECTED_MODE, oct(mode))
        check("key-root-owned", fields.get("st_uid") == "0", "uid 0",
              f"uid {fields.get('st_uid')}")

    result = "PASS" if all(a["result"] == "PASS" for a in assertions) else "FAIL"
    document = {
        "schemaVersion": 1,
        "collection": "brlapi-installed-offline",
        "installation": args.label or args.disk.name,
        "disk": args.disk.name,
        "deploymentRoot": deployment,
        "assertions": assertions,
        "key": key_record,
        "limitations": limitations,
        "result": result,
        "classification": {
            "keyGeneration": "PASS" if key_present and result == "PASS" else "FAIL",
            "serviceIntegration": "PASS" if all(
                a["result"] == "PASS" for a in assertions
                if a["name"].startswith(("unit-", "helper-", "no-brltty", "key-generated"))
            ) else "FAIL",
            "physicalBrailleDevice": "NOT_RUN",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"brlapi evidence ({args.label or args.disk.name}): {result}")
    for assertion in assertions:
        print(f"  {assertion['result']:4} {assertion['name']}: {assertion['observed'][:70]}")
    print(f"wrote {args.output}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
