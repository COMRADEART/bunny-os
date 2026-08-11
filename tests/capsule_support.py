# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One place that builds a whole trust-and-capsule world in a temporary directory.

Every suite in this phase needs the same five things wired together — a grant
store, an audit, a gate with a scripted surface, a capsule runtime and a
catalogue — and building them by hand in each test file is how two suites come
to be testing subtly different systems.

Two decisions worth stating.

**The environment is set per fixture, not per process.** ``BUNNY_TRUST_ROOT`` and
``BUNNY_CAPSULE_ROOT`` are restored on teardown, so a suite that runs alongside
another does not silently share a store. A test that leaked a root would pass
locally and fail on a machine where the suites run in a different order, which is
the worst kind of failure to debug.

**The machine is described, never measured.** :class:`World` takes a
:class:`~capsules.backends.MachineProbe` with the programs and kernel features
stated. A suite that probed the real machine would assert different things on a
developer's Windows laptop, on the Fedora builder and in CI — and "the sandbox
refuses when user namespaces are off" would quietly stop being tested on every
machine where they are on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterable, Mapping, Sequence

import capsules
import catalog
import trust
from capsules.backends import MachineProbe
from capsules.manifest import CapsuleManifest, ResourceLimits
from capsules.runtime import CapsuleRuntime, RecordingExecutor
from trust.audit import TrustAudit
from trust.gate import ScriptedSurface, TrustGate
from trust.store import TrustStore

__all__ = ["World", "confining_probe", "manifest_for", "unconfined_probe"]


def confining_probe() -> MachineProbe:
    """A machine that can actually sandbox: bwrap, flatpak, user namespaces, a portal."""
    return MachineProbe(
        programs=frozenset({"bwrap", "flatpak", "systemd-run"}),
        user_namespaces=True,
        portal=True,
        graphical_session=True,
    )


def unconfined_probe() -> MachineProbe:
    """A machine with the binaries and no user namespaces. Nothing confines here."""
    return MachineProbe(
        programs=frozenset({"bwrap", "flatpak", "systemd-run"}),
        user_namespaces=False,
        portal=True,
        graphical_session=True,
    )


def manifest_for(
    application_id: str = "org.example.PhotoEditor",
    *,
    display_name: str = "Photo Editor",
    required: Iterable[str] = ("files",),
    optional: Iterable[str] = ("gpu", "network"),
    backend: str = "bubblewrap",
    package_source: str = "fedora-rpm",
    package_reference: str = "/usr/bin/photoeditor",
    network_ceiling: str = "none",
    network_domains: Iterable[str] = (),
    reasons: Mapping[str, str] | None = None,
) -> CapsuleManifest:
    return CapsuleManifest(
        identity=capsules.capsule_identity(application_id),
        display_name=display_name,
        package_source=package_source,
        package_reference=package_reference,
        preferred_backend=backend,
        required_permissions=frozenset(required),
        optional_permissions=frozenset(optional),
        permission_reasons=dict(reasons or {"files": "to open the file you choose"}),
        network_ceiling=network_ceiling,
        network_domains=frozenset(network_domains),
        limits=ResourceLimits(),
    )


@dataclass
class World:
    """A complete, isolated Bunny world in a temporary directory."""

    base: Path
    home: Path
    store: TrustStore
    audit: TrustAudit
    surface: ScriptedSurface
    gate: TrustGate
    runtime: CapsuleRuntime
    registry: catalog.CatalogRegistry
    executor: RecordingExecutor
    _previous_environment: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        session_id: str = "session-1",
        answers: Sequence[tuple[str, str, str]] = (),
        probe: MachineProbe | None = None,
        load_catalog: bool = True,
    ) -> "World":
        base = Path(tempfile.mkdtemp(prefix="bunny-world-"))
        home = base / "home"
        for name in ("Documents", "Downloads", "Pictures", "Music", "Videos", "Desktop"):
            (home / name).mkdir(parents=True, exist_ok=True)

        previous = {
            key: os.environ.get(key)
            for key in (
                "BUNNY_TRUST_ROOT",
                "BUNNY_CAPSULE_ROOT",
                "XDG_DOCUMENTS_DIR",
                "XDG_DOWNLOAD_DIR",
                "XDG_PICTURES_DIR",
                "XDG_MUSIC_DIR",
                "XDG_VIDEOS_DIR",
                "XDG_DESKTOP_DIR",
            )
        }
        os.environ["BUNNY_TRUST_ROOT"] = str(base / "trust")
        os.environ["BUNNY_CAPSULE_ROOT"] = str(base / "capsules")
        os.environ["XDG_DOCUMENTS_DIR"] = str(home / "Documents")
        os.environ["XDG_DOWNLOAD_DIR"] = str(home / "Downloads")
        os.environ["XDG_PICTURES_DIR"] = str(home / "Pictures")
        os.environ["XDG_MUSIC_DIR"] = str(home / "Music")
        os.environ["XDG_VIDEOS_DIR"] = str(home / "Videos")
        os.environ["XDG_DESKTOP_DIR"] = str(home / "Desktop")

        registry = catalog.load_catalog() if load_catalog else catalog.CatalogRegistry.from_entries(())
        names = dict(registry.names())
        names.setdefault("org.example.PhotoEditor", "Photo Editor")

        store = TrustStore(trust.default_store_path(), session_id=session_id).load()
        audit = TrustAudit(trust.default_audit_path(), names=names)
        surface = ScriptedSurface(answers=list(answers))
        gate = TrustGate(store=store, audit=audit, surface=surface, names=names)
        executor = RecordingExecutor()
        runtime = CapsuleRuntime(
            store=store,
            audit=audit,
            gate=gate,
            session_id=session_id,
            root=capsules.default_capsule_root(),
            probe=probe or confining_probe(),
            executor=executor,
        )
        return cls(
            base=base,
            home=home,
            store=store,
            audit=audit,
            surface=surface,
            gate=gate,
            runtime=runtime,
            registry=registry,
            executor=executor,
            _previous_environment=previous,
        )

    # -- convenience -----------------------------------------------------

    def file(self, relative: str, content: bytes = b"data") -> Path:
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def install(self, manifest: CapsuleManifest | None = None, *, install_consent: bool = False):
        return self.runtime.install(manifest or manifest_for(), install_consent=install_consent)

    def answer(self, *answers: tuple[str, str, str]) -> None:
        self.surface.answers.extend(answers)

    def request(self, capsule, **kwargs):  # type: ignore[no-untyped-def]
        return self.runtime.request_permission(capsule, **kwargs)

    def close(self) -> None:
        for key, value in self._previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.base, ignore_errors=True)
