# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The adapter behind the fail-closed gate: what actually installs Bunny OS.

`InstallerService._dispatch` raises `BackendUnavailable` on
``installer.install.start`` whenever ``production_adapter is None``, and until
this module existed nothing anywhere passed one. That gate is not being removed —
this is the thing it was waiting for, and it keeps failing closed for every
reason it can still fail.

## What it does, in order

1. Read the **installation medium's own kickstart** and take its payload
   directive. `installer.backend.kickstart` refuses to render without one, which
   is what stops this installing something other than the system on the medium.
2. Render the plan the backend already validated into a kickstart.
3. Write it to tmpfs at 0600.
4. Ask the executor whether it can install at all, and refuse before touching
   anything if it cannot.
5. Start it, and report engine stages as they happen.

Steps 1–4 all happen before any write, and each can refuse. Step 5 is the first
irreversible thing this codebase does.

## Why the executor is a separate object

The DBus interface Anaconda exposes is the one thing here that cannot be checked
without booting an installer ISO. Method names change between Anaconda releases,
and a wrong guess would be discovered at the worst possible moment — after a
person typed the name of a disk and pressed the button.

So :class:`AnacondaDBusExecutor` **introspects before it acts**. It asks the Boss
what methods it has, compares that against what it needs, and if anything is
missing it refuses and *says which*. The failure mode becomes a clear message on
the failure screen with the disk untouched, instead of an exception halfway
through a partition table. When this first runs on a real ISO the refusal will
name the actual interface, which is a better way to learn it than reading
release notes.

:class:`RecordingExecutor` is the same interface with nothing behind it. It is
what the tests drive and what ``--dry-run`` uses, and it can never write to a
disk because it has no code that could.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Mapping, Protocol, Sequence

from installer.backend.kickstart import KickstartError, redacted, render
from installer.backend.state import STAGES

__all__ = [
    "MEDIUM_KICKSTART_PATHS",
    "AnacondaAdapter",
    "AnacondaDBusExecutor",
    "ExecutorUnavailable",
    "RecordingExecutor",
    "read_medium_kickstart",
]

#: Where a bootc-generic-iso installer environment keeps the kickstart it was
#: built with. Ordered by how specific each location is; the first readable one
#: wins and the search is recorded so a failure can say where it looked.
MEDIUM_KICKSTART_PATHS = (
    # First and authoritative: Bunny's own medium kickstart, shipped in the
    # live filesystem beside the payload OCI layout it names. Run 13 proved
    # the /run/install paths below describe a medium anaconda mounted for
    # itself — a dmsquash-live boot mounts at /run/initramfs/live and this
    # medium carries no kickstart of its own at all.
    Path("/usr/share/bunny-os/medium.ks"),
    Path("/run/install/repo/osbuild.ks"),
    Path("/run/install/repo/ks.cfg"),
    Path("/run/install/repo/kickstart/osbuild.ks"),
    Path("/usr/share/anaconda/interactive-defaults.ks"),
    Path("/run/anaconda/ks.cfg"),
)

#: tmpfs. The rendered kickstart contains a LUKS passphrase in the clear because
#: kickstart has no indirection for one, so it must never touch a real disk.
_RUNTIME = Path("/run/bunny-setup")


class ExecutorUnavailable(RuntimeError):
    """Installation cannot proceed, and nothing has been written."""


def read_medium_kickstart(paths: Sequence[Path] = MEDIUM_KICKSTART_PATHS) -> tuple[list[str], Path]:
    """The medium's kickstart, and where it was found.

    Raises rather than returning an empty document. An empty base would render a
    kickstart with no payload directive, which `kickstart.render` refuses — but
    the message it gives would be about the payload rather than about the file
    that was never found, and the second is the one that helps.
    """
    for candidate in paths:
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace").splitlines(), candidate
        except OSError:
            continue
    raise ExecutorUnavailable(
        "the installation medium's kickstart was not found; looked in "
        + ", ".join(str(path) for path in paths)
    )


