# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What can be asserted about a GNOME Shell desktop without starting one.

The desktop is JavaScript running inside a compositor. Most of what it does can
only be judged by looking at a screen, and this file does not pretend otherwise:
there is no test here for whether the character looks right.

What *is* testable is the part that fails silently. A layout that overlaps at a
resolution nobody tried; a state vocabulary that has drifted from the runtime's;
a metric that fabricates a zero instead of admitting it could not read the
sensor; a file that will not reach the image. Each of those passes every visual
check and each is caught below.

Three of these tests cross the language boundary on purpose. The character
states, the companion's presentation phases and the design tokens are each
defined once and consumed on the other side, and a compiler that would notice
the drift does not exist for this pair of languages.
"""

from __future__ import annotations

import contextlib
import importlib.machinery
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from tests.support import ROOT

sys.path.insert(0, str(ROOT / "build/scripts"))
from install_routes import installed_destination, routes_for_profile  # noqa: E402

EXTENSION = ROOT / "shell/components/gnome-shell-extension"
LIB = EXTENSION / "lib"

#: The resolutions the brief names, plus the two edges that bracket them.
RESOLUTIONS = (
    (1920, 1080),
    (1366, 768),
    (1600, 900),
    (2560, 1440),
    (1280, 720),
    (1024, 768),
    (3840, 2160),
)


def module_text(relative: str) -> str:
    return (EXTENSION / relative).read_text(encoding="utf-8")


class LayoutTests(unittest.TestCase):
    """The layout solver, run for real under node.

    lib/layout.js imports nothing, which is what makes this possible: the
    geometry can be evaluated outside GJS, so "no widget overlaps another at
    1920x1080" is a measured result rather than a claim someone checked once by
    looking at a screenshot.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")
        script = "\n".join([
            f"import {{solve, overlappingPairs, PANEL_KEYS}} from '{(LIB / 'layout.js').as_uri()}';",
            f"const sizes = {json.dumps(RESOLUTIONS)};",
            "const out = sizes.map(([width, height]) => {",
            "  const s = solve({width, height});",
            "  return {width, height, breakpoint: s.breakpoint, columns: s.columns,",
            "          sidebarMode: s.sidebarMode, dropped: s.dropped,",
            "          overlaps: overlappingPairs(s), rects: s.rects, keys: PANEL_KEYS};",
            "});",
            "console.log(JSON.stringify(out));",
        ])
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True, text=True, cwd=ROOT,
        )
        if result.returncode != 0:
            raise AssertionError(f"the layout solver would not run: {result.stderr.strip()}")
        cls.solutions = {(row["width"], row["height"]): row for row in json.loads(result.stdout)}

    def test_no_panel_overlaps_at_any_supported_resolution(self) -> None:
        for size, solution in self.solutions.items():
            with self.subTest(resolution=size):
                self.assertEqual(
                    solution["overlaps"], [],
                    f"{size[0]}x{size[1]} overlaps: {solution['overlaps']}")

    def test_every_panel_stays_on_screen(self) -> None:
        for (width, height), solution in self.solutions.items():
            for name, rect in solution["rects"].items():
                with self.subTest(resolution=(width, height), panel=name):
                    self.assertGreaterEqual(rect["x"], 0)
                    self.assertGreaterEqual(rect["y"], 0)
                    self.assertLessEqual(rect["x"] + rect["width"], width)
                    self.assertLessEqual(rect["y"] + rect["height"], height)

    def test_the_character_survives_every_resolution(self) -> None:
        """The brief's "keep character visible" at small sizes, as an assertion."""
        for size, solution in self.solutions.items():
            with self.subTest(resolution=size):
                character = solution["rects"].get("character")
                self.assertIsNotNone(character, "the character band was dropped")
                self.assertGreaterEqual(character["width"], 300)
                self.assertGreaterEqual(character["height"], 200)

    def test_the_chrome_is_never_dropped(self) -> None:
        for size, solution in self.solutions.items():
            with self.subTest(resolution=size):
                for name in ("topBar", "sidebar", "dock"):
                    self.assertIn(name, solution["rects"])
                    self.assertNotIn(name, solution["dropped"])

    def test_the_reference_resolution_keeps_every_card(self) -> None:
        self.assertEqual(self.solutions[(1920, 1080)]["dropped"], [])
        self.assertEqual(self.solutions[(1920, 1080)]["columns"], 2)

    def test_small_screens_collapse_the_sidebar_rather_than_hiding_it(self) -> None:
        self.assertEqual(self.solutions[(1366, 768)]["sidebarMode"], "collapsed")
        self.assertEqual(self.solutions[(1920, 1080)]["sidebarMode"], "expanded")

    def test_dropping_a_card_is_reported_not_silent(self) -> None:
        """A widget that vanishes without saying so is a bug nobody can report."""
        cramped = self.solutions[(1280, 720)]
        for key in ("systemOverview", "quickAccess", "media", "agenda", "systemMonitor", "assistant"):
            with self.subTest(card=key):
                present = key in cramped["rects"]
                reported = key in cramped["dropped"]
                # Exactly one must be true. Both false is a card that vanished
                # without a word; both true is a card in two states at once.
                self.assertNotEqual(
                    present, reported,
                    f"{key}: placed={present}, reported dropped={reported}")


