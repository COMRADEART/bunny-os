# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3 — static tests for the first-login and chronyd corrections.

These assert properties of the shipped source: what the units declare, where
the tmpfiles rule is installed, and that the build wires both in. They are the
half of Stage 3 that can be decided without booting; the behavioural half is
in test_config_dir.py and the evidence half is in the dsq-2 gate.

Each test names the way the correction could be faked and rejects it, rather
than asserting that the fix "is present" — a fix is present in a unit that
also removes ProtectHome=, and that unit is not the fix.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]

# The install set is declared in build/scripts/install_routes.py and both the
# installer and the closure analyser are driven by it. Tests that used to grep
# install-root.py for a call ask the declaration instead: a route is a fact
# about what gets installed, and a substring is a fact about how it is spelled.
if str(ROOT / "build/scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "build/scripts"))


def install_routes():
    from install_routes import INSTALL_ROUTES

    return INSTALL_ROUTES

USER_UNIT_DIR = ROOT / "systemd/user"
FIRST_BOOT = USER_UNIT_DIR / "bunny-first-boot.service"
CONFIG_DIR_UNIT = USER_UNIT_DIR / "bunny-config-dir.service"
TMPFILES_RULE = ROOT / "config/user-tmpfiles/bunny-os.conf"
SYSTEM_TMPFILES = ROOT / "config/tmpfiles/bunny-os.conf"
CHRONYD_DROPIN = ROOT / "systemd/chronyd.service.d/50-bunny-nss-order.conf"
INSTALL_ROOT = ROOT / "build/scripts/install-root.py"
USER_PRESET = ROOT / "config/systemd/60-bunny-os-user.preset"
CI_VERIFY = ROOT / "build/scripts/ci-verify-units.sh"
GUARD_PROGRAM = ROOT / "scripts/bunny-config-dir.py"

#: The directory the first-login flow writes into, relative to the home.
BUNNY_CONFIG = "%h/.config/bunny-os"

#: The only user-tmpfiles.d directory systemd --user actually reads on this
#: base image. /usr/lib/user-tmpfiles.d is not a search path: a rule placed
#: there is never read and the failure is silent. Measured on
#: quay.io/fedora/fedora-bootc:44, systemd 259.
INSTALLED_RULE_PATH = "/usr/share/user-tmpfiles.d/bunny-os.conf"


def directives(unit: Path, name: str) -> list[str]:
    """Every value assigned to `name`, ignoring comments."""
    values = []
    for line in unit.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            values.append(value.strip())
    return values


def one(unit: Path, name: str) -> str:
    values = directives(unit, name)
    if len(values) != 1:
        raise AssertionError(
            f"{unit.name}: expected exactly one {name}=, found {len(values)}")
    return values[0]


def code_of(path: Path) -> str:
    """The file with comments and docstrings stripped.

    These tests assert what a program *does*. A comment explaining why a
    wrong path is wrong contains that wrong path, and a docstring describing
    a call the program deliberately avoids contains the name of the call.
    Matching against raw text makes an accurate explanation look like the
    defect it explains.
    """
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        import io
        import tokenize
        kept = []
        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            previous_type = tokenize.INDENT
            for token in tokens:
                if token.type == tokenize.COMMENT:
                    continue
                # A string that is the whole statement is a docstring.
                if (token.type == tokenize.STRING and
                        previous_type in (tokenize.INDENT, tokenize.NEWLINE,
                                          tokenize.NL, tokenize.DEDENT)):
                    continue
                if token.type not in (tokenize.NL, tokenize.NEWLINE,
                                      tokenize.INDENT, tokenize.DEDENT):
                    previous_type = token.type
                kept.append(token.string)
        except tokenize.TokenError:
            return source
        return "\n".join(kept)
    return "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("#"))


def tmpfiles_lines(rule: Path) -> list[list[str]]:
    lines = []
    for line in rule.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped.split())
    return lines


