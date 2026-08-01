#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run one installed-system qualification scenario in QEMU/KVM, and prove it ran.

Every scenario receives a disposable disk, its own OVMF variable store, its
own TPM socket when the scenario asks for one, and a serial log that is the
primary evidence stream. The runner records the exact QEMU configuration it
launched, takes screendumps at declared checkpoints, hashes every evidence
file, and emits a verdict record conforming to
``schemas/installed-qualification-record.schema.json``.

Authority comes from the evidence context, never from the invocation: the
runner resolves ``evidence-context.json`` through ``release.installed`` and
refuses media whose digest is not the one the context pins. A scenario run
against an unpinned artifact would produce evidence about nothing.

The verdict is honest about its environment: ``environment`` is always
``qemu-kvm`` here, ``tpmState`` is ``swtpm`` when a software TPM was attached,
and nothing this runner emits can satisfy a physical-hardware prerequisite —
the record schema and the adversarial tests both enforce that downstream.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from release.installed import evidence_id, resolve_context  # noqa: E402

OVMF_CODE = Path("/usr/share/edk2/ovmf/OVMF_CODE_4M.qcow2")
OVMF_VARS = Path("/usr/share/edk2/ovmf/OVMF_VARS_4M.qcow2")
OVMF_CODE_SECBOOT = Path("/usr/share/edk2/ovmf/OVMF_CODE_4M.secboot.qcow2")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Qmp:
    """The smallest QMP client this runner needs: negotiate, execute, close."""

    def __init__(self, path: Path) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(str(path))
        self.buffer = b""
        self._read_message()  # greeting
        self.execute("qmp_capabilities")

    def _read_message(self) -> dict:
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("QMP socket closed")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return json.loads(line)

    def execute(self, command: str, arguments: dict | None = None) -> dict:
        payload: dict = {"execute": command}
        if arguments:
            payload["arguments"] = arguments
        self.sock.sendall(json.dumps(payload).encode() + b"\n")
        while True:
            message = self._read_message()
            if "return" in message or "error" in message:
                return message

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def wait_for_markers(
    serial_log: Path,
    markers: list[dict],
    timeout: int,
    checkpoint: callable,
    serial_inputs: list[dict] | None = None,
    serial_socket: Path | None = None,
) -> tuple[dict[str, bool], list[str]]:
    """Scan the serial log until every required marker appears or time runs out.

    Screendump checkpoints fire when their trigger marker lands, so the
    screenshot shows the state the marker announced rather than an arbitrary
    later moment. Serial inputs fire once each, when their prompt regex
    appears; the environment variable named by ``sendFromEnv`` supplies the
    text, so a credential never sits in a scenario file.
    """
    found: dict[str, bool] = {m["label"]: False for m in markers}
    sent: list[str] = []
    pending_inputs = list(serial_inputs or [])
    deadline = time.monotonic() + timeout
    fired: set[str] = set()
    connection: socket.socket | None = None
    last_prompt_offset = 0
    while time.monotonic() < deadline:
        text = serial_log.read_text(encoding="utf-8", errors="replace") if serial_log.exists() else ""
        for marker in markers:
            label = marker["label"]
            if not found[label] and re.search(marker["regex"], text):
                found[label] = True
                if label not in fired:
                    fired.add(label)
                    checkpoint(label)
        for entry in list(pending_inputs):
            # Only text that arrived since the previous send is eligible to
            # trigger the next input, so three wrong-passphrase sends need
            # three distinct prompts rather than one prompt read three times.
            if re.search(entry["promptRegex"], text[last_prompt_offset:]):
                payload = os.environ.get(entry["sendFromEnv"], "")
                if not payload and entry.get("required", True):
                    raise SystemExit(
                        f"BLOCKED: serial input requires ${entry['sendFromEnv']} and it is "
                        "empty. A prompt answered with nothing is not the scenario."
                    )
                try:
                    if connection is None:
                        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        connection.settimeout(10)
                        connection.connect(str(serial_socket))
                    connection.sendall((payload + "\n").encode())
                    sent.append(entry["label"])
                    last_prompt_offset = len(text)
                    repeat = int(entry.get("repeat", 1)) - 1
                    if repeat > 0:
                        entry["repeat"] = repeat
                    else:
                        pending_inputs.remove(entry)
                except OSError as exc:
                    raise SystemExit(f"BLOCKED: serial send failed: {exc}")
        if all(found[m["label"]] for m in markers if m.get("required", True)) \
                and not pending_inputs:
            break
        time.sleep(5)
    if connection is not None:
        connection.close()
    return found, sent


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_scenario")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--disk", type=Path, help="pre-installed disk image for installed-disk scenarios")
    parser.add_argument("--derived-disk", type=Path,
                        help="a disk produced by an installation run this session; pinned "
                             "through its installation record rather than by its own digest")
    parser.add_argument("--install-record", type=Path,
                        help="the installation record that produced --derived-disk; required "
                             "with it, and its digest is embedded in the verdict")
    parser.add_argument("--installer-iso", type=Path)
    parser.add_argument("--recovery-iso", type=Path)
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/installed-system/evidence")
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--operator", default=os.environ.get("BUNNY_OPERATOR", ""))
    parser.add_argument("--keep-disk", action="store_true")
    args = parser.parse_args()

    if not args.operator:
        print("BLOCKED: --operator (or BUNNY_OPERATOR) is required. Evidence without an "
              "operator is one of the exact records the adversarial tests refuse.",
              file=sys.stderr)
        return 2

    context = resolve_context(ROOT)
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    name = scenario["name"]
    run_id = evidence_id(name, date=datetime.date.today().strftime("%Y%m%d"),
                         sequence=args.sequence)
    evidence_dir = args.evidence_root / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    work = evidence_dir / "work"
    work.mkdir()

    started = now()
    assertions: list[dict] = []
    limitations: list[str] = list(scenario.get("notes", []) if isinstance(
        scenario.get("notes"), list) else [])

    # ---------------------------------------------------------------- media
    # Every attached artifact must be the one the context pins. An artifact
    # digest is recomputed from the bytes on disk, not read from a manifest.
    def pinned(path: Path, context_field: str) -> Path:
        actual = sha256_file(path)
        expected = getattr(context, context_field)
        if actual != expected:
            raise SystemExit(
                f"BLOCKED: {path.name} digests to {actual[:12]} but the context pins "
                f"{context_field}={str(expected)[:12]}. Evidence about an unpinned "
                "artifact is evidence about nothing."
            )
        return path

    disk_path = evidence_dir / "work" / "target-disk.qcow2"
    boot_disk: Path | None = None
    install_record_digest = None
    if args.derived_disk:
        # A disk minted by an installation run has a per-run digest by design
        # (per-installation identities). Its custody chain runs through the
        # installation record: the record names the image it deployed, the
        # record's digest lands in this verdict, and a verdict whose record
        # is missing proves nothing and is refused here.
        if not args.install_record or not args.install_record.is_file():
            raise SystemExit(
                "BLOCKED: --derived-disk requires --install-record; a derived disk "
                "without its installation record has no custody chain to the archive."
            )
        install_record_digest = sha256_file(args.install_record)
        shutil.copy(args.install_record, evidence_dir / "installation-record.json")
        raw = args.derived_disk
        subprocess.run(
            ["qemu-img", "convert", "-O", "qcow2", str(raw), str(disk_path)],
            check=True, capture_output=True,
        )
        boot_disk = disk_path
    elif args.disk:
        source = pinned(args.disk, "installationArtifactDigest")
        # The scenario boots a copy. The pinned artifact is immutable evidence;
        # a run that mutated it would invalidate every later run's binding.
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", "-b", str(source.resolve()),
             "-F", source.suffix.lstrip(".").replace("img", "raw") or "qcow2",
             str(disk_path)],
            check=True, capture_output=True,
        )
        boot_disk = disk_path
    else:
        size = scenario.get("disk", {}).get("sizeGiB", 64)
        subprocess.run(["qemu-img", "create", "-f", "qcow2", str(disk_path), f"{size}G"],
                       check=True, capture_output=True)
        boot_disk = disk_path

    # ------------------------------------------------------------- firmware
    firmware = scenario.get("firmware", "uefi")
    code = OVMF_CODE_SECBOOT if firmware == "uefi-secure-boot-development" else OVMF_CODE
    vars_copy = work / "OVMF_VARS.qcow2"
    shutil.copy(OVMF_VARS, vars_copy)

    serial_log = evidence_dir / "serial.log"
    serial_socket = work / "serial.sock"
    qmp_socket = work / "qmp.sock"

    # Scenarios that answer a prompt (a LUKS passphrase, a confirmation) get a
    # writable serial: a chardev socket whose logfile still captures every
    # byte for evidence. What is SENT is never logged by this runner — the
    # send text may be a test credential, and the guest does not echo
    # passphrase input either.
    serial_inputs = scenario.get("serialInputs", [])

    qemu = [
        "qemu-system-x86_64",
        "-machine", "q35,accel=kvm",
        "-cpu", "host",
        "-smp", str(scenario.get("resources", {}).get("vcpus", 4)),
        "-m", str(scenario.get("resources", {}).get("memoryMiB", 8192)),
        "-drive", f"if=pflash,format=qcow2,readonly=on,file={code}",
        "-drive", f"if=pflash,format=qcow2,file={vars_copy}",
        "-drive", f"file={boot_disk},format=qcow2,if=virtio",
        "-chardev",
        f"socket,id=ser0,path={serial_socket},server=on,wait=off,logfile={serial_log}",
        "-serial", "chardev:ser0",
        "-qmp", f"unix:{qmp_socket},server,nowait",
        "-display", "none",
        "-vga", "virtio",
        "-no-reboot",
    ]

    if scenario.get("network", "enabled") == "absent":
        qemu += ["-nic", "none"]
        assertions.append({
            "name": "network-boundary-absent",
            "expected": "no NIC attached at the VM boundary",
            "observed": "-nic none", "result": "PASS",
        })
    else:
        pcap = evidence_dir / "network.pcap"
        qemu += ["-netdev", f"user,id=n0", "-device", "virtio-net-pci,netdev=n0",
                 "-object", f"filter-dump,id=fd0,netdev=n0,file={pcap}"]

    swtpm_process = None
    if scenario.get("tpm") == "swtpm":
        tpm_dir = work / "tpm"
        tpm_dir.mkdir()
        tpm_sock = work / "swtpm.sock"
        swtpm_process = subprocess.Popen(
            ["swtpm", "socket", "--tpmstate", f"dir={tpm_dir}", "--tpm2",
             "--ctrl", f"type=unixio,path={tpm_sock}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        qemu += ["-chardev", f"socket,id=chrtpm,path={tpm_sock}",
                 "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                 "-device", "tpm-tis,tpmdev=tpm0"]

    if args.installer_iso:
        qemu += ["-cdrom", str(pinned(args.installer_iso, "installationArtifactDigest"))]
    if args.recovery_iso:
        qemu += ["-cdrom", str(pinned(args.recovery_iso, "recoveryArtifactDigest"))]

    (evidence_dir / "qemu-command.json").write_text(
        json.dumps({"argv": qemu, "scenario": scenario, "startedAt": started},
                   indent=2) + "\n", encoding="utf-8")

    process = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    qmp: Qmp | None = None
    screenshots = evidence_dir / "screenshots"
    screenshots.mkdir()

    def checkpoint(label: str) -> None:
        nonlocal qmp
        try:
            if qmp is None:
                qmp = Qmp(qmp_socket)
            target = screenshots / f"{label}.ppm"
            qmp.execute("screendump", {"filename": str(target)})
        except (OSError, ConnectionError):
            limitations.append(f"screendump at checkpoint {label} failed; serial log remains "
                               "the primary evidence for it")

    try:
        deadline = time.monotonic() + 30
        while not qmp_socket.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
                raise SystemExit(f"BLOCKED: QEMU exited immediately: {stderr[:500]}")
            time.sleep(0.5)

        found, inputs_sent = wait_for_markers(
            serial_log, scenario.get("markers", []),
            scenario.get("timeoutSeconds", 600), checkpoint,
            serial_inputs=serial_inputs, serial_socket=serial_socket,
        )
        for marker in scenario.get("markers", []):
            assertions.append({
                "name": f"marker:{marker['label']}",
                "expected": marker["regex"],
                "observed": "matched" if found[marker["label"]] else "absent within timeout",
                "result": "PASS" if found[marker["label"]] or not marker.get("required", True)
                          else "FAIL",
            })
        for entry in serial_inputs:
            assertions.append({
                "name": f"serial-input:{entry['label']}",
                "expected": f"prompt {entry['promptRegex']!r} answered",
                "observed": "sent" if entry["label"] in inputs_sent else "prompt never appeared",
                "result": "PASS" if entry["label"] in inputs_sent else "FAIL",
            })

        # Forbidden markers: what must NOT have happened. A refusal scenario
        # is only a pass when the refusal is visible AND the forbidden success
        # is absent — an empty log satisfies neither.
        final_text = serial_log.read_text(encoding="utf-8", errors="replace") \
            if serial_log.exists() else ""
        for forbidden in scenario.get("forbiddenMarkers", []):
            hit = re.search(forbidden["regex"], final_text)
            assertions.append({
                "name": f"forbidden:{forbidden['label']}",
                "expected": f"absent: {forbidden['regex']}",
                "observed": hit.group(0)[:80] if hit else "absent",
                "result": "FAIL" if hit else "PASS",
            })

        # Clean shutdown, escalating only when the guest does not respond: a
        # forced quit is recorded, because disk state after a forced quit is a
        # different claim than disk state after an orderly stop.
        try:
            if qmp is None:
                qmp = Qmp(qmp_socket)
            qmp.execute("system_powerdown")
            for _ in range(60):
                if process.poll() is not None:
                    break
                time.sleep(2)
            if process.poll() is None:
                qmp.execute("quit")
                limitations.append("guest did not power down within 120s; QEMU was quit")
        except (OSError, ConnectionError):
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                limitations.append("QEMU required SIGKILL")
    finally:
        if qmp is not None:
            qmp.close()
        if swtpm_process is not None:
            swtpm_process.terminate()

    completed = now()

    # A refusal scenario is expressed directly — the refusal is a required
    # marker, the success it prevents is a forbidden one — so a single rule
    # decides every scenario: the run passes when every assertion passed.
    # There is no inversion to audit and no way to pass on an empty log.
    result = "PASS" if assertions and all(
        a["result"] == "PASS" for a in assertions) else "FAIL"

    if not args.keep_disk and disk_path.exists():
        disk_path.unlink()
        shutil.rmtree(work, ignore_errors=True)

    evidence_files = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path.name != "record.json":
            evidence_files.append({
                "path": str(path.relative_to(evidence_dir)),
                "sha256": sha256_file(path),
                "createdAt": completed,
                "collectionCommand": "run_scenario.py",
                "redactionStatus": "not-required",
                "retentionClass": "evidence",
            })

    record = {
        "schemaVersion": 1,
        "evidenceId": run_id,
        "sourceCommit": context.sourceCommit,
        "sourceArchiveDigest": context.sourceArchiveDigest,
        "installationArtifactDigest": context.installationArtifactDigest,
        **({"recoveryArtifactDigest": context.recoveryArtifactDigest}
           if context.recoveryArtifactDigest else {}),
        "environment": "qemu-kvm",
        "firmwareMode": firmware,
        "secureBootState": "development-keys" if firmware == "uefi-secure-boot-development"
                           else "disabled",
        "tpmState": "swtpm" if scenario.get("tpm") == "swtpm" else "absent",
        "encryptionState": scenario.get("encryption", "none"),
        "scenario": name,
        "scenarioVersion": context.scenarioVersion,
        "startedAt": started,
        "completedAt": completed,
        "result": result,
        **({"installationRecordSha256": install_record_digest}
           if install_record_digest else {}),
        "assertions": assertions,
        "evidenceFiles": evidence_files,
        "operator": args.operator,
        "limitations": limitations,
    }
    (evidence_dir / "record.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"{run_id}: {result}")
    for assertion in assertions:
        print(f"  {assertion['result']:4} {assertion['name']}")
    print(f"evidence in {evidence_dir}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
