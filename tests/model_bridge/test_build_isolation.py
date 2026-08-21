# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 17: the bridge is installed; the training subsystem is not.

The previous milestone asserted one half of this — that ``model_studio`` never
reaches the image. This milestone adds the other half, and the pair is what
makes the boundary a boundary rather than a diagram: the runtime bridge **is**
carried into the image by an install route, the training tree **is not**, and
both facts are checked against ``build/scripts/install_routes.py`` itself rather
than against a list kept here.

Asserting only the negative would have been a weaker test that passes on a
build where the bridge was accidentally dropped from the image too.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "companion" / "models"
STUDIO = ROOT / "model_studio"

#: Packages that are the training side. The runtime may not import any of them.
TRAINING_PACKAGES = frozenset({"model_studio"})

#: Heavy dependencies that belong to training and must not become runtime
#: dependencies of the bridge. Named individually because "the bridge got big"
#: is not something a diff review reliably catches.
TRAINING_DEPENDENCIES = frozenset({
    "torch", "transformers", "peft", "safetensors", "datasets", "accelerate",
    "bitsandbytes", "gguf", "numpy", "huggingface_hub", "sentencepiece", "tokenizers",
})


def _install_routes():
    name = "bunny_install_routes"
    if name in sys.modules:
        return sys.modules[name]
    location = ROOT / "build/scripts/install_routes.py"
    spec = importlib.util.spec_from_file_location(name, location)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sources(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def _destinations(relative: str) -> list[str]:
    routes = _install_routes()
    found = []
    for route in routes.INSTALL_ROUTES:
        destination = routes.installed_destination(route, relative)
        if destination is not None:
            found.append(destination)
    return found


class TheBridgeIsInstalled(unittest.TestCase):
    def test_every_bridge_module_reaches_the_image(self) -> None:
        missing = []
        for path in _sources(BRIDGE):
            relative = path.relative_to(ROOT).as_posix()
            if not _destinations(relative):
                missing.append(relative)
        self.assertEqual(
            missing, [],
            "the runtime model bridge must be installed; these modules reach no route",
        )

    def test_it_lands_on_the_companion_import_path(self) -> None:
        destination = _destinations("companion/models/registry.py")
        self.assertEqual(destination, ["/usr/lib/bunny-os/python/companion/models/registry.py"])

    def test_the_artifact_schema_is_published_with_the_others(self) -> None:
        destination = _destinations("schemas/bunny-model-artifact.schema.json")
        self.assertEqual(destination, ["/usr/share/bunny-os/schemas/bunny-model-artifact.schema.json"])

    def test_the_runtime_cli_reaches_the_image(self) -> None:
        self.assertTrue(_destinations("tools/bunny-os/bunny_os/model_cli.py"))

    def test_no_new_install_route_was_needed(self) -> None:
        """The bridge rides the existing companion package route.

        Worth asserting because the alternative — a new route — is the thing
        that would have had to be reviewed, and a milestone that quietly added
        one would have widened the install set.
        """
        routes = _install_routes()
        sources = {route.source for route in routes.INSTALL_ROUTES}
        self.assertIn("companion", sources)
        self.assertNotIn("companion/models", sources,
                         "companion/models needs no route of its own")


class TheTrainingTreeIsNot(unittest.TestCase):
    def test_no_install_route_carries_model_studio(self) -> None:
        carried = []
        for path in _sources(STUDIO) + [STUDIO / "bin" / "bunny-model"]:
            relative = path.relative_to(ROOT).as_posix()
            for destination in _destinations(relative):
                carried.append(f"{relative} -> {destination}")
        self.assertEqual(
            carried, [],
            "Bunny Model Studio must not reach the image. Training code on a Bunny "
            "machine is exactly what this boundary exists to prevent.",
        )

    def test_the_export_module_is_not_installed(self) -> None:
        """Export is a training-side act; the runtime never exports."""
        self.assertEqual(_destinations("model_studio/export.py"), [])


class NoCouplingEitherWay(unittest.TestCase):
    def _imports(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_the_bridge_imports_nothing_from_model_studio(self) -> None:
        offenders = []
        for path in _sources(BRIDGE):
            for name in self._imports(path) & TRAINING_PACKAGES:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {name}")
        self.assertEqual(offenders, [])

    def test_the_bridge_pulls_in_no_training_dependency(self) -> None:
        """Phase 18. Loading an adapter must not drag a tensor stack into the image."""
        offenders = []
        for path in _sources(BRIDGE):
            for name in self._imports(path) & TRAINING_DEPENDENCIES:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {name}")
        self.assertEqual(
            offenders, [],
            "the runtime bridge is metadata, digests and one HTTP call; it must not "
            "acquire a training dependency to load an adapter",
        )

    def test_the_installed_cli_imports_no_training_code(self) -> None:
        path = ROOT / "tools/bunny-os/bunny_os/model_cli.py"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("model_studio", text)

    def test_model_studio_still_imports_no_runtime(self) -> None:
        """The previous milestone's property, re-asserted because it now has a neighbour."""
        runtime = {"companion", "capsules", "trust", "catalog", "capability"}
        offenders = []
        for path in _sources(STUDIO):
            for name in self._imports(path) & runtime:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {name}")
        self.assertEqual(offenders, [])

    def test_the_bridge_uses_only_the_standard_library_and_the_companion(self) -> None:
        allowed = {"companion", "dataclasses", "json", "os", "pathlib", "hashlib", "stat",
                   "typing", "tempfile", "time", "datetime", "re", "sys", "__future__"}
        unexpected: set[str] = set()
        for path in _sources(BRIDGE):
            unexpected |= self._imports(path) - allowed
        self.assertEqual(
            unexpected, set(),
            "a new third-party import in the runtime bridge is a new runtime "
            "dependency for every Bunny machine and needs to be a decision",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