class TmpfilesRuleTests(unittest.TestCase):
    """Rejections 1, 2 and 5 — the directory must actually be created, by a
    mechanism that reaches an account which already exists."""

    def test_rule_creates_the_bunny_directory(self):
        """1. Bunny directory absent after user tmpfiles execution."""
        paths = {fields[1] for fields in tmpfiles_lines(TMPFILES_RULE)
                 if fields[0] == "d"}
        self.assertIn(BUNNY_CONFIG, paths,
                      "the user-tmpfiles rule does not create the Bunny "
                      "configuration directory, so a fresh home will not have "
                      "it when the sandbox is built")

    def test_rule_covers_every_readwritepath(self):
        """5. ReadWritePaths names a path that remains absent.

        Both entries are inside the home and both are absent on a fresh one.
        Creating only the first still fails namespace setup, and it fails
        identically — with the *other* path named — which is exactly how this
        defect stayed misread as a single-path problem.
        """
        declared = one(FIRST_BOOT, "ReadWritePaths").split()
        created = {fields[1] for fields in tmpfiles_lines(TMPFILES_RULE)
                   if fields[0] == "d"}
        missing = [path for path in declared if path not in created]
        self.assertEqual(missing, [],
                         f"ReadWritePaths names {missing}, which nothing "
                         "creates before the unit starts")

    def test_rule_mode_is_not_world_accessible(self):
        """8. World-readable or world-writable directory accepted."""
        for fields in tmpfiles_lines(TMPFILES_RULE):
            mode = int(fields[2], 8)
            self.assertEqual(mode & 0o077, 0,
                             f"{fields[1]} is created mode {fields[2]}, which "
                             "grants access outside the owning user")

    def test_rule_does_not_hard_code_a_user(self):
        """11. A test user path is hard-coded into the image."""
        for fields in tmpfiles_lines(TMPFILES_RULE):
            path = fields[1]
            self.assertTrue(
                path.startswith("%h/"),
                f"{path} is not anchored on the %h specifier, so it names one "
                "particular home rather than the home of whoever logs in")
            owner, group = fields[3], fields[4]
            self.assertEqual((owner, group), ("-", "-"),
                             f"{path} names owner {owner}:{group} instead of "
                             "deferring to the invoking user")

    def test_rule_is_installed_to_a_path_systemd_reads(self):
        """A rule in /usr/lib/user-tmpfiles.d is never read, and nothing
        reports that it was skipped."""
        destinations = {route.destination for route in install_routes()}
        if INSTALLED_RULE_PATH not in destinations:
            self.fail("build/scripts/install_routes.py declares no route that "
                      f"installs the per-user tmpfiles rule to {INSTALLED_RULE_PATH}, "
                      "the only user-tmpfiles.d directory systemd --user reads "
                      "on this base image")
        # The wrong directory is named in a diagnostic message on purpose, and
        # a message is not an installation — so this asks the route table rather
        # than searching the installer's text for the string.
        wrong = [item for item in destinations if item.startswith("/usr/lib/user-tmpfiles.d/")]
        if wrong:
            self.fail(f"a declared route installs {wrong} under "
                      "/usr/lib/user-tmpfiles.d/, which is not in the --user "
                      "search path; a rule placed there is never read and "
                      "nothing reports that it was skipped")

    def test_correction_is_not_only_skel(self):
        """2. Directory created only through /etc/skel.

        /etc/skel is copied when an account is created, so it cannot repair an
        existing account that lacks the directory — one of the cases the
        correction is required to handle.
        """
        self.assertNotIn("/etc/skel", code_of(INSTALL_ROOT),
                         "the build populates /etc/skel; a skel-only "
                         "correction leaves every existing account broken")


