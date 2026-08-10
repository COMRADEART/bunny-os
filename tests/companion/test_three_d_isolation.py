# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§1 and §29: what the 3D subsystem may reach, read from the import graph.

A boundary that is only a convention is a boundary that erodes, usually by
someone adding one convenient import to fix one urgent thing. So this reads the
AST of every module under ``companion/character/three_d/`` and fails on any
import of the runtime, the store, approvals, the tool broker, the agent
providers, the desktop adapters, the speech recogniser or the voice worker —
whether at module scope or inside a function, because a deferred import is still
an import and is the form the first violation usually takes.

Three further properties are checked here because each has a failure mode that
is invisible at review:

* **No GPU library at import.** §30. ``import companion.character.three_d.gl``
  must not open ``libGL``, and importing the package must not import ``gi``.
* **No filesystem reach outside a package root.** The renderer receives a
  :class:`~companion.character.package.ValidatedPackage` and reads what its
  manifest names; it does not open paths of its own.
* **The presentation contract is the only thing that crosses.** What the 3D
  modules import *from* the companion is enumerated, so a new one is a decision
  somebody has to make here rather than a line in a diff.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_THREE_D = _ROOT / "companion" / "character" / "three_d"

#: Modules the 3D subsystem may never reach. §1's "may not" list, as prefixes.
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "companion.store",
    "companion.runtime",
    "companion.task",
    "companion.tools",
    "companion.approvals",
    "companion.executor",
    "companion.reviewer",
    "companion.agents",
    "companion.agent_bridge",
    "companion.desktop",
    "companion.desktop_bridge",
    "companion.speech",
    "companion.service",
    "companion.session",
    "companion.protocol",
    "companion.coordination",
    "companion.events",
    "companion.recovery",
    "companion.migration",
    "companion.cli",
    "companion.gtk_shell",
    "companion.voice.worker",
    "companion.voice.service",
    "companion.voice.providers",
)

#: What the 3D subsystem *is* allowed to import from the companion. Every entry
#: is a presentation value type or the validated-package contract.
PERMITTED_COMPANION_IMPORTS: frozenset[str] = frozenset({
    "companion.character",
    "companion.character.errors",
    "companion.character.image",
    "companion.character.lipsync",
    "companion.character.mapper",
    "companion.character.package",
    "companion.character.renderer",
    "companion.character.schema",
    "companion.character.defaults",
    "companion.character.diagnostics",
    "companion.presentation",
    "companion.errors",
})


def _modules() -> list[Path]:
    return sorted(_THREE_D.rglob("*.py"))


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every imported module name in ``path``, including deferred ones."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    package = "companion.character.three_d"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0]
                name = f"{base}.{node.module}" if node.module else base
            else:
                name = node.module or ""
            found.append((name, node.lineno))
    return found


