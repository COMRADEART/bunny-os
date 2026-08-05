# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from companion.character.defaults import default_character_path


class CharacterPackageFixture:
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-character-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package_root = self.root / "package"
        shutil.copytree(default_character_path(), self.package_root)
        # The copy has to be writable, and the original deliberately is not.
        #
        # `default_character_path` prefers the *installed* package, and an
        # installed package is mode 0444 and root-owned — which is right, since
        # a character a user can rewrite is a character that renders whatever
        # that user last wrote. `copytree` preserves those bits, so on any
        # machine with Bunny OS actually installed every test that edits a
        # manifest failed with EACCES. It passed on a developer checkout, where
        # the fallback source is an ordinary file, and on Windows, where the
        # read-only bit does not stop the owner writing.
        for path in self.package_root.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)

    @property
    def manifest_path(self) -> Path:
        return self.package_root / "manifest.json"

    def manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, value: dict) -> None:
        self.manifest_path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )

    def asset(self, asset_id: str) -> tuple[dict, Path]:
        manifest = self.manifest()
        record = next(item for item in manifest["assetInventory"] if item["assetId"] == asset_id)
        return record, self.package_root / Path(record["path"])

    def rehash(self, asset_id: str) -> None:
        manifest = self.manifest()
        record = next(item for item in manifest["assetInventory"] if item["assetId"] == asset_id)
        path = self.package_root / Path(record["path"])
        record["sizeBytes"] = path.stat().st_size
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_manifest(manifest)

    def make_static(self) -> None:
        manifest = self.manifest()
        manifest["presentationType"] = "static-image"
        for animation in manifest["animations"].values():
            animation["kind"] = "static"
            animation["frames"] = animation["frames"][:1]
            animation["loop"] = False
        self.write_manifest(manifest)

    def archive(self, name: str = "character.zip") -> Path:
        output = self.root / name
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(self.package_root).as_posix())
        return output