class FirstBootUnitTests(unittest.TestCase):
    """Rejections 3, 4 and 16 — the sandbox must still be a sandbox, and the
    ordering must be a real dependency."""

    def test_protecthome_is_still_read_only(self):
        """3. Service succeeds only because ProtectHome was removed."""
        self.assertEqual(one(FIRST_BOOT, "ProtectHome"), "read-only",
                         "ProtectHome=read-only is the constraint this "
                         "correction had to work within; a unit that drops it "
                         "has removed the protection rather than fixed the "
                         "defect")

    def test_readwritepaths_stays_narrow(self):
        """4. Service writes to all of %h."""
        declared = one(FIRST_BOOT, "ReadWritePaths").split()
        forbidden = {"%h", "%h/", "%h/.config", "%h/.config/", "/home", "~"}
        for path in declared:
            self.assertNotIn(
                path, forbidden,
                f"ReadWritePaths grants {path}, which is broader than the "
                "directories this service owns")
            self.assertTrue(
                path.startswith(BUNNY_CONFIG) or
                path.startswith("%h/.config/systemd/user"),
                f"ReadWritePaths grants {path}, which is outside the "
                "directories this service is entitled to write")

    def test_depends_on_the_directory_unit(self):
        """16. After= added without proving the dependency is scheduled.

        After= alone orders two units *if* both are already in the
        transaction; it never puts one there. The directory unit must be
        pulled in as well as ordered, or a boot that does not happen to
        include it is ordered against nothing.
        """
        after = " ".join(directives(FIRST_BOOT, "After")).split()
        self.assertIn("bunny-config-dir.service", after,
                      "bunny-first-boot is not ordered after the unit that "
                      "establishes its writable paths")
        pulling = (directives(FIRST_BOOT, "Requires") +
                   directives(FIRST_BOOT, "Wants") +
                   directives(FIRST_BOOT, "BindsTo"))
        self.assertTrue(
            any("bunny-config-dir.service" in value for value in pulling),
            "bunny-first-boot orders itself after bunny-config-dir.service "
            "but nothing pulls that unit into the transaction, so the "
            "ordering can be satisfied vacuously")

    def test_config_home_agrees_with_the_sandbox(self):
        """The program resolves XDG_CONFIG_HOME; the sandbox cannot. If they
        disagree the program writes outside its own writable path."""
        environment = directives(FIRST_BOOT, "Environment")
        pinned = [value for value in environment
                  if value.startswith("XDG_CONFIG_HOME=")]
        self.assertEqual(
            len(pinned), 1,
            "the unit does not pin XDG_CONFIG_HOME, so a user who sets it "
            "elsewhere has bunny-first-boot write outside ReadWritePaths")
        self.assertEqual(pinned[0], "XDG_CONFIG_HOME=%h/.config")

    def test_still_activated(self):
        self.assertIn("graphical-session.target",
                      directives(FIRST_BOOT, "WantedBy"))
        self.assertIn("enable bunny-first-boot.service",
                      USER_PRESET.read_text(encoding="utf-8"))


class ConfigDirUnitTests(unittest.TestCase):
    """The guard must not reintroduce the failure it exists to prevent."""

    def test_no_path_dependent_sandbox_directives(self):
        """A ReadWritePaths= or ProtectHome= on this unit would move the
        226/NAMESPACE failure one unit earlier, where nothing is left to
        report it."""
        for directive in ("ReadWritePaths", "ProtectHome", "BindPaths",
                          "BindReadOnlyPaths", "WorkingDirectory",
                          "RootDirectory", "StateDirectory"):
            self.assertEqual(
                directives(CONFIG_DIR_UNIT, directive), [],
                f"bunny-config-dir.service declares {directive}=, whose "
                "evaluation depends on a path in the home existing — the "
                "condition this unit exists to establish")

    def test_ordered_before_first_boot_and_after_tmpfiles(self):
        self.assertIn("bunny-first-boot.service",
                      " ".join(directives(CONFIG_DIR_UNIT, "Before")).split())
        after = " ".join(directives(CONFIG_DIR_UNIT, "After")).split()
        wants = " ".join(directives(CONFIG_DIR_UNIT, "Wants")).split()
        self.assertIn("systemd-tmpfiles-setup.service", after)
        self.assertIn(
            "systemd-tmpfiles-setup.service", wants,
            "the tmpfiles unit is pulled in by basic.target with Wants=, so "
            "its presence depends on a preset this image does not own; state "
            "the requirement here instead of inheriting it")

    def test_retains_the_hardening_that_does_not_depend_on_paths(self):
        for directive, expected in (("NoNewPrivileges", "yes"),
                                    ("ProtectSystem", "strict"),
                                    ("RestrictNamespaces", "yes"),
                                    ("MemoryDenyWriteExecute", "yes"),
                                    ("LockPersonality", "yes")):
            self.assertEqual(one(CONFIG_DIR_UNIT, directive), expected)

    def test_is_installed_and_enabled(self):
        install = INSTALL_ROOT.read_text(encoding="utf-8")
        self.assertIn("bunny-config-dir", install)
        self.assertIn("enable bunny-config-dir.service",
                      USER_PRESET.read_text(encoding="utf-8"))
        self.assertIn(
            "graphical-session.target.wants/bunny-config-dir.service", install,
            "the build does not assert the guard's enablement symlink exists; "
            "systemctl enable succeeding is a statement about a command, not "
            "about the artifact")

    def test_ci_verifies_the_new_unit_and_drop_ins(self):
        ci = CI_VERIFY.read_text(encoding="utf-8")
        self.assertIn("bunny-config-dir", ci,
                      "ci-verify-units.sh installs unit programs by an "
                      "explicit list; a unit missing from it is verified "
                      "against a program that is not there")
        self.assertIn("service.d", ci,
                      "ci-verify-units.sh copies units by glob and would "
                      "silently skip the chronyd drop-in directory")