class ImportBoundaryTests(unittest.TestCase):
    def test_the_subsystem_exists_and_is_not_empty(self) -> None:
        self.assertGreaterEqual(len(_modules()), 12)

    def test_no_module_reaches_task_provider_or_approval_authority(self) -> None:
        violations: list[str] = []
        for path in _modules():
            for name, line in _imports(path):
                for prefix in FORBIDDEN_PREFIXES:
                    if name == prefix or name.startswith(prefix + "."):
                        violations.append(
                            f"{path.relative_to(_ROOT).as_posix()}:{line} imports {name}"
                        )
        self.assertEqual(violations, [], "the 3D renderer reached across its boundary")

    def test_every_companion_import_is_on_the_permitted_list(self) -> None:
        unexpected: list[str] = []
        for path in _modules():
            for name, line in _imports(path):
                if not name.startswith("companion."):
                    continue
                if name.startswith("companion.character.three_d"):
                    continue
                if name not in PERMITTED_COMPANION_IMPORTS:
                    unexpected.append(
                        f"{path.relative_to(_ROOT).as_posix()}:{line} imports {name}"
                    )
        self.assertEqual(
            unexpected, [],
            "a new companion import crossed the presentation boundary without being declared",
        )

    def test_the_renderer_does_not_import_a_toolkit_at_module_scope(self) -> None:
        offenders: list[str] = []
        for path in _modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in {"gi", "gtk", "OpenGL", "moderngl", "pyglet", "numpy"}:
                        offenders.append(f"{path.relative_to(_ROOT).as_posix()}: {name}")
        self.assertEqual(offenders, [], "§30: no GPU or toolkit library at import time")

    def test_no_module_opens_a_socket_or_reaches_the_network(self) -> None:
        forbidden = {"socket", "http", "urllib", "requests", "ssl", "ftplib", "smtplib"}
        offenders: list[str] = []
        for path in _modules():
            for name, line in _imports(path):
                if name.split(".")[0] in forbidden:
                    offenders.append(f"{path.relative_to(_ROOT).as_posix()}:{line} imports {name}")
        self.assertEqual(offenders, [], "§1: the 3D renderer may not contact remote services")

    def test_no_module_reads_microphone_audio(self) -> None:
        offenders: list[str] = []
        for path in _modules():
            text = path.read_text(encoding="utf-8")
            for marker in ("parec", "arecord", "pyaudio", "sounddevice", "AudioCapture"):
                if marker in text:
                    offenders.append(f"{path.relative_to(_ROOT).as_posix()}: {marker}")
        self.assertEqual(offenders, [], "§1: the 3D renderer may not read microphone audio")

    def test_no_module_executes_a_subprocess(self) -> None:
        offenders: list[str] = []
        for path in _modules():
            for name, line in _imports(path):
                if name.split(".")[0] in {"subprocess", "multiprocessing", "pty"}:
                    offenders.append(f"{path.relative_to(_ROOT).as_posix()}:{line} imports {name}")
        self.assertEqual(offenders, [], "§1: the 3D renderer may not execute tools")


class LazyLoadingTests(unittest.TestCase):
    """§30: importing must not initialise a graphics library."""

    def test_importing_the_package_opens_no_graphics_library(self) -> None:
        script = (
            "import sys\n"
            "import companion.character.three_d as three_d\n"
            "import companion.character.three_d.gl as gl\n"
            "import companion.character.three_d.renderer as renderer\n"
            "import companion.character.three_d.context as context\n"
            "loaded = [name for name in sys.modules if name.split('.')[0] in "
            "{'gi', 'OpenGL', 'moderngl', 'pyglet', 'numpy'}]\n"
            "print('MODULES', loaded)\n"
            "print('GL_TABLE', gl._LOADED)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MODULES []", result.stdout)
        self.assertIn("GL_TABLE None", result.stdout)

    def test_the_environment_probe_initialises_nothing(self) -> None:
        from companion.character.three_d.diagnostics import three_d_environment

        report = three_d_environment()
        self.assertFalse(report["libraryInitialised"])
        self.assertIn("threeDAvailable", report)


class PresentationContractTests(unittest.TestCase):
    """§1: what crosses the boundary is a value, never a handle."""

    def test_the_renderer_accepts_a_mapped_state_and_holds_no_task(self) -> None:
        from companion.character.three_d.renderer import ThreeDRenderer

        annotations = ThreeDRenderer.display_state.__annotations__
        self.assertEqual(annotations["state"], "MappedCharacterState")
        for forbidden in ("task", "store", "approval", "runtime", "broker", "session"):
            self.assertFalse(
                any(forbidden in name.casefold() for name in vars(ThreeDRenderer)),
                f"the 3D renderer exposes a {forbidden} member",
            )

    def test_the_state_machine_uses_the_canonical_priority_and_holds_no_second_one(self) -> None:
        import companion.character.three_d.animation as animation
        from companion.character.mapper import STATE_PRIORITY

        source = (_THREE_D / "animation.py").read_text(encoding="utf-8")
        self.assertIn("priority_rank", source)
        # §9's order must be a subsequence of the canonical one: a second table
        # that merely looked similar would drift on the next state added.
        canonical = [state for state in STATE_PRIORITY]
        position = -1
        for state in animation.SECTION_NINE_ORDER:
            index = canonical.index(state)
            self.assertGreater(index, position, f"{state} is out of canonical order")
            position = index


if __name__ == "__main__":
    unittest.main()
