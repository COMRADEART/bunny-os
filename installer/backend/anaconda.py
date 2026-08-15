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
import re
import shutil
import tempfile
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from installer.backend.kickstart import KickstartError, redacted, render
from installer.backend.state import STAGES

__all__ = [
    "MEDIUM_KICKSTART_PATHS",
    "AnacondaAdapter",
    "AnacondaDBusExecutor",
    "ExecutorUnavailable",
    "InstallationFailed",
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


class InstallationFailed(RuntimeError):
    """An anaconda task failed past the write boundary.

    Carries anaconda's own sentence about what went wrong, flattened from the
    DBus error, so the failure screen can show the engine's words. It is
    deliberately not `ExecutorUnavailable`: that class promises "no disk was
    touched", and this one exists precisely because the disk was. Run 18's
    version of this reached the screen as "the installer backend failed:
    Error" — the name of an exception class where the one useful fact
    should have been.
    """


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
    REQUIRED_BOSS_METHODS = ("StartModulesWithTask", "ReadKickstartFile",
                             "CollectRequirements", "InstallWithTasks")

    #: Likewise verified: `pyanaconda/modules/common/task/task_interface.py`
    #: publishes Name, Progress, Steps and IsRunning as properties, and Start,
    #: Cancel and Finish as methods, with Started/Stopped/Failed/Succeeded
    #: signals. This adapter polls IsRunning rather than subscribing, because a
    #: missed signal on a bus it does not own would hang an installation.
    REQUIRED_TASK_MEMBERS = ("Start", "Finish", "IsRunning", "Name")

    BUS_ADDRESS_FILE = Path("/run/anaconda/bus.address")
    BOSS_SERVICE = "org.fedoraproject.Anaconda.Boss"
    BOSS_PATH = "/org/fedoraproject/Anaconda/Boss"

    #: The Storage module, addressed directly. Run 17 proved why: the Boss's
    #: `InstallWithTasks` returns tasks that "complete" against whatever storage
    #: model the module holds, and a module that has never scanned a device and
    #: never had a partitioning applied holds nothing — the run reported
    #: completion over a 196 KB disk. Storage is choreographed here the same way
    #: anaconda's own `pyanaconda/ui/lib/storage.py` does it: scan, configure,
    #: validate, apply, and only then install. Tasks returned by this module
    #: live on this bus name, not the Boss's.
    STORAGE_SERVICE = "org.fedoraproject.Anaconda.Modules.Storage"
    STORAGE_PATH = "/org/fedoraproject/Anaconda/Modules/Storage"
    PARTITIONING_INTERFACE = "org.fedoraproject.Anaconda.Modules.Storage.Partitioning"

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

        # The modules first, and this line is run 15's lesson — the worst
        # failure of the whole journey, because it was a lying success. In
        # anaconda's own flow the main process calls StartModulesWithTask
        # before anything else; a bare DBus-activated Boss has no modules, and
        # a module-less Boss parses a kickstart without errors, returns
        # non-empty no-op tasks, and "completes" an installation that wrote
        # nothing while the screen said Bunny OS is ready. The disk was 196 KB.
        on_stage("Preparing", "Starting the installer's modules")
        module_task = boss.call_sync(
            "StartModulesWithTask", None, 0, 120_000, None).unpack()[0]
        self._run_tasks([module_task], on_stage=on_stage)
        # Polled, not read once: the boss records its observers through a
        # succeeded-signal in its own loop, which fires AFTER the task's
        # Finish returns to this side — measured at about a second. A single
        # read right after Finish sees an empty list on a boss that started
        # nine modules, and the guard below then refuses a working installer.
        deadline = time.time() + 30.0
        while True:
            modules = boss.call_sync("GetModules", None, 0, 120_000, None).unpack()[0]
            if modules:
                break
            if time.time() >= deadline:
                raise ExecutorUnavailable(
                    "Anaconda started no modules; a module-less installer parses "
                    "everything and writes nothing. No disk was touched.")
            time.sleep(0.5)
        on_stage("Preparing", f"{len(modules)} installer modules running")

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

        # The storage module now knows what the kickstart *wants*; it has not
        # yet looked at what the machine *has*, and nothing connects the two on
        # its own. Run 17 is the proof: without this choreography the install
        # tasks ran against an empty storage model, reported completion, and
        # left the disk at 196 KB. This is the sequence anaconda's own UI
        # performs in `pyanaconda/ui/lib/storage.py::apply_partitioning`: scan
        # the devices, let the kickstart-created partitioning schedule its
        # actions against the real model, validate the plan, apply it — every
        # step able to refuse while the disk is still untouched.
        def storage_call(method: str, parameters=None):
            return self._bus.call_sync(
                self.STORAGE_SERVICE, self.STORAGE_PATH, self.STORAGE_SERVICE,
                method, parameters, None, 0, 120_000, None)

        try:
            on_stage("Validating storage", "Scanning the machine's disks")
            scan_task = storage_call("ScanDevicesWithTask").unpack()[0]
            self._run_tasks([scan_task], on_stage=on_stage,
                            service=self.STORAGE_SERVICE)

            # Read fresh through Properties.Get rather than a proxy's cache:
            # the list was populated by the kickstart read, after any proxy
            # created at connect time took its snapshot.
            created = self._bus.call_sync(
                self.STORAGE_SERVICE, self.STORAGE_PATH,
                "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (self.STORAGE_SERVICE, "CreatedPartitioning")),
                None, 0, 120_000, None).unpack()[0]
            if not created:
                raise ExecutorUnavailable(
                    "the kickstart produced no partitioning; an installation "
                    "with no layout writes nothing. No disk was touched.")
            partitioning = created[-1]

            on_stage("Validating storage", "Planning the partition layout")
            configure_task = self._bus.call_sync(
                self.STORAGE_SERVICE, partitioning, self.PARTITIONING_INTERFACE,
                "ConfigureWithTask", None, None, 0, 120_000, None).unpack()[0]
            self._run_tasks([configure_task], on_stage=on_stage,
                            service=self.STORAGE_SERVICE)

            validate_task = self._bus.call_sync(
                self.STORAGE_SERVICE, partitioning, self.PARTITIONING_INTERFACE,
                "ValidateWithTask", None, None, 0, 120_000, None).unpack()[0]
            report_proxy = self._run_tasks([validate_task], on_stage=on_stage,
                                           service=self.STORAGE_SERVICE)
            verdict = report_proxy.call_sync(
                "GetResult", None, 0, 60_000, None).unpack()[0]
            layout_errors = [str(item) for item in verdict.get("error-messages", [])]
            layout_warnings = [str(item) for item in verdict.get("warning-messages", [])]
            if layout_warnings:
                on_stage("Validating storage", "; ".join(layout_warnings)[:200])
            if layout_errors:
                raise ExecutorUnavailable(
                    "the planned layout failed validation: "
                    + "; ".join(layout_errors) + ". No disk was touched.")

            storage_call("ApplyPartitioning", GLib.Variant("(o)", (partitioning,)))
            on_stage("Validating storage", "Partition plan applied")
        except ExecutorUnavailable:
            raise
        except Exception as error:                          # GLib.Error
            raise ExecutorUnavailable(
                "the storage layout could not be prepared: "
                f"{self._flatten_dbus_error(error)}. No disk was touched.") from error

        boss.call_sync("CollectRequirements", None, 0, 120_000, None)
        tasks = boss.call_sync("InstallWithTasks", None, 0, 120_000, None).unpack()[0]
        if not tasks:
            raise ExecutorUnavailable(
                "Anaconda returned no installation tasks; nothing was written")
        try:
            self._run_tasks(tasks, on_stage=on_stage)
        except Exception as error:                          # GLib.Error
            # Past the write boundary an anaconda task's own failure sentence
            # is the fact the failure screen exists to carry.
            raise InstallationFailed(self._flatten_dbus_error(error)) from error

        # Finish the way anaconda itself finishes: tear the target down, so
        # every late write reaches the disk and the filesystems unmount
        # cleanly. Run 25 completed without this and the installed system
        # was missing its user, its locale and its logs' contents: the
        # executor stopped at the last install task, the target stayed
        # mounted, the final /etc writes sat in the guest's page cache, and
        # powering the machine off threw them away — while the six-gigabyte
        # payload, written early and fsynced by ostree, survived and made
        # the disk look almost right. The payload module unmounts its binds
        # first, then storage unmounts and deactivates what it mounted —
        # anaconda's own order. A teardown failure fails the install: a
        # disk that cannot be unmounted is a disk whose contents cannot be
        # promised.
        on_stage("Finishing", "Unmounting the installed system")
        for service, path in (
            ("org.fedoraproject.Anaconda.Modules.Payloads",
             "/org/fedoraproject/Anaconda/Modules/Payloads"),
            (self.STORAGE_SERVICE, self.STORAGE_PATH),
        ):
            try:
                teardown = self._bus.call_sync(
                    service, path, service, "TeardownWithTasks",
                    None, None, 0, 120_000, None).unpack()[0]
                self._run_tasks(teardown, on_stage=on_stage, service=service)
            except Exception as error:                      # GLib.Error
                raise InstallationFailed(
                    "the installed system could not be unmounted cleanly: "
                    + self._flatten_dbus_error(error)) from error

    @staticmethod
    def _flatten_dbus_error(error: Exception) -> str:
        """The sentence inside a GLib.Error, for a person.

        str(GLib.Error) is "g-io-error-quark: GDBus.Error:org.fedoraproject.
        Anaconda.…SomeError: the actual sentence (36)". The person needs the
        sentence; the quark, the interface name and the code are noise on a
        failure screen.
        """
        text = str(error)
        marker = "GDBus.Error:"
        if marker in text:
            text = text.split(marker, 1)[1]
            if ": " in text:
                text = text.split(": ", 1)[1]
        return re.sub(r"\s*\(\d+\)$", "", text).strip()

    @staticmethod
    def _message(item: Mapping[str, Any]) -> str:
        """One KickstartMessage, flattened for a person to read."""
        def value(key: str) -> Any:
            found = item.get(key)
            return found.unpack() if hasattr(found, "unpack") else found

        text = str(value("message") or "").strip()
        line = value("line-number")
        return f"line {line}: {text}" if line else text

    def _run_tasks(self, task_paths: Sequence[str], *,
                   on_stage: Callable[[str, str], None],
                   service: str | None = None):
        """Run each task to completion, reporting its own name as the stage.

        Anaconda's task names are the engine's truth about what is happening, so
        they are passed through rather than replaced. `backend.progress` maps
        them onto the seven phrases the person sees.

        Tasks live on the bus name of the module that created them — the Boss's
        for install tasks, the Storage module's for scan/configure/validate —
        so the owner is a parameter. Returns the last task's proxy, because a
        validation task's verdict is fetched with `GetResult` after `Finish`.

        Completion is witnessed through the task's **signals**, not a proxy's
        property cache. The first version polled
        ``proxy.get_cached_property("IsRunning")`` — but a Gio proxy's cache
        updates only on `PropertiesChanged`, and anaconda's task interface never
        emits it; tasks speak through `Started`/`Stopped`/`ProgressChanged`
        signals instead. The cache therefore held its creation-time snapshot —
        `False`, taken before `Start` — so the loop broke on its first
        iteration and every task was fired and forgotten. That is the second
        half of run 17's lying success (the module-start "worked" only because
        the separate `GetModules` poll covered for it), and why a fifteen-stage
        install produced exactly one progress message.
        """
        from gi.repository import Gio, GLib  # type: ignore

        owner = service or self.BOSS_SERVICE
        proxy = None
        for path in task_paths:
            proxy = Gio.DBusProxy.new_sync(
                self._bus, Gio.DBusProxyFlags.NONE, None,
                owner, path, "org.fedoraproject.Anaconda.Task", None)
            name = proxy.get_cached_property("Name")
            label = name.unpack() if name is not None else path.rsplit("/", 1)[-1]
            on_stage(str(label), f"Running {label}")

            state = {"stopped": False, "last": ""}

            def on_signal(_connection, _sender, _path, _interface, member,
                          parameters, *, _state=state, _label=label):
                if member == "Stopped":
                    _state["stopped"] = True
                elif member == "ProgressChanged":
                    # (step, message). The message is Anaconda's own sentence
                    # about what it is doing — the "real installer state" §23
                    # asks for. The step number is deliberately not turned
                    # into a percentage.
                    try:
                        _step, message = parameters.unpack()
                    except (TypeError, ValueError):
                        return
                    if message and str(message) != _state["last"]:
                        on_stage(str(_label), str(message))
                        _state["last"] = str(message)

            # Subscribed before Start: AddMatch and the Start call travel the
            # same connection in order, so a Stopped emitted in response to
            # Start cannot outrun the subscription.
            subscription = self._bus.signal_subscribe(
                None, "org.fedoraproject.Anaconda.Task", None, path, None,
                Gio.DBusSignalFlags.NONE, on_signal)
            try:
                proxy.call_sync("Start", None, 0, GLib.MAXINT32, None)
                context = GLib.MainContext.default()
                started = time.time()
                checked = started
                while not state["stopped"]:
                    if not context.iteration(False):
                        time.sleep(0.1)
                    # Belt against a missed signal: a live IsRunning read (a
                    # Properties.Get round trip, never the cache). Only after a
                    # grace period, because is_running is briefly False between
                    # Start returning and the task's thread existing — the
                    # exact stale-False this rewrite removes.
                    now = time.time()
                    if now - started > 5.0 and now - checked > 2.0:
                        checked = now
                        running = self._bus.call_sync(
                            owner, path, "org.freedesktop.DBus.Properties",
                            "Get",
                            GLib.Variant("(ss)", ("org.fedoraproject.Anaconda.Task",
                                                  "IsRunning")),
                            None, 0, 30_000, None).unpack()[0]
                        if not running:
                            break
            finally:
                self._bus.signal_unsubscribe(subscription)
            # Finish re-raises whatever the task failed with, which is what
            # turns an installer error into this phase's failure screen.
            proxy.call_sync("Finish", None, 0, 60_000, None)
        return proxy


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