class ChronydOrderingTests(unittest.TestCase):
    """Rejections 14, 16 and 17 — ordering that is real, scheduled, and
    acyclic."""

    def test_ordered_after_identity_is_resolvable(self):
        """14. Chronyd starts before authselect completes."""
        after = " ".join(directives(CHRONYD_DROPIN, "After")).split()
        self.assertIn("nss-user-lookup.target", after)
        self.assertIn(
            "authselect-apply-changes.service", after,
            "the measured window is authselect's; the target alone is the "
            "contract, and the record should name both")

    def test_the_passive_target_is_pulled_in(self):
        """16. After= added without proving the dependency is scheduled.

        nss-user-lookup.target is passive: nothing pulls it into the boot
        transaction on its own, and an After= on a unit that is not in the
        transaction orders nothing at all.
        """
        wants = " ".join(directives(CHRONYD_DROPIN, "Wants")).split()
        self.assertIn(
            "nss-user-lookup.target", wants,
            "chronyd is ordered after a passive target that nothing pulls "
            "into the transaction, so the ordering is vacuous")

    def test_does_not_require_authselect(self):
        """18-adjacent: do not delay chronyd indefinitely where authselect is
        not applicable. Requires= on a unit with
        ConditionPathIsReadWrite=/etc would fail chronyd on a read-only /etc
        rather than let it start."""
        for directive in ("Requires", "BindsTo", "Requisite"):
            values = " ".join(directives(CHRONYD_DROPIN, directive)).split()
            self.assertNotIn(
                "authselect-apply-changes.service", values,
                f"{directive}=authselect-apply-changes.service makes chronyd "
                "fail wherever authselect does not apply")

    def test_introduces_no_cycle(self):
        """17. Ordering change creates a systemd cycle.

        A cycle needs the ordered-after units to reach back to chronyd. The
        drop-in adds edges out of chronyd only; assert it adds no Before= that
        could close a loop through the units it orders after.
        """
        before = " ".join(directives(CHRONYD_DROPIN, "Before")).split()
        self.assertEqual(
            before, [],
            "the drop-in adds Before= edges as well as After=, which is how "
            "an ordering change closes a cycle")

    def test_drop_in_lands_in_the_image(self):
        """The drop-in directory reaches /usr/lib/systemd/system, by a route.

        Asked of the shared install declaration and of the predicate that
        selects files, so it answers about *this* drop-in rather than about the
        continued existence of a line of code that might install something else.
        """
        from install_routes import installed_destination

        relative = CHRONYD_DROPIN.relative_to(ROOT).as_posix()
        landed = [
            installed_destination(route, relative) for route in install_routes()
        ]
        landed = [item for item in landed if item is not None]
        self.assertEqual(
            landed, [f"/usr/lib/systemd/system/{relative[len('systemd/'):]}"],
            "no declared install route carries the chronyd drop-in into the image",
        )


class GuardProgramSourceTests(unittest.TestCase):
    """Rejections 6, 7 and 10, asserted against the program's source so that a
    correction which deletes a refusal is caught even if no test drives it."""

    def test_refuses_rather_than_follows_or_replaces(self):
        source = code_of(GUARD_PROGRAM)
        self.assertIn("O_NOFOLLOW", source,
                      "the guard opens the directory without O_NOFOLLOW, so a "
                      "symlink swapped in after the check is followed")
        self.assertIn("S_ISLNK", source)
        self.assertIn("st_uid", source)

    def test_never_recurses_or_deletes(self):
        """Asserted against the executable tokens: the module docstring
        explains that tmpfiles cannot chown, and matching raw text would read
        that explanation as the defect."""
        source = code_of(GUARD_PROGRAM)
        for forbidden in ("rmtree", "removedirs", "chown", "walk",
                          "unlink", "rmdir"):
            if forbidden in source:
                self.fail(f"scripts/bunny-config-dir.py calls {forbidden}, "
                          "which either takes ownership of or destroys user "
                          "data it does not own")

    def test_named_paths_match_the_unit(self):
        """10. User A receives ownership belonging to user B — the guard must
        derive its paths from the caller's own home, never a literal."""
        source = code_of(GUARD_PROGRAM)
        self.assertNotRegex(
            source, re.compile(r"/home/[a-z]"),
            "the guard names a literal home directory")
        declared = one(FIRST_BOOT, "ReadWritePaths").split()
        for path in declared:
            relative = path.replace("%h/", "")
            self.assertIn(
                f'"{relative}"', source,
                f"the unit sandboxes {path} but the guard does not verify it")


if __name__ == "__main__":
    unittest.main()