class ModuleSyntaxTests(unittest.TestCase):
    """Every module the extension ships must parse as strict-mode ES.

    This exists because it happened. `lib/services/voice.js` named a parameter
    `arguments`, which is legal in a sloppy-mode script and a SyntaxError in a
    module — and every module is strict. GJS raised it while *loading* the
    import graph, so it happened before `enable()` was called and the top-level
    try/catch in extension.js never ran. GNOME Shell recorded the extension as
    state 3 (ERROR), started its own desktop instead, and the session looked
    like an ordinary GNOME login: correct top bar, working overview, no Bunny
    anything. A screenshot of it is indistinguishable from a session where the
    desktop is simply switched off.

    Nothing else in this suite would catch it. The layout tests import
    `lib/layout.js` alone, the rest read the modules as *text*, and the Python
    that packages them never parses them. So the graph is parsed here, one file
    at a time, so that the failure names the file.

    Parsing is all that is wanted: `--check` does not resolve imports, which is
    what makes it usable on modules that import `gi://` and `resource:///`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")

    def _parse(self, path: Path) -> subprocess.CompletedProcess:
        # `encoding="utf-8"` on the call, not only on the read: without it
        # Python encodes the child's stdin with the platform's preferred codec,
        # which on Windows is cp1252, and the first module containing an emoji
        # raised UnicodeEncodeError instead of reporting a syntax result.
        return subprocess.run(
            [shutil.which("node"), "--input-type=module", "--check"],
            input=path.read_text(encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
        )

    def test_every_extension_module_parses_as_a_module(self) -> None:
        modules = sorted(EXTENSION.rglob("*.js"))
        self.assertGreater(len(modules), 20, "the extension's modules were not found")
        for module in modules:
            with self.subTest(module=str(module.relative_to(EXTENSION))):
                result = self._parse(module)
                self.assertEqual(
                    result.returncode, 0,
                    f"{module.relative_to(ROOT)} does not parse as an ES module:\n"
                    f"{result.stderr.strip()}")

    def test_the_check_would_fail_on_the_defect_it_was_written_for(self) -> None:
        """The negative control: a check that cannot fail proves nothing.

        A parameter named `arguments` is the exact fault that cost a desktop,
        so it is the fault this asserts the check still detects.
        """
        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "planted.js"
            planted.write_text(
                "export function f(arguments) { return arguments[0]; }\n",
                encoding="utf-8")
            result = self._parse(planted)
        self.assertNotEqual(result.returncode, 0,
                            "the module syntax check no longer detects a strict-mode violation")
        self.assertIn("arguments", result.stderr)


class CharacterStateTests(unittest.TestCase):
    def test_the_ten_states_the_brief_names_all_exist(self) -> None:
        text = module_text("lib/character/state.js")
        declared = set(re.findall(r"'(\w+)'", re.search(r"STATES = \[(.*?)\]", text, re.S).group(1)))
        self.assertEqual(declared, {
            "idle", "listening", "thinking", "working", "success",
            "warning", "error", "talking", "sleeping", "celebrating",
        })

    def test_every_state_has_a_pose(self) -> None:
        """A state with no pose would animate as idle and look like a bug."""
        states = set(re.findall(
            r"'(\w+)'",
            re.search(r"STATES = \[(.*?)\]", module_text("lib/character/state.js"), re.S).group(1)))
        poses = set(re.findall(r"^\s{8}(\w+): \{", module_text("lib/character/definition.js"), re.M))
        self.assertEqual(states - poses, set(), "states with no pose in the character definition")

    def test_every_companion_phase_maps_to_a_character_state(self) -> None:
        """The cross-language check.

        companion/presentation.py owns the phase vocabulary and the desktop
        reacts to it. A phase added there and not here would leave the character
        holding its previous expression through a state the runtime considers
        distinct — silently, because an unmapped phase is a lookup that returns
        undefined and a state change that does not happen.
        """
        from companion.presentation import PRESENTATION_PHASES

        text = module_text("lib/services/assistant.js")
        table = re.search(r"PHASE_TO_STATE = \{(.*?)\n\};", text, re.S).group(1)
        mapped = set(re.findall(r"^\s{4}(\w+):", table, re.M))
        self.assertEqual(
            set(PRESENTATION_PHASES) - mapped, set(),
            "companion presentation phases with no character state")

    def test_every_mapped_state_is_a_real_state(self) -> None:
        text = module_text("lib/services/assistant.js")
        table = re.search(r"PHASE_TO_STATE = \{(.*?)\n\};", text, re.S).group(1)
        targets = set(re.findall(r":\s*'(\w+)'", table))
        states = set(re.findall(
            r"'(\w+)'",
            re.search(r"STATES = \[(.*?)\]", module_text("lib/character/state.js"), re.S).group(1)))
        self.assertEqual(targets - states, set(), "phases mapped to states that do not exist")


class HonestMetricTests(unittest.TestCase):
    """The rule that a reader returns null rather than a plausible number.

    This is the brief's "do not fabricate information" turned into something a
    change can fail. The specific mistake it guards is the cheap one: writing
    ``?? 0`` to make a null go away, which produces a dashboard reporting 0%
    CPU, 0°C and a flat battery on a machine whose sensors simply could not be
    read.
    """

    READERS = (
        "lib/services/telemetry.js",
        "lib/services/power.js",
        "lib/services/network.js",
        "lib/services/brightness.js",
    )

    def test_no_reader_substitutes_a_zero_for_a_missing_measurement(self) -> None:
        for relative in self.READERS:
            text = module_text(relative)
            for pattern in (r"\?\?\s*0\b", r"\|\|\s*0\b"):
                with self.subTest(module=relative, pattern=pattern):
                    self.assertIsNone(
                        re.search(pattern, text),
                        f"{relative} falls back to 0 for a measurement")

    def test_the_unavailable_wording_has_one_definition(self) -> None:
        self.assertIn("export const UNAVAILABLE = 'Unavailable';", module_text("lib/widgets.js"))
        for relative in ("lib/cards/systemOverview.js", "lib/cards/systemMonitor.js"):
            self.assertIn("UNAVAILABLE", module_text(relative))

    def test_a_machine_without_a_battery_reports_ac_power(self) -> None:
        self.assertIn("'AC Power'", module_text("lib/cards/systemMonitor.js"))
        self.assertIn("present: false", module_text("lib/services/power.js"))


class MotionTests(unittest.TestCase):
    def test_reduced_motion_cannot_be_bypassed(self) -> None:
        """Every animation goes through animation.js, so one check honours the setting.

        A component calling ``actor.ease`` directly would animate in a session
        that asked for no animation, and nothing else would notice.
        """
        offenders = [
            path.relative_to(EXTENSION).as_posix()
            for path in sorted(EXTENSION.rglob("*.js"))
            if path.name != "animation.js"
            and re.search(r"\.ease\(", path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], "modules animating without going through animation.js")

    def test_animation_module_consults_the_accessibility_setting(self) -> None:
        text = module_text("lib/animation.js")
        self.assertIn("St.Settings.get().enable_animations", text)


class IntrospectionSafetyTests(unittest.TestCase):
    """Guards for the failure class that took the desktop down on its first boot.

    `Clutter.AccessibleRole.PUSH_BUTTON` parses, resolves, passes every static
    check in this repository, and throws at runtime because Clutter has no
    AccessibleRole — the property is an `Atk.Role`. It threw inside the first
    widget the top bar built, propagated out of DesktopShell's constructor, and
    the entire desktop refused to start over a screen-reader hint. The
    screenshot from that run is a GNOME session with GNOME's panel back.

    Nothing static can tell whether a GI enum exists; that needs the library.
    What can be checked is that the two habits which turned a wrong constant
    into a dead desktop are gone: the role is set in one guarded place, and the
    constant is looked up by name so a miss is a log line and not a TypeError.
    """

    def test_no_module_assigns_an_accessible_role_directly(self) -> None:
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            # util.js is the one guarded place, and the assignment inside
            # setAccessibleRole is what every other module is required to use.
            if path.name == "util.js":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"\.accessible_role\s*=", text):
                offenders.append(path.relative_to(EXTENSION).as_posix())
        self.assertEqual(
            offenders, [],
            "assign accessible roles through setAccessibleRole, which cannot throw")

    def test_clutter_has_no_accessible_role_namespace_in_use(self) -> None:
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            if path.name == "util.js":
                continue  # names it in the comment that explains the bug
            if "Clutter.AccessibleRole" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(EXTENSION).as_posix())
        self.assertEqual(offenders, [], "Clutter has no AccessibleRole; roles are Atk.Role")

    def test_no_module_writes_to_accessible_description(self) -> None:
        """St actors have no accessible-description, and assigning one is silent.

        `accessible-name` and `accessible-role` are the two properties St
        exposes. Assigning `accessible_description` in GJS creates an ordinary
        JavaScript property on the object; nothing reads it and no assistive
        technology sees it. Measured on a booted image: every one of the 307
        controls in the desktop's accessibility tree reported an empty
        description, including the character's — which was the only thing
        telling a screen-reader user what the assistant was doing.

        Six places wrote to it. They now put the information in the name.
        """
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith(("//", "*")):
                    continue
                if re.search(r"\.accessible_description\s*=", line):
                    offenders.append(f"{path.relative_to(EXTENSION).as_posix()}:{number}")
        self.assertEqual(
            offenders, [],
            "accessible_description is not a St property; put it in accessible_name",
        )

    def test_the_character_announces_its_state_in_its_name(self) -> None:
        text = module_text("lib/character/viewport.js")
        self.assertIn("this._hit.accessible_name = reason", text)
        self.assertIn("Bunny, your assistant —", text)

    def test_the_role_helper_looks_the_constant_up_rather_than_dereferencing_it(self) -> None:
        text = module_text("lib/util.js")
        self.assertIn("Atk?.Role?.[roleName]", text)
        self.assertIn("logOnce(", text.split("export function setAccessibleRole")[1][:900])


class DesignTokenTests(unittest.TestCase):
    """The shipped stylesheet is generated; these are the properties of the output.

    There used to be a pairing check here, because `stylesheet.css` repeated
    every literal from `lib/tokens.js` by hand and a test was the only thing
    keeping the two in step. The stylesheet is now rendered from the tokens by
    `build/scripts/render_design_assets.mjs`, so the pairing is a fact about the
    build rather than a claim to check — `tests/shell/test_design_tokens.py`
    regenerates and compares. What is worth asserting here is what the generated
    default sheet must contain whatever the tokens say.
    """

    def test_the_shipped_sheet_declares_a_ground_and_a_foreground(self) -> None:
        """The fallback has to be legible on its own: it is what a failed theme manager leaves."""
        css = module_text("stylesheet.css")
        self.assertIn(".bunny-wallpaper-fallback", css)
        self.assertRegex(css, r"\.bunny-card,[\s\S]*?background-color: ")
        self.assertRegex(css, r"\.bunny-card,[\s\S]*?color: ")

    def test_the_accent_is_violet_as_the_brief_specifies(self) -> None:
        css = module_text("stylesheet.css").lower()
        self.assertIn("#a78bfa", css)
        self.assertIn("#7c3aed", css)

    def test_no_size_in_the_generated_sheet_is_written_by_hand(self) -> None:
        """Every font-size must come from the type scale, or scaling cannot move it."""
        header = module_text("stylesheet.css")[:400]
        self.assertIn("Generated by lib/design/stylesheet.js", header)
        self.assertIn("Do not edit", header)

    def test_focus_is_visible_on_every_interactive_class(self) -> None:
        """A keyboard-operable desktop with no focus ring is not keyboard-operable."""
        css = module_text("stylesheet.css")
        focusable = {
            ".bunny-sidebar-row", ".bunny-dock-tile", ".bunny-quick-tile",
            ".bunny-search-row", ".bunny-suggestion-row", ".bunny-agenda-row",
            ".bunny-media-button", ".bunny-power-row", ".bunny-card-action",
            ".bunny-assistant-icon-button", ".bunny-top-battery", ".bunny-top-clock-box",
        }
        for selector in sorted(focusable):
            with self.subTest(selector=selector):
                self.assertIn(f"{selector}:focus", css)


#: Directories whose every tracked file is installed as an executable.
#:
#: Kept as a floor, not as the definition. `installed_programs()` derives the
#: real set from the install table, so a new executable installed from anywhere
#: is covered without anyone remembering to add its directory here.
PROGRAM_DIRECTORIES = ("shell/services/bin", "installer/bin")


def installed_programs() -> list[str]:
    """Every repository file the image installs with an executable mode.

    Derived from `INSTALL_ROUTES`, which is the same table `install-root.py`
    copies from and `build-input-closure.py` classifies against — so this cannot
    drift from what actually reaches the image, which a hardcoded directory list
    silently would.

    The defect that motivated it was one file: a CRLF shebang made the kernel
    refuse the exec, and the guard that existed named two directories by hand.
    Any executable installed from a third directory would have been unguarded.
    """
    paths = set()
    for directory in PROGRAM_DIRECTORIES:
        root = ROOT / directory
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    paths.add(path.relative_to(ROOT).as_posix())
    for route in routes_for_profile("beta"):
        # 0o111 — any execute bit. A 0644 data file is not a program and its
        # line endings are the parser's business, not the kernel's.
        if getattr(route, "kind", "") != "file" or not (getattr(route, "mode", 0) & 0o111):
            continue
        source = getattr(route, "source", "")
        if source and (ROOT / source).is_file():
            paths.add(source)
    return sorted(paths)


def tracked_programs() -> list[tuple[str, str]]:
    """Each installed program and the line ending **git stores** for it.

    The stored blob, not the working tree. A Windows checkout made before
    `.gitattributes` marked these `-text` still has CRLF on disk and always
    will, because `-text` means "reproduce verbatim" — so a test that read the
    working tree would fail on Windows and pass on Linux while saying nothing
    about what reaches the image. The build checks out from the object store,
    so the object store is the thing to check.
    """
    result = subprocess.run(
        ["git", "ls-files", "--eol", "--", *installed_programs()],
        capture_output=True, text=True, cwd=ROOT, timeout=60)
    if result.returncode != 0:
        raise unittest.SkipTest(f"git could not list the programs: {result.stderr.strip()}")
    programs = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        path = fields[-1].strip()
        index_eol = fields[0].split()[0].removeprefix("i/")
        programs.append((path, index_eol))
    return programs


def index_blob(path: str) -> bytes:
    """The bytes git has for a path, unfiltered."""
    result = subprocess.run(["git", "show", f":{path}"],
                            capture_output=True, cwd=ROOT, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"git could not read {path}: {result.stderr[:200]!r}")
    return result.stdout


class InstallTests(unittest.TestCase):
    def test_every_extension_module_reaches_the_image(self) -> None:
        routes = routes_for_profile("beta")
        for path in sorted(EXTENSION.rglob("*.js")):
            relative = path.relative_to(ROOT).as_posix()
            with self.subTest(module=relative):
                destinations = [
                    installed_destination(route, relative) for route in routes
                    if installed_destination(route, relative)
                ]
                self.assertEqual(
                    len(destinations), 1,
                    f"{relative} has {len(destinations)} install destinations")
                self.assertTrue(destinations[0].startswith(
                    "/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org/"))

    def test_the_assistant_bridge_is_installed_as_a_command(self) -> None:
        routes = routes_for_profile("beta")
        destinations = [
            installed_destination(route, "shell/services/bin/bunny-shell-assistant")
            for route in routes
            if installed_destination(route, "shell/services/bin/bunny-shell-assistant")
        ]
        self.assertEqual(destinations, ["/usr/bin/bunny-shell-assistant"])

    def test_no_installed_program_carries_a_carriage_return(self) -> None:
        """A CRLF blob makes the shebang name an interpreter that does not exist.

        `shell/services/bin/bunny-shell-assistant` was committed with CRLF. It
        is installed to /usr/bin mode 0555 and begins `#!/usr/bin/python3`, so
        with a trailing CR the kernel looks for `/usr/bin/python3\\r`, refuses
        the exec, and reports "no such file or directory" while naming a file
        that is plainly there.

        The desktop's only route to the companion is
        `Gio.Subprocess.new([BRIDGE, ...])`, which execs it directly. So the
        assistant could not be started at all: the suggestion panel showed
        "Assistant offline", a typed request sat at "Thinking…" for ever, and no
        permission prompt could ever appear — on a machine whose runtime was
        active and answering.

        `.gitattributes` marks these paths `-text` so git will not *introduce*
        CRLF. That is a different guarantee from the bytes being clean, and this
        checks the bytes. `-text` faithfully reproduces whatever was committed,
        so the guard that was supposed to prevent this is precisely what made it
        permanent.
        """
        offenders = [
            path for path, eol in tracked_programs()
            if eol == "crlf"
        ]
        self.assertEqual(
            [], offenders,
            "these are installed as executables and will not exec: " + ", ".join(offenders))

    def test_every_installed_program_starts_with_a_usable_shebang(self) -> None:
        """The positive half. Nothing above would notice a missing `#!` at all."""
        programs = tracked_programs()
        self.assertTrue(programs, "no installed programs were found to check")
        for path, _ in programs:
            with self.subTest(program=path):
                first = index_blob(path).split(b"\n", 1)[0]
                self.assertTrue(first.startswith(b"#!"), f"no shebang: {first[:40]!r}")
                interpreter = first[2:].split()[0].decode("utf-8", "replace")
                self.assertTrue(
                    interpreter.startswith("/"),
                    f"the interpreter is not an absolute path: {interpreter!r}")
                self.assertEqual(
                    interpreter, interpreter.strip(),
                    f"the interpreter path carries whitespace: {interpreter!r}")

    def test_the_wallpaper_the_dconf_default_names_is_installed_there(self) -> None:
        """The default and the route have to agree or the desktop has no wallpaper."""
        dconf = (ROOT / "shell/components/dconf/10-bunny-shell").read_text(encoding="utf-8")
        uri = re.search(r"^picture-uri='file://([^']+)'", dconf, re.M).group(1)
        routes = routes_for_profile("beta")
        source = "shell/assets/wallpapers/" + Path(uri).name
        self.assertTrue((ROOT / source).is_file(), f"{source} is not in the repository")
        destinations = [
            installed_destination(route, source) for route in routes
            if installed_destination(route, source)
        ]
        self.assertEqual(destinations, [uri])

    def test_a_minimal_profile_gets_no_desktop(self) -> None:
        routes = routes_for_profile("minimal")
        relative = "shell/components/gnome-shell-extension/lib/desktopShell.js"
        self.assertEqual(
            [installed_destination(route, relative) for route in routes
             if installed_destination(route, relative)],
            [])


class ExtensionContractTests(unittest.TestCase):
    def test_metadata_still_targets_the_shipped_shell(self) -> None:
        metadata = json.loads((EXTENSION / "metadata.json").read_text(encoding="utf-8"))
        self.assertIn("50", metadata["shell-version"])
        self.assertEqual(metadata["settings-schema"], "org.gnome.shell.extensions.bunny-shell")

    def test_the_desktop_can_be_turned_off_without_removing_the_extension(self) -> None:
        schema = (EXTENSION / "schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml").read_text(
            encoding="utf-8")
        self.assertIn('name="desktop-enabled"', schema)
        self.assertIn('name="desktop-blur"', schema)

    def test_every_keybinding_the_desktop_registers_exists_in_the_schema(self) -> None:
        """addKeybinding on a key the schema lacks aborts enable() with a GLib error."""
        schema = (EXTENSION / "schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml").read_text(
            encoding="utf-8")
        declared = set(re.findall(r'<key name="([^"]+)" type="as">', schema))
        used = set(re.findall(r"bind\('([^']+)'", module_text("lib/desktopShell.js")))
        used |= set(re.findall(r"\['(open-[\w-]+)', '", module_text("extension.js")))
        self.assertEqual(used - declared, set(), "keybindings used but not declared in the schema")

    def test_failure_to_start_the_desktop_restores_the_gnome_panel(self) -> None:
        """Otherwise a bad enable() leaves a session with no top bar and no way back."""
        text = module_text("extension.js")
        self.assertIn("_recoverToGnomeDesktop", text)
        self.assertIn("Main.layoutManager.panelBox.show()", text)
        self.assertIn("Main.layoutManager.panelBox.show()", module_text("lib/desktopShell.js"))

    def test_the_safe_session_starts_neither_half(self) -> None:
        self.assertIn(
            "if (GLib.getenv('BUNNY_SHELL_MODE') !== 'normal')", module_text("extension.js"))


class NavigationContractTests(unittest.TestCase):
    def test_the_sidebar_carries_the_items_the_brief_names(self) -> None:
        ids = set(re.findall(r"\{id: '([\w-]+)'", module_text("lib/sidebar.js")))
        self.assertLessEqual(
            {"home", "assistant", "files", "apps", "settings", "terminal", "store"}, ids)

    def test_the_dock_carries_the_entries_the_brief_names(self) -> None:
        ids = set(re.findall(r"\{id: '([\w-]+)'", module_text("lib/bottomDock.js")))
        self.assertLessEqual(
            {"assistant", "files", "browser", "vscode", "terminal", "spotify", "applications"}, ids)

    def test_launching_goes_through_the_launcher_service(self) -> None:
        """OS integration behind services: no component spawns a process itself."""
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            relative = path.relative_to(EXTENSION).as_posix()
            if relative in {"extension.js", "lib/services/launcher.js",
                            "lib/services/search.js", "lib/services/assistant.js",
                            "lib/services/voice.js", "lib/services/agenda.js",
                            "lib/services/network.js"}:
                continue
            if "Gio.Subprocess.new" in path.read_text(encoding="utf-8"):
                offenders.append(relative)
        self.assertEqual(offenders, [], "components spawning processes outside a service")


class InstalledCommandTests(unittest.TestCase):
    """Every bunny-* command has to survive being at /usr/bin.

    The scripts in shell/services/bin add the installed Python tree to sys.path
    with a candidate list that also names the repository root as
    ``Path(__file__).resolve().parents[3]`` — correct from a checkout, where the
    script is four levels down. Installed, the script is /usr/bin/<name>, whose
    resolved path has three parents, and a *tuple literal* evaluates both
    entries before the loop sees either: IndexError during construction, and
    the installed tree — the entry that would have worked — never tried.

    Measured on a booted image, where `bunny-shell-assistant health` produced
    `IndexError: 3` and the assistant card had no runtime. `bunny-companion`
    carried the identical line and had simply never been run from /usr/bin.

    Checked statically, and the first attempt at checking it functionally is
    the reason why: copying the script into a temporary directory and running
    it there does not reproduce the fault, because a temporary directory is
    several levels deep and `parents[3]` resolves happily. The negative control
    passed, which is exactly what a test that cannot see the bug looks like.
    Reproducing it needs a path with precisely three parents, which is
    `/usr/bin/x` and nothing a test may create.

    So the rule is encoded instead of the symptom: a script that indexes
    `.parents[n]` must also measure `len(...parents)` before it does. That is
    what the fix is, it is portable, and it fails on the unguarded form.
    """

    COMMAND_DIRECTORIES = ("shell/services/bin", "installer/bin")

    def test_the_voice_settings_page_can_reach_the_companion(self) -> None:
        """`bunny-settings` adds bunny_shell to the path, and nothing added companion.

        Measured on a booted image, on screen: the Voice page read "Voice
        settings are unavailable because Bunny Companion is not reachable: No
        module named 'companion'". /usr/bin/bunny-settings puts
        /usr/lib/bunny-shell on sys.path so `bunny_shell` imports; `companion`
        lives in /usr/lib/bunny-os/python and nothing put that there. So the
        engine selector, the provider list and the readiness text were
        unreachable on every installed system, behind a message that blamed the
        service.

        The guard is the same one the bridge uses: try the import first, and
        only fall back to the installed tree, so a checkout is never shadowed.
        """
        text = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn("_make_the_companion_importable", text)
        body = text.split("def _make_the_companion_importable", 1)[1].split(chr(10) + "def ", 1)[0]
        self.assertIn("/usr/lib/bunny-os/python", body)
        self.assertIn("import companion.protocol", body)
        self.assertIn("return", body.split("except ImportError", 1)[0],
                      "an unconditional prepend would shadow a developer's checkout")
        page = text.split("def _voice_settings", 1)[1]
        self.assertLess(
            page.index("_make_the_companion_importable()"),
            page.index("from companion.protocol import"),
            "the path has to be arranged before the import that needs it")

    def _commands(self):
        for directory in self.COMMAND_DIRECTORIES:
            base = ROOT / directory
            if not base.is_dir():
                continue
            for script in sorted(base.iterdir()):
                if not script.is_file():
                    continue
                text = script.read_text(encoding="utf-8", errors="replace")
                if "python3" not in text[:200]:
                    continue
                yield f"{directory}/{script.name}", text

    #: /usr/bin/<name> has three parents: /usr/bin, /usr and /. Indices 0..2
    #: resolve there; 3 and beyond do not, and are the ones that need a guard.
    #: bunny-approvals and its siblings use parents[1] and are correct as they
    #: stand — a rule that flagged them too would be a rule people switch off.
    SAFE_AT_USR_BIN = 3

    def test_no_command_indexes_past_its_own_path_depth_unguarded(self) -> None:
        for name, text in self._commands():
            deep = [int(index) for index in re.findall(r"\.parents\[(\d+)\]", text)
                    if int(index) >= self.SAFE_AT_USR_BIN]
            if not deep:
                continue
            with self.subTest(command=name):
                self.assertRegex(
                    text, r"len\(\s*[\w.]+\.parents\s*\)",
                    f"{name} indexes .parents[{max(deep)}] without checking how many there "
                    "are; installed at /usr/bin there are three, and the index raises "
                    "IndexError while the candidate list is being built")

    def test_a_command_that_needs_the_python_tree_names_it_first(self) -> None:
        """The entry that works on the image must not sit behind the one that throws."""
        for name, text in self._commands():
            if not re.search(r"\.parents\[(\d+)\]", text):
                continue
            if not any(int(index) >= self.SAFE_AT_USR_BIN
                       for index in re.findall(r"\.parents\[(\d+)\]", text)):
                continue
            with self.subTest(command=name):
                self.assertIn("/usr/lib/bunny-os/python", text)


class AssistantBridgeTests(unittest.TestCase):
    """The bridge is a real program; run it."""

    BRIDGE = ROOT / "shell/services/bin/bunny-shell-assistant"

    def test_health_reports_a_reason_when_no_runtime_is_listening(self) -> None:
        """The state on a checkout, and on any machine where the service is down.

        Asserted because "unavailable" with no reason is what the assistant card
        would otherwise have to show, and a user cannot act on that.
        """
        result = subprocess.run(
            [sys.executable, str(self.BRIDGE), "health"],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, f"expected one event, got {lines}")
        document = json.loads(lines[0])
        self.assertEqual(document["event"], "health")
        self.assertIn("available", document)
        if not document["available"]:
            self.assertTrue(document["reason"], "unavailable with no reason")
            self.assertIn("systemctl", document["hint"])

    def test_an_empty_request_is_refused_rather_than_submitted(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.BRIDGE), "ask", "   "],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
        self.assertEqual(result.returncode, 2)
        document = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(document["event"], "error")

    def test_the_bridge_does_not_reimplement_the_protocol(self) -> None:
        text = self.BRIDGE.read_text(encoding="utf-8")
        self.assertIn("from companion.protocol import", text)
        self.assertNotIn("socket.socket", text)

    def test_the_desktop_has_no_second_protocol_client(self) -> None:
        """GJS must reach the companion only through the bridge."""
        for path in sorted(EXTENSION.rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(module=path.relative_to(EXTENSION).as_posix()):
                self.assertNotIn("bunny-companion/companion.sock", text)
                self.assertNotIn("UnixSocketAddress", text)


def _load_bridge():
    """Import the bridge as a module, despite it having no ``.py`` suffix."""
    import importlib.util

    path = ROOT / "shell/services/bin/bunny-shell-assistant"
    spec = importlib.util.spec_from_loader(
        "bunny_shell_assistant",
        importlib.machinery.SourceFileLoader("bunny_shell_assistant", str(path)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApprovalIsNotASlowAnswerTests(unittest.TestCase):
    """A task waiting for permission must not be reported as a timeout.

    The desktop showed *"the runtime did not finish within the deadline"* where a
    permission question should have been. Nothing was broken in the runtime: the
    task had reached ``waiting_for_approval`` and was waiting for a person, and
    ``watch`` held one clock for both a slow answer and an unanswered question.

    The test spends real time on purpose. A structural check — "the source
    mentions ``waiting_since``" — would pass against an implementation that
    tracked the value and never subtracted it, which is the failure this guards.
    """

    class _Runtime:
        """A task that sits in ``waiting_for_approval`` and then completes."""

        def __init__(self, asking_for: float) -> None:
            self.asking_for = asking_for
            self.started = time.monotonic()
            self.revision = 0

        def get_presentation_state(self, task_id: str) -> dict:
            self.revision += 1
            if time.monotonic() - self.started < self.asking_for:
                return {
                    "revision": self.revision,
                    "state": {
                        "phase": "waiting_for_approval",
                        "statusText": "May I?",
                        "approvalState": "pending",
                        "approvals": [{
                            "requestId": "approval:1",
                            "decision": "pending",
                            "action": "launch_application",
                            "reason": "Bunny Image Tool wants to open a file.",
                        }],
                    },
                }
            return {
                "revision": self.revision,
                "state": {"phase": "success", "resultSummary": "Done."},
            }

    def _run_watch(self, runtime, budget: float) -> tuple[int, list[dict]]:
        bridge = _load_bridge()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = bridge.watch(runtime, "task-1",
                                deadline=time.monotonic() + budget)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        return code, events

    def test_a_question_on_screen_does_not_spend_the_deadline(self) -> None:
        code, events = self._run_watch(self._Runtime(asking_for=1.2), budget=0.6)
        reasons = [e.get("reason") for e in events if e.get("event") == "error"]
        self.assertEqual(
            [], reasons,
            "a task waiting for permission was reported as a runtime timeout")
        self.assertEqual(0, code)
        self.assertEqual(
            ["approval:1"],
            [e["requestId"] for e in events if e.get("event") == "approval"],
            "the question the person was waiting on was never emitted")
        self.assertIn("finished", [e.get("event") for e in events])

    def test_the_deadline_still_ends_a_task_that_hangs_without_asking(self) -> None:
        """The clock is suspended, not removed.

        Without this, the fix for the first test would be "never time out",
        which would leave a genuinely stuck runtime spinning forever behind a
        thinking animation.
        """

        class _Stuck:
            revision = 0

            def get_presentation_state(self, task_id: str) -> dict:
                _Stuck.revision += 1
                return {"revision": _Stuck.revision,
                        "state": {"phase": "working", "statusText": "…"}}

        code, events = self._run_watch(_Stuck(), budget=0.5)
        self.assertEqual(5, code)
        self.assertIn(
            "the runtime did not finish within the deadline",
            [e.get("reason") for e in events if e.get("event") == "error"])

    def test_time_spent_asking_is_not_credited_back_as_runtime_budget(self) -> None:
        """A task that stops waiting resumes the deadline it had left.

        The wrong fix is to restart the clock when the answer arrives, which
        hands a task a fresh full budget for every question it asks. Here the
        runtime asks briefly and then hangs; the remaining budget is small, so
        it must still time out.
        """

        class _AsksThenHangs:
            def __init__(self) -> None:
                self.started = time.monotonic()
                self.revision = 0

            def get_presentation_state(self, task_id: str) -> dict:
                self.revision += 1
                waiting = 0.3 < (time.monotonic() - self.started) < 0.9
                if waiting:
                    return {"revision": self.revision, "state": {
                        "phase": "waiting_for_approval",
                        "approvals": [{"requestId": "approval:2", "decision": "pending"}],
                    }}
                return {"revision": self.revision,
                        "state": {"phase": "working", "statusText": "…"}}

        code, events = self._run_watch(_AsksThenHangs(), budget=0.8)
        self.assertEqual(5, code, "a hung task survived because it had asked a question")
        self.assertIn(
            "the runtime did not finish within the deadline",
            [e.get("reason") for e in events if e.get("event") == "error"])


# ===========================================================================
# The Alpha validation phase. Everything below guards a defect that was found
# by looking at a booted machine or at a rendered picture, not by reasoning
# about the source.
# ===========================================================================


def run_node(script: str) -> object:
    """Evaluate an ES module fragment under node and parse what it prints."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is unavailable on this host")
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"node refused the module: {result.stderr.strip()}")
    return json.loads(result.stdout)


