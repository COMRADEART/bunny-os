# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The BrlAPI per-device key: the twenty ways it can fail to reach a device.

The defect this suite encodes was measured, not reviewed into existence. The
unit shipped, finalisation removed ``/etc/brlapi.key`` from the image, and
nothing installed the program the unit's ``ExecStart`` named or enabled the
unit that would have run it — so an installed system booted with no BrlAPI
authorisation key at all, and a braille display that is unauthorised is, to the
person at the machine, a braille display that is broken.

Two halves, deliberately:

* the **static** half parses the generator source, the unit, the preset, the
  install script and the finaliser as text. It runs on every platform, needs
  no Linux, no root and no boot, and it is where the shipping-and-enablement
  defect is actually catchable.
* the **runtime** half executes ``scripts/bunny-brlapi-key.py`` as a
  subprocess. The generator imports ``grp``, which does not exist on Windows,
  so these skip there with a stated reason rather than being weakened into
  something that passes everywhere by testing nothing.

Where a case genuinely needs a booted system, the test asserts the
source-level guarantee that makes the case true and says, in a comment, what
remains unverifiable offline. No case is silently dropped.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

GENERATOR_PATH = ROOT / "scripts/bunny-brlapi-key.py"
UNIT_PATH = ROOT / "systemd/bunny-brlapi-key.service"
PRESET_PATH = ROOT / "config/systemd/60-bunny-os.preset"
INSTALL_ROOT_PATH = ROOT / "build/scripts/install-root.py"
FINALISE_PATH = ROOT / "build/scripts/finalise-image.sh"

UNIT_NAME = "bunny-brlapi-key.service"
PROGRAM_NAME = "bunny-brlapi-key"
INSTALLED_PROGRAM = "/usr/libexec/bunny-brlapi-key"
KEY_PATH = "/etc/brlapi.key"

GENERATOR_SOURCE = GENERATOR_PATH.read_text(encoding="utf-8")
UNIT_SOURCE = UNIT_PATH.read_text(encoding="utf-8")
PRESET_SOURCE = PRESET_PATH.read_text(encoding="utf-8")
INSTALL_ROOT_SOURCE = INSTALL_ROOT_PATH.read_text(encoding="utf-8")
FINALISE_SOURCE = FINALISE_PATH.read_text(encoding="utf-8")

