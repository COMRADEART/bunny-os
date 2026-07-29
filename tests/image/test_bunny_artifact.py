from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.support import ROOT


SCRIPT = ROOT / "build/scripts/verify-bunny-artifact.py"
SPEC = importlib.util.spec_from_file_location("verify_bunny_artifact", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class BunnyArtifactTests(unittest.TestCase):
    def invoke(self, manifest: Path, payload: Path) -> int:
        import sys
        old = sys.argv
        sys.argv = [str(SCRIPT), str(manifest), str(payload)]
        try:
            return module.main()
        finally:
            sys.argv = old

    def test_explicit_placeholder_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.invoke(ROOT / "build/manifests/bunny-artifact.placeholder.json", Path(temporary)), 0)

    def test_traversal_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = json.loads((ROOT / "build/manifests/bunny-artifact.placeholder.json").read_text(encoding="utf-8"))
            value["status"] = "verified"
            value["runtimeMode"] = "tauri-supervised"
            value["files"] = [{"path": "../escape", "sha256": "0" * 64, "mode": "0555"}]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "unsafe"):
                self.invoke(manifest, root)


if __name__ == "__main__":
    unittest.main()

