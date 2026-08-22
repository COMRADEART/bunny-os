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
    "bunny-anaconda-bus-ready",
    "bunny-health-check",
    "bunny-first-boot",
    "bunny-config-dir",
    "bunny-brlapi-key",
    "bunny-recovery-generator",
    "bunny-recovery-prepare",
    "bunny-recovery",
    "bunny-safe-graphics",
    "bunny-live-session",
    # The Public Alpha session programs. The window launcher is what makes
    # "Bunny appears when you log in" true — the runtime has been a unit since
    # the integration branch and nothing started the *window* — and the
    # diagnostics program is deliberately outside the companion, because the
    # moment it is wanted is the moment the companion is not there to offer it.
    #
    # Installed on every profile rather than only the desktop ones: the units
    # that run them carry their own conditions, and a profile that has no
    # graphical session simply never starts them. A profile that had the unit
    # and not the program would be a unit that fails at every login.
    "bunny-companion-window",
    "bunny-companion-recovery",
    # The first application a capsule runs. It is a system program rather than
    # part of the companion package because a capsule gives its process no Bunny
    # code on its import path: a program that imported the companion could not
    # run inside the sandbox it exists for, and the failure would only appear on
    # a machine where the sandbox worked. The catalogue entry names this exact
    # path, so a profile with the entry and without the program would offer an
    # operation that cannot start.
    "bunny-image-tool",
    # The readiness probe. Installed on every profile because the thing it
    # answers - "is this session usable" - is a question a support call asks as
    # often as a qualification harness does, and a probe that only exists in a
    # test image cannot answer it on a machine that is actually broken.
    "bunny-session-ready",
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
    # The three packages the Companion speaks for: the permission layer, the
    # capsule runtime, and the curated catalogue. On the same import path as the
    # companion, because `companion.capsule_bridge` imports all three and an
    # installed system with the companion and without them gives the user
    # service an ImportError on every start.
    #
    # `trust` first in this list for the same reason it is first in the
    # dependency order: `capsules` and `catalog` both import it and neither is
    # useful without it.
    InstallRoute(
        "trust-package", "package",
        "trust", "/usr/lib/bunny-os/python/trust", 0o444,
        note="copy_python_package: source only, read-only. The permission layer.",
    ),
    InstallRoute(
        "capsules-package", "package",
        "capsules", "/usr/lib/bunny-os/python/capsules", 0o444,
        note="copy_python_package: source only, read-only. The App Capsule runtime.",
    ),
    InstallRoute(
        "catalog-package", "package",
        "catalog", "/usr/lib/bunny-os/python/catalog", 0o444,
        note=(
            "copy_python_package: source only. The catalogue's JSON entries live "
            "under catalog/data/ and are installed by the route below, because a "
            "package route copies source and these are data."
        ),
    ),
    # The curated catalogue entries. Without them every application resolves to
    # UNDECLARED and the trust layer refuses everything not already granted —
    # fail-closed, correct, and completely unusable. This is the route whose
    # absence would make a booted image look like a permission bug.
    InstallRoute(
        "app-catalog-entries", "tree",
        "catalog/data", "/usr/share/bunny-os/catalog", 0o444,
    ),
    # Data the capability registry reads at start-up. Without it the registry
    # silently falls back to the source tree, which does not exist on an
    # installed system.
    InstallRoute(
        "capability-service-manifests", "tree",
        "capability/services", "/usr/share/bunny-os/capability/services", 0o444,
        # The probe manifest is a validation fixture: it names an entry point
        # under capability/testing/, which no route installs, and a fixture on a
        # read-only root is attack surface with no user. Excluded by stem, the
        # way the pre-table installer excluded it.
        exclude_stems=("bunny-capability-probe",),
    ),
    _file_route(
        "capability-supervisor-executable",
        "services/bunny-capability-supervisor/bunny_capability_supervisor.py",
        "/usr/libexec/bunny-capability-supervisor", 0o555,
        note="the control plane's entry point; enabled by install_activation() "
             "in install-root.py — presets are never applied in this build",
    ),
    _file_route(
        "capability-supervisor-configuration",
        "config/bunny-os/capability-supervisor.json",
        "/etc/bunny-os/capability/supervisor.json", 0o644,
        note="observe-only as shipped; enabling apply is a documented operator act",
    ),
    # The Alpha speech model is immutable image data, not first-run mutable
    # state. Shipping the reviewed bytes here makes push-to-talk work offline
    # on a fresh installation and avoids any silent boot-time download.
    InstallRoute(
        "speech-recognition-models", "tree",
        "assets/voice/models", "/usr/share/bunny-os/speech-models", 0o444,
        profiles=DESKTOP_PROFILES,
        note="pinned local Vosk models with per-file Bunny integrity manifests",
    ),
    # Neural speech is immutable image data as well. Pocket is the default;
    # Kitten nano INT8 is the explicit low-resource option. Both trees carry a
    # manifest with every runtime file's size and SHA-256, and neither worker
    # has a download path at runtime.
    #
    # One route per engine, not one route for "the voice assets". The
    # destinations and the bytes are unchanged; what changes is that the
    # boundary is now stated where the build can act on it. Pocket costs about
    # 1.1 GiB uncompressed against Kitten's ~107 MiB, and a future image that
    # wants the small engine has to be able to leave the large one out by
    # dropping a route from a profile — not by editing a tree that mixes them,
    # and certainly not by changing SpeechSynthesisService, which selects by
    # provider id and descends a fixed fallback order whatever is installed.
    #
    # Conceptually: `bunny-voice-core` is the runtime, the recogniser model and
    # the licences; `bunny-tts-pocket` is the two routes below marked pocket;
    # `bunny-tts-kitten` is the kitten route; `bunny-tts-espeak` is a package
    # dependency rather than an asset, because eSpeak NG and Speech Dispatcher
    # come from Fedora.
    InstallRoute(
        "speech-synthesis-model-pocket", "tree",
        "assets/voice/tts/pocket", "/usr/share/bunny-os/voice/pocket", 0o444,
        profiles=DESKTOP_PROFILES,
        note="bunny-tts-pocket: the default engine's English model and prepared voice",
    ),
    InstallRoute(
        "speech-synthesis-model-kitten", "tree",
        "assets/voice/tts/kitten", "/usr/share/bunny-os/voice/kitten", 0o444,
        profiles=DESKTOP_PROFILES,
        note="bunny-tts-kitten: the low-resource engine's nano INT8 model and voices",
    ),
    InstallRoute(
        "speech-synthesis-runtime", "tree",
        "assets/voice/runtime", "/usr/lib/bunny-os/voice-runtime", 0o444,
        profiles=DESKTOP_PROFILES,
        note="bunny-tts-pocket: Pocket TTS v2.1.0 pure-Python runtime from an "
             "immutable upstream tag, plus the CPU PyTorch wheel it expands",
    ),
    InstallRoute(
        "speech-recognition-licenses", "tree",
        "assets/voice/licenses", "/usr/share/licenses/bunny-os-voice", 0o444,
        profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "speech-recognition-provenance", "assets/voice/PROVENANCE.json",
        "/usr/share/doc/bunny-os/voice-provenance.json", 0o444,
        profiles=DESKTOP_PROFILES,
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
    # A Speech Dispatcher drop-in, read through the `Include "clients/*.conf"`
    # that its own speechd.conf ends with. A drop-in rather than an edit,
    # because the RPM owns speechd.conf and an image that rewrote it would
    # report a modified configuration file for ever after. Desktop profiles
    # only: a profile with no voice runtime has no Speech Dispatcher to
    # configure.
    _file_route(
        "speech-dispatcher-log-bound", "config/speech-dispatcher/bunny-os.conf",
        "/etc/speech-dispatcher/clients/bunny-os.conf", 0o644,
        profiles=DESKTOP_PROFILES,
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
    # One entry the Public Alpha adds on the desktop profiles only, because an
    # applications list is a thing a desktop has. The companion entry itself is
    # installed by the shell-applications tree (Exec=/usr/bin/bunny-companion —
    # the tested policy); installing the desktop-integration variant here as
    # well put two different Exec= policies at one destination and let tuple
    # position decide which shipped. The diagnostics entry is the §18 surface,
    # reachable when there is no companion window to reach it from.
    _file_route(
        "companion-diagnostics-desktop-entry",
        "desktop-integration/art.comrade.BunnyDiagnostics.desktop",
        "/usr/share/applications/art.comrade.BunnyDiagnostics.desktop", 0o644,
        profiles=DESKTOP_PROFILES,
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
    # A session that ships is not a session anyone gets: GDM starts plain
    # GNOME for a user with no AccountsService record, where the Bunny
    # extension is inert (extension.js requires BUNNY_SHELL_MODE, which only
    # bunny-shell-session sets). The first attempted fix put
    # DefaultSession=bunny.desktop in /etc/gdm/custom.conf — and login-8b
    # measured GDM starting session "gnome" with that key in place, because
    # GDM's own schema (gdm.schemas) has no such key. There is no route for a
    # gdm default here any more: the mechanism GDM actually reads is the
    # per-user AccountsService record, which the installer now writes for the
    # account it creates (installer/backend/anaconda.py, _place_handoff).
    #
    # That write reaches exactly one account. An account added later through
    # the Users panel or created by gnome-initial-setup on an OEM device used
    # to land in stock GNOME — the same defect wearing a different user.
    # accounts-daemon's user templates are the mechanism for those: applied
    # when the *daemon* creates the account (the D-Bus CreateUser both of
    # those surfaces call), one template per account type. Measured on
    # accountsservice 23.13.9/fc44, because the obvious spellings are wrong
    # twice over: the filename is the bare account type — `standard`, not
    # `standard.template` — and a template never reaches an account that
    # already exists (useradd from a shell stays untemplated; the greeter
    # still offers Bunny to it). /usr/share/accountsservice/user-templates
    # is the vendor half of the search path and was verified to apply;
    # /etc/accountsservice/user-templates is the admin override. Desktop
    # profiles only, like the session the templates name.
    _file_route(
        "accountsservice-standard-template",
        "config/accountsservice/standard.template",
        "/usr/share/accountsservice/user-templates/standard", 0o644,
        profiles=DESKTOP_PROFILES,
    ),
    _file_route(
        "accountsservice-administrator-template",
        "config/accountsservice/administrator.template",
        "/usr/share/accountsservice/user-templates/administrator", 0o644,
        profiles=DESKTOP_PROFILES,
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
    # The trusted model directories the local.llamacli adapter and the Vosk
    # recognizer read. No model is vendored here: the tree carries a
    # PROVISIONING.md that documents the operator step, and the directory's
    # existence is what makes the trusted path available by default. An
    # operator who drops a GGUF / a vosk-model-* directory into the source
    # tree and rebuilds has it installed read-only; the adapter auto-discovers
    # it. 0444 matches the adapter's refusal of a writable model file.
    InstallRoute(
        "agent-models", "tree", "assets/ai/models",
        "/usr/share/bunny-os/agent-models", 0o444, profiles=DESKTOP_PROFILES,
        note=(
            "trusted local-AI model directory; no model vendored, provisioned "
            "by the operator — see assets/ai/models/PROVISIONING.md"
        ),
    ),
    # (A second route, "speech-models", installed this same tree to this same
    # destination and was removed: two routes writing one destination is what
    # install_all_routes' duplicate-destination guard refuses, and which bytes
    # shipped would have depended on tuple order had they ever differed. The
    # surviving declaration is "speech-recognition-models" above — the id the
    # installer's completeness gate and the closure analyser name.)
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
    # The initramfs modules image-builder requires of a bootc installer medium.
    # Placing the file is necessary and not sufficient: the initramfs has to be
    # regenerated afterwards, which build/Containerfile does for the live
    # profile. See the file's own comment for what happens without it.
    _file_route(
        "live-dracut-modules", "installer/config/bunny-live-dracut.conf",
        "/usr/lib/dracut/dracut.conf.d/95-bunny-live.conf", 0o444,
        profiles=LIVE_PROFILES,
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
    # The §42 driver. Almost every other harness in build/scripts stays on the
    # host and is injected into a disk image with guestfish, which an ISO cannot
    # be — it is read-only and there is nothing to inject into. So this one
    # ships, and the thing that drives the installer is the thing the installer
    # carries. It does nothing unless a kernel argument asks for it.
    _file_route(
        "live-setup-driver", "build/scripts/setup-drive.py",
        "/usr/libexec/bunny-setup-drive", 0o555, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "live-setup-driver-autostart",
        "installer/frontend/art.comrade.BunnySetupDrive-autostart.desktop",
        "/etc/xdg/autostart/art.comrade.BunnySetupDrive.desktop", 0o644,
        profiles=LIVE_PROFILES,
    ),
    _file_route(
        "live-medium-kickstart",
        "installer/config/medium.ks",
        "/usr/share/bunny-os/medium.ks", 0o444, profiles=LIVE_PROFILES,
    ),
    _file_route(
        "live-tmpfiles",
        "installer/config/tmpfiles-live.conf",
        "/usr/lib/tmpfiles.d/bunny-live.conf", 0o644, profiles=LIVE_PROFILES,
    ),
    # The medium runs permissive, the way Fedora's own installer media do;
    # the installed system keeps the payload's enforcing config. Run 21: the
    # services-configuration step's `systemctl enable --root` was denied
    # under the medium's enforcing policy and the install died after the
    # disk was erased. The file carries the full reasoning.
    _file_route(
        "live-selinux-permissive",
        "installer/config/selinux-live.conf",
        "/etc/selinux/config", 0o644, profiles=LIVE_PROFILES,
    ),
    # /mnt is a symlink on a bootc medium and systemd's enable --root
    # re-roots it inside the target (runs 18-23). Anaconda gets real paths.
    _file_route(
        "live-anaconda-target",
        "installer/config/anaconda-target-live.conf",
        "/etc/anaconda/conf.d/95-bunny-target.conf", 0o644, profiles=LIVE_PROFILES,
    ),
    # A medium-only overlay of one anaconda file: enable_service keeps
    # systemctl's words (module processes drop helper output at birth) and
    # tolerates a failed enable exactly when the unit is already wanted on
    # the target's own filesystem — runs 18-24 died at a preset-enabled
    # chronyd's redundant enable. The overlay file carries the reasoning.
    _file_route(
        "live-pyanaconda-service",
        "installer/overlays/pyanaconda-core-service.py",
        "/usr/lib64/python3.14/site-packages/pyanaconda/core/service.py",
        0o644, profiles=LIVE_PROFILES,
    ),
    InstallRoute(
        id="live-installer-payload",
        kind="tree",
        source="build/payload-oci",
        destination="/usr/share/bunny-os/payload-oci",
        mode=0o644,
        profiles=LIVE_PROFILES,
        note=(
            "The offline installation payload as an OCI layout, exported by "
            "build-live-image.sh from the exact payload image this medium is "
            "built beside. Run 13 of Journey A opened the ISO and found "
            "neither payload nor kickstart - a LiveOS medium embeds nothing "
            "by itself - so the install source rides in the live filesystem "
            "and medium.ks points anaconda at it."
        ),
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
        "destination": (
            "/usr/lib/bunny-os/voice-runtime/site-packages/"
            "{torch,functorch,torchgen,torch-2.9.1+cpu.dist-info}/**"
        ),
        "derivedFrom": (
            "assets/voice/runtime/wheels/torch-2.9.1+cpu-cp314-cp314-"
            "manylinux_2_28_x86_64.whl and its pinned MANIFEST.json"
        ),
        "producer": "install-root.py:expand_vendored_voice_wheels",
        "note": (
            "official PyTorch CPU wheel; outer SHA-256 and every wheel RECORD entry "
            "are verified before the build-time staging wheel is removed"
        ),
    },
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
        "destination": "/usr/lib/os-release",
        "derivedFrom": (
            "the base image's own os-release, plus the version, channel, build id, "
            "commit and profile of this build"
        ),
        "producer": "install-root.py:write_os_release",
        "note": (
            "extended, not rewritten. ID, VERSION_ID, PLATFORM_ID and CPE_NAME are kept "
            "exactly as the base image wrote them because dnf, SELinux and bootc key off "
            "them; NAME, PRETTY_NAME and VARIANT are display strings and are replaced. "
            "Changes on every commit, like release.json"
        ),
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
    "expand_vendored_voice_wheels",
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
    "write_os_release",
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
