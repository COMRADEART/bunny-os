#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run one TPM boot experiment against the frozen qualified disk, and prove
what actually happened when the machine "reset".

Design constraints, all of them lessons this repository already paid for:

* The qualified QCOW2 is never booted directly. Every run recomputes its
  digest, refuses a mismatch, and boots a copy-on-write overlay.
* "Reset" is a classification derived from QMP events and traces, never from
  a screenshot. A screen showing the firmware logo proves nothing; the QMP
  SHUTDOWN/RESET event stream, the QEMU debug log and the serial transcript
  together decide between a firmware-requested reset, a bootloader reboot
  command, a triple fault, a watchdog, a host kill and a harness timeout.
  What cannot be decided stays UNKNOWN, and UNKNOWN blocks.
* Every writable input is per-run: the disk overlay, the OVMF variable
  store, the TPM state directory. Reuse is an explicit, recorded choice —
  the variable being tested — never an accident of a shared directory.
* Diagnostic variation (TCG, another CPU model, another machine type, an
  alternative disk) is declared in the record as ``diagnostic: true`` and
  can never satisfy a supported-path requirement downstream.
* High-volume traces stay out of Git: when the QEMU debug log exceeds the
  retention bound it is moved to the trace root, and the evidence keeps its
  digest, an excerpt, and the retention location.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))

from tpm_context import (  # noqa: E402
    ContextError,
    experiment_id,
    resolve_context,
    sha256_file,
)

DEBUG_LOG_RETENTION_BYTES = 2 * 1024 * 1024

# Serial markers that place a boot on the boot-chain timeline. The stage a
# boot reached is judged from which of these appeared, in log order.
STAGE_MARKERS = [
    ("firmware-bds", r"BdsDxe: loading Boot"),
    ("boot-option-started", r"BdsDxe: starting Boot"),
    ("restoration-dialog", r"Boot Option Restoration"),
    ("reset-announced", r"Reset System"),
    ("grub-menu", r"GRUB version \d"),
    ("kernel-loaded", r"(Loading Linux|Linux version \d|Booting a command list)"),
    ("initramfs", r"(dracut-initqueue|Reached target .*Initrd)"),
    ("multi-user", r"Reached target .*Multi-User System"),
    ("graphical", r"Reached target .*Graphical Interface"),
    ("health-check", r"Finished .*Bunny OS boot health check"),
]

CLASSIFICATIONS = (
    "FIRMWARE_REQUESTED_RESET",
    "QEMU_DEVICE_RESET",
    "GUEST_TRIPLE_FAULT",
    "WATCHDOG_RESET",
    "BOOTLOADER_REBOOT_COMMAND",
    "HOST_TERMINATED",
    "HARNESS_TIMEOUT",
    "UNKNOWN",
)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