class StorageSelectionTests(unittest.TestCase):
    """Which filesystem "Storage" means, decided from a mount table.

    The desktop's first booted image reported ``14.2 MB / 14.2 MB`` on a machine
    with a 14 GB partition. Nothing was broken and no number was invented: ``/``
    is an ostree composefs mount and statfs on it describes the composed image.
    That is the shape of wrong the ``Unavailable`` discipline cannot catch,
    because a confident measurement of the wrong object is indistinguishable
    from a measurement of the right one.

    ``lib/services/storage.js`` imports nothing, so the decision can be made
    here against fixture mount tables — including the exact one that produced
    the 14.2 MB reading.
    """

    #: A bootc/ostree machine: composefs root, real disk at /sysroot, /var and
    #: /var/home bound from it. This is the shape the wrong answer came from.
    OSTREE = """\
23 1 0:22 / / rw,relatime shared:1 - overlay overlay rw,lowerdir=/run/ostree/.private/cfsroot-lower
24 23 0:23 / /proc rw,nosuid,nodev,noexec shared:2 - proc proc rw
25 23 0:24 / /sys rw,nosuid,nodev,noexec shared:3 - sysfs sysfs rw
26 23 0:6 / /dev rw,nosuid shared:4 - devtmpfs devtmpfs rw,size=4096k
27 23 0:25 / /run rw,nosuid,nodev shared:5 - tmpfs tmpfs rw,mode=755
28 23 0:26 / /tmp rw,nosuid,nodev shared:6 - tmpfs tmpfs rw
40 23 254:4 / /sysroot rw,relatime shared:7 - ext4 /dev/vda4 rw,seclabel
41 23 254:4 /ostree/deploy/default/var /var rw,relatime shared:8 - ext4 /dev/vda4 rw,seclabel
42 23 254:2 / /boot rw,relatime shared:9 - ext4 /dev/vda2 rw,seclabel
43 42 254:1 / /boot/efi rw,relatime shared:10 - vfat /dev/vda1 rw
"""

    #: An ordinary installation: one writable ext4 root.
    ORDINARY = """\
23 1 254:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw,seclabel
24 23 0:23 / /proc rw,nosuid,nodev,noexec shared:2 - proc proc rw
25 23 0:25 / /run rw,nosuid,nodev shared:3 - tmpfs tmpfs rw,mode=755
"""

    #: A live session: read-only squashfs root, everything writable on tmpfs.
    LIVE = """\
23 1 0:22 / / ro,relatime shared:1 - squashfs /dev/loop0 ro
24 23 0:25 / /run rw,nosuid,nodev shared:2 - tmpfs tmpfs rw,mode=755
25 23 0:30 / /home rw,relatime shared:3 - tmpfs tmpfs rw
26 23 0:31 / /var rw,relatime shared:4 - tmpfs tmpfs rw
"""

    #: Everything read-only: a recovery shell with no writable filesystem.
    READ_ONLY = """\
23 1 254:1 / / ro,relatime shared:1 - ext4 /dev/sda1 ro,seclabel
24 23 0:23 / /proc rw,nosuid,nodev,noexec shared:2 - proc proc rw
"""

    #: A machine whose data is on its own partition, mounted nowhere the rules
    #: name. The last-resort rule is what has to answer this one.
    SEPARATE_DATA = """\
23 1 0:22 / / ro,relatime shared:1 - squashfs /dev/loop0 ro
24 23 0:25 / /run rw,nosuid,nodev shared:2 - tmpfs tmpfs rw,mode=755
30 23 254:5 / /data rw,relatime shared:3 - xfs /dev/sdb1 rw
"""

    @staticmethod
    def select(mountinfo: str, home: str | None) -> dict:
        module = (LIB / "services/storage.js").as_uri()
        script = "\n".join([
            f"import {{parseMountinfo, selectStorageMount}} from '{module}';",
            f"const text = {json.dumps(mountinfo)};",
            f"const home = {json.dumps(home)};",
            "const choice = selectStorageMount(parseMountinfo(text), {homeDirectory: home});",
            "console.log(JSON.stringify({",
            "  mountPoint: choice.mount ? choice.mount.mountPoint : null,",
            "  filesystemType: choice.mount ? choice.mount.filesystemType : null,",
            "  role: choice.role, rejected: choice.rejected,",
            "}));",
        ])
        return run_node(script)

    def test_a_composefs_root_never_wins(self) -> None:
        """The 14.2 MB reading, as a regression test."""
        choice = self.select(self.OSTREE, "/var/home/bunny")
        self.assertNotEqual(choice["mountPoint"], "/")
        self.assertNotEqual(choice["filesystemType"], "overlay")

    def test_a_composefs_root_with_a_persistent_home_reports_the_disk(self) -> None:
        choice = self.select(self.OSTREE, "/var/home/bunny")
        self.assertEqual(choice["mountPoint"], "/var")
        self.assertEqual(choice["filesystemType"], "ext4")
        self.assertEqual(choice["role"], "user-data")

    def test_an_ordinary_ext4_root_reports_the_root(self) -> None:
        choice = self.select(self.ORDINARY, "/home/bunny")
        self.assertEqual(choice["mountPoint"], "/")
        self.assertEqual(choice["filesystemType"], "ext4")

    def test_a_tmpfs_only_session_reports_nothing(self) -> None:
        """A live session's home is a tmpfs; its capacity is not storage."""
        choice = self.select(self.LIVE, "/home/live")
        self.assertIsNone(choice["mountPoint"])
        self.assertTrue(any("does not survive" in entry["reason"]
                            for entry in choice["rejected"]))

    def test_a_read_only_root_reports_nothing(self) -> None:
        choice = self.select(self.READ_ONLY, "/root")
        self.assertIsNone(choice["mountPoint"])

    def test_a_separate_data_partition_is_found_by_the_last_rule(self) -> None:
        choice = self.select(self.SEPARATE_DATA, "/home/bunny")
        self.assertEqual(choice["mountPoint"], "/data")
        self.assertEqual(choice["role"], "persistent-mount")

    def test_boot_is_never_reported_as_user_storage(self) -> None:
        """/boot is real, writable and 600 MB. It is not the machine's storage."""
        choice = self.select(self.OSTREE, "/var/home/bunny")
        self.assertNotIn(choice["mountPoint"], ("/boot", "/boot/efi"))

    def test_the_reason_a_candidate_was_skipped_is_carried(self) -> None:
        """"Unavailable" with no explanation is what made the first bug invisible."""
        choice = self.select(self.LIVE, "/home/live")
        self.assertTrue(choice["rejected"])
        for entry in choice["rejected"]:
            self.assertTrue(entry["reason"].strip())

    def test_the_telemetry_reader_asks_the_mount_table(self) -> None:
        text = module_text("lib/services/telemetry.js")
        self.assertIn("/proc/self/mountinfo", text)
        self.assertIn("selectStorageMount", text)

    def test_storage_js_imports_nothing(self) -> None:
        """The property that makes every test above possible."""
        text = module_text("lib/services/storage.js")
        self.assertNotIn("import ", text.split("*/")[-1] if "*/" in text else text)
        self.assertNotIn("gi://", text)


