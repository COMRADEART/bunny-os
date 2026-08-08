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

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
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

    def test_the_role_helper_looks_the_constant_up_rather_than_dereferencing_it(self) -> None:
        text = module_text("lib/util.js")
        self.assertIn("Atk?.Role?.[roleName]", text)
        self.assertIn("logOnce(", text.split("export function setAccessibleRole")[1][:900])


class DesignTokenTests(unittest.TestCase):
    """stylesheet.css repeats literals from tokens.js; this is the pairing check."""

    def test_every_palette_colour_appears_in_the_stylesheet(self) -> None:
        tokens = module_text("lib/tokens.js")
        block = re.search(r"export const Colour = \{(.*?)\n\};", tokens, re.S).group(1)
        css = module_text("stylesheet.css").lower()
        for name, value in re.findall(r"(\w+):\s*'([^']+)'", block):
            with self.subTest(token=name):
                if value.startswith("#"):
                    self.assertIn(value.lower(), css, f"{name} ({value}) is not used in stylesheet.css")
                else:
                    # rgba() is written with the same spacing in both files.
                    self.assertIn(value.lower(), css, f"{name} ({value}) is not used in stylesheet.css")

    def test_the_accent_is_violet_as_the_brief_specifies(self) -> None:
        tokens = module_text("lib/tokens.js")
        self.assertIn("ACCENT: '#8B5CF6'", tokens)
        self.assertIn("ACCENT_BRIGHT: '#A78BFA'", tokens)

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
                            "lib/services/agenda.js", "lib/services/network.js"}:
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


if __name__ == "__main__":
    unittest.main()