# The install set is declared as data in build/scripts/install_routes.py, and
# both install-root.py and build-input-closure.py are driven by it. That module
# is pure standard library and imports cleanly on any platform, so the three
# installation facts below are asserted against the declaration rather than
# against the shape of a call inside a Linux-only script.
if str(ROOT / "build/scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "build/scripts"))


def install_route_declaration():
    import install_routes

    return install_routes


def installed_program_route():
    """The single declared route that installs the key generator."""
    declaration = install_route_declaration()
    matches = [
        route for route in declaration.INSTALL_ROUTES
        if route.source == f"scripts/{PROGRAM_NAME}.py"
    ]
    assert len(matches) == 1, f"expected one install route for {PROGRAM_NAME}, found {matches}"
    return matches[0]

#: The install script and the generator are Linux-only modules — ``grp`` and
#: absolute ``/usr`` paths — so they are parsed, never imported. A test that
#: could only run on the target platform could not have caught a packaging
#: defect on a developer's machine, and this one was a packaging defect.
GENERATOR_TREE = ast.parse(GENERATOR_SOURCE)
INSTALL_ROOT_TREE = ast.parse(INSTALL_ROOT_SOURCE)

#: A group that certainly does not exist, so the generator takes its
#: "group absent" branch and never attempts a chown the test process could not
#: perform. The chown path is a root-only behaviour and is asserted statically.
ABSENT_GROUP = "bunny-brlapi-key-test-group-absent"

POSIX_ONLY = unittest.skipUnless(
    sys.platform != "win32",
    "scripts/bunny-brlapi-key.py imports grp, which does not exist on Windows, so the "
    "generator cannot be executed here. The static half of this suite runs on Windows.",
)


def parse_unit(text: str) -> dict[str, dict[str, list[str]]]:
    """Parse a systemd unit into ``section -> directive -> [values]``.

    Directives repeat legitimately in systemd (``After=`` twice is a union),
    so every value is kept rather than the last one winning.
    """
    sections: dict[str, dict[str, list[str]]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        sections.setdefault(current, {}).setdefault(key.strip(), []).append(value.strip())
    return sections


UNIT = parse_unit(UNIT_SOURCE)


def unit_words(section: str, directive: str) -> list[str]:
    """Every whitespace-separated token of a possibly repeated directive."""
    return [
        word
        for value in UNIT.get(section, {}).get(directive, [])
        for word in value.split()
    ]


def module_constant(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a module-level constant")


def assigned_literal(tree: ast.Module, name: str) -> object:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no assignment to {name} was found")


def copy_mode_in_loop_over(tree: ast.Module, iterable_name: str) -> int | None:
    """The mode argument of the ``copy_file`` call inside ``for _ in <name>``."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and isinstance(node.iter, ast.Name)
            and node.iter.id == iterable_name
        ):
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "copy_file"
                    and len(call.args) >= 3
                    and isinstance(call.args[2], ast.Constant)
                ):
                    return call.args[2].value
    return None


def systemctl_enable_argument_lists(tree: ast.Module) -> list[list[str]]:
    """Every literal argv list that invokes ``systemctl enable``."""
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.List)):
            continue
        argv = [
            element.value
            for element in node.args[0].elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if argv and argv[0].endswith("systemctl") and "enable" in argv:
            found.append(argv)
    return found


def required_activation_links(tree: ast.Module) -> dict[str, str]:
    """``required_activation`` as ``unit name -> asserted symlink path``."""
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "required_activation"
                for target in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            continue
        links: dict[str, str] = {}
        for key, value in zip(node.value.keys, node.value.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            strings = [
                inner.value
                for inner in ast.walk(value)
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
            ]
            links[key.value] = "".join(strings)
        return links
    return {}


def run_generator(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Execute the generator out-of-process, as the unit would."""
    return subprocess.run(
        [sys.executable, str(GENERATOR_PATH), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class HelperReachesTheInstalledRoot(unittest.TestCase):
    """Cases 1-3. The half of the defect a build could have caught."""

    def test_the_generator_is_installed_into_the_image(self) -> None:
        # Refuses: the unit ships, ExecStart names /usr/libexec/bunny-brlapi-key,
        # and nothing ever copies the program there — so the service fails with
        # status=203/EXEC on a device and the key is never minted.
        #
        # Asked of build/scripts/install_routes.py, which is the declaration the
        # installer is driven by and the closure analyser reads. It used to be
        # asked of a list literal inside install-root.py, which is the same fact
        # in a place only one of the two programs could see.
        self.assertIn(PROGRAM_NAME, install_route_declaration().SYSTEM_SCRIPTS)

    def test_the_installed_path_is_the_one_the_unit_executes(self) -> None:
        # Refuses: the program is installed, but somewhere the unit does not
        # look. Shipping it to /usr/bin would satisfy the test above and still
        # leave ExecStart pointing at nothing.
        self.assertEqual(installed_program_route().destination, INSTALLED_PROGRAM)
        self.assertEqual(UNIT["Service"]["ExecStart"], [INSTALLED_PROGRAM])
        self.assertEqual(INSTALLED_PROGRAM, f"/usr/libexec/{PROGRAM_NAME}")

    def test_the_generator_is_installed_executable(self) -> None:
        # Refuses: the file lands at the right path with mode 0644, so systemd
        # cannot execute it — the same 203/EXEC failure, one bit away.
        self.assertEqual(
            installed_program_route().mode, 0o555, "scripts must be installed executable",
        )

    def test_the_service_is_enabled_by_the_build(self) -> None:
        # Refuses: the unit is installed but never enabled. systemd's default
        # preset policy disables what no preset names, so an un-enabled unit is
        # an inert unit and /etc/brlapi.key is never created.
        enabled = [unit for argv in systemctl_enable_argument_lists(INSTALL_ROOT_TREE) for unit in argv]
        self.assertIn(UNIT_NAME, enabled)

    def test_the_generator_source_file_the_installer_names_exists(self) -> None:
        # Refuses: script_names lists a name whose scripts/<name>.py is absent,
        # which turns the build into a failure at image time rather than a
        # missing file at boot time — but only if something checks.
        self.assertTrue(GENERATOR_PATH.is_file(), f"{GENERATOR_PATH} is missing")


class PresetEnablesTheService(unittest.TestCase):
    """Case 4."""

    def test_the_preset_enables_the_service(self) -> None:
        # Refuses: the preset omits the unit, so any path that re-applies
        # presets (a preset-all, a fresh /etc) silently disables it again.
        lines = [line.strip() for line in PRESET_SOURCE.splitlines()]
        self.assertIn(f"enable {UNIT_NAME}", lines)

    def test_the_preset_does_not_also_disable_it(self) -> None:
        # Refuses: an "enable" line shadowed by a later "disable" line for the
        # same unit — the file would still contain the string the case asks for.
        self.assertNotIn(f"disable {UNIT_NAME}", [line.strip() for line in PRESET_SOURCE.splitlines()])


class UnitOrderingAndInstallation(unittest.TestCase):
    """Cases 5-7 and 19. Everything about *when* the key is minted."""

    def test_the_unit_is_wanted_by_sysinit_target(self) -> None:
        # Refuses: WantedBy=multi-user.target, which is ordered after
        # basic.target and therefore after brltty — the key would be created,
        # but too late to authorise the braille display for that session.
        self.assertEqual(unit_words("Install", "WantedBy"), ["sysinit.target"])

    def test_the_unit_is_ordered_before_brltty_and_basic_target(self) -> None:
        # Refuses: no Before=, so systemd is free to start brltty first and the
        # display comes up unauthorised.
        before = unit_words("Unit", "Before")
        self.assertIn("brltty.service", before)
        self.assertIn("basic.target", before)

    def test_the_unit_is_ordered_before_the_brltty_udev_path_too(self) -> None:
        # Case 19. brltty-udev.service is how a display hotplugged early gets
        # its daemon; ordering before brltty.service alone leaves that path
        # racing the generator.
        #
        # Offline this is all that is checkable: unit ordering is a statement
        # about the dependency graph, and whether systemd honoured it on a real
        # boot is verified by the installed-system harness, which reads the
        # journal timestamps of the two units on a booted device.
        self.assertIn("brltty-udev.service", unit_words("Unit", "Before"))

    def test_the_unit_waits_for_local_filesystems(self) -> None:
        # Refuses: the generator runs before /etc is mounted read-write. Case 6
        # and the first half of case 7.
        self.assertIn("local-fs.target", unit_words("Unit", "After"))

    def test_writing_to_etc_is_declared_rather_than_assumed(self) -> None:
        # Case 7, second half. ProtectSystem=strict makes the whole filesystem
        # read-only inside the unit's namespace, so /etc is writable *only*
        # because ReadWritePaths says so. Together with After=local-fs.target
        # this means a wrong ordering fails loudly — the unit cannot write into
        # a namespace whose /etc is not yet there — rather than writing a key
        # into a tmpfs that is about to be replaced by the real /etc.
        self.assertEqual(UNIT["Service"]["ProtectSystem"], ["strict"])
        self.assertIn("/etc", unit_words("Service", "ReadWritePaths"))
        # RequiresMountsFor=/etc states the same requirement as an ordering
        # dependency rather than leaving it implied by local-fs.target: on an
        # ostree system /etc is composed at boot, and ordering after the mount
        # that provides it is the difference between writing the key and not.
        self.assertIn("/etc", unit_words("Unit", "RequiresMountsFor"))

    def test_default_dependencies_are_off_so_early_ordering_is_possible(self) -> None:
        # Refuses: leaving DefaultDependencies=yes, which injects
        # After=basic.target and makes Before=basic.target an ordering cycle
        # systemd resolves by dropping one of the two edges — silently.
        self.assertEqual(UNIT["Unit"]["DefaultDependencies"], ["no"])

    def test_the_generator_writes_the_path_the_rest_of_the_system_names(self) -> None:
        # Refuses: the generator defaulting to a path finalisation does not
        # clear and the documentation does not describe, so the image ships a
        # shared key at /etc/brlapi.key while a per-device key is minted
        # somewhere nothing reads.
        default_path = re.search(r'DEFAULT_PATH = Path\("([^"]+)"\)', GENERATOR_SOURCE)
        self.assertIsNotNone(default_path)
        self.assertEqual(default_path.group(1), KEY_PATH)
        self.assertIn(KEY_PATH, FINALISE_SOURCE)

    def test_the_unit_runs_unconditionally_so_recovery_stays_reachable(self) -> None:
        # Refuses: ConditionPathExists=!/etc/brlapi.key, which the unit used to
        # carry. It reads as "only run when the key is missing" and it made the
        # generator's recovery policy unreachable — an empty or malformed key is
        # a file that exists, so systemd skipped the unit, and the one case
        # where a braille user most needs the key rebuilt was the one case
        # nothing would rebuild it. Deciding is the generator's job, and the
        # replacement tests in KeyLifecycleOnTheDevice only mean anything if the
        # unit actually reaches that code on a boot where a key is present.
        self.assertNotIn("ConditionPathExists", UNIT["Unit"])

    def test_the_unit_is_a_oneshot_that_stays_satisfied(self) -> None:
        # Refuses: Type=simple, under which systemd considers the unit started
        # the moment it forks — so Before=brltty.service would order against
        # the *launch* of the generator, not its completion, and brltty could
        # still read a key that is not there yet.
        self.assertEqual(UNIT["Service"]["Type"], ["oneshot"])
        self.assertEqual(UNIT["Service"]["RemainAfterExit"], ["yes"])


class ImageShipsNoKey(unittest.TestCase):
    """Case 8. The key must be absent before first boot, or it is not per-device."""

    def test_finalisation_removes_the_key_from_the_image(self) -> None:
        # Refuses: brltty's %post mints the key at *image build* time, so every
        # device installed from one image would share one authorisation key and
        # anyone holding the image would hold it.
        self.assertRegex(FINALISE_SOURCE, rf"rm -f {re.escape(KEY_PATH)}\b")

    def test_finalisation_verifies_the_key_is_gone_afterwards(self) -> None:
        # Refuses: the removal runs but something later recreates the key, and
        # nothing looks again. The finaliser's leftovers sweep is the check that
        # the artifact, not the command, is what was verified.
        swept = [
            body
            for body in re.findall(r"for path in ((?:.|\n)*?); do", FINALISE_SOURCE)
            if KEY_PATH in body
        ]
        self.assertTrue(
            swept,
            f"no leftovers sweep in finalise-image.sh iterates over {KEY_PATH}",
        )
        self.assertIn("must not be present in the immutable artifact", FINALISE_SOURCE)

    def test_the_removal_names_the_service_that_replaces_it(self) -> None:
        # Refuses: a removal that is just a deletion. Removing a secret without
        # arranging for its regeneration is how accessibility gets traded away
        # for a matching digest.
        self.assertIn(UNIT_NAME, FINALISE_SOURCE)


class KeyLifecycleOnTheDevice(unittest.TestCase):
    """Cases 9-11, 16-17. Executed, not inspected."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.key = self.directory / "brlapi.key"

    def read_key(self, path: Path | None = None) -> str:
        return (path or self.key).read_text(encoding="ascii").strip()

    @POSIX_ONLY
    def test_a_key_is_created_when_none_exists(self) -> None:
        # Case 9. Refuses: first boot leaves no key at all, which is no braille
        # output for the whole session.
        result = run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.key.is_file())
        value = self.read_key()
        self.assertEqual(len(value), 32, f"expected 32 hex characters, got {value!r}")
        self.assertRegex(value, r"\A[0-9a-f]{32}\Z")

    @POSIX_ONLY
    def test_an_existing_well_formed_key_is_left_alone(self) -> None:
        # Case 10. Refuses: rotation on every boot, which invalidates every
        # client already authorised against the key — a screen reader that
        # worked yesterday stops working today.
        run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        first = self.read_key()
        second_run = run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        self.assertEqual(second_run.returncode, 0, second_run.stderr)
        self.assertEqual(self.read_key(), first)
        self.assertIn("leaving it alone", second_run.stdout)

    @POSIX_ONLY
    def test_two_installations_receive_different_keys(self) -> None:
        # Case 11. The whole point of moving generation to the device. Refuses:
        # a deterministic derivation that would make two builds compare equal
        # while destroying the property the file exists for.
        first = self.directory / "a" / "brlapi.key"
        second = self.directory / "b" / "brlapi.key"
        run_generator("--path", str(first), "--group", ABSENT_GROUP)
        run_generator("--path", str(second), "--group", ABSENT_GROUP)
        self.assertNotEqual(self.read_key(first), self.read_key(second))

    @POSIX_ONLY
    def test_an_empty_key_is_replaced(self) -> None:
        # Case 16. Refuses: treating "the file exists" as "the key is usable".
        # An empty key authorises nobody, and ConditionPathExists would keep the
        # unit from ever running again, so leaving it is permanent silence.
        self.key.write_text("", encoding="ascii")
        result = run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(self.read_key(), r"\A[0-9a-f]{32}\Z")

    @POSIX_ONLY
    def test_a_malformed_key_is_replaced_and_the_replacement_is_announced(self) -> None:
        # Case 17. Refuses: a silent replacement. A key that changed underneath
        # a working setup is something an operator has to be able to find
        # afterwards, so the warning is part of the behaviour, not decoration.
        self.key.write_text("not-a-key\n", encoding="ascii")
        result = run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(self.read_key(), r"\A[0-9a-f]{32}\Z")
        self.assertIn("not a usable BrlAPI key", result.stderr)

    @POSIX_ONLY
    def test_a_truncated_key_is_treated_as_malformed(self) -> None:
        # Refuses: a length check that accepts a short hex string. A truncated
        # write leaves something that looks like a key and authorises nothing.
        self.key.write_text("0123456789abcdef\n", encoding="ascii")
        run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        self.assertEqual(len(self.read_key()), 32)

    def test_the_key_length_matches_the_format_brltty_expects(self) -> None:
        # Static counterpart, runs everywhere: brltty's own scriptlet emits 128
        # bits as 32 lowercase hex characters, and the generator must match that
        # exactly or nothing downstream can read what it wrote.
        self.assertEqual(module_constant(GENERATOR_TREE, "KEY_BYTES"), 16)


class KeyPermissionsAndOwnership(unittest.TestCase):
    """Cases 12-13."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.key = self.directory / "brlapi.key"

    @POSIX_ONLY
    def test_the_generated_key_has_mode_0640(self) -> None:
        # Case 12. Refuses: a world-readable secret. 0644 would let any local
        # account read the key and impersonate an authorised BrlAPI client.
        result = run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o640)

    @POSIX_ONLY
    def test_check_refuses_a_key_with_the_wrong_mode(self) -> None:
        # Case 12, the detection half. Refuses: --check reporting PASS on a
        # key anyone can read, which would make the installed-system harness
        # certify a broken permission boundary.
        run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        os.chmod(self.key, 0o644)
        result = run_generator("--path", str(self.key), "--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mode 0644", result.stdout)

    @POSIX_ONLY
    def test_check_refuses_an_absent_key(self) -> None:
        # Refuses: --check exiting zero when there is nothing there, which is
        # the exact state an un-enabled unit leaves the device in.
        result = run_generator("--path", str(self.directory / "nothing"), "--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absent", result.stdout)

    def test_check_tests_the_owner_and_expects_root(self) -> None:
        # Case 13, source-level. A test process cannot create a root-owned file
        # without being root, and cannot chown one away from root without
        # CAP_CHOWN, so the *wrong-owner* state is not forceable portably. What
        # is assertable offline is that the check exists and compares against
        # uid 0 — which is the guarantee the case rests on.
        #
        # Unverifiable offline: that a real device's key is in fact root-owned.
        # That is measured by the installed-system harness, which stats the
        # file on a booted device.
        self.assertIn("info.st_uid != 0", GENERATOR_SOURCE)
        self.assertIn("expected 0", GENERATOR_SOURCE)

    @POSIX_ONLY
    def test_the_owner_branch_of_check_actually_fires(self) -> None:
        # Case 13, runtime. The branch above is not merely present: when the
        # test runs unprivileged the generated key is owned by the test user,
        # and --check must say so and exit nonzero. Under root the same run
        # must not complain, which is the other half of the same assertion.
        run_generator("--path", str(self.key), "--group", ABSENT_GROUP)
        result = run_generator("--path", str(self.key), "--check")
        if os.geteuid() == 0:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("owner uid", result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("owner uid", result.stdout)

    def test_the_unit_masks_permissions_for_anything_it_creates(self) -> None:
        # Refuses: relying solely on the generator's explicit chmod. UMask=0077
        # means even a file created by a future code path is not born readable.
        self.assertEqual(UNIT["Service"]["UMask"], ["0077"])

    def test_the_declared_mode_is_the_one_the_group_needs(self) -> None:
        # Runs everywhere. 0640 is not arbitrary: root writes it, the brlapi
        # group reads it, and nobody else sees it.
        self.assertEqual(module_constant(GENERATOR_TREE, "MODE"), 0o640)

    def test_the_generator_warns_rather_than_silently_shipping_a_useless_key(self) -> None:
        # Refuses: creating a root:root key when the brlapi group is absent and
        # saying nothing — brltty clients could not read it and the failure
        # would present as a dead display with a healthy-looking service.
        self.assertIn("does not exist; the key is owned by root:root", GENERATOR_SOURCE)


class TheKeyNeverReachesTheJournal(unittest.TestCase):
    """Case 14."""

    @POSIX_ONLY
    def test_the_key_value_appears_in_neither_stream(self) -> None:
        # Refuses: printing the key on success. A secret in a journal is a
        # secret in every log shipper, crash report and support bundle
        # downstream of it — including the ones users send to strangers.
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "brlapi.key"
            result = run_generator("--path", str(key), "--group", ABSENT_GROUP)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = key.read_text(encoding="ascii").strip()
        self.assertNotIn(value, result.stdout)
        self.assertNotIn(value, result.stderr)

    @POSIX_ONLY
    def test_the_replacement_warning_does_not_carry_the_new_key(self) -> None:
        # Refuses: leaking on the *error* path, which is the path most likely
        # to be pasted into a bug report.
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "brlapi.key"
            key.write_text("not-a-key\n", encoding="ascii")
            result = run_generator("--path", str(key), "--group", ABSENT_GROUP)
            value = key.read_text(encoding="ascii").strip()
        self.assertNotIn(value, result.stdout + result.stderr)

    def test_no_print_call_in_the_generator_takes_the_key_value(self) -> None:
        # Static and total, where the subprocess tests are only a sample: no
        # print() anywhere in the source references the `value` binding, so no
        # input and no future branch can make one leak.
        for node in ast.walk(GENERATOR_TREE):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                names = {
                    inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)
                }
                self.assertNotIn("value", names, f"print() at line {node.lineno} references the key")

    def test_the_unit_sends_both_streams_to_the_journal(self) -> None:
        # The case is "the key appears in journal output", so the unit must in
        # fact be journalled — asserting silence on a unit that logs nowhere
        # would prove nothing.
        self.assertEqual(UNIT["Service"]["StandardOutput"], ["journal"])
        self.assertEqual(UNIT["Service"]["StandardError"], ["journal"])

    def test_the_source_states_the_no_printing_rule(self) -> None:
        # Refuses: a rule that lives only in a reviewer's head and is
        # reintroduced by the next person adding a debug line.
        self.assertIn("The value itself is never printed", GENERATOR_SOURCE)


class WritingTheKeyIsAtomic(unittest.TestCase):
    """Case 15."""

    def test_the_key_is_written_through_a_temporary_and_renamed(self) -> None:
        # Refuses: opening /etc/brlapi.key directly and writing into it, under
        # which a crash or a power cut mid-write leaves a truncated file that
        # exists — so ConditionPathExists suppresses the unit forever and the
        # display never authorises again.
        self.assertIn("os.replace(temporary, path)", GENERATOR_SOURCE)
        self.assertIn('temporary = parent / f".{path.name}.new"', GENERATOR_SOURCE)
        calls = {
            node.func.attr
            for node in ast.walk(GENERATOR_TREE)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("replace", calls)

    def test_the_temporary_is_created_with_the_final_mode(self) -> None:
        # Refuses: creating the temporary 0644 and chmod-ing afterwards, which
        # leaves a window in which the key is world-readable on disk.
        self.assertIn("os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MODE", GENERATOR_SOURCE)

    def test_a_failed_write_removes_the_temporary(self) -> None:
        # Refuses: leaving .brlapi.key.new behind on an exception, accumulating
        # partial secrets in /etc.
        self.assertIn("temporary.unlink(missing_ok=True)", GENERATOR_SOURCE)

    @POSIX_ONLY
    def test_a_stale_temporary_does_not_survive_as_the_real_key(self) -> None:
        # Case 15, runtime. Simulates the interrupted write: a leftover
        # .brlapi.key.new from a run that died before the rename. The next run
        # must produce a correct key and must not promote the debris.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "brlapi.key"
            stale = root / ".brlapi.key.new"
            stale.write_text("dead beef from an interrupted run\n", encoding="ascii")
            result = run_generator("--path", str(key), "--group", ABSENT_GROUP)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = key.read_text(encoding="ascii").strip()
            self.assertRegex(value, r"\A[0-9a-f]{32}\Z")
            self.assertNotIn("dead beef", value)
            self.assertFalse(stale.exists(), "the temporary was left behind")

    @POSIX_ONLY
    def test_no_partial_file_remains_after_a_normal_run(self) -> None:
        # Refuses: the key being correct while /etc accumulates a second copy of
        # it under a dotted name that nothing cleans up.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_generator("--path", str(root / "brlapi.key"), "--group", ABSENT_GROUP)
            self.assertEqual([entry.name for entry in root.iterdir()], ["brlapi.key"])


class RandomnessSource(unittest.TestCase):
    """Case 18."""

    def test_the_key_comes_from_the_kernel_csprng(self) -> None:
        # Refuses: a pseudo-random source. os.urandom blocks until the pool is
        # initialised, which is exactly the condition on a first boot where
        # entropy is scarce — and a key drawn from a seeded PRNG on a fleet of
        # identical devices is not a secret at all.
        #
        # Unverifiable offline: that the kernel pool is genuinely unavailable
        # and that generation then blocks rather than proceeding with weak
        # entropy. Forcing that state needs control of the kernel, so what is
        # asserted here is the choice of source, which is what determines the
        # behaviour.
        self.assertIn("os.urandom(KEY_BYTES)", GENERATOR_SOURCE)

    def test_no_pseudo_random_source_is_used(self) -> None:
        # Refuses: someone swapping in `random` for testability. The module
        # would still produce 32 hex characters and every other test here would
        # still pass.
        lowered = GENERATOR_SOURCE.lower()
        self.assertNotRegex(GENERATOR_SOURCE, re.compile(r"^\s*import random\b", re.MULTILINE))
        self.assertNotRegex(GENERATOR_SOURCE, r"\brandom\.rand")
        self.assertNotRegex(GENERATOR_SOURCE, r"\brandom\.seed\b")
        self.assertNotIn("pseudo", lowered)
        imported = {
            alias.name
            for node in ast.walk(GENERATOR_TREE)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("random", imported)

    def test_deterministic_generation_is_refused_in_writing(self) -> None:
        # Refuses: the reproducibility pressure that created this file in the
        # first place being resolved the wrong way — making two builds match by
        # deriving the key from something reproducible.
        self.assertIn("Deterministic generation is refused outright", GENERATOR_SOURCE)


class SourceInspectionCannotSubstituteForActivation(unittest.TestCase):
    """Case 20. The meta-test: the one that encodes the actual defect.

    Every other static test here reads a file and finds the right string in it.
    That is precisely the kind of checking that reported PASS while installed
    systems shipped with an inert unit and no key: the unit existed, the
    ExecStart was well-formed, the preset was fine, and none of it was true of
    the artifact. So the build itself must assert the *symlink* — a statement
    about the filesystem that was produced, not about a command that exited
    zero — and this test refuses a build script that has stopped doing so.
    """

    def test_the_build_asserts_the_activation_symlink_exists(self) -> None:
        links = required_activation_links(INSTALL_ROOT_TREE)
        self.assertIn(UNIT_NAME, links)
        self.assertEqual(
            links[UNIT_NAME], f"/etc/systemd/system/sysinit.target.wants/{UNIT_NAME}"
        )
        # The asserted symlink must live under the target the unit is actually
        # WantedBy, or the assertion checks a path systemd would never create.
        self.assertIn("sysinit.target", unit_words("Install", "WantedBy"))

    def test_the_build_checks_the_link_rather_than_the_exit_code(self) -> None:
        self.assertIn("is_symlink()", INSTALL_ROOT_SOURCE)

    def test_a_missing_activation_stops_the_build(self) -> None:
        # Refuses: an install script that notices the missing symlink, prints a
        # warning, and produces the image anyway.
        raises = [
            node
            for node in ast.walk(INSTALL_ROOT_TREE)
            if isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id == "SystemExit"
        ]
        self.assertTrue(raises, "install-root.py raises no SystemExit at all")

        # Whether the SystemExit is the *consequence* of the activation check is
        # a structural question, not a distance. This was a line count — the
        # raise had to fall within 30 lines of the anchor — and every unit added
        # to the table pushed it further away, so the Public Alpha pass broke
        # this test by strengthening the very check it defends: seven units
        # asserted where there had been four. A test that fails when the check
        # gets stronger is measuring the wrong thing, and raising the constant
        # would only postpone the next false failure.
        #
        # The chain that actually matters is anchor -> table -> list -> guard ->
        # raise, and each link is asserted below.
        anchor = INSTALL_ROOT_SOURCE.index(f"sysinit.target.wants/{UNIT_NAME}")
        anchor_line = INSTALL_ROOT_SOURCE[:anchor].count("\n") + 1

        def assignment_to(name: str) -> ast.Assign | None:
            return next(
                (
                    node
                    for node in ast.walk(INSTALL_ROOT_TREE)
                    if isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == name
                        for target in node.targets
                    )
                ),
                None,
            )

        # The anchor is inside the table the check reads, not merely somewhere
        # above the raise.
        table = assignment_to("required_activation")
        self.assertIsNotNone(table, "install-root.py has no required_activation table")
        self.assertLessEqual(table.lineno, anchor_line)
        self.assertGreaterEqual(table.end_lineno, anchor_line)

        # The missing list is computed from that table.
        missing = assignment_to("missing_activation")
        self.assertIsNotNone(missing, "install-root.py computes no missing_activation list")
        self.assertIn(
            "required_activation",
            ast.dump(missing),
            "missing_activation is not derived from required_activation, so the "
            "refusal is not about the units the table requires",
        )

        # And the raise is guarded by that list rather than merely near it.
        guard = next(
            (
                node
                for node in ast.walk(INSTALL_ROOT_TREE)
                if isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "missing_activation"
            ),
            None,
        )
        self.assertIsNotNone(guard, "nothing acts on missing_activation")
        self.assertTrue(
            [node for node in ast.walk(guard) if node in raises],
            "the missing-activation branch does not raise SystemExit; a build that "
            "detects a missing enablement and continues is the defect, not the fix",
        )

    def test_the_refusal_names_the_units_it_found_missing(self) -> None:
        # Refuses: a bare `raise SystemExit(1)` that leaves whoever hits it
        # bisecting a build to find out which unit was not enabled.
        self.assertIn("missing_activation", INSTALL_ROOT_SOURCE)
        self.assertIn("BLOCKED: these units are not activated", INSTALL_ROOT_SOURCE)

    def test_the_enablement_and_the_assertion_cover_the_same_unit(self) -> None:
        # Refuses: the two halves drifting — enabling one unit while asserting
        # the symlink of another, so the assertion passes on a build that never
        # enabled the accessibility service.
        enabled = {unit for argv in systemctl_enable_argument_lists(INSTALL_ROOT_TREE) for unit in argv}
        for unit in required_activation_links(INSTALL_ROOT_TREE):
            self.assertIn(unit, enabled, f"{unit} is asserted but never enabled")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