class CompactFigureTests(unittest.TestCase):
    """A used-of-total pair has to fit beside its label in the narrow card.

    `3.9 GB / 8.3 GB` does not: at the compact breakpoint the card is 248 pixels
    and the value ellipsised to `3.9 GB…`, dropping the half of the figure that
    gives the other half a meaning. Measured on the 1366x768 boot of the Alpha
    image, not predicted.
    """

    #: Roughly what fits beside a label in a 248px card at 11px. Deliberately a
    #: character count rather than a pixel measurement: this test cannot lay out
    #: text, and the failure it guards is an order-of-magnitude one.
    BUDGET = 12

    @classmethod
    def setUpClass(cls) -> None:
        # format.js, not util.js: the formatters live in a module that imports
        # nothing so this can evaluate the real function rather than a copy.
        module = (LIB / "format.js").as_uri()
        cls.cases = run_node("\n".join([
            f"import {{formatPair}} from '{module}';",
            "const cases = [",
            "  [1023, 6227702579], [4187593114, 8912896000],",
            "  [0, 8912896000], [8912896000, 8912896000],",
            "  [512, 2048], [1536, 1048576],",
            "];",
            "console.log(JSON.stringify(cases.map(([u, t]) => "
            "({used: u, total: t, text: formatPair(u, t)}))));",
        ]))

    def test_every_pair_fits_the_narrow_card(self) -> None:
        for case in self.cases:
            with self.subTest(**case):
                self.assertIsNotNone(case["text"])
                self.assertLessEqual(len(case["text"]), self.BUDGET, case["text"])

    def test_both_numbers_survive(self) -> None:
        """Short is not the goal; short *and complete* is."""
        for case in self.cases:
            with self.subTest(**case):
                self.assertIn("/", case["text"])
                left, right = case["text"].split("/")
                self.assertTrue(left.strip())
                self.assertTrue(right.strip())

    def test_one_unit_for_both_numbers(self) -> None:
        """`975.5 MB / 5.8 GB` invites a comparison between different units."""
        for case in self.cases:
            with self.subTest(**case):
                self.assertEqual(len(re.findall(r"[KMGT]?B", case["text"])), 1)

    def test_a_refused_measurement_is_still_null(self) -> None:
        result = run_node("\n".join([
            f"import {{formatPair}} from '{(LIB / 'format.js').as_uri()}';",
            "console.log(JSON.stringify([formatPair(1, 0), formatPair(null, 10), "
            "formatPair(1, null)]));",
        ]))
        self.assertEqual(result, [None, None, None])

    def test_the_card_uses_it(self) -> None:
        text = module_text("lib/cards/systemOverview.js")
        self.assertIn("formatPair(memory.usedBytes", text)
        self.assertIn("formatPair(storage.usedBytes", text)

    def test_the_dial_gives_the_figures_room_on_a_narrow_card(self) -> None:
        """A shorter string was not enough on its own.

        With `formatPair` alone, RAM fitted and Storage did not — the label is
        four characters longer and the 96-pixel dial was taking 39% of a
        248-pixel card. Both halves of the fix are needed and both are checked,
        because a future change that restores the fixed dial size would put the
        truncation back with the shorter string still in place.
        """
        text = module_text("lib/cards/systemOverview.js")
        self.assertIn("resize(width)", text)
        self.assertIn("DIAL_NARROW", text)
        base = module_text("lib/cards/base.js")
        self.assertIn("this.resize(rect.width);", base,
                      "Card.show must pass its width to the card")

    def test_the_card_stacks_when_it_is_too_narrow_to_sit_side_by_side(self) -> None:
        """The third attempt, and the one that stopped depending on arithmetic.

        A shorter string fixed RAM. A smaller dial fixed nothing else, because
        "Storage" is four characters longer than "RAM". Putting the figures
        below the dial gives every row the card's full width and removes the
        question of how long a label may be.
        """
        text = module_text("lib/cards/systemOverview.js")
        self.assertIn("setOrientation(this._body, narrow)", text)
        self.assertIn("bunny-overview-body-stacked", text)
        self.assertIn(".bunny-overview-body-stacked", module_text("stylesheet.css"))

    def test_the_orientation_helper_handles_both_shell_versions(self) -> None:
        """`vertical` was removed in favour of `orientation`; both are tried."""
        text = module_text("lib/widgets.js")
        block = text.split("export function setOrientation")[1][:500]
        self.assertIn("Clutter.Orientation.VERTICAL", block)
        self.assertIn("widget.vertical = vertical", block)

    def test_the_narrow_dial_is_smaller_than_the_wide_one(self) -> None:
        text = module_text("lib/cards/systemOverview.js")
        wide = int(re.search(r"const DIAL_WIDE = (\d+);", text).group(1))
        narrow = int(re.search(r"const DIAL_NARROW = (\d+);", text).group(1))
        self.assertLess(narrow, wide)
        # And not so small it stops being a dial.
        self.assertGreaterEqual(narrow, 60)


