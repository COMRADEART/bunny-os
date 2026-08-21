# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The architectural rule, asserted rather than documented.

Bunny OS has two AI paths and they meet at a directory on disk. Three claims
follow from that, and a claim nobody checks is a comment:

1. no install route carries this package into the image;
2. nothing here imports the Bunny OS runtime, and nothing in the runtime imports
   this package;
3. there is no upload path in this package at all.

The first is checked against ``build/scripts/install_routes.py`` itself — the
single declaration of what reaches the image — rather than against a list
maintained here, so adding a route would fail this test with no second edit.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "model_studio"

#: The packages that make up the Bunny OS runtime. Training code importing any
#: of these would put it on the Companion's execution path by dependency even
#: if no install route ever carried it.
RUNTIME_PACKAGES = frozenset({
    "companion", "capsules", "trust", "catalog", "capability", "installer",
    "shell", "services", "oem", "sync", "enterprise", "bunny_os", "bunny_shell",
    "bunny_system_broker", "release", "operations",
})

#: Every way a Python program publishes a model. None of them may appear.
UPLOAD_SYMBOLS = (
    "push_to_hub", "upload_file", "upload_folder", "create_repo", "HfApi",
    "create_commit", "CommitOperationAdd",
)

#: Network primitives. ``snapshot_download`` is the single approved exception
#: and is allowed in exactly one module.
NETWORK_SYMBOLS = ("socket", "requests", "httpx", "aiohttp", "urllib", "http")
DOWNLOAD_EXCEPTION = ("snapshot_download", "models.py")


def _sources() -> list[Path]:
    return sorted(
        path for path in PACKAGE.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _install_routes():
    """The build's own route table, loaded from the file the build reads.

    Registered in ``sys.modules`` before execution because it defines
    dataclasses, and ``dataclasses`` resolves annotations through the module
    entry — a module executed without one raises inside the decorator.
    """
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


class NotInTheImage(unittest.TestCase):
    def test_no_install_route_carries_this_package(self) -> None:
        """The isolation is a build property, and this is where it is enforced."""
        routes = _install_routes()
        carried: list[str] = []
        for path in _sources() + [PACKAGE / "bin/bunny-model"]:
            relative = path.relative_to(ROOT).as_posix()
            for route in routes.INSTALL_ROUTES:
                if routes.installed_destination(route, relative) is not None:
                    carried.append(f"{relative} -> {route.id}")
        self.assertEqual(
            carried, [],
            "Bunny Model Studio must not reach the image. A route here would put "
            "training code on a Bunny machine, and this test is the reason that "
            "cannot happen by accident.",
        )

    def test_no_route_names_the_package_directory(self) -> None:
        routes = _install_routes()
        for route in routes.INSTALL_ROUTES:
            self.assertFalse(
                route.source.startswith("model_studio"),
                f"route {route.id} installs from model_studio",
            )

    def test_the_schema_is_not_in_the_installed_schemas_directory(self) -> None:
        """`schemas/` is an install route; a training schema there would ship."""
        self.assertFalse((ROOT / "schemas/bunny-training-config.schema.json").exists())
        self.assertTrue((PACKAGE / "schemas/bunny-training-config.schema.json").is_file())


class NoRuntimeCoupling(unittest.TestCase):
    def _imports(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
        return names

    def test_nothing_here_imports_the_runtime(self) -> None:
        offenders: list[str] = []
        for path in _sources():
            for name in self._imports(path) & RUNTIME_PACKAGES:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {name}")
        self.assertEqual(offenders, [])

    def test_the_runtime_does_not_import_this_package(self) -> None:
        offenders: list[str] = []
        for package in ("companion", "capsules", "trust", "catalog", "capability",
                        "shell", "installer", "services", "tools"):
            directory = ROOT / package
            if not directory.is_dir():
                continue
            for path in directory.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                if "model_studio" in path.read_text(encoding="utf-8", errors="replace"):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            offenders, [],
            "the handoff between Model Studio and the Bunny OS runtime is a directory "
            "on disk, not an import",
        )


def _code_symbols(path: Path) -> tuple[set[str], set[str]]:
    """Every module imported and every identifier used, from the syntax tree.

    Deliberately not a text search. The first version of this test was one, and
    it failed on ``config.py`` — whose docstring says, in prose, that there is no
    ``push_to_hub`` here. A check that cannot tell documentation from code
    punishes the file for explaining itself, and the obvious way to make it pass
    is to delete the explanation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A symbol reached by name rather than by syntax - importlib,
            # getattr - would hide from the walk above. Module-level constants
            # naming an import are the one legitimate case, and they are checked
            # here rather than trusted.
            if node.value.split(".")[0] in {"socket", "requests", "httpx", "aiohttp",
                                            "urllib", "http", "huggingface_hub"}:
                modules.add(node.value.split(".")[0])
    return modules, names


class NoUploadPath(unittest.TestCase):
    def test_no_module_can_publish_a_model(self) -> None:
        offenders: list[str] = []
        for path in _sources():
            _, names = _code_symbols(path)
            for symbol in UPLOAD_SYMBOLS:
                if symbol in names:
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}: {symbol}")
        self.assertEqual(
            offenders, [],
            "Model Studio has no upload path. Not a disabled one - none, so that a "
            "configuration mistake cannot become a published personal corpus.",
        )

    def test_the_only_network_call_is_the_approved_download(self) -> None:
        symbol, allowed_file = DOWNLOAD_EXCEPTION
        offenders: list[str] = []
        for path in _sources():
            modules, names = _code_symbols(path)
            relative = path.relative_to(ROOT).as_posix()
            if symbol in names and path.name != allowed_file:
                offenders.append(f"{relative}: {symbol}")
            for network in NETWORK_SYMBOLS:
                if network in modules:
                    offenders.append(f"{relative}: imports {network}")
        self.assertEqual(offenders, [])

    def test_the_download_exists_where_it_is_supposed_to(self) -> None:
        """A negative control: the check above must be able to see the one call there is."""
        _, names = _code_symbols(PACKAGE / "models.py")
        self.assertIn(DOWNLOAD_EXCEPTION[0], names)

    def test_the_refusal_is_reachable_and_explains_itself(self) -> None:
        from model_studio.errors import NetworkRefused
        from model_studio.network import refuse_upload

        with self.assertRaises(NetworkRefused):
            refuse_upload()


class LicenceHeaders(unittest.TestCase):
    def test_every_source_file_declares_the_project_licence(self) -> None:
        missing = [
            path.relative_to(ROOT).as_posix()
            for path in _sources() + [PACKAGE / "bin/bunny-model"]
            if "SPDX-License-Identifier: GPL-3.0-or-later"
            not in path.read_text(encoding="utf-8")[:4000]
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
