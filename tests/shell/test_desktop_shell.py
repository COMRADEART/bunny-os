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


if __name__ == "__main__":
    unittest.main()