class Executor(Protocol):
    """What the adapter needs from whatever actually performs the install."""

    def preflight(self) -> None:
        """Raise :class:`ExecutorUnavailable` if this cannot install. No writes."""

    def install(self, kickstart: Path, *, on_stage: Callable[[str, str], None]) -> None:
        """Perform the installation, calling ``on_stage(stage, detail)`` as it goes."""


@dataclass
class RecordingExecutor:
    """An executor that records what it was asked to do and does nothing.

    Used by the tests and by ``--dry-run``. It walks the engine's real stage list
    so that everything downstream — the stage mapping, the Companion phase, the
    progress rows — is exercised against the same sequence a real install
    produces. It cannot write to a disk: there is no code in it that could.
    """

    available: bool = True
    fail_at: str | None = None
    kickstarts: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)

    def preflight(self) -> None:
        if not self.available:
            raise ExecutorUnavailable("the recording executor was configured as unavailable")

    def install(self, kickstart: Path, *, on_stage: Callable[[str, str], None]) -> None:
        self.kickstarts.append(kickstart.read_text(encoding="utf-8"))
        for stage in STAGES[1:]:
            if self.fail_at is not None and stage == self.fail_at:
                raise RuntimeError(f"deliberate failure at {stage}")
            self.stages.append(stage)
            on_stage(stage, f"{stage} (recorded, nothing was written)")


