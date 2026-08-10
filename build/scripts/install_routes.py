# SPDX-License-Identifier: GPL-3.0-or-later
"""What the build installs into the image, declared once and read by both sides.

This module exists because the two programs that need to agree about the install
set were separately maintaining their own idea of it, and they disagreed.

``build/scripts/install-root.py`` puts files into the container filesystem.
``build/scripts/build-input-closure.py`` answers "is this change build-affecting?"
by reading the installer. The reader modelled ``copy_tree`` and ``copy_file`` and
nothing else, so ``copy_python_package`` — the call that installs the *entire*
``capability`` and ``companion`` packages — was skipped. Not reported as
unresolved: skipped, because the loop that collected routes filtered on the
helper name before it recorded anything. Every Python file under ``companion/``
was therefore classified ``context-only``, which reads as "probably not in the
artifact", and the voice runtime's build impact was reported as zero paths when
it was in fact the whole package.

A second list is a second truth. So there is one list, here, and:

* :func:`installed_destination` is the *only* implementation of "does this
  repository path reach the image, and where" — the installer selects the files
  it copies with it, and the analyser classifies changed paths with it. They
  cannot drift because there is nothing to drift between;
* the semantics of each helper are properties of a route ``kind`` rather than of
  a function name, so renaming a helper cannot silently drop coverage;
* :data:`MODELLED_HELPERS` names every call the installer may use to put bytes
  in the image, and :func:`audit_installer` refuses anything else. A new helper
  fails the closure closed — exit 2, no claim — until it is modelled here.

Nothing in this module touches the filesystem except :func:`route_files`, and
nothing in it imports anything outside the standard library, because it is
imported by a script that runs inside a bootc container with no repository
Python on its path.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Mapping, Sequence

__all__ = [
    "COPY_HELPERS",
    "GENERATED_ROUTES",
    "GENERATOR_FUNCTIONS",
    "INSTALL_ROUTES",
    "INSTALL_STAGES",
    "MODELLED_HELPERS",
    "PROFILES",
    "SYSTEM_SCRIPTS",
    "InstallRoute",
    "UnmodelledInstaller",
    "audit_installer",
    "declared_routes_json",
    "installed_destination",
    "route_files",
    "routes_for_profile",
]

#: Every profile ``install-root.py`` accepts. A route names the subset it
#: applies to; a route that names none applies to all of them.
PROFILES: tuple[str, ...] = (
    "developer", "minimal", "desktop", "recovery", "shell", "shell-test", "live", "beta",
)

#: Profiles that get the desktop shell, the character packages and the companion
#: assets. Named rather than repeated, because the set appears twice in the
#: installer and once in the preset table and a copy that fell out of step would
#: install a shell into a profile that has no session to run it.
DESKTOP_PROFILES = frozenset({"developer", "desktop", "shell", "shell-test", "live", "beta"})

#: Profiles that carry the installer front end.
INSTALLER_PROFILES = frozenset({"live", "beta"})

#: The bootable installation medium.
LIVE_PROFILES = frozenset({"live"})

#: Directory names a ``tree`` route never descends into. Build residue: bytecode
#: that embeds the source path and mtime of the machine that produced it, and
#: dependency trees that belong to a developer checkout.
TREE_EXCLUDED = ("__pycache__", "node_modules", "target")

#: Directory names a ``package`` route never descends into, and the reason is
#: not tidiness. These packages carry test fixtures, probe helpers and sample
#: data: a fixture is untrusted-input-shaped content, and putting it on a
#: read-only root enlarges the artifact and the attack surface for no benefit.
PACKAGE_EXCLUDED = ("__pycache__", "testing", "tests")

#: A ``package`` route installs source and only source.
PACKAGE_SUFFIXES = (".py",)

#: The first-boot and recovery programs, installed from ``scripts/<name>.py``.
#: One tuple, read by the installer's loop and by the route table below, so a
#: program added here is installed *and* classified without a second edit.
#:
#: ``bunny-brlapi-key`` is in this list because its absence was measured rather
#: than noticed: the unit shipped, finalisation removes ``/etc/brlapi.key`` from
#: the archive, and nothing installed the program that mints it on first boot.
SYSTEM_SCRIPTS: tuple[str, ...] = (
    "bunny-health-check",
    "bunny-first-boot",
    "bunny-config-dir",
    "bunny-brlapi-key",
    "bunny-recovery-generator",
    "bunny-recovery-prepare",
    "bunny-recovery",
    "bunny-safe-graphics",
    "bunny-live-session",
)

#: The one system script that is a systemd generator rather than a libexec
#: program, and therefore lands somewhere else.
SYSTEM_SCRIPT_DESTINATIONS: Mapping[str, str] = {
    "bunny-recovery-generator": "/usr/lib/systemd/system-generators/bunny-recovery-generator",
}


@dataclass(frozen=True)
class InstallRoute:
    """One rule that carries repository content into the image.

    ``kind`` is the whole of the copying semantics, and the reason it is a
    property of the route rather than of the helper that executes it: a helper
    can be renamed, split or inlined without any of these fields moving.

    ``file``
        one repository file to one absolute destination.
    ``tree``
        a directory copied recursively, skipping :data:`TREE_EXCLUDED`.
    ``package``
        a repository Python package: ``*.py`` only, skipping
        :data:`PACKAGE_EXCLUDED`. This is ``copy_python_package``, and it is the
        route the analyser did not model.
    ``glob``
        the flat contents of one directory, with per-name destination
        overrides for the entries that go somewhere else.
    """

    id: str
    kind: str
    source: str
    destination: str
    mode: int = 0o644
    #: ``None`` means every profile.
    profiles: frozenset[str] | None = None
    exclude: tuple[str, ...] = ()
    exclude_stems: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    destination_overrides: Mapping[str, str] = field(default_factory=dict)
    note: str = ""

    def applies_to(self, profile: str) -> bool:
        return self.profiles is None or profile in self.profiles

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "destination": self.destination,
            "mode": oct(self.mode),
            "profiles": sorted(self.profiles) if self.profiles is not None else list(PROFILES),
            "exclude": list(self.effective_exclude),
            "excludeStems": list(self.exclude_stems),
            "suffixes": list(self.effective_suffixes),
            "destinationOverrides": dict(self.destination_overrides),
            "note": self.note,
        }

    @property
    def effective_exclude(self) -> tuple[str, ...]:
        if self.exclude:
            return self.exclude
        if self.kind == "tree":
            return TREE_EXCLUDED
        if self.kind == "package":
            return PACKAGE_EXCLUDED
        return ()

    @property
    def effective_suffixes(self) -> tuple[str, ...]:
        if self.suffixes:
            return self.suffixes
        return PACKAGE_SUFFIXES if self.kind == "package" else ()


def _file_route(identifier: str, source: str, destination: str, mode: int, **extra: Any) -> InstallRoute:
    return InstallRoute(identifier, "file", source, destination, mode, **extra)


_SCRIPT_ROUTES = tuple(
    _file_route(
        f"system-script-{name}",
        f"scripts/{name}.py",
        SYSTEM_SCRIPT_DESTINATIONS.get(name, f"/usr/libexec/{name}"),
        0o555,
        note="first-boot, health and recovery programs",
    )
    for name in SYSTEM_SCRIPTS
)


#: Every route, in installer order. This is the install set.
INSTALL_ROUTES: tuple[InstallRoute, ...] = (
    InstallRoute(
        "system-broker-python", "tree",
        "services/bunny-system-broker/src/bunny_system_broker",
        "/usr/lib/bunny-system-broker/bunny_system_broker", 0o644,
    ),
    InstallRoute(
        "bunny-os-python", "tree",
        "tools/bunny-os/bunny_os", "/usr/lib/bunny-os/python/bunny_os", 0o644,
    ),
    # The capability runtime and the companion, on one import path so that
    # `bunny-os companion` works on an installed system without a second copy of
    # either. The companion imports the capability runtime for every routing
    # decision; installing one without the other gives the user service an
    # ImportError on each restart.
    InstallRoute(
        "capability-package", "package",
        "capability", "/usr/lib/bunny-os/python/capability", 0o444,
        note="copy_python_package: source only, no fixtures, read-only",
    ),
    InstallRoute(
        "companion-package", "package",
        "companion", "/usr/lib/bunny-os/python/companion", 0o444,
        note=(
            "copy_python_package: the whole companion package including "
            "companion/voice/ and companion/character/. The route the closure "
            "analyser did not model, which is why the voice runtime's build "
            "impact was reported as zero"
        ),
    ),
    # Data the capability registry reads at start-up. Without it the registry
    # silently falls back to the source tree, which does not exist on an
    # installed system.
    InstallRoute(
        "capability-service-manifests", "tree",
        "capability/services", "/usr/share/bunny-os/capability/services", 0o444,
    ),
    _file_route(
        "companion-service-executable",
        "services/bunny-companion/bunny_companion_service.py",
        "/usr/libexec/bunny-companion-service", 0o555,
    ),
    InstallRoute(
        "installer-python", "tree",
        "installer", "/usr/lib/bunny-installer/installer", 0o644,
    ),
    _file_route(
        "system-broker-executable",
        "services/bunny-system-broker/bin/bunny-system-broker",
        "/usr/libexec/bunny-system-broker", 0o555,
    ),
    _file_route(
        "update-agent-executable",
        "services/bunny-update-agent/bunny_update_agent.py",
        "/usr/libexec/bunny-update-agent", 0o555,
    ),
    _file_route("bunny-os-command", "tools/bunny-os/bin/bunny-os", "/usr/bin/bunny-os", 0o555),
    _file_route(
        "bunny-os-info-command", "tools/bunny-os/bin/bunny-os-info",
        "/usr/bin/bunny-os-info", 0o555,
    ),
    *_SCRIPT_ROUTES,
    _file_route(
        "greenboot-health-check", "scripts/greenboot-bunny-health.sh",
        "/usr/libexec/greenboot/check/required.d/10-bunny-os-health", 0o555,
    ),
    InstallRoute(
        "system-units", "tree", "systemd", "/usr/lib/systemd/system", 0o644,
        exclude=(*TREE_EXCLUDED, "user"),
        note=(
            "the `user` subdirectory is removed from /usr/lib/systemd/system "
            "after the copy; excluded here so the analyser reports where a user "
            "unit actually lands rather than where it is briefly written"
        ),
    ),
    InstallRoute(
        "user-units", "tree", "systemd/user", "/usr/lib/systemd/user", 0o644,
    ),
    _file_route(
        "polkit-policy", "config/polkit/art.comrade.bunny-os.policy",
        "/usr/share/polkit-1/actions/art.comrade.bunny-os.policy", 0o644,
    ),
    _file_route(
        "tmpfiles", "config/tmpfiles/bunny-os.conf",
        "/usr/lib/tmpfiles.d/bunny-os.conf", 0o644,
    ),
    # /usr/share/user-tmpfiles.d, not /usr/lib/user-tmpfiles.d: the latter is not
    # in systemd's --user search path and a rule placed there is never read.
    _file_route(
        "user-tmpfiles", "config/user-tmpfiles/bunny-os.conf",
        "/usr/share/user-tmpfiles.d/bunny-os.conf", 0o644,
    ),
    _file_route(
        "firewalld-zone", "config/firewalld/bunny-default.xml",
        "/usr/lib/firewalld/zones/bunny-default.xml", 0o644,
    ),
    _file_route(
        "system-preset", "config/systemd/60-bunny-os.preset",
        "/usr/lib/systemd/system-preset/60-bunny-os.preset", 0o644,
    ),
    _file_route(
        "user-preset", "config/systemd/60-bunny-os-user.preset",
        "/usr/lib/systemd/user-preset/60-bunny-os.preset", 0o644,
    ),
    _file_route(
        "sysctl", "config/sysctl/60-bunny-os.conf",
        "/usr/lib/sysctl.d/60-bunny-os.conf", 0o644,
    ),
    _file_route(
        "desktop-entry", "desktop-integration/art.comrade.Bunny.desktop",
        "/usr/share/applications/art.comrade.Bunny.desktop", 0o644,
    ),
    _file_route(
        "desktop-launcher", "desktop-integration/bunny-desktop-launch.py",
        "/usr/libexec/bunny-desktop-launch", 0o555,
    ),

    # -- the desktop profiles ------------------------------------------------
    InstallRoute(
        "shell-python", "tree", "shell/services/bunny_shell",
        "/usr/lib/bunny-shell/bunny_shell", 0o644, profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "shell-commands", "glob", "shell/services/bin", "/usr/bin", 0o555,
        profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "shell-service-executable", "shell/services/bin/bunny-shell-service",
        "/usr/libexec/bunny-shell-service", 0o555, profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "shell-session-executable", "shell/session/bunny-shell-session.py",
        "/usr/libexec/bunny-shell-session", 0o555, profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "wayland-session", "shell/session/bunny.desktop",
        "/usr/share/wayland-sessions/bunny.desktop", 0o644, profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "wayland-safe-session", "shell/session/bunny-safe.desktop",
        "/usr/share/wayland-sessions/bunny-safe.desktop", 0o644, profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "gnome-shell-extension", "tree", "shell/components/gnome-shell-extension",
        "/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org", 0o644,
        profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "shell-applications", "tree", "shell/components/applications",
        "/usr/share/applications", 0o644, profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "nautilus-extension", "shell/components/nautilus/bunny-nautilus.py",
        "/usr/share/nautilus-python/extensions/bunny-nautilus.py", 0o444,
        profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "dconf-shell-defaults", "shell/components/dconf/10-bunny-shell",
        "/etc/dconf/db/local.d/10-bunny-shell", 0o644, profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "dconf-user-profile", "shell/components/dconf/profile-user",
        "/etc/dconf/profile/user", 0o644, profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "shell-themes", "tree", "shell/themes", "/usr/share/bunny-shell/themes", 0o444,
        profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "wallpapers", "tree", "shell/assets/wallpapers",
        "/usr/share/backgrounds/bunny-os", 0o444, profiles=DESKTOP_PROFILES,
    ),
    # 0444: the character is read-only data on a read-only filesystem, and
    # companion.characters refuses it outright if it is ever found executable.
    InstallRoute(
        "companion-shell-assets", "tree", "shell/assets/companion",
        "/usr/share/bunny-shell/companion", 0o444, profiles=DESKTOP_PROFILES,
    ),
    # Character packages are data, never imported as code. 0444 matches the
    # validator's refusal of an executable bit, so a package that arrived with
    # one would be refused rather than drawn. These are the mouth assets the
    # lip-sync slice draws.
    InstallRoute(
        "character-packages", "tree", "assets/companion/characters",
        "/usr/share/bunny-os/companion/characters", 0o444, profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "icons", "tree", "shell/icons/hicolor", "/usr/share/icons/hicolor", 0o444,
        profiles=DESKTOP_PROFILES,
    ),
    InstallRoute(
        "shell-schemas", "tree", "shell/schemas", "/usr/share/bunny-os/schemas/shell", 0o444,
        profiles=DESKTOP_PROFILES,
    ),

    # -- the installer profiles ----------------------------------------------
    InstallRoute(
        "installer-commands", "glob", "installer/bin", "/usr/bin", 0o555,
        profiles=INSTALLER_PROFILES,
        destination_overrides={"bunny-installer-backend": "/usr/libexec/bunny-installer-backend"},
    ),
    _file_route(
        "installer-desktop-entry", "installer/frontend/art.comrade.BunnyInstaller.desktop",
        "/usr/share/applications/art.comrade.BunnyInstaller.desktop", 0o644,
        profiles=INSTALLER_PROFILES,
    ),
    _file_route(
        "first-run-desktop-entry", "installer/first_run/art.comrade.BunnyFirstRun.desktop",
        "/usr/share/applications/art.comrade.BunnyFirstRun.desktop", 0o644,
        profiles=INSTALLER_PROFILES,
    ),

    # -- the live medium -----------------------------------------------------
    _file_route(
        "live-iso-config", "installer/config/iso.yaml",
        "/usr/lib/image-builder/bootc/iso.yaml", 0o444, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "anaconda-profile", "installer/config/bunny-os.conf",
        "/etc/anaconda/profile.d/bunny-os.conf", 0o444, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "anaconda-defaults", "installer/config/interactive-defaults.ks",
        "/usr/share/anaconda/interactive-defaults.ks", 0o444, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "live-gdm-config", "installer/config/gdm-live.conf",
        "/etc/gdm/custom.conf", 0o644, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "live-dconf-defaults", "installer/config/20-bunny-live",
        "/etc/dconf/db/local.d/20-bunny-live", 0o644, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "live-installer-autostart",
        "installer/frontend/art.comrade.BunnyInstaller-autostart.desktop",
        "/etc/xdg/autostart/art.comrade.BunnyInstaller.desktop", 0o644, profiles=LIVE_PROFILES,
    ),

    # -- unconditional, and last ---------------------------------------------
    _file_route(
        "update-configuration", "build/manifests/update.disabled.json",
        "/etc/bunny-os/update.json", 0o600,
    ),
    _file_route(
        "artifact-manifest", "build/manifests/bunny-artifact.placeholder.json",
        "/usr/share/bunny-os/bunny-artifact.json", 0o444,
    ),
    _file_route(
        "revoked-update-keys", "build/keys/revoked-keys.json",
        "/usr/share/bunny-os/update-keys/revoked-keys.json", 0o444,
    ),
    # Qualification scaffolding, not a feature: the marker is how an update and
    # a rollback are observed to have changed the deployed root rather than
    # assumed to have.
    _file_route(
        "qualification-update-marker", "config/qualification-update-marker.json",
        "/usr/share/bunny-os/qualification-update-marker.json", 0o444,
    ),
    InstallRoute("schemas", "tree", "schemas", "/usr/share/bunny-os/schemas", 0o444),
    InstallRoute("documentation", "tree", "docs", "/usr/share/doc/bunny-os", 0o444),
    _file_route("architecture-document", "ARCHITECTURE.md", "/usr/share/doc/bunny-os/ARCHITECTURE.md", 0o444),
    _file_route("readme", "README.md", "/usr/share/doc/bunny-os/README.md", 0o444),

    # The verified release payload. Its destination is computed from the
    # artifact manifest's version, so the installed path carries a wildcard —
    # reported as a route with a wildcard rather than dropped, because a path
    # this analyser could not resolve and silently omitted is the exact failure
    # this whole module exists to prevent.
    InstallRoute(
        "release-payload", "tree", "build/artifacts/bunny", "/opt/bunny/releases/*", 0o644,
        note=(
            "copied only when build/manifests/bunny-artifact.placeholder.json "
            "records status=verified; the release directory is named from the "
            "manifest's bunnyVersion and the per-file mode comes from the manifest"
        ),
    ),
)


#: Paths written into the image that are not copies of a repository file. They
#: are declared because a reader of the copy routes alone would miss them, and
#: two of them change on every commit — which is why an unchanged layer digest
#: is never an unchanged image.
GENERATED_ROUTES: tuple[Mapping[str, Any], ...] = (
    {
        "destination": "OCI config label org.opencontainers.image.revision",
        "derivedFrom": "the git commit being built (BUNNY_SOURCE_COMMIT)",
        "producer": "build/Containerfile",
        "note": (
            "every commit changes the OCI configuration digest, whatever its content. "
            "Recorded here so that an unchanged layer digest is never mistaken for an "
            "unchanged image."
        ),
    },
    {
        "destination": "/usr/lib/bunny-os/release.json",
        "derivedFrom": "the git commit being built (sourceCommit field)",
        "producer": "install-root.py:write_release_metadata",
        "note": "changes on every commit",
    },
    {
        "destination": "/usr/lib/bunny-os/packages.txt",
        "derivedFrom": "rpm -qa inside the container",
        "producer": "install-root.py:write_package_inventory",
        "note": "derived from the package snapshot, not from repository sources",
    },
    {
        "destination": "/opt/bunny/current",
        "derivedFrom": "build/manifests/bunny-artifact.placeholder.json (bunnyVersion, status)",
        "producer": "install-root.py:install_release_payload",
        "note": "a relative symlink into /opt/bunny/releases",
    },
    {
        "destination": "/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org/schemas/gschemas.compiled",
        "derivedFrom": "shell/components/gnome-shell-extension/schemas/*.xml",
        "producer": "glib-compile-schemas",
        "note": "compiled in place from the copied schema sources",
    },
    {
        "destination": "/etc/dconf/db/local",
        "derivedFrom": "shell/components/dconf/10-bunny-shell and installer/config/20-bunny-live",
        "producer": "dconf update",
        "note": "the compiled dconf database",
    },
    {
        "destination": "/usr/share/icons/hicolor/icon-theme.cache",
        "derivedFrom": "shell/icons/hicolor/**",
        "producer": "gtk-update-icon-cache",
        "note": "best-effort; the build does not fail if it is absent",
    },
    {
        "destination": "/var/lib/bunny, /var/cache/bunny, /var/log/bunny, /var/lib/bunny-os/**",
        "derivedFrom": "nothing; created empty with fixed modes",
        "producer": "install-root.py:create_state_directories",
        "note": "state directories, no repository content",
    },
    {
        "destination": "/etc/systemd/**/*.wants/*.service, /etc/systemd/user/**",
        "derivedFrom": "systemd/** and config/systemd/*.preset",
        "producer": "systemctl enable",
        "note": (
            "activation symlinks. A unit that ships without its enablement is a "
            "unit systemd will never start, which is how /etc/brlapi.key came to "
            "be absent on every installed system; install-root.py asserts these "
            "exist before it returns"
        ),
    },
)


#: The functions in ``install-root.py`` that actually move repository bytes, and
#: the route ``kind`` each implements. Nothing else may copy.
#:
#: This is the fail-closed list. :func:`audit_installer` refuses an installer
#: that defines a copying helper absent from it, *or* issues a copy from
#: anywhere but one of these, and the closure analyser turns that refusal into
#: exit 2 with no claim made. A helper added without a route kind to model it
#: therefore fails the gate rather than quietly widening the install set behind
#: the analyser's back.
COPY_HELPERS: Mapping[str, str] = {
    "copy_file": "file",
    "copy_route": "route-engine",
}

#: The table-driven stages ``main`` is allowed to call. Each may issue copies,
#: and each must do so through the route table; none takes a source path of its
#: own. They are separated from :data:`COPY_HELPERS` so that "who may copy" and
#: "who may be called from ``main``" are two different questions with two
#: different answers — the arrangement that makes ``main`` unable to install
#: anything the table has not declared.
INSTALL_STAGES: frozenset[str] = frozenset({
    "install_all_routes",
    "install_release_payload",
    "install_activation",
})

#: Functions that may write generated content — a file whose bytes are computed
#: rather than copied. Each corresponds to an entry in :data:`GENERATED_ROUTES`.
#: A new generated file written from anywhere else fails the audit, because a
#: generated file nobody declared is a build input nobody can attribute.
GENERATOR_FUNCTIONS: frozenset[str] = frozenset({
    "write_release_metadata",
    "write_package_inventory",
})

#: Everything the installer is permitted to do that puts bytes in the image.
MODELLED_HELPERS: Mapping[str, str] = {
    **COPY_HELPERS,
    **{name: "stage" for name in sorted(INSTALL_STAGES)},
    **{name: "generated" for name in sorted(GENERATOR_FUNCTIONS)},
}

#: Standard-library primitives that actually move bytes. They may appear only
#: inside a definition named in :data:`COPY_HELPERS`; anywhere else they are an
#: unmodelled install route.
_COPY_PRIMITIVES = frozenset({
    "copyfile", "copytree", "copy", "copy2", "copyfileobj", "copymode", "copystat",
    "link", "symlink_to", "hardlink_to",
})

#: Primitives that write computed content. Permitted only inside
#: :data:`GENERATOR_FUNCTIONS`.
_WRITE_PRIMITIVES = frozenset({"write_text", "write_bytes"})

#: A definition whose name begins with one of these is an install helper by
#: convention, and must be modelled. The convention is enforced rather than
#: trusted: a helper called something else is caught by the primitive rule
#: above, because it has to copy bytes somehow.
_HELPER_PREFIXES = ("copy_", "install_")


class UnmodelledInstaller(RuntimeError):
    """The installer does something the route table does not describe."""


# --------------------------------------------------------------------------- #
# The predicate. One implementation, both consumers.
# --------------------------------------------------------------------------- #


def _excluded(route: InstallRoute, remainder: str) -> bool:
    parts = PurePosixPath(remainder).parts if remainder else ()
    if set(route.effective_exclude).intersection(parts):
        return True
    if remainder and PurePosixPath(remainder).stem in route.exclude_stems:
        return True
    suffixes = route.effective_suffixes
    if suffixes and remainder and PurePosixPath(remainder).suffix not in suffixes:
        return True
    return False


def installed_destination(route: InstallRoute, path: str) -> str | None:
    """Where ``path`` lands under ``route``, or ``None`` if it does not.

    ``path`` is repository-relative and POSIX-separated. This is a pure string
    function on purpose: the analyser calls it for paths that no longer exist
    (a file deleted by the change it is classifying) and the installer calls it
    for paths that do. A predicate that needed the file to be present could not
    answer the analyser's question at all.
    """
    normalised = path.replace("\\", "/").strip("/")
    if not normalised:
        return None
    source = route.source.strip("/")

    if route.kind == "file":
        return route.destination if normalised == source else None

    if route.kind == "glob":
        parent, _, name = normalised.rpartition("/")
        if parent != source or not name:
            return None
        override = route.destination_overrides.get(name)
        if override:
            return override
        return f"{route.destination.rstrip('/')}/{name}"

    if route.kind in ("tree", "package"):
        if normalised == source:
            return route.destination
        if not normalised.startswith(source + "/"):
            return None
        remainder = normalised[len(source) + 1:]
        if _excluded(route, remainder):
            return None
        return f"{route.destination.rstrip('/')}/{remainder}"

    raise UnmodelledInstaller(f"route {route.id!r} has unknown kind {route.kind!r}")


def routes_for_profile(profile: str, routes: Sequence[InstallRoute] = INSTALL_ROUTES) -> tuple[InstallRoute, ...]:
    if profile not in PROFILES:
        raise UnmodelledInstaller(f"{profile!r} is not an install profile")
    return tuple(route for route in routes if route.applies_to(profile))


def route_files(route: InstallRoute, source_root: Path) -> Iterator[tuple[Path, str]]:
    """The files ``route`` selects under ``source_root``, and where each lands.

    Selection is :func:`installed_destination` applied to every candidate, so
    the installer copies exactly the set the analyser reports. A file the
    analyser calls installed that the installer skips — or the reverse — would
    require the two to disagree about a function neither of them owns a second
    copy of.
    """
    source = source_root / route.source
    if route.kind == "file":
        if source.is_file():
            yield source, route.destination
        return

    if route.kind == "glob":
        if not source.is_dir():
            return
        for item in sorted(source.iterdir()):
            if not item.is_file():
                continue
            destination = installed_destination(route, f"{route.source}/{item.name}")
            if destination is not None:
                yield item, destination
        return

    if route.kind in ("tree", "package"):
        if not source.is_dir():
            return
        for item in sorted(source.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(source).as_posix()
            destination = installed_destination(route, f"{route.source}/{relative}")
            if destination is not None:
                yield item, destination
        return

    raise UnmodelledInstaller(f"route {route.id!r} has unknown kind {route.kind!r}")


# --------------------------------------------------------------------------- #
# The fail-closed audit
# --------------------------------------------------------------------------- #


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def audit_installer(installer: Path | str, *, source: str | None = None) -> list[str]:
    """Every way ``install-root.py`` could install something that is not modelled.

    Returns a list of complaints; empty means the route table describes the
    installer completely. The caller is expected to *refuse to answer* when this
    is non-empty rather than to answer without the unmodelled part, because an
    understated closure is worse than no closure: it licenses exactly the "this
    change does not affect the build" claim it cannot support.
    """
    text = source if source is not None else Path(installer).read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(installer))
    complaints: list[str] = []

    #: Which function definition each node sits inside, so a primitive can be
    #: allowed in a modelled helper and refused outside one.
    enclosing: dict[int, str] = {}

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            enclosing[id(child)] = name
            walk(child, name)

    enclosing[id(tree)] = ""
    walk(tree, "")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith(_HELPER_PREFIXES) and node.name not in MODELLED_HELPERS:
                complaints.append(
                    f"line {node.lineno}: {node.name}() is an install helper the route "
                    "table does not model. Declare it in COPY_HELPERS or INSTALL_STAGES "
                    "with the route kind it implements, or express it as a route."
                )
            continue
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if not name:
            continue
        holder = enclosing.get(id(node), "")
        if name.startswith(_HELPER_PREFIXES) and name not in MODELLED_HELPERS:
            complaints.append(
                f"line {node.lineno}: {name}() is called to install something and is "
                "not modelled"
            )
        elif name in COPY_HELPERS and holder not in COPY_HELPERS and holder not in INSTALL_STAGES:
            # The rule that keeps `main` from installing anything the table has
            # not declared. A copy issued from an arbitrary function takes its
            # source and destination from that function's arguments, which the
            # analyser cannot read; the same copy issued from a stage takes them
            # from a route, which it can.
            complaints.append(
                f"line {node.lineno}: {name}() is called from "
                f"{holder or 'module scope'} rather than from a route stage; its "
                "source and destination are not declared in INSTALL_ROUTES"
            )
        elif name in _COPY_PRIMITIVES and holder not in COPY_HELPERS and holder not in INSTALL_STAGES:
            complaints.append(
                f"line {node.lineno}: {name}() copies bytes from "
                f"{holder or 'module scope'}, which is not a modelled copy helper; "
                "the route table cannot describe what it installs"
            )
        elif name in _WRITE_PRIMITIVES and holder not in GENERATOR_FUNCTIONS:
            complaints.append(
                f"line {node.lineno}: {name}() writes generated content from "
                f"{holder or 'module scope'}, which is not a declared generator; "
                "add it to GENERATOR_FUNCTIONS and GENERATED_ROUTES"
            )
    return complaints


def declared_routes_json() -> list[dict[str, Any]]:
    return [route.to_json() for route in INSTALL_ROUTES]


def iter_routes(profile: str | None = None) -> Iterable[InstallRoute]:
    return INSTALL_ROUTES if profile is None else routes_for_profile(profile)