class IconTests(unittest.TestCase):
    """Every icon name the desktop draws, against the theme that ships.

    `shop-symbolic` was the sidebar's Store icon from the day it was written and
    adwaita-icon-theme has never had it, so that row drew the missing-image
    placeholder on every boot. It is the same failure as a tofu box and nothing
    in the repository could see it, because an icon name is a string.

    tests/shell/data/adwaita-icon-inventory.txt is the icon theme's own file
    list, read from adwaita-icon-theme-50.0-1.fc44 on the reference host — the
    package build/packages/desktop.txt installs.
    """

    INVENTORY = ROOT / "tests/shell/data/adwaita-icon-inventory.txt"

    @classmethod
    def setUpClass(cls) -> None:
        cls.available = {
            line.strip() for line in cls.INVENTORY.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        cls.declared = run_node("\n".join([
            # iconNames.js, not icons.js: the names live in a module that
            # imports nothing, precisely so this check can run without a
            # compositor. icons.js re-exports them for the desktop's callers.
            f"import {{ALL_ICON_NAMES, BUNNY_ICONS}} from '{(LIB / 'iconNames.js').as_uri()}';",
            "console.log(JSON.stringify({names: ALL_ICON_NAMES, bunny: BUNNY_ICONS}));",
        ]))

    def test_the_inventory_is_not_empty(self) -> None:
        """A check whose input vanished would pass by accident."""
        self.assertGreater(len(self.available), 300)

    def test_every_declared_icon_exists_in_the_theme_or_is_ours(self) -> None:
        bunny = set(self.declared["bunny"])
        for name in self.declared["names"]:
            with self.subTest(icon=name):
                self.assertTrue(
                    name in self.available or name in bunny,
                    f"{name} is in neither the icon theme nor shell/icons")

    def test_every_bunny_icon_is_actually_in_the_repository(self) -> None:
        for name in self.declared["bunny"]:
            with self.subTest(icon=name):
                matches = list((ROOT / "shell/icons").rglob(f"{name}.svg"))
                self.assertTrue(matches, f"{name} is declared but no SVG ships it")

    def test_shop_symbolic_is_gone(self) -> None:
        """The specific name, because this is the bug that motivated the check.

        Code only. Two comments name it deliberately — the record of what was
        wrong is worth more than the tidiness of never writing the string.
        """
        self.assertNotIn("shop-symbolic", self.available)
        for path in sorted(EXTENSION.rglob("*.js")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith(("//", "*")):
                    continue
                with self.subTest(module=path.relative_to(EXTENSION).as_posix(), line=number):
                    self.assertNotIn("shop-symbolic", line)

    def test_no_module_writes_an_icon_name_inline(self) -> None:
        """What makes the list above complete rather than one somebody maintains."""
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            if path.name in ("icons.js", "iconNames.js"):
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith(("//", "*")):
                    continue
                if re.search(r"'[a-z][a-z0-9-]*-symbolic'", line):
                    offenders.append(f"{path.relative_to(EXTENSION).as_posix()}: {line.strip()}")
        self.assertEqual(offenders, [], "icon names belong in lib/iconNames.js")

    def test_a_missing_icon_falls_back_rather_than_drawing_a_broken_image(self) -> None:
        text = module_text("lib/icons.js")
        self.assertIn("has_icon", text)
        self.assertIn("logOnce(", text)


class EmojiTests(unittest.TestCase):
    """No control's meaning may depend on a codepoint the image need not have.

    Every emoji on the first booted desktop was a tofu box: the image shipped
    sans and CJK fonts and no emoji font. The font is installed now, and this
    check is not about that image — it is about the next one. A label that reads
    correctly only when a particular font package is present is a label that a
    packaging change can silently empty.
    """

    #: Codepoint ranges that are emoji, dingbats, arrows and geometric shapes:
    #: everything outside the Latin text and typographic punctuation that a
    #: desktop font is actually required to cover.
    RISKY = (
        (0x2190, 0x21FF),    # arrows
        (0x2300, 0x23FF),    # technical (⌘, ⏻)
        (0x25A0, 0x25FF),    # geometric shapes (▣)
        (0x2600, 0x27BF),    # symbols and dingbats (☀, ⚠, ✓)
        (0x2B00, 0x2BFF),    # more arrows and shapes
        (0x1F000, 0x1FAFF),  # emoji
        (0xFE0F, 0xFE0F),    # the variation selector
    )

    @classmethod
    def risky_characters(cls, text: str) -> set[str]:
        return {
            character for character in text
            if any(low <= ord(character) <= high for low, high in cls.RISKY)
        }

    @staticmethod
    def string_literals(text: str) -> list[tuple[int, str]]:
        """Every string literal in a JavaScript source, with its line number.

        A character scanner rather than a regex, because the two constructs that
        have to be told apart both contain the same characters: a comment
        describing an emoji and a label containing one. Several comments in
        lib/iconNames.js name the glyph each icon replaced, and that record is
        worth more than the tidiness of never writing the character — so the
        scanner has to know it is inside a comment, which a regex over lines
        cannot reliably do once a backtick appears in one.
        """
        found: list[tuple[int, str]] = []
        index = 0
        line = 1
        length = len(text)
        while index < length:
            character = text[index]
            if character == "\n":
                line += 1
                index += 1
            elif text.startswith("//", index):
                while index < length and text[index] != "\n":
                    index += 1
            elif text.startswith("/*", index):
                end = text.find("*/", index + 2)
                end = length if end == -1 else end + 2
                line += text.count("\n", index, end)
                index = end
            elif character in "'\"`":
                quote = character
                start_line = line
                index += 1
                literal = []
                while index < length:
                    if text[index] == "\\":
                        index += 2
                        continue
                    if text[index] == quote:
                        index += 1
                        break
                    if text[index] == "\n":
                        line += 1
                    literal.append(text[index])
                    index += 1
                found.append((start_line, "".join(literal)))
            else:
                index += 1
        return found

    def test_no_user_facing_string_carries_an_emoji(self) -> None:
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            for number, literal in self.string_literals(path.read_text(encoding="utf-8")):
                found = self.risky_characters(literal)
                if found:
                    offenders.append(
                        f"{path.relative_to(EXTENSION).as_posix()}:{number} "
                        f"{' '.join('U+%04X' % ord(c) for c in sorted(found))}")
        self.assertEqual(offenders, [], "use an icon from lib/icons.js, not a glyph")

    def test_the_stylesheet_carries_no_emoji_either(self) -> None:
        found = self.risky_characters(module_text("stylesheet.css"))
        self.assertEqual(found, set())

    def test_the_throughput_arrows_are_icons(self) -> None:
        text = module_text("lib/cards/systemMonitor.js")
        self.assertIn("Icons.UPLOAD", text)
        self.assertIn("Icons.DOWNLOAD", text)


class CharacterFigureTests(unittest.TestCase):
    """The figure, measured on its own pixels.

    The character has read as a robed figure on two separate booted images. Both
    times the fault was visible in the first picture anybody took, and both
    times nothing in this repository could have said so: "does it look like a
    person in a hoodie" is not a question about source code.

    Three parts of it are, though, once the figure can be rendered outside a
    compositor — which lib/character/figure.js exists to allow. A robe is a
    single mass below the waist; a hoodie over trousers is a garment that ends,
    and two legs with daylight between them. Those are countable.

    Rendered with gjs. Where gjs is absent the test skips rather than passing:
    a silent pass on the reference host is how the first version shipped.
    """

    FIGURE = LIB / "character/figure.js"
    WIDTH = 200
    HEIGHT = 300

    @classmethod
    def setUpClass(cls) -> None:
        gjs = shutil.which("gjs")
        if not gjs:
            raise unittest.SkipTest("gjs is unavailable on this host")
        # Render idle to a PPM the test can read without an image library, and
        # report the geometry the definition claims, so the two can be compared.
        script = f"""
import Cairo from 'cairo';
const {{drawFigure}} = await import('{cls.FIGURE.as_uri()}');
const {{DEFAULT_CHARACTER}} = await import('{(LIB / "character/definition.js").as_uri()}');
const pose = {{
    breathe: 0, bob: 0, armLift: 0, headTilt: 0, lean: 0,
    eyeOpen: 1, mouthOpen: 0.06, glow: 1, accent: 'rimLight',
    indicator: 'none', indicatorPhase: 0,
}};
const surface = new Cairo.ImageSurface(Cairo.Format.ARGB32, {cls.WIDTH}, {cls.HEIGHT});
const cr = new Cairo.Context(surface);
drawFigure(cr, DEFAULT_CHARACTER, pose, {cls.WIDTH}, {cls.HEIGHT});
cr.$dispose();
surface.writeToPNG('{{PNG}}');
print(JSON.stringify(DEFAULT_CHARACTER.geometry));
"""
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "figure.png"
            source = Path(directory) / "render.js"
            source.write_text(script.replace("{PNG}", png.as_posix()), encoding="utf-8")
            result = subprocess.run(
                [gjs, "-m", str(source)], capture_output=True, text=True, timeout=120, cwd=ROOT)
            if result.returncode != 0:
                raise AssertionError(f"the figure would not render: {result.stderr.strip()}")
            cls.geometry = json.loads(result.stdout)
            cls.pixels, cls.size = cls._read_png(png)

    @staticmethod
    def _read_png(path: Path):
        """Alpha coverage per pixel, without an image library.

        Cairo writes a PNG; zlib and struct are enough to get the raw pixels
        back out of one, and adding an image dependency to the test suite for
        this would be a poor trade.
        """
        import struct
        import zlib

        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        offset = 8
        width = height = 0
        idat = b""
        while offset < len(data):
            length, kind = struct.unpack(">I4s", data[offset:offset + 8])
            body = data[offset + 8:offset + 8 + length]
            if kind == b"IHDR":
                width, height, depth, colour = struct.unpack(">IIBB", body[:10])
                assert depth == 8 and colour == 6, (depth, colour)
            elif kind == b"IDAT":
                idat += body
            offset += 12 + length
        raw = zlib.decompress(idat)

        stride = width * 4
        rows = []
        previous = bytearray(stride)
        position = 0
        for _ in range(height):
            filter_type = raw[position]
            position += 1
            line = bytearray(raw[position:position + stride])
            position += stride
            for index in range(stride):
                left = line[index - 4] if index >= 4 else 0
                up = previous[index]
                upper_left = previous[index - 4] if index >= 4 else 0
                if filter_type == 1:
                    line[index] = (line[index] + left) & 0xFF
                elif filter_type == 2:
                    line[index] = (line[index] + up) & 0xFF
                elif filter_type == 3:
                    line[index] = (line[index] + (left + up) // 2) & 0xFF
                elif filter_type == 4:
                    p = left + up - upper_left
                    pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                    predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upper_left)
                    line[index] = (line[index] + predictor) & 0xFF
            rows.append(bytes(line))
            previous = line
        # Alpha is the fourth byte of each BGRA/RGBA quad; Cairo's ARGB32 is
        # premultiplied and written as RGBA by writeToPNG.
        return [[row[x * 4 + 3] for x in range(width)] for row in rows], (width, height)

    def runs_at(self, y: int) -> list[tuple[int, int]]:
        """Horizontal runs of drawn pixels on one scanline."""
        row = self.pixels[y]
        runs = []
        start = None
        for x, alpha in enumerate(row):
            if alpha > 40 and start is None:
                start = x
            elif alpha <= 40 and start is not None:
                runs.append((start, x - 1))
                start = None
        if start is not None:
            runs.append((start, len(row) - 1))
        # Ignore hairline runs: an anti-aliased edge or the rim light is not a
        # limb, and counting one as a leg would make this test pass for the
        # wrong reason.
        return [run for run in runs if run[1] - run[0] >= 3]

    def unit_to_pixel_y(self, unit: float) -> int:
        """The 100x150 definition box maps into the surface, centred."""
        scale = min(self.WIDTH / 100, self.HEIGHT / 150)
        top = (self.HEIGHT - 150 * scale) / 2
        return int(round(top + unit * scale))

    def test_the_legs_are_two_separated_shapes(self) -> None:
        """The robe test.

        Measured a third of the way down the shin, below the hem and above the
        shoes. A robe gives one run here; a person in trousers gives two.
        """
        hip = self.geometry["hip"]["y"]
        length = self.geometry["leg"]["length"]
        y = self.unit_to_pixel_y(hip + length * 0.45)
        runs = self.runs_at(y)
        self.assertEqual(
            len(runs), 2,
            f"expected two legs at y={y}, found {len(runs)} run(s): {runs}")

    def test_there_is_real_daylight_between_the_legs(self) -> None:
        """Two runs one pixel apart is one leg with a seam drawn on it."""
        hip = self.geometry["hip"]["y"]
        length = self.geometry["leg"]["length"]
        y = self.unit_to_pixel_y(hip + length * 0.45)
        runs = self.runs_at(y)
        self.assertEqual(len(runs), 2)
        gap = runs[1][0] - runs[0][1]
        self.assertGreaterEqual(gap, 4, f"only {gap}px between the legs")

    def ink_at(self, y: int) -> int:
        """How much figure there is on one scanline, in pixels.

        The sum of the runs, not the distance from the first to the last. Extent
        is the wrong measure here and measuring it was the first mistake in this
        test: at hem height the extent includes the two hands hanging beside the
        hips, so a correct figure reported a hem wider than its own shoulders.
        Ink is what actually separates the two silhouettes — a robe keeps its
        ink all the way to the floor, and a person in trousers loses half of it
        the moment the garment ends.
        """
        return sum(end - start + 1 for start, end in self.runs_at(y))

    def test_the_silhouette_loses_half_its_ink_where_the_garment_ends(self) -> None:
        """The robe test, from the other direction.

        A robe has no hem: the garment continues past the knee and the figure is
        as wide at the shin as at the waist. A hoodie over trousers narrows
        sharply, once, at a specific height — and that abrupt loss is the thing
        a reader's eye uses to decide it is looking at clothes rather than a
        cassock.
        """
        hem = self.geometry["torso"]["hem"]
        above = self.ink_at(self.unit_to_pixel_y(hem - 4))
        below = self.ink_at(self.unit_to_pixel_y(hem + 14))
        self.assertGreater(above, 0)
        self.assertLess(
            below, above * 0.7,
            f"{below}px of figure below the hem against {above}px above it: "
            "the garment does not visibly end")

    def test_the_stance_is_wider_than_the_hips(self) -> None:
        """A figure balancing on a point reads as a robe even with two legs."""
        stance = (self.geometry["leg"]["separation"] + self.geometry["leg"]["thighWidth"])
        self.assertGreater(stance, self.geometry["hip"]["halfWidth"] * 2)

    def test_the_head_is_narrower_than_the_shoulders(self) -> None:
        """A head as wide as the shoulders is a mascot, not a person."""
        head = self.ink_at(self.unit_to_pixel_y(self.geometry["headCentre"][1]))
        shoulder = self.ink_at(self.unit_to_pixel_y(self.geometry["torso"]["top"] + 6))
        self.assertGreater(head, 0)
        self.assertGreater(shoulder, 0)
        self.assertLess(head, shoulder, f"head {head}px against shoulders {shoulder}px")

    def test_the_head_is_one_shape(self) -> None:
        """Two runs at the head's centre line means the face is split by something."""
        runs = self.runs_at(self.unit_to_pixel_y(self.geometry["headCentre"][1]))
        self.assertEqual(len(runs), 1, f"the head is drawn as {len(runs)} shapes: {runs}")

    def test_the_figure_is_between_six_and_seven_heads_tall(self) -> None:
        """Stylised, but adult. Under six reads as a child or a mascot."""
        occupied = [y for y, row in enumerate(self.pixels) if any(alpha > 40 for alpha in row)]
        self.assertTrue(occupied)
        scale = min(self.WIDTH / 100, self.HEIGHT / 150)
        # The ground shadow is drawn below the feet and is part of the scene,
        # not the figure, so the body ends at the shoe rather than at the last
        # drawn row.
        head_height = self.geometry["headRadius"] * 2 * scale
        body = (self.unit_to_pixel_y(
            self.geometry["hip"]["y"] + self.geometry["leg"]["length"]
            + self.geometry["shoe"]["height"]) - min(occupied))
        self.assertGreater(body / head_height, 5.8)
        self.assertLess(body / head_height, 7.5)


class CharacterStateVisualisationTests(unittest.TestCase):
    def test_every_state_declares_an_indicator(self) -> None:
        text = module_text("lib/character/definition.js")
        block = re.search(r"poses: \{(.*?)\n    \},", text, re.S).group(1)
        for name in re.findall(r"^\s*(\w+): \{", block, re.M):
            with self.subTest(state=name):
                entry = re.search(rf"{name}: \{{([^}}]*)\}}", block).group(1)
                self.assertIn("indicator:", entry)

    def test_the_state_accents_the_poses_name_are_defined_colours(self) -> None:
        """`accent: 'success'` fell through to violet for the whole first release.

        The palette had no `success`, `warning` or `error` entry, so the rim
        light's documented colour change had never once happened on screen.
        """
        text = module_text("lib/character/definition.js")
        palette = re.search(r"palette: \{(.*?)\n    \},", text, re.S).group(1)
        defined = set(re.findall(r"^\s*(\w+):", palette, re.M))
        for accent in set(re.findall(r"accent: '(\w+)'", text)):
            with self.subTest(accent=accent):
                self.assertIn(accent, defined, f"pose accent {accent!r} is not a palette colour")

    def test_the_figure_module_imports_no_gi_namespace(self) -> None:
        """What lets the character be rendered — and therefore looked at — offline."""
        text = module_text("lib/character/figure.js")
        self.assertNotIn("gi://", text)
        self.assertIn("import Cairo from 'cairo';", text)


class PointerOwnershipTests(unittest.TestCase):
    """Nothing on the dashboard could be pressed, and the cause was not ours.

    `Main.layoutManager._coverPane` is a full-screen, fully transparent,
    *reactive* actor that GNOME shows to swallow input while its startup
    animation runs, and disposes of when the animation finishes. That animation
    eases `panelBox` into place. This desktop hid `panelBox` at enable() and
    re-hid it on every `notify::visible`, so the animation never finished, the
    cover pane was never disposed of, and it sat in uiGroup above
    `window_group` taking every pointer event for the life of the session.

    Measured with `global.stage.get_actor_at_pos`, which is the compositor's own
    picking: a press at the Quick Access tile, at the microphone button, at a
    suggestion chip, at the assistant's entry and at empty desktop all returned
    `Main.layoutManager._coverPane`. The dock and the sidebar worked because
    they are chrome added *after* the pane. With the Bunny desktop switched off
    in the same image, the same points picked ordinary actors — which is how
    "GNOME does this to everyone" was ruled out.

    These assertions are on the source, because the failure is a sequence — hide
    the panel, then the animation never completes — and no widget is wrong at
    any point in it.
    """

    MODULE = "lib/desktopShell.js"

    def setUp(self) -> None:
        self.text = module_text(self.MODULE)

    def test_the_panel_is_not_hidden_before_startup_finishes(self) -> None:
        """The regression: an *unguarded* hide() as soon as the box is in hand.

        The guarded hide inside the `notify::visible` handler is the point of
        the handler and must stay; what may not come back is a hide between
        taking the panelBox and arming that handler, which is what ran during
        GNOME's animation.
        """
        body = self.text.split("_hidePanel() {", 1)[1].split("\n    }", 1)[0]
        preamble = body.split("connect('notify::visible'", 1)[0]
        self.assertNotIn(
            "hide()", preamble,
            "hiding the panel before the watcher is armed is what stopped GNOME's "
            "startup animation completing and left the cover pane over the desktop")
        self.assertIn("_takeThePanelWhenStartupIsOver", body)

    def test_the_panel_is_taken_only_after_startup_or_a_deadline(self) -> None:
        body = self.text.split("_takeThePanelWhenStartupIsOver() {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("'startup-complete'", body)
        self.assertIn("_panelTimer", body, "a signal that already fired never fires again")
        self.assertIn("_releaseTheCoverPane()", body)

    def test_the_visibility_watcher_is_inert_until_then(self) -> None:
        body = self.text.split("_hidePanel() {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("_panelMayHide", body)
        self.assertIn("!this._panelMayHide", body,
                      "the watcher must not re-hide the panel mid-animation")

    def test_the_cover_pane_is_released_rather_than_assumed_gone(self) -> None:
        body = self.text.split("_releaseTheCoverPane() {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("Main.layoutManager._coverPane", body)
        self.assertIn("pane.hide()", body)
        self.assertIn("if (!pane || !pane.visible)", body,
                      "hiding a pane GNOME is legitimately using would be worse than the bug")

    def test_no_decorative_layer_is_made_reactive_to_win_the_pick(self) -> None:
        """The fix must not be "make the desktop swallow input too".

        Reactivity belongs to controls. `makeActivatable` is the one place that
        grants it, and the content layer itself must stay non-reactive so that a
        press on empty desktop reaches whatever is behind it.
        """
        self.assertNotIn("_desktopLayer.reactive = true", self.text)
        self.assertNotIn("_desktopLayer.reactive=true", self.text)

    def test_voice_availability_is_asked_again_rather_than_once(self) -> None:
        """The companion starts after the session; one question is one race.

        The microphone button read "Speak to Bunny. Unavailable: the companion
        runtime is unreachable" with sensitive=false, for the whole session, on
        a machine whose companion was answering by the time anyone pressed it.
        """
        self.assertIn("_watchVoiceAvailability", self.text)
        body = self.text.split("_watchVoiceAvailability() {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("_voiceHealthTimer", body)
        self.assertIn("setVoiceAvailable", body)
        # The retry moved into `_pollHealth`, which the assistant now shares, so
        # the bound is checked where it lives. Still checked, and now once for
        # both consumers rather than once for the one that had the defect first.
        self.assertIn("_pollHealth(this.voice,", body, "voice must use the shared poller")
        # Matched by shape, not by the exact parameter list. This split on the
        # literal `_pollHealth(service, report) {` and broke with an IndexError
        # the moment Phase 5 gave the poller an optional `name` argument for
        # instrumentation — a change that does not touch the property this test
        # is about. A test that fails because a signature gained a defaulted
        # parameter is testing the spelling of the code, not its behaviour.
        signature = re.search(r"_pollHealth\(service, report[^)]*\) \{", self.text)
        self.assertIsNotNone(signature, "the shared health poller is gone")
        poller = self.text[signature.end():].split("\n    }", 1)[0]
        self.assertIn("attemptsLeft", poller, "the retry has to be bounded")
        self.assertRegex(poller, r"attemptsLeft\s*=\s*\d+",
                         "the bound has to be a finite number")
        self.assertIn("attemptsLeft -= 1", poller, "the bound has to be decremented")


class ApprovalPromptFocusTests(unittest.TestCase):
    """A permission question has to take the focus, and land on the safe answer.

    The two buttons were focusable and nothing ever focused them: the entry kept
    the focus it took when the panel opened. A keyboard user had to guess that a
    question had appeared and then Tab to find it, and a screen reader announced
    nothing at all, because nothing had changed focus.

    For an ordinary control that is an inconvenience. For the surface that
    decides whether an application may read someone's files it is the difference
    between being asked and being bypassed.
    """

    COMPONENT = "lib/components/trust.js"

    @classmethod
    def setUpClass(cls) -> None:
        # The question is drawn by the Trust component now, not by the panel;
        # the panel builds a model and hands it over. So the ordering property
        # is asserted where it lives, and the *decision* behind the focus —
        # deny unless the request says otherwise — is measured against the
        # projection that produces `initialFocus` rather than read out of a
        # source string in either file.
        text = module_text(cls.COMPONENT)
        start = text.index("    show(model) {")
        cls.body = text[start:text.index("\n    }", start)]

    def test_the_question_takes_the_focus(self) -> None:
        self.assertIn("_focusSafeAnswer(model)", self.body,
                      "a permission question appears without taking focus")
        self.assertIn("grab_key_focus()", module_text(self.COMPONENT))

    def test_the_focused_button_is_the_safe_default(self) -> None:
        """Deny unless the request says otherwise.

        The trust layer's oldest rule is that an unanswered question is a
        denial. The button under the finger — the one a reflexive Return
        presses — has to agree with it, so the focus follows `safeDefault`
        rather than being hard-wired to either answer.

        Measured rather than read: four approvals through the real projection.
        """
        measured = run_node(
            f"import {{buildApproval}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "const focus = approval => buildApproval(approval).initialFocus;\n"
            "console.log(JSON.stringify({\n"
            "  denied: focus({requestId: 'r', safeDefault: 'denied'}),\n"
            "  allowed: focus({requestId: 'r', safeDefault: 'allowed'}),\n"
            "  absent: focus({requestId: 'r'}),\n"
            "  nonsense: focus({requestId: 'r', safeDefault: 'yes please'}),\n"
            "}));\n"
        )
        self.assertEqual(measured["denied"], "deny")
        self.assertEqual(measured["allowed"], "allow")
        # An approval carrying no safe default, or one this build does not
        # recognise, is a question whose safe answer is unknown — and the safe
        # answer to an unknown question is no.
        self.assertEqual(measured["absent"], "deny")
        self.assertEqual(measured["nonsense"], "deny")

    def test_the_default_and_escape_actions_are_always_denial(self) -> None:
        """Whatever is focused, Return-without-reading and Escape both deny."""
        measured = run_node(
            f"import {{buildApproval}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "const m = buildApproval({requestId: 'r', safeDefault: 'allowed'});\n"
            "console.log(JSON.stringify({d: m.defaultAction, e: m.escapeAction, c: m.closeAction}));\n"
        )
        self.assertEqual(measured, {"d": "deny", "e": "deny", "c": "deny"})

    def test_focus_is_taken_only_once_the_prompt_is_visible(self) -> None:
        """Focusing a hidden actor does nothing and loses the announcement."""
        self.assertLess(
            self.body.index("this.actor.visible = true"),
            self.body.index("_focusSafeAnswer(model)"),
            "focus is grabbed before the prompt is shown")


class QuickAccessLabelTests(unittest.TestCase):
    """Five of eight launcher labels were unreadable on the booted desktop.

    Photographed at 1920x1080:

        Files      Terminal    Bunny       Bunny App…
        Bunny Co…  Bunny Dia…  Bunny Lau…  Bunny Sett…

    Four of the ellipsised four began "Bunny ", so the truncation removed
    exactly the word that told them apart — and "Bunny Co…" is either Bunny
    Command or Bunny Companion, both of which this image installs.

    The tile is 55px by deliberate arithmetic, so the label had to get shorter
    rather than the tile wider.
    """

    @classmethod
    def setUpClass(cls) -> None:
        module = (LIB / "format.js").as_uri()
        cls.labels = run_node("\n".join([
            f"import {{tileLabel}} from '{module}';",
            "const names = ['Bunny Companion', 'Bunny Command', 'Bunny Settings',",
            "  'Bunny Diagnostics', 'Bunny', 'Files', 'Terminal', 'Bunny ', ''];",
            "console.log(JSON.stringify(Object.fromEntries(",
            "  names.map(name => [name, tileLabel(name)]))));",
        ]))

    def test_the_distinguishing_word_survives(self) -> None:
        self.assertEqual(self.labels["Bunny Companion"], "Companion")
        self.assertEqual(self.labels["Bunny Command"], "Command")
        self.assertNotEqual(
            self.labels["Bunny Companion"], self.labels["Bunny Command"],
            "the two names that collided when truncated still collide")

    def test_no_label_is_left_empty(self) -> None:
        """An application actually called "Bunny" must keep a name."""
        self.assertEqual(self.labels["Bunny"], "Bunny")
        self.assertEqual(self.labels["Bunny "], "Bunny")
        for name, label in self.labels.items():
            if name.strip():
                with self.subTest(application=name):
                    self.assertTrue(label, f"{name!r} would draw an empty tile")

    def test_names_that_are_not_prefixed_are_untouched(self) -> None:
        self.assertEqual(self.labels["Files"], "Files")
        self.assertEqual(self.labels["Terminal"], "Terminal")

    def test_every_shortened_label_fits_the_tile(self) -> None:
        """55px at 9px type is about 11 characters before the ellipsis.

        A bound rather than a rendering measurement: this cannot know the font,
        so it checks the thing that was actually wrong — that the labels the
        image ships are no longer long enough to lose their distinguishing word.
        """
        for name, label in self.labels.items():
            if not name.strip():
                continue
            with self.subTest(application=name):
                self.assertLessEqual(
                    len(label), 12,
                    f"{name!r} still draws {label!r}, which will ellipsise")

    def test_the_full_name_is_what_a_screen_reader_gets(self) -> None:
        """Drawn short, spoken in full. A screen reader has no width limit."""
        card = (LIB / "cards/quickAccess.js").read_text(encoding="utf-8")
        self.assertIn("label: tileLabel(app.get_name())", card)
        self.assertIn("accessibleName: app.get_name()", card)


class FailureIsolationTests(unittest.TestCase):
    """One widget's failure must not be every widget's failure.

    Three separate graphical boots died in this exact way, each over a single
    call: an Atk role looked up on Clutter, a parameter addChrome no longer
    accepts, a private field that had moved. In every case the desktop was
    correct except for one line, and in every case the user got no desktop.
    """

    def test_the_power_menu_does_not_pass_the_parameter_that_broke_the_first_boot(self) -> None:
        """`affectsInputRegion` survived in the power menu long after it was
        removed from the call that aborted the first graphical boot. Params.parse
        refuses an unrecognised key, and addChrome parents before it parses — so
        pressing Power would have thrown on every machine. Nothing had pressed it.
        """
        for path in sorted(EXTENSION.rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("//"):
                    continue
                with self.subTest(module=path.relative_to(EXTENSION).as_posix(), line=number):
                    self.assertNotIn("affectsInputRegion", line)

    def test_optional_components_are_built_through_the_guard(self) -> None:
        text = module_text("lib/desktopShell.js")
        for component in ("top bar", "sidebar", "dock", "character", "assistant panel",
                          "system overview", "quick access"):
            with self.subTest(component=component):
                self.assertIn(f"this._optional('{component}'", text)

    def test_a_failed_component_is_recorded_and_reported(self) -> None:
        text = module_text("lib/desktopShell.js")
        self.assertIn("this.degraded.push(what)", text)
        self.assertIn("_reportDegradation", text)
        # Logged, not swallowed. A desktop missing its dock with nothing in the
        # journal is worse than one that refused to start.
        self.assertIn("logError_(`${what} could not be created", text)

    #: Everything `_optional` can hand back as null.
    OPTIONAL = (
        "this.topBar", "this.sidebar", "this.dock", "this.wallpaper",
        "this.notificationLayer", "this._bubble", "this._suggestions",
        "this._characterViewport", "this._assistantPanel",
        "this.power", "this.network", "this.audio", "this.brightness",
        "this.media", "this.agenda", "this.assistant",
    )

    def test_every_use_of_an_optional_component_is_guarded(self) -> None:
        """A component that can be null must never be dereferenced with a bare dot.

        Two forms are accepted: optional chaining, and a plain dot inside an
        explicit `if (component)` — because a run of statements under one check
        reads better than five question marks. Anything else is a line that
        works until the day the component it names fails to build, which is the
        exact day the isolation is supposed to pay for itself.
        """
        lines = module_text("lib/desktopShell.js").splitlines()
        offenders = []
        for name in self.OPTIONAL:
            pattern = re.escape(name)
            block_guard = False       # inside `if (component) { ... }`
            block_indent = 0
            method_guard = False      # after `if (!component) { ...; return; }`
            for number, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith(("//", "*", "/*")):
                    continue
                indent = len(line) - len(line.lstrip())

                # A method body starts at indent 8; a new method header at 4
                # ends whatever the previous one had established.
                if indent == 4 and re.match(r"^(_?\w+)\(", stripped):
                    method_guard = False
                    block_guard = False

                if block_guard and indent <= block_indent and stripped.startswith("}"):
                    block_guard = False

                # An early return on the negative guards the rest of the method.
                if re.search(rf"if \(!{pattern}\)", line) or \
                        re.search(rf"if \({pattern} === null\)", line):
                    method_guard = True
                    continue
                if re.search(rf"if \({pattern}(\s*!==\s*null)?\)", line):
                    block_guard = True
                    block_indent = indent
                    continue

                # An assignment is not a dereference.
                if re.search(rf"{pattern}\s*=[^=]", line):
                    continue

                for member in re.findall(rf"{pattern}\.(\w+)", line):
                    if block_guard or method_guard:
                        continue
                    offenders.append(f"{number}: {name}.{member} in {stripped[:70]}")
        self.assertEqual(offenders, [], "an optional component is dereferenced unguarded")


class InteractionHarnessTests(unittest.TestCase):
    """The harness that presses the desktop's controls.

    Criterion 9 — "Files and Terminal can launch" — shipped as "both resolve and
    are in the dock. Not clicked — the harness has no pointer." These check the
    pieces that closed it, and in particular that the click is real input rather
    than a call into the desktop's own code.
    """

    SCRIPTS = ROOT / "build/scripts"

    def test_the_harness_gives_the_guest_an_absolute_pointer(self) -> None:
        text = (self.SCRIPTS / "vm-desktop-story.sh").read_text(encoding="utf-8")
        self.assertIn("virtio-tablet-pci", text)
        self.assertIn("virtserialport", text)

    def test_the_click_is_injected_at_the_device_layer(self) -> None:
        """Not a synthesised Clutter event and not an accessibility action.

        An AT-SPI `doAction` on the tile would run the handler while skipping
        libinput, Mutter's focus and Clutter's pick — three of the places this
        desktop has actually been wrong.
        """
        text = (self.SCRIPTS / "qmp-input.py").read_text(encoding="utf-8")
        self.assertIn("input-send-event", text)
        for forbidden in ("do_action", "doAction", "Atspi.Action"):
            self.assertNotIn(forbidden, text)

    def test_the_driver_proves_the_keyboard_reached_the_terminal(self) -> None:
        text = (self.SCRIPTS / "desktop-drive.py").read_text(encoding="utf-8")
        self.assertIn("type_text", text)
        self.assertIn("bunny-terminal-typed", text)
        story = (self.SCRIPTS / "vm-desktop-story.sh").read_text(encoding="utf-8")
        self.assertIn("bunny-terminal-typed.txt", story)

    def test_launch_evidence_is_four_independent_signals(self) -> None:
        text = (self.SCRIPTS / "desktop_interaction.py").read_text(encoding="utf-8")
        for signal in ("systemctl", "pgrep", "busctl", "Atspi"):
            with self.subTest(signal=signal):
                self.assertIn(signal, text)

    def test_the_interaction_module_is_injected_with_the_probe(self) -> None:
        text = (self.SCRIPTS / "desktop-inject.sh").read_text(encoding="utf-8")
        self.assertIn("desktop_interaction.py", text)
        # And labelled, because a guestfish-created file has no SELinux label
        # and that is what cost the first graphical run its GDM.
        self.assertIn('apply_label "${deployment}/etc/desktop_interaction.py"', text)

    def test_a_baseline_is_taken_before_anything_is_pressed(self) -> None:
        """"It was running after the click" is only evidence if it was not before."""
        text = (self.SCRIPTS / "desktop-drive.py").read_text(encoding="utf-8")
        self.assertIn("baselineClean", text)


class AssistantFlowTests(unittest.TestCase):
    """The desktop's half of a request, checked where it can be checked.

    None of this can run a compositor, so what is asserted is the shape of the
    code that survives contact with one: that every callback is guarded by the
    request it belongs to, that a request cannot hang for ever, and that nothing
    in the path blocks the main loop.
    """

    SERVICE = "lib/services/assistant.js"
    SHELL = "lib/desktopShell.js"

    @staticmethod
    def failure_handler(shell: str) -> str:
        """The body of `_failRequest`, not the call sites that mention it.

        Splitting on the bare name found the call inside `_ask` first, which is
        three lines long and contains none of what this checks.
        """
        marker = "_failRequest(reason, {retry = null} = {}) {"
        start = shell.index(marker)
        return shell[start:start + 1600]

    def test_the_watchdog_does_not_run_while_a_question_is_on_screen(self) -> None:
        """The same defect as the bridge's deadline, one layer up.

        Measured on a booted guest: the permission prompt was replaced after 200
        seconds by "The assistant did not answer in time" — while the answer it
        was waiting for was the person's, and the person had not been given 200
        seconds to read a sentence about their own files.

        Fixing only the bridge was not enough, because the desktop keeps its own
        clock and that clock had never heard of approvals.
        """
        service = module_text(self.SERVICE)
        self.assertIn("_awaitingPerson", service,
                      "the desktop's watchdog has no notion of waiting for a person")
        start = service.index("case 'approval':")
        approval_case = service[start:service.index("case 'reply':", start)]
        self.assertIn("this._awaitingPerson = true", approval_case)
        self.assertIn("this._watchdog?.stop()", approval_case,
                      "the watchdog keeps running while the question is unanswered")

    def test_the_watchdog_is_rearmed_once_the_question_is_answered(self) -> None:
        """Suspended, not removed.

        Without this, the fix degrades into "a task that ever asked anything can
        never time out", which is how a genuinely stuck request ends up sitting
        behind a thinking animation for ever.
        """
        service = module_text(self.SERVICE)
        start = service.index("case 'phase':")
        phase_case = service[start:service.index("case 'approval':", start)]
        self.assertIn("_awaitingPerson = false", phase_case)
        self.assertIn("armWatchdog()", phase_case,
                      "leaving waiting_for_approval does not restart the clock")
        self.assertIn("line.phase !== 'waiting_for_approval'", phase_case,
                      "the clock restarts while the question is still on screen")

    def test_availability_is_polled_rather_than_asked_once(self) -> None:
        """A cold boot must not leave the desktop claiming the assistant is off.

        Photographed on a booted guest: the suggestion panel read
        "Assistant offline — open Settings" while the readiness probe reported
        `bunny-companion.service` active and its socket answering. GNOME Shell
        *is* the session; the companion is a user unit pulled in by
        `graphical-session.target`, so the single startup check regularly runs
        before the socket exists and nothing asked again.

        Both consumers must go through the shared poller, because this exact
        defect was found on voice, fixed on voice, and left in place for the
        assistant sitting ten lines above it.
        """
        shell = module_text(self.SHELL)
        self.assertRegex(
            shell, r"_pollHealth\(service, report[^)]*\) \{",
            "the shared health poller is gone; the two consumers will drift again")
        for consumer in ("this.assistant", "this.voice"):
            with self.subTest(consumer=consumer):
                self.assertRegex(
                    shell, rf"_pollHealth\({re.escape(consumer)},",
                    f"{consumer} does not poll for availability")
        # Asking once is the defect. The startup path must not call checkHealth
        # directly any more.
        direct = re.findall(r"this\.(assistant|voice)\?\.checkHealth\(", shell)
        self.assertEqual([], direct,
                         f"a consumer still asks once at startup: {direct}")

    def test_offline_is_announced_only_after_the_attempts_run_out(self) -> None:
        """"Still starting" and "not there" are different, and only one is news.

        Announcing the first attempt's failure is what put the character to
        sleep and printed a warning bubble on a desktop whose runtime came up
        two seconds later.
        """
        shell = module_text(self.SHELL)
        start = shell.index("_watchAssistantAvailability() {")
        body = shell[start:shell.index("\n    }", start)]
        self.assertIn("if (!settled)", body,
                      "the assistant reports unavailability before the poll has settled")
        self.assertLess(
            body.index("if (!settled)"), body.index("setState('sleeping'"),
            "the character is put to sleep before the poll has settled")

    def test_every_request_gets_an_identifier(self) -> None:
        text = module_text(self.SERVICE)
        self.assertIn("this._sequence += 1", text)
        self.assertIn("const requestId = this._sequence", text)
        # And every callback carries it, or the desktop cannot tell whose news
        # it is hearing.
        for callback in ("onAccepted", "onPhase", "onReply", "onFinished", "onError"):
            with self.subTest(callback=callback):
                self.assertRegex(text, rf"{callback}\?\.\([^)]*\{{requestId\}}\)")

    def test_a_late_callback_for_an_old_request_changes_nothing(self) -> None:
        """The out-of-order protection, at both ends.

        The service refuses to deliver a callback for a superseded request, and
        the shell refuses to act on one it is given. Either alone would be
        enough today; both together survive one of them being refactored.
        """
        service = module_text(self.SERVICE)
        self.assertIn("const stillCurrent = () => this._activeRequestId === requestId", service)
        self.assertIn("if (!stillCurrent())\n                return;", service)

        shell = module_text(self.SHELL)
        self.assertIn("_owns(meta)", shell)
        self.assertIn("return meta.requestId === this._requestId", shell)
        for callback in ("onPhase", "onReply", "onFinished", "onError"):
            with self.subTest(callback=callback):
                body = shell.split(f"{callback}: (", 1)[1][:200]
                self.assertIn("this._owns(meta)", body,
                              f"{callback} acts without checking whose request it is")

    def test_a_request_that_never_answers_still_ends(self) -> None:
        """The character must not be left in THINKING by a bridge that died."""
        text = module_text(self.SERVICE)
        self.assertIn("WATCHDOG_MS", text)
        self.assertIn("this._watchdog = timeout(WATCHDOG_MS", text)
        # And a closed pipe with nothing terminal before it is itself terminal.
        self.assertIn("The assistant service stopped before answering.", text)

    def test_the_character_lands_on_idle_from_every_transient_state(self) -> None:
        shell = module_text(self.SHELL)
        transient = re.search(r"const TRANSIENT_STATES = new Set\(\[(.*?)\]\)", shell, re.S).group(1)
        for state in ("talking", "success", "error"):
            self.assertIn(f"'{state}'", transient)
        # WORKING and LISTENING belong to a request in progress and must not be
        # cleared by a dwell timer from an earlier one.
        for state in ("working", "listening"):
            self.assertNotIn(f"'{state}'", transient)

    def test_every_terminal_phase_returns_the_character_to_idle(self) -> None:
        """Success, failure and everything else must all land somewhere."""
        shell = module_text(self.SHELL)
        finished = shell.split("onFinished: (phase, meta)", 1)[1]
        finished = finished[:finished.index("onError:")]
        self.assertEqual(finished.count("_returnToIdleAfterTalking()"), 2,
                         "success and the other terminal phases must both settle")
        failure = self.failure_handler(shell)
        self.assertIn("_returnToIdleAfterTalking()", failure)

    def test_the_backend_is_reached_asynchronously(self) -> None:
        """A synchronous read on the compositor's main loop is a frozen desktop."""
        text = module_text(self.SERVICE)
        self.assertIn("read_line_async", text)
        for blocking in ("read_line(", "communicate_utf8(", "spawn_sync", "wait_check(", "wait()"):
            with self.subTest(call=blocking):
                self.assertNotIn(blocking, text)

    def test_no_shell_module_blocks_the_main_loop(self) -> None:
        """Statically detectable blocking calls, across the whole extension."""
        forbidden = (
            "spawn_command_line_sync", "spawn_sync", "communicate_utf8(", "communicate(",
            "wait_check(", "GLib.usleep", "load_contents_finish(null)",
        )
        offenders = []
        for path in sorted(EXTENSION.rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith(("//", "*")):
                    continue
                for call in forbidden:
                    if call in line:
                        offenders.append(
                            f"{path.relative_to(EXTENSION).as_posix()}:{number} {call}")
        self.assertEqual(offenders, [], "these block the compositor's main loop")

    def test_a_failure_is_reported_to_the_user_and_the_journal(self) -> None:
        shell = module_text(self.SHELL)
        failure = self.failure_handler(shell)
        self.assertIn("logError_(", failure)          # the journal gets the detail
        self.assertIn("this.notifications.error(", failure)  # the user gets a sentence
        self.assertIn("onActivate", failure)          # and a way to try again

    def test_the_assistant_activation_shortcut_exists_and_is_not_super_space(self) -> None:
        """Super+Space is GNOME's input-source switch and must not be taken.

        Measured on the reference host: `org.gnome.desktop.wm.keybindings
        switch-input-source` is `['<Super>space', 'XF86Keyboard']`. Taking it
        would cost every multilingual user their layout switch.
        """
        schema = (EXTENSION / "schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml") \
            .read_text(encoding="utf-8")
        binding = re.search(
            r'name="focus-desktop-assistant".*?<default>\[(.*?)\]</default>', schema, re.S)
        self.assertIsNotNone(binding, "the assistant needs an activation shortcut")
        self.assertNotIn("&lt;Super&gt;space", binding.group(1))
        # And the shell must actually bind it to activation.
        self.assertIn("bind('focus-desktop-assistant', () => this._activateAssistant())",
                      module_text(self.SHELL))

    def test_activation_focuses_the_input_and_shows_it_happened(self) -> None:
        shell = module_text(self.SHELL)
        body = shell.split("_activateAssistant() {", 1)[1][:500]
        self.assertNotIn("setState('listening'", body,
                         "typed focus must never imply an active microphone")
        self.assertIn("focusInput()", body)
        self.assertIn("_bubble?.say(", body)

    def test_escape_leaves_the_input(self) -> None:
        panel = module_text("lib/assistant/panel.js")
        self.assertIn("Clutter.KEY_Escape", panel)
        self.assertIn("onDismiss", panel)
        shell = module_text(self.SHELL)
        dismiss = shell.split("_dismissAssistant() {", 1)[1][:400]
        # Escape releases speech resources but still does not cancel a task.
        self.assertIn("_releaseVoiceInteraction", dismiss)
        self.assertNotIn("cancel_task", dismiss)


class BubbleResponseTests(unittest.TestCase):
    """The bubble is the primary response surface, with a bound on its size."""

    def test_a_long_answer_is_previewed_rather_than_shown_whole(self) -> None:
        text = module_text("lib/assistant/bubble.js")
        self.assertIn("PREVIEW_LIMIT", text)
        limit = int(re.search(r"const PREVIEW_LIMIT = (\d+);", text).group(1))
        # Small enough not to cover the dashboard, large enough to be an answer.
        self.assertGreater(limit, 80)
        self.assertLess(limit, 500)

    def test_the_whole_answer_reaches_a_screen_reader(self) -> None:
        """Truncation is a visual accommodation and must not remove information."""
        text = module_text("lib/assistant/bubble.js")
        self.assertIn("accessible_name = `Bunny says: ${full}`", text)

    def test_the_rest_is_reachable(self) -> None:
        text = module_text("lib/assistant/bubble.js")
        self.assertIn("onOpenFull", text)
        self.assertIn("bunny-bubble-more", text)
        self.assertTrue(".bunny-bubble-more" in module_text("stylesheet.css"),
                        "the affordance needs a style or it is an unstyled button")

    def test_the_bubble_is_bounded(self) -> None:
        text = module_text("lib/assistant/bubble.js")
        self.assertIn("const MAX_WIDTH", text)


class QuickAccessTests(unittest.TestCase):
    """Only installed applications, with their own icons.

    The booted screenshots showed five tiles carrying the same generic icon,
    which reads as a broken icon theme rather than as "you do not have these".
    """

    MODULE = "lib/cards/quickAccess.js"

    def test_no_tile_is_drawn_for_something_that_is_not_installed(self) -> None:
        """Code only. The comments explain what was removed and why."""
        code = "\n".join(
            line for line in module_text(self.MODULE).splitlines()
            if not line.lstrip().startswith(("//", "*", "/*"))
        )
        self.assertNotIn("setUnavailable", code)
        self.assertNotIn("not installed", code)

    def test_every_tile_uses_the_application_s_own_icon(self) -> None:
        text = module_text(self.MODULE)
        # The loop is found by what it iterates, not by its exact heading: the
        # tiles moved from a row into a grid and the heading changed with them,
        # which broke this test while the property it guards was untouched.
        marker = "of chosen.entries()"
        self.assertIn(marker, text, "the tile loop no longer iterates `chosen`")
        body = text.split(marker, 1)[1]
        self.assertIn("gicon: app.get_icon()", body)
        self.assertNotIn("APP_GENERIC", body)
        self.assertNotIn("iconName", body)

    def test_the_tiles_wrap_rather_than_running_out_of_the_card(self) -> None:
        """Eight tiles in one 304px card ran 300px out over the wallpaper.

        The count is what the machine has installed, so the container has to
        wrap. Asserted on the layout the module asks for, because the overflow
        itself is only visible in a photograph.
        """
        text = module_text(self.MODULE)
        self.assertIn("Clutter.GridLayout", text)
        # The count is computed from the theme, not fixed, because the card and
        # the tile both grow with the text scale. Measured at every scale rather
        # than asserted once: a constant that was right at 100 % was the
        # original defect, and it would have been wrong again at 125 %.
        self.assertIn("tilesAcross()", text)
        self.assertNotRegex(
            text, r"const TILES_PER_ROW\s*=",
            "the tile count is a theme computation now; a constant cannot follow the scale")
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                measured = run_node(
                    f"import {{tilesPerRow}} from '{(LIB / 'layout.js').as_uri()}';\n"
                    f"import {{resolveTheme}} from '{(LIB / 'design/theme.js').as_uri()}';\n"
                    f"const t = resolveTheme({{textScale: {scale}}});\n"
                    "const perRow = tilesPerRow({cardWidth: t.metric.cardWidth,"
                    " cardPadding: t.space.md, tileWidth: t.metric.quickTileWidth,"
                    " tilePadding: t.space.xs, gap: t.metric.quickTileGap});\n"
                    "const used = perRow * (t.metric.quickTileWidth + 2 * t.space.xs)"
                    " + (perRow - 1) * t.metric.quickTileGap;\n"
                    "console.log(JSON.stringify({perRow, used,"
                    " content: t.metric.cardWidth - 2 * t.space.md}));\n"
                )
                self.assertGreaterEqual(measured["perRow"], 1)
                self.assertLessEqual(
                    measured["used"], measured["content"],
                    f"at {scale}x, {measured['perRow']} tiles need {measured['used']}px "
                    f"and the card gives {measured['content']}px")

    def test_tiles_come_from_the_installed_registry(self) -> None:
        text = module_text(self.MODULE)
        self.assertIn("this._launcher.resolve(logical)", text)
        self.assertIn("this._launcher.listAll()", text)

    def test_an_empty_card_says_so(self) -> None:
        text = module_text(self.MODULE)
        self.assertIn("_empty.visible = chosen.length === 0", text)


class CompanionWindowTests(unittest.TestCase):
    """The backend runs at login; the window does not."""

    def test_the_build_does_not_enable_the_window_unit(self) -> None:
        installer = (ROOT / "build/scripts/install-root.py").read_text(encoding="utf-8")
        start = installer.index('"/usr/bin/systemctl", "--global", "enable"')
        finish = installer.index("], check=True)", start)
        block = installer[start:finish]
        self.assertIn("bunny-companion.service", block)
        self.assertNotIn("bunny-companion-window.service", block)

    def test_the_runtime_unit_is_still_a_background_service(self) -> None:
        unit = (ROOT / "systemd/user/bunny-companion.service").read_text(encoding="utf-8")
        self.assertIn("WantedBy=graphical-session.target", unit)
        self.assertIn("ExecStart=/usr/libexec/bunny-companion-service", unit)


class StartupDeferralTests(unittest.TestCase):
    """The desktop is never built while the shell is still starting.

    Building it during startup restructures the stage under the startup
    animation, one of layout.js's awaits never resolves, 'startup-complete'
    never fires, and Main.actionMode stays NONE — where windowManager.js's
    `_filterKeybinding` drops every keybinding for the life of the session.
    That was the ACPI power key defect: every Phase 3/4 boot that built the
    desktop during startup is missing the "GNOME Shell started" message the
    startup-complete handler logs, and ignored the press; the boots that
    deferred (or had no desktop) show the message and power off cleanly.
    Evidence: qualification/phase4/power-key/, runs p4-power-1..8.

    These are text-level assertions on the shipped source with comments
    stripped, for the same reason test_corrections strips them: an accurate
    explanation of the defect contains the names of the defect.
    """

    @staticmethod
    def _stripped() -> str:
        text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return re.sub(r"^\s*//.*$", "", text, flags=re.M)

    @classmethod
    def _method_body(cls, name: str) -> str:
        code = cls._stripped()
        _, _, rest = code.partition(f"{name}() {{")
        body, _, _ = rest.partition("\n    }")
        return body

    def test_enable_defers_construction_while_the_shell_is_starting(self) -> None:
        enable = self._method_body("enable")
        self.assertIn("_startingUp", enable,
                      "enable() no longer asks whether the shell is starting; "
                      "a desktop built during startup stalls the startup "
                      "animation and every keybinding dies with it")
        self.assertIn("'startup-complete'", enable,
                      "the deferred build must ride the same signal that "
                      "flips Main.actionMode from NONE")

    def test_enable_builds_nothing_before_the_startup_check(self) -> None:
        enable = self._method_body("enable")
        before_check, _, _ = enable.partition("_startingUp")
        self.assertNotIn(
            "_enableDesktop", before_check,
            "the desktop is constructed before the startup check — that is "
            "the exact ordering that killed the power key")

    def test_disable_cancels_a_pending_deferred_build(self) -> None:
        disable = self._method_body("disable")
        self.assertIn(
            "_startupCompleteId", disable,
            "a logout during startup would leak the deferred build into a "
            "session that no longer owns it")

    @staticmethod
    def _dismiss_body() -> str:
        text = (LIB / "desktopShell.js").read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        _, _, rest = text.partition("_dismissOverviewOnce() {")
        body, _, _ = rest.partition("\n    }")
        return body

    def test_the_overview_is_never_hidden_during_startup(self) -> None:
        """The precise mechanism: overviewControls' runStartupAnimation
        awaits ensureAllocation(), which never settles if the overview is
        hidden before its first allocation — and every keybinding in the
        session dies with that promise."""
        body = self._dismiss_body()
        self.assertIn(
            "_startingUp", body,
            "the overview is dismissed without asking whether the shell is "
            "still starting; that hang is what killed the power key")
        guard, _, after = body.partition("_startingUp")
        self.assertNotIn(
            "Main.overview.hide()", guard,
            "the overview is hidden before the startup guard is consulted")
        self.assertNotIn(
            "_overviewDismissed = true", guard,
            "the once-flag is set before the startup guard, so the "
            "startup-complete retry would find the work already 'done' and "
            "the overview would stay open for ever")
        self.assertIn("Main.overview.hide()", after,
                      "nothing dismisses the overview after the guard")

    def test_the_startup_complete_retry_exists(self) -> None:
        """The guard defers the dismissal, so something must come back for
        it. Without this connection a guarded dismissal is a dismissal that
        never happens."""
        text = (LIB / "desktopShell.js").read_text(encoding="utf-8")
        self.assertIn("'startup-complete', () => this._dismissOverviewOnce()", text)


if __name__ == "__main__":
    unittest.main()