class AnacondaDBusExecutor:
    """Drive the installer through Anaconda's own DBus modules.

    Every method name this needs is listed in :attr:`REQUIRED_BOSS_METHODS` and
    checked by introspection in :meth:`preflight`, before anything happens. That
    is deliberate: this is the only code in the phase whose external contract
    could not be verified without an installer ISO, so it is written to discover
    that it is wrong at the one moment when discovering it is free.
    """

    #: The Boss methods the installation sequence uses.
    #:
    #: **Verified against anaconda-core 44.30-2.fc44**, not guessed: the three
    #: appear in `pyanaconda/modules/boss/boss_interface.py` with the signatures
    #: this adapter relies on —
    #:
    #:     ReadKickstartFile(path: Str) -> Structure   (a KickstartReport)
    #:     CollectRequirements()        -> List[Structure]
    #:     InstallWithTasks()           -> List[ObjPath]
    #:
    #: `preflight` still introspects and still refuses, because the package on
    #: the medium is what matters and it is not necessarily this one.
    REQUIRED_BOSS_METHODS = ("ReadKickstartFile", "CollectRequirements", "InstallWithTasks")

    #: Likewise verified: `pyanaconda/modules/common/task/task_interface.py`
    #: publishes Name, Progress, Steps and IsRunning as properties, and Start,
    #: Cancel and Finish as methods, with Started/Stopped/Failed/Succeeded
    #: signals. This adapter polls IsRunning rather than subscribing, because a
    #: missed signal on a bus it does not own would hang an installation.
    REQUIRED_TASK_MEMBERS = ("Start", "Finish", "IsRunning", "Name")

    BUS_ADDRESS_FILE = Path("/run/anaconda/bus.address")
    BOSS_SERVICE = "org.fedoraproject.Anaconda.Boss"
    BOSS_PATH = "/org/fedoraproject/Anaconda/Boss"

    def __init__(self, *, bus_address: str | None = None) -> None:
        self._bus_address = bus_address
        self._bus = None
        self._boss = None

    # -- discovery -------------------------------------------------------

    def _address(self) -> str:
        if self._bus_address:
            return self._bus_address
        try:
            return self.BUS_ADDRESS_FILE.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ExecutorUnavailable(
                f"Anaconda's private bus address is not readable at "
                f"{self.BUS_ADDRESS_FILE}; this is not an installer environment"
            ) from error

    def _connect(self):
        if self._boss is not None:
            return self._boss
        try:
            import gi  # type: ignore

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio  # type: ignore
        except (ImportError, ValueError) as error:
            raise ExecutorUnavailable("GIO is required to reach Anaconda's bus") from error

        try:
            self._bus = Gio.DBusConnection.new_for_address_sync(
                self._address(),
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None,
            )
            self._boss = Gio.DBusProxy.new_sync(
                self._bus, Gio.DBusProxyFlags.NONE, None,
                self.BOSS_SERVICE, self.BOSS_PATH, self.BOSS_SERVICE, None,
            )
        except Exception as error:                          # GLib.Error
            raise ExecutorUnavailable(
                f"could not reach {self.BOSS_SERVICE}: {error}") from error
        return self._boss

    # -- the gate --------------------------------------------------------

    def preflight(self) -> None:
        """Refuse now, with a reason, rather than part way through a disk.

        Introspects the Boss and compares its actual methods against
        :attr:`REQUIRED_BOSS_METHODS`. A missing method is reported by name, so a
        first run on a real ISO produces a message that says exactly what this
        installer expected and what Anaconda offers instead.
        """
        boss = self._connect()
        try:
            xml = boss.get_connection().call_sync(
                self.BOSS_SERVICE, self.BOSS_PATH,
                "org.freedesktop.DBus.Introspectable", "Introspect",
                None, None, 0, 10_000, None,
            ).unpack()[0]
        except Exception as error:
            raise ExecutorUnavailable(f"Anaconda's Boss could not be introspected: {error}") from error

        missing = [name for name in self.REQUIRED_BOSS_METHODS
                   if f'name="{name}"' not in xml]
        if missing:
            offered = sorted(set(
                fragment.split('"', 1)[0]
                for fragment in xml.split('<method name="')[1:]
            ))
            raise ExecutorUnavailable(
                "Anaconda's Boss does not offer the method(s) this installer "
                f"needs: {', '.join(missing)}. It offers: {', '.join(offered) or 'nothing'}. "
                "No disk was touched."
            )

    def install(self, kickstart: Path, *, on_stage: Callable[[str, str], None]) -> None:
        from gi.repository import GLib  # type: ignore

        boss = self._connect()
        on_stage("Validating storage", f"Handing {kickstart.name} to the installer")

        # `ReadKickstartFile` returns a **KickstartReport**, not nothing. An
        # earlier version discarded it, which meant a kickstart Anaconda could
        # not parse produced no error here and the install proceeded to
        # `InstallWithTasks` anyway. The structure is
        # `{error-messages: [...], warning-messages: [...]}`, each message
        # carrying module-name, file-name, line-number and message; a report is
        # valid exactly when the error list is empty.
        report = boss.call_sync(
            "ReadKickstartFile", GLib.Variant("(s)", (str(kickstart),)),
            0, 120_000, None).unpack()[0]
        errors = [self._message(item) for item in report.get("error-messages", [])]
        warnings = [self._message(item) for item in report.get("warning-messages", [])]
        if warnings:
            on_stage("Validating storage", "; ".join(warnings)[:200])
        if errors:
            raise ExecutorUnavailable(
                "Anaconda refused the installation plan: " + "; ".join(errors)
                + ". No disk was touched."
            )

        boss.call_sync("CollectRequirements", None, 0, 120_000, None)
        tasks = boss.call_sync("InstallWithTasks", None, 0, 120_000, None).unpack()[0]
        if not tasks:
            raise ExecutorUnavailable(
                "Anaconda returned no installation tasks; nothing was written")
        self._run_tasks(tasks, on_stage=on_stage)

    @staticmethod
    def _message(item: Mapping[str, Any]) -> str:
        """One KickstartMessage, flattened for a person to read."""
        def value(key: str) -> Any:
            found = item.get(key)
            return found.unpack() if hasattr(found, "unpack") else found

        text = str(value("message") or "").strip()
        line = value("line-number")
        return f"line {line}: {text}" if line else text

    def _run_tasks(self, task_paths: Sequence[str], *, on_stage: Callable[[str, str], None]) -> None:
        """Run each task to completion, reporting its own name as the stage.

        Anaconda's task names are the engine's truth about what is happening, so
        they are passed through rather than replaced. `backend.progress` maps
        them onto the seven phrases the person sees.
        """
        from gi.repository import Gio, GLib  # type: ignore

        for path in task_paths:
            proxy = Gio.DBusProxy.new_sync(
                self._bus, Gio.DBusProxyFlags.NONE, None,
                self.BOSS_SERVICE, path, "org.fedoraproject.Anaconda.Task", None)
            name = proxy.get_cached_property("Name")
            label = name.unpack() if name is not None else path.rsplit("/", 1)[-1]
            on_stage(str(label), f"Running {label}")
            proxy.call_sync("Start", None, 0, GLib.MAXINT32, None)
            loop = GLib.MainContext.default()
            last = ""
            while True:
                running = proxy.get_cached_property("IsRunning")
                if running is not None and not running.unpack():
                    break
                # `Progress` is (step, message). The message is Anaconda's own
                # sentence about what it is doing, which is the "real installer
                # state" §23 asks for — the step number is deliberately not
                # turned into a percentage.
                progress = proxy.get_cached_property("Progress")
                if progress is not None:
                    try:
                        _step, message = progress.unpack()
                        if message and message != last:
                            on_stage(str(label), str(message))
                            last = str(message)
                    except (TypeError, ValueError):
                        pass
                while loop.pending():
                    loop.iteration(False)
            # Finish re-raises whatever the task failed with, which is what
            # turns an installer error into this phase's failure screen.
            proxy.call_sync("Finish", None, 0, 60_000, None)