class QmpClient:
    """QMP with a continuous event reader. Every event is timestamped with
    host wall-clock time and appended to an events file as it arrives; the
    command channel shares the socket under a lock."""

    def __init__(self, path: Path, events_path: Path) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(str(path))
        self.buffer = b""
        self.events: list[dict] = []
        self.events_path = events_path
        self.lock = threading.Lock()
        self.responses: list[dict] = []
        self.closed = False
        #: Set when the reader thread stops before the run does. From that
        #: moment the event list is frozen, so a later reset is invisible —
        #: and a run that cannot see a reset must not be scored as one that
        #: saw none.
        self.reader_died = False
        greeting = self._read_message()
        self._record({"event": "_QMP_GREETING", "qmp": greeting.get("QMP", {}),
                      "hostTime": now()})
        self._send({"execute": "qmp_capabilities"})
        self._await_response()
        self.reader = threading.Thread(target=self._pump, daemon=True)
        self.reader.start()

    def _read_message(self) -> dict:
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("QMP socket closed")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return json.loads(line)

    def _record(self, event: dict) -> None:
        self.events.append(event)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def _send(self, payload: dict) -> None:
        self.sock.sendall(json.dumps(payload).encode() + b"\n")

    def _await_response(self, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self._read_message()
            except socket.timeout:
                continue
            if "return" in message or "error" in message:
                return message
            message["hostTime"] = now()
            self._record(message)
        raise TimeoutError("no QMP response within timeout")

    def _pump(self) -> None:
        while not self.closed:
            try:
                message = self._read_message()
            except (socket.timeout,):
                continue
            except (ConnectionError, OSError, json.JSONDecodeError):
                if not self.closed:
                    self.reader_died = True
                return
            with self.lock:
                if "return" in message or "error" in message:
                    self.responses.append(message)
                else:
                    message["hostTime"] = now()
                    self._record(message)

    def execute(self, command: str, arguments: dict | None = None,
                timeout: float = 15) -> dict:
        payload: dict = {"execute": command}
        if arguments:
            payload["arguments"] = arguments
        with self.lock:
            self.responses.clear()
        self._send(payload)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.responses:
                    return self.responses.pop(0)
            time.sleep(0.05)
        raise TimeoutError(f"QMP {command} got no response")

    def event_names(self) -> list[str]:
        with self.lock:
            return [e.get("event", "") for e in self.events]

    def find_events(self, name: str) -> list[dict]:
        with self.lock:
            return [e for e in self.events if e.get("event") == name]

    def close(self) -> None:
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


def manifest(directory: Path) -> list[dict]:
    entries = []
    if directory and directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                entries.append({"path": str(path.relative_to(directory)),
                                "sha256": sha256_file(path),
                                "sizeBytes": path.stat().st_size})
    return entries


def read_serial(serial_log: Path) -> str:
    if serial_log.exists():
        return serial_log.read_text(encoding="utf-8", errors="replace")
    return ""


def stage_reached(text: str) -> list[str]:
    return [name for name, regex in STAGE_MARKERS if re.search(regex, text)]


def split_boot_segments(serial_text: str) -> list[str]:
    """Split a multi-boot transcript at each firmware restart.

    In continuation mode one serial log holds several boots. Every boot
    begins with OVMF's BDS announcing a boot option, so that line is the
    seam. Classification judges one segment, never the whole log: boot #1's
    restoration dialog must not explain boot #3's reset.
    """
    marks = [m.start() for m in re.finditer(r"BdsDxe: loading Boot", serial_text)]
    if len(marks) <= 1:
        return [serial_text]
    bounds = marks + [len(serial_text)]
    return [serial_text[bounds[i]:bounds[i + 1]] for i in range(len(marks))]


def classify(events: list[dict], serial_text: str, process_alive: bool,
             timed_out: bool, qemu_stderr: str, *, classify_index: int = 0,
             boot_segments: list[str] | None = None,
             debug_text: str = "") -> tuple[str, list[str]]:
    """Mechanical classification of what ended (or froze) the boot.

    Returns (classification, basis). The basis lists the exact observations
    the classification rests on, so a reader can re-derive it. Anything the
    events cannot decide stays UNKNOWN — a blocking answer, deliberately.

    ``classify_index`` names which guest reset is the anomalous one (resets
    within a run's commanded budget are not anomalies). ``boot_segments``
    supplies the per-boot transcript slices so a later reset is judged on
    its own boot's output. ``debug_text`` is the QEMU debug log, which is
    where a triple fault is visible at all.
    """
    basis: list[str] = []
    names = [e.get("event") for e in events]

    watchdogs = [e for e in events if e.get("event") == "WATCHDOG"]
    if watchdogs:
        basis.append(f"QMP WATCHDOG event: {json.dumps(watchdogs[0].get('data', {}))}")
        return "WATCHDOG_RESET", basis

    panics = [e for e in events if e.get("event") == "GUEST_PANICKED"]
    if panics:
        basis.append(f"QMP GUEST_PANICKED: {json.dumps(panics[0].get('data', {}))}")
        return "UNKNOWN", basis + ["guest panic is not a reset; classified UNKNOWN "
                                   "pending the panic payload"]

    resets = [e for e in events if e.get("event") == "RESET"]
    shutdowns = [e for e in events if e.get("event") == "SHUTDOWN"]
    # Only reason=guest-reset is a guest reset. A guest that powered itself
    # off also reports guest: true, with reason guest-shutdown, and treating
    # that as a reset would classify an orderly poweroff as a reboot command.
    guest_resets = [e for e in resets + shutdowns
                    if e.get("data", {}).get("reason") == "guest-reset"]
    guest_shutdowns = [e for e in shutdowns
                       if e.get("data", {}).get("reason") == "guest-shutdown"
                       or (e.get("data", {}).get("guest")
                           and e.get("data", {}).get("reason") != "guest-reset")]
    host_resets = [e for e in resets
                   if str(e.get("data", {}).get("reason", "")).startswith("host-qmp")]

    if host_resets and not guest_resets:
        basis.append(f"RESET with host reason: {json.dumps(host_resets[0]['data'])}")
        return "QEMU_DEVICE_RESET", basis

    if guest_resets:
        # Classify the event that made this run anomalous, not the first one:
        # in continuation mode the first reset is often the expected,
        # budgeted one and the anomaly is a later reset.
        index = min(classify_index, len(guest_resets) - 1)
        event = guest_resets[index]
        basis.append(f"QMP {event['event']} at {event.get('hostTime')} "
                     f"(guest reset #{index + 1} of {len(guest_resets)}): "
                     f"{json.dumps(event.get('data', {}))}")

        # Judge from the transcript segment that belongs to THIS reset — the
        # text between the preceding guest reset and this one. In continuation
        # mode the whole log spans several boots, and boot #1's restoration
        # dialog would otherwise justify calling a later, unrelated reset a
        # bootloader reboot.
        segment = serial_text
        if boot_segments and index < len(boot_segments):
            segment = boot_segments[index]
            basis.append(f"judged on the transcript segment for boot "
                         f"#{index + 1} ({len(segment)} bytes), not the whole log")

        started = re.search(r"BdsDxe: starting Boot", segment)
        announced = re.search(r"Reset System", segment)
        dialog = re.search(r"Boot Option Restoration", segment)
        fault = re.search(r"(Triple fault|triple fault)", debug_text or "")
        if fault:
            basis.append(f"QEMU debug log records a triple fault: "
                         f"{fault.group(0)!r}")
            return "GUEST_TRIPLE_FAULT", basis
        if announced and started:
            basis.append("this segment shows a boot option was started and the "
                         "resetting component printed its intent "
                         "('Reset System'" + (", 'Boot Option Restoration' dialog"
                                              if dialog else "") + ") before the event")
            basis.append("classification places the reset in the loaded boot chain, "
                         "not the firmware core; the issuing binary is identified by "
                         "the executable-isolation evidence, not by this event")
            return "BOOTLOADER_REBOOT_COMMAND", basis
        if not started:
            basis.append("this segment shows no boot option was ever started; "
                         "the reset was requested before any handoff")
            return "FIRMWARE_REQUESTED_RESET", basis
        basis.append("a boot option was started but no component printed a reset "
                     "intent; a deliberate reboot and a fault are indistinguishable "
                     "from these events alone")
        return "UNKNOWN", basis

    if timed_out and process_alive:
        basis.append("timeout expired with QEMU alive and no reset/shutdown event")
        return "HARNESS_TIMEOUT", basis
    if guest_shutdowns:
        basis.append(f"guest-initiated shutdown, not a reset: "
                     f"{json.dumps(guest_shutdowns[0].get('data', {}))}")
        return "UNKNOWN", basis
    if not process_alive:
        basis.append(f"QEMU process exited without a guest reset event; stderr: "
                     f"{qemu_stderr[:300]!r}")
        return "HOST_TERMINATED", basis
    return "UNKNOWN", basis + ["no terminal event observed"]


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_tpm_experiment")
    parser.add_argument("--name", required=True, help="experiment slug, e.g. crb-fresh-cold")
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--disk-source", type=Path,
                        default=Path("/var/tmp/bunny-installables-g/bunny-os-b9c317d35b85.qcow2"))
    parser.add_argument("--no-disk", action="store_true",
                        help="firmware-only control: no disk attached")
    parser.add_argument("--alt-disk", type=Path,
                        help="diagnostic alternative disk (known-good comparator); "
                             "recorded as diagnostic evidence, never Bunny qualification")
    parser.add_argument("--tpm", choices=("none", "crb", "tis"), default="none")
    parser.add_argument("--tpm-state", default="fresh",
                        help="'fresh' or 'reuse:<dir>' — reuse copies the named state "
                             "directory so the source stays immutable")
    parser.add_argument("--vars", default="fresh",
                        help="'fresh' or 'reuse:<file>' — reuse copies the named OVMF "
                             "variable store")
    parser.add_argument("--accel", choices=("kvm", "tcg"), default="kvm")
    parser.add_argument("--cpu", default=None,
                        help="defaults to the pinned CPU mode (or 'max' under TCG)")
    parser.add_argument("--machine", default=None, help="defaults to the pinned machine type")
    parser.add_argument("--smm", action="store_true", help="add smm=on to the machine")
    parser.add_argument("--smp", type=int, default=4)
    parser.add_argument("--memory", type=int, default=8192)
    parser.add_argument("--on-reset", choices=("stop", "continue"), default="stop",
                        help="stop: freeze at the first reset (-no-reboot -no-shutdown) "
                             "and capture post-state; continue: let the guest reboot and "
                             "observe what follows")
    parser.add_argument("--max-resets", type=int, default=3,
                        help="continue mode: quit and record a reset loop beyond this")
    parser.add_argument("--expected-resets", type=int, default=0,
                        help="resets that are part of the cell's expectation; more is FAIL")
    parser.add_argument("--reboot-after-target", action="store_true",
                        help="after reaching the boot target, request an orderly guest "
                             "reboot (ctrl-alt-del) and require a second boot to target")
    parser.add_argument("--qemu-reset-after-target", action="store_true",
                        help="after reaching the boot target, issue QMP system_reset and "
                             "require a second boot to target")
    parser.add_argument("--require-target", action="store_true",
                        help="the run only passes if the boot target is reached")
    parser.add_argument("--expect", choices=("target", "stable", "reset"),
                        default="target",
                        help="the cell's expectation: 'target' — boot completes within "
                             "the allowed reset budget; 'stable' — nothing terminal "
                             "happens for the whole window (firmware-only control); "
                             "'reset' — at least one guest reset is observed and "
                             "classified (reproduction cells)")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--trace-int", action="store_true",
                        help="add interrupt/exception tracing to the QEMU debug log "
                             "(high volume; retained outside Git)")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--operator", default=os.environ.get("BUNNY_OPERATOR", ""))
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/tpm/evidence")
    parser.add_argument("--trace-root", type=Path, default=Path("/root/tpm-traces"))
    parser.add_argument("--note", action="append", default=[],
                        help="limitation or context note recorded verbatim")
    args = parser.parse_args()

    if not args.operator:
        print("BLOCKED: --operator (or BUNNY_OPERATOR) is required.", file=sys.stderr)
        return 2

    try:
        context = resolve_context(ROOT)
    except ContextError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    machine = args.machine or context.machineType
    cpu = args.cpu or (context.cpuMode if args.accel == "kvm" else "max")
    diagnostic = bool(
        args.alt_disk
        or args.accel != "kvm"
        or machine != context.machineType
        or cpu != context.cpuMode
    )

    run_id = experiment_id(args.name, date=datetime.date.today().strftime("%Y%m%d"),
                           sequence=args.sequence)
    evidence_dir = args.evidence_root / run_id
    if evidence_dir.exists():
        print(f"BLOCKED: {evidence_dir} already exists; two runs may not share an "
              "evidence id. Pass a different --sequence.", file=sys.stderr)
        return 2
    evidence_dir.mkdir(parents=True)
    work = evidence_dir / "work"
    work.mkdir()
    limitations: list[str] = list(args.note)
    started = now()

    # ------------------------------------------------------------------ disk
    boot_disk: Path | None = None
    alt_disk_digest = None
    if args.no_disk:
        pass
    elif args.alt_disk:
        alt_disk_digest = sha256_file(args.alt_disk)
        overlay = work / "disk-overlay.qcow2"
        subprocess.run(["qemu-img", "create", "-f", "qcow2",
                        "-b", str(args.alt_disk.resolve()), "-F", "qcow2", str(overlay)],
                       check=True, capture_output=True)
        boot_disk = overlay
        limitations.append(
            "diagnostic alternative disk; this record is not Bunny qualification evidence")
    else:
        actual = sha256_file(args.disk_source)
        if actual != context.installationArtifactDigest:
            print(f"BLOCKED: {args.disk_source} digests to {actual[:12]} but the context "
                  f"pins {context.installationArtifactDigest[:12]}. The frozen source "
                  "changed; nothing may be measured against it.", file=sys.stderr)
            return 2
        overlay = work / "disk-overlay.qcow2"
        subprocess.run(["qemu-img", "create", "-f", "qcow2",
                        "-b", str(args.disk_source.resolve()), "-F", "qcow2", str(overlay)],
                       check=True, capture_output=True)
        boot_disk = overlay

    # -------------------------------------------------------------- firmware
    vars_copy = work / "OVMF_VARS.qcow2"
    if args.vars == "fresh":
        shutil.copy(context.ovmfVarsTemplatePath, vars_copy)
        vars_state = "fresh"
        vars_source_digest = context.ovmfVarsTemplateDigest
    elif args.vars.startswith("reuse:"):
        source = Path(args.vars.split(":", 1)[1])
        vars_source_digest = sha256_file(source)
        shutil.copy(source, vars_copy)
        vars_state = "reused"
    else:
        print(f"BLOCKED: --vars must be 'fresh' or 'reuse:<file>', got {args.vars!r}",
              file=sys.stderr)
        return 2

    # ------------------------------------------------------------------- tpm
    tpm_state_dir: Path | None = None
    tpm_state = "none"
    tpm_state_source_manifest: list[dict] = []
    swtpm_process = None
    if args.tpm != "none":
        tpm_state_dir = work / "tpm-state"
        if args.tpm_state == "fresh":
            tpm_state_dir.mkdir()
            tpm_state = "fresh"
        elif args.tpm_state.startswith("reuse:"):
            source_dir = Path(args.tpm_state.split(":", 1)[1])
            tpm_state_source_manifest = manifest(source_dir)
            shutil.copytree(source_dir, tpm_state_dir)
            tpm_state = "reused"
        else:
            print(f"BLOCKED: --tpm-state must be 'fresh' or 'reuse:<dir>', got "
                  f"{args.tpm_state!r}", file=sys.stderr)
            return 2

    socket_dir = Path(tempfile.mkdtemp(prefix="tpmq-", dir="/tmp"))
    serial_socket = socket_dir / "ser.sock"
    qmp_socket = socket_dir / "qmp.sock"
    tpm_sock = socket_dir / "tpm.sock"
    serial_log = evidence_dir / "serial.log"
    events_path = evidence_dir / "qmp-events.jsonl"
    debug_log = evidence_dir / "qemu-debug.log"

    def abandon(message: str) -> int:
        """Leave nothing running and nothing lying around. Every early exit
        after swtpm starts goes through here — a returned-from run that left
        a TPM emulator alive would contaminate the next experiment's state,
        which is the one thing this harness exists to keep separate."""
        print(f"BLOCKED: {message}", file=sys.stderr)
        if swtpm_process is not None and swtpm_process.poll() is None:
            swtpm_process.terminate()
            try:
                swtpm_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                swtpm_process.kill()
        shutil.rmtree(socket_dir, ignore_errors=True)
        return 2

    if args.tpm != "none":
        swtpm_stdout = (evidence_dir / "swtpm-stdout.log").open("wb")
        swtpm_stderr = (evidence_dir / "swtpm-stderr.log").open("wb")
        swtpm_log = evidence_dir / "swtpm.log"
        swtpm_process = subprocess.Popen(
            ["swtpm", "socket", "--tpmstate", f"dir={tpm_state_dir}", "--tpm2",
             "--ctrl", f"type=unixio,path={tpm_sock}",
             "--log", f"file={swtpm_log},level=5"],
            stdout=swtpm_stdout, stderr=swtpm_stderr)
        ready = time.monotonic() + 15
        while not tpm_sock.exists() and time.monotonic() < ready:
            if swtpm_process.poll() is not None:
                return abandon("swtpm exited before its socket appeared")
            time.sleep(0.2)
        if not tpm_sock.exists():
            return abandon("swtpm did not create its control socket in 15s")

    # ------------------------------------------------------------------ qemu
    machine_arg = f"{machine},accel={args.accel}" + (",smm=on" if args.smm else "")
    debug_flags = "cpu_reset,guest_errors" + (",int" if args.trace_int else "")
    qemu = [
        "qemu-system-x86_64",
        "-machine", machine_arg,
        "-cpu", cpu,
        "-smp", str(args.smp),
        "-m", str(args.memory),
        "-drive", f"if=pflash,format=qcow2,readonly=on,file={context.ovmfCodePath}",
        "-drive", f"if=pflash,format=qcow2,file={vars_copy}",
        "-chardev",
        f"socket,id=ser0,path={serial_socket},server=on,wait=off,logfile={serial_log}",
        "-serial", "chardev:ser0",
        "-qmp", f"unix:{qmp_socket},server,nowait",
        "-display", "none",
        "-vga", "virtio",
        "-D", str(debug_log),
        "-d", debug_flags,
    ]
    if boot_disk is not None:
        qemu += ["-drive", f"file={boot_disk},format=qcow2,if=virtio"]
    if args.on_reset == "stop":
        qemu += ["-no-reboot", "-no-shutdown"]
    if args.no_network:
        qemu += ["-nic", "none"]
    else:
        qemu += ["-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0"]
    if args.tpm != "none":
        device = {"crb": "tpm-crb", "tis": "tpm-tis"}[args.tpm]
        qemu += ["-chardev", f"socket,id=chrtpm,path={tpm_sock}",
                 "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                 "-device", f"{device},tpmdev=tpm0"]

    # Everything from here to the cleanup block can fail — a missing
    # emulator binary, an unwritable evidence directory — and swtpm is
    # already running. Any exception in this window goes through abandon()
    # so no TPM emulator outlives the run that started it.
    try:
        (evidence_dir / "qemu-command.json").write_text(json.dumps({
            "argv": qemu, "startedAt": started, "experiment": vars(args) | {
                "disk_source": str(args.disk_source),
                "alt_disk": str(args.alt_disk or ""),
                "evidence_root": str(args.evidence_root),
                "trace_root": str(args.trace_root)},
        }, indent=2, default=str) + "\n", encoding="utf-8")
        process = subprocess.Popen(qemu, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
        screenshots = evidence_dir / "screenshots"
        screenshots.mkdir()
    except OSError as exc:
        return abandon(f"could not start the run: {exc}")
    qmp: QmpClient | None = None

    def screendump(label: str) -> None:
        if qmp is None:
            return
        try:
            qmp.execute("screendump", {"filename": str(screenshots / f"{label}.ppm")})
        except (TimeoutError, OSError, ConnectionError):
            limitations.append(f"screendump {label} failed")

    timed_out = False
    phase_events: list[dict] = []
    try:
        deadline = time.monotonic() + 30
        while not qmp_socket.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
                return abandon(f"QEMU exited immediately: {stderr[:500]}")
            time.sleep(0.2)
        qmp = QmpClient(qmp_socket, events_path)

        # ------------------------------------------------------- wait loop
        seen_stages: set[str] = set()
        reset_count = 0
        second_boot_offset: int | None = None
        second_target = False
        reboot_requested = False
        reboot_attempts = 0
        last_reboot_attempt = 0.0
        deadline = time.monotonic() + args.timeout

        def send_ctrl_alt_del() -> None:
            # ctrl-alt-del reaches PID 1 only from a text VT in translated
            # keyboard mode. A Wayland compositor holds its VT in raw mode
            # and may or may not yield to ctrl-alt-f3 depending on session
            # state — measured: the identical sequence rebooted one boot and
            # was swallowed by the next. So the request is attempted, watched
            # for effect, and retried; the caller counts attempts.
            qmp.execute("send-key", {"keys": [
                {"type": "qcode", "data": "ctrl"},
                {"type": "qcode", "data": "alt"},
                {"type": "qcode", "data": "f3"}]})
            time.sleep(4)
            qmp.execute("send-key", {"keys": [
                {"type": "qcode", "data": "ctrl"},
                {"type": "qcode", "data": "alt"},
                {"type": "qcode", "data": "delete"}]})
        while time.monotonic() < deadline:
            text = read_serial(serial_log)
            for stage in stage_reached(text):
                if stage not in seen_stages:
                    seen_stages.add(stage)
                    screendump(f"stage-{stage}")
            resets_now = len([e for e in qmp.find_events("RESET")
                              if e.get("data", {}).get("reason") == "guest-reset"])
            shutdown_events = qmp.find_events("SHUTDOWN")
            if args.on_reset == "stop" and (resets_now or shutdown_events):
                time.sleep(1)
                screendump("post-event")
                try:
                    status = qmp.execute("query-status")
                    phase_events.append({"queryStatus": status.get("return", {}),
                                         "hostTime": now()})
                except (TimeoutError, OSError, ConnectionError):
                    pass
                break
            if resets_now > reset_count:
                reset_count = resets_now
                screendump(f"post-reset-{reset_count}")
                if reboot_requested and second_boot_offset is None:
                    second_boot_offset = len(text)
                if reset_count > args.max_resets:
                    limitations.append(
                        f"reset loop: {reset_count} guest resets exceeded --max-resets; "
                        "run stopped")
                    break
            if shutdown_events and args.on_reset == "continue":
                break
            target_hit = ("graphical" in seen_stages or "multi-user" in seen_stages)
            if target_hit and (args.reboot_after_target or args.qemu_reset_after_target) \
                    and not reboot_requested:
                # Let the first boot settle before disturbing it, so the
                # health check has appeared in the log for phase judgement.
                if "health-check" in seen_stages:
                    reboot_requested = True
                    screendump("pre-reboot")
                    second_boot_offset = len(text)
                    if args.reboot_after_target:
                        send_ctrl_alt_del()
                        reboot_attempts = 1
                        last_reboot_attempt = time.monotonic()
                    else:
                        qmp.execute("system_reset")
            elif target_hit and not (args.reboot_after_target
                                     or args.qemu_reset_after_target):
                if "health-check" in seen_stages:
                    break
            if reboot_requested and args.reboot_after_target and reset_count == 0 \
                    and not [e for e in qmp.find_events("RESET")
                             if e.get("data", {}).get("reason") == "guest-reset"] \
                    and time.monotonic() - last_reboot_attempt > 30 \
                    and reboot_attempts < 6:
                send_ctrl_alt_del()
                reboot_attempts += 1
                last_reboot_attempt = time.monotonic()
            if second_boot_offset is not None:
                tail = text[second_boot_offset:]
                if re.search(r"Reached target .*(Multi-User System|Graphical Interface)",
                             tail):
                    second_target = True
                    screendump("second-boot-target")
                    break
            if process.poll() is not None:
                break
            time.sleep(3)
        else:
            timed_out = True
        screendump("final")
    finally:
        completed = now()
        process_alive = process.poll() is None
        qemu_stderr = ""
        try:
            if qmp is not None:
                try:
                    qmp.execute("quit", timeout=5)
                except (TimeoutError, OSError, ConnectionError):
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    limitations.append("QEMU required SIGKILL")
            if process.stderr:
                qemu_stderr = process.stderr.read().decode(errors="replace")
                if qemu_stderr:
                    (evidence_dir / "qemu-stderr.log").write_text(
                        qemu_stderr, encoding="utf-8")
        finally:
            if qmp is not None:
                qmp.close()
            if swtpm_process is not None:
                swtpm_process.terminate()
                try:
                    swtpm_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    swtpm_process.kill()
            shutil.rmtree(socket_dir, ignore_errors=True)

    # --------------------------------------------------------- post capture
    if reboot_attempts > 1:
        limitations.append(
            f"guest reboot needed {reboot_attempts} ctrl-alt-del attempts; the "
            "graphical session swallows the sequence until the VT yields")

    dmesg = subprocess.run(["dmesg"], capture_output=True, text=True)
    if dmesg.returncode == 0:
        tail = "\n".join(dmesg.stdout.splitlines()[-120:])
        (evidence_dir / "host-dmesg-tail.log").write_text(tail + "\n", encoding="utf-8")

    tpm_state_after = manifest(tpm_state_dir) if tpm_state_dir else []
    vars_after_digest = sha256_file(vars_copy) if vars_copy.exists() else None
    reader_died = qmp.reader_died if qmp is not None else False

    if debug_log.exists() and debug_log.stat().st_size > DEBUG_LOG_RETENTION_BYTES:
        args.trace_root.mkdir(parents=True, exist_ok=True)
        retained = args.trace_root / f"{run_id}-qemu-debug.log"
        digest = sha256_file(debug_log)
        lines = debug_log.read_text(encoding="utf-8", errors="replace").splitlines()
        excerpt = lines[:200] + ["... [truncated; full log retained outside git] ..."] \
            + lines[-400:]
        shutil.move(str(debug_log), str(retained))
        (evidence_dir / "qemu-debug-excerpt.log").write_text(
            "\n".join(excerpt) + "\n", encoding="utf-8")
        (evidence_dir / "qemu-debug-retention.json").write_text(json.dumps({
            "sha256": digest, "retainedAt": str(retained),
            "sizeBytes": retained.stat().st_size,
            "lifecycle": "raw trace retained outside git on the builder",
        }, indent=2) + "\n", encoding="utf-8")

    serial_text = read_serial(serial_log)
    stages = stage_reached(serial_text)
    # Failed units are recorded separately from boot success: an intermittent
    # gdm or avahi failure is a different fact than a TPM reset, and folding
    # them together is one of the exact confusions the adversarial tests
    # refuse. Names only — the classification across boots happens in
    # dispose_failed_units.py, never inside a single run.
    #
    # Scope: this is the serial console's view, not the journal's. A unit
    # that failed quietly does not appear here, so an empty list means "the
    # console reported none", not "none failed". The offline journal
    # collector remains the authority on the unit landscape.
    failed_units = sorted({m.group(1) for m in re.finditer(
        r"\[FAILED\][^\n]*?Failed to start ([^\n\r.]+)", serial_text)}
        | {m.group(1) for m in re.finditer(
            r"([-\w\\.@]+\.(?:service|socket|mount|target)): Failed with result",
            serial_text)})
    events = qmp.events if qmp is not None else []
    # A guest reset is a guest RESET, or the SHUTDOWN that QEMU emits in its
    # place under -no-reboot — but only with reason guest-reset. A guest that
    # powered itself off also carries guest: true, with reason guest-shutdown,
    # and calling that a reset would let a reproduction cell "reproduce" a
    # reset by observing an orderly poweroff.
    guest_reset_events = [e for e in events
                          if e.get("data", {}).get("reason") == "guest-reset"
                          and e.get("event") in ("RESET", "SHUTDOWN")]
    reset_total = len([e for e in events
                       if e.get("event") == "RESET"
                       and e.get("data", {}).get("reason") == "guest-reset"])
    if args.on_reset == "stop":
        reset_total = max(reset_total, len(guest_reset_events) and 1)

    # Classification is only meaningful when something terminal happened while
    # the run was still being observed: a guest reset, a watchdog, a panic, an
    # unexpected QEMU death, or a timeout on a run that was expected to boot.
    # The harness's own orderly quit after the observation window is not an
    # event — an earlier version classified its own cleanup as HOST_TERMINATED.
    names_seen = {e.get("event") for e in events}
    unexpected_death = not process_alive
    # A reboot this run commanded IN THE GUEST is not an anomalous event: it
    # needs no classification, the same way an operator typing `reboot` is
    # not a finding. Only resets beyond that budget are classified — an
    # earlier version classified its own commanded reboot as UNKNOWN, which
    # the importer correctly blocks on.
    #
    # A QMP system_reset is NOT in this budget: QEMU reports it with a host
    # reason, so it never enters guest_reset_events in the first place.
    # Budgeting for it would silently excuse one genuine spontaneous guest
    # reset per qemu-reset run — precisely the event these cells exist to
    # detect.
    commanded_resets = 1 if args.reboot_after_target else 0
    anomalous_resets = len(guest_reset_events) > commanded_resets
    classification = None
    basis: list[str] = []
    if anomalous_resets or {"WATCHDOG", "GUEST_PANICKED"} & names_seen \
            or unexpected_death \
            or (timed_out and not args.no_disk and not
                ("graphical" in stages or "multi-user" in stages)):
        debug_text = ""
        for candidate in (debug_log, evidence_dir / "qemu-debug-excerpt.log"):
            if candidate.exists():
                debug_text = candidate.read_text(encoding="utf-8", errors="replace")
                break
        classification, basis = classify(
            events, serial_text, process_alive, timed_out, qemu_stderr,
            classify_index=commanded_resets,
            boot_segments=split_boot_segments(serial_text),
            debug_text=debug_text)
    if reader_died:
        limitations.append(
            "the QMP event reader stopped before the run ended; events after "
            "that point were not observed and this run cannot be treated as "
            "having seen everything that happened")

    target_reached = "graphical" in stages or "multi-user" in stages
    health = "health-check" in stages
    second_boot_required = args.reboot_after_target or args.qemu_reset_after_target

    # The health-check marker is Bunny's own unit; an alternative disk cannot
    # print it and is judged on the boot target alone.
    health_ok = health or bool(args.alt_disk)
    if args.expect == "stable" or args.no_disk:
        # Stability cells pass by remaining alive for the whole observation
        # window: no guest reset, no panic, no unexpected death. Running out
        # the clock IS the expected outcome.
        result = "PASS" if (not guest_reset_events and process_alive
                            and not ({"WATCHDOG", "GUEST_PANICKED"} & names_seen)) \
            else "FAIL"
    elif args.expect == "reset":
        # Reproduction cells pass by observing and classifying at least one
        # guest reset. A run where nothing reset did not reproduce.
        result = "PASS" if guest_reset_events else "FAIL"
    elif second_boot_required:
        # A commanded guest reboot must actually have rebooted the guest. The
        # serial marker alone is not enough: systemd re-reaching a target on
        # the FIRST boot (a session restart re-printing "Reached target
        # Graphical Interface") looks identical in the transcript, and would
        # claim a machine survived a reboot it never took. A platform reset
        # is host-side and leaves no guest-reset event, so it is exempt.
        rebooted = bool(guest_reset_events) if args.reboot_after_target else True
        result = "PASS" if (target_reached and health_ok and second_target
                            and rebooted) else "FAIL"
        if args.reboot_after_target and second_target and not rebooted:
            limitations.append(
                "the boot target was re-reached without any guest reset: the "
                "commanded reboot never took effect, so this run proves "
                "nothing about surviving a reboot")
    else:
        ok = target_reached and health_ok and reset_total <= args.expected_resets
        result = "PASS" if ok else "FAIL"
        if timed_out and not target_reached and not guest_reset_events:
            result = "INCONCLUSIVE"

    # A run whose event stream went blind cannot assert that nothing further
    # happened. Any PASS that rests on the ABSENCE of an event is downgraded;
    # a PASS that rests on positive observations (it booted, it reached its
    # target) still stands, with the limitation recorded either way.
    if reader_died and result == "PASS" and args.expect in ("stable",):
        result = "INCONCLUSIVE"

    # Writable state is not evidence: record digests, sizes and lifecycle,
    # then remove the working copies.
    work_manifest = {
        "diskOverlay": ({"sha256": sha256_file(work / "disk-overlay.qcow2"),
                         "sizeBytes": (work / "disk-overlay.qcow2").stat().st_size}
                        if (work / "disk-overlay.qcow2").exists() else None),
        "ovmfVarsAfter": {"sha256": vars_after_digest},
        "tpmStateAfter": tpm_state_after,
        "lifecycle": "working copies deleted after digest capture",
    }
    (evidence_dir / "work-manifest.json").write_text(
        json.dumps(work_manifest, indent=2) + "\n", encoding="utf-8")
    # Preserve reusable state for chained experiments before deleting work/:
    # the caller may name this run's vars/tpm state as a reuse source, so move
    # them to stable names inside the evidence dir but outside git (gitignored
    # 'state' dir), recorded by digest above.
    state_keep = evidence_dir / "state"
    state_keep.mkdir()
    if vars_copy.exists():
        shutil.move(str(vars_copy), str(state_keep / "OVMF_VARS.qcow2"))
    if tpm_state_dir and tpm_state_dir.exists():
        shutil.move(str(tpm_state_dir), str(state_keep / "tpm-state"))
    shutil.rmtree(work, ignore_errors=True)

    evidence_files = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path.name != "record.json" \
                and "state" not in path.relative_to(evidence_dir).parts:
            evidence_files.append({
                "path": str(path.relative_to(evidence_dir)),
                "sha256": sha256_file(path),
                "sizeBytes": path.stat().st_size,
                "createdAt": completed,
                "collectionCommand": "run_tpm_experiment.py",
                "retentionClass": "evidence",
            })

    record = {
        "schemaVersion": 1,
        "evidenceId": run_id,
        "sourceCommit": context.sourceCommit,
        "sourceArchiveDigest": context.sourceArchiveDigest,
        "installationArtifactDigest": context.installationArtifactDigest,
        "qemuDigest": context.qemuDigest,
        "qemuVersion": context.qemuVersion,
        "ovmfCodeDigest": context.ovmfCodeDigest,
        "ovmfVarsTemplateDigest": context.ovmfVarsTemplateDigest,
        "swtpmDigest": context.swtpmDigest,
        "swtpmVersion": context.swtpmVersion,
        "libtpmsVersion": context.libtpmsVersion,
        "scenarioVersion": context.scenarioVersion,
        "environment": f"qemu-{args.accel}",
        "acceleration": args.accel,
        "machineType": machine,
        "cpuModel": cpu,
        "diagnostic": diagnostic,
        "diskAttached": not args.no_disk,
        **({"altDiskSha256": alt_disk_digest} if alt_disk_digest else {}),
        "ovmfVarsState": vars_state,
        "ovmfVarsSourceDigest": vars_source_digest,
        "ovmfVarsAfterDigest": vars_after_digest,
        "tpmInterface": args.tpm,
        "tpmState": tpm_state,
        **({"tpmStateSourceManifest": tpm_state_source_manifest}
           if tpm_state_source_manifest else {}),
        "secureBootState": "disabled",
        "smmState": "on" if args.smm else "off",
        "bootType": ("guest-reboot" if args.reboot_after_target
                     else "qemu-reset" if args.qemu_reset_after_target else "cold"),
        "onReset": args.on_reset,
        "expectation": args.expect,
        "expectedResets": args.expected_resets,
        "guestResetCount": reset_total,
        "stagesReached": stages,
        "lastStage": stages[-1] if stages else "none",
        "failedUnits": failed_units,
        "secondBootTargetReached": second_target if second_boot_required else None,
        **({"resetClassification": classification,
            "classificationBasis": basis} if classification else {}),
        "result": result,
        "startedAt": started,
        "completedAt": completed,
        "operator": args.operator,
        "limitations": limitations,
        "evidenceFiles": evidence_files,
    }
    (evidence_dir / "record.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"{run_id}: {result}"
          + (f" [{classification}]" if classification else "")
          + f" stages={'>'.join(stages) if stages else 'none'}"
          + f" resets={reset_total}")
    print(f"evidence in {evidence_dir}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