@dataclass
class AnacondaAdapter:
    """The object `InstallerService` calls, and the only one that can install.

    Its `start` signature is the seam the service already had:
    ``start(plan=..., confirmations=...)``. The service has, by then, matched the
    typed confirmation phrase against the disk with
    `storage.safety.assert_confirmed` and refused if it did not match — so this
    is reached only for a plan a person confirmed by naming the disk.
    """

    executor: Executor
    choices: Mapping[str, Any]
    password_hash: str
    passphrase: str | None = None
    medium_paths: Sequence[Path] = MEDIUM_KICKSTART_PATHS
    runtime_directory: Path = _RUNTIME
    on_stage: Callable[[str, str], None] | None = None
    #: Set once a kickstart has been rendered, for the audit log and the
    #: "installation details" disclosure. Always the redacted form.
    rendered: str | None = None
    medium_source: Path | None = None

    def configure_installation(self, *, choices: Mapping[str, Any], password_hash: str,
                               passphrase: str | None,
                               on_stage: Callable[[str, str], None] | None = None) -> None:
        """The per-installation half.

        The adapter is constructed empty when the backend starts, because a
        password cannot exist before a person has typed one. The service calls
        this once the validated plan and the descriptor-delivered secrets are
        both in hand, immediately before ``start``.
        """
        self.choices = choices
        self.password_hash = password_hash
        self.passphrase = passphrase
        if on_stage is not None:
            self.on_stage = on_stage

    def prepare(self, plan: Mapping[str, Any]) -> str:
        """Everything up to but not including a write. Safe to call twice."""
        base, source = read_medium_kickstart(self.medium_paths)
        self.medium_source = source
        try:
            document = render(
                plan=plan,
                choices=self.choices,
                base=base,
                password_hash=self.password_hash,
                passphrase=self.passphrase,
            )
        except KickstartError as error:
            raise ExecutorUnavailable(f"the installation plan could not be rendered: {error}") from error
        self.rendered = redacted(document)
        return document

    def start(self, *, plan: Mapping[str, Any], confirmations: Mapping[str, Any]) -> None:
        document = self.prepare(plan)
        # Refuse before writing anything, for any reason the executor has.
        self.executor.preflight()

        self.runtime_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(
            prefix="install-", suffix=".ks", dir=self.runtime_directory)
        path = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(document)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o600)
            self.executor.install(path, on_stage=self._stage)
        finally:
            # The passphrase is in this file in the clear. It goes away whether
            # the installation succeeded, failed, or raised on the way in.
            try:
                path.unlink()
            except OSError:
                pass

    def _stage(self, stage: str, detail: str) -> None:
        if self.on_stage is not None:
            self.on_stage(stage, detail)

    def diagnostics(self, destination: Path) -> Path:
        """Preserve what §25 requires after a failure, with no secret in it."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"medium kickstart: {self.medium_source}",
            "",
            "rendered kickstart (secrets redacted):",
            self.rendered or "(nothing was rendered)",
        ]
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        try:
            shutil.chown(destination, user=os.getuid())
        except (OSError, AttributeError, LookupError):
            pass
        destination.chmod(0o600)
        return destination
