#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run one dsq-1 display-stack reliability boot and collect its evidence.

Per-boot lifecycle (Stages 3, 4, 5 and 7 of the pass):

1. Verify the frozen artifact digest; refuse a mismatch.
2. Boot a fresh copy-on-write overlay with a per-run OVMF variable store
   (fresh from the template, or copied from a recorded seed) and, for TPM
   cells, a per-run swtpm state directory.
3. Watch serial for boot stages; count guest resets via QMP. Cell C is the
   only cell where exactly one firmware restoration reset is expected.
4. After graphical.target appears on serial, hold the observation window,
   take screendumps (supporting evidence only), then request a guest
   shutdown via ACPI power-button. The shutdown method actually used is
   recorded; a forced quit is a documented degradation, not a silent one.
5. Mount the overlay read-only offline, copy the installed journal out,
   analyse the exact boot ID, write excerpts, list coredump files, hash
   everything into the record.

A collection failure never becomes an empty failed-unit list: the analysis
fields stay null and ``collection.status`` says why.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "qualification" / "tpm" / "scripts"))

from dsq_context import (  # noqa: E402
    ContextError,
    JOURNAL_COLLECTOR_VERSION,
    AUTHORITY_FIELDS,
    resolve_context,
    sha256_file,
)
import dsq_disk  # noqa: E402
from journal_analysis import (  # noqa: E402
    JournalError,
    analyze_boot,
    excerpts,
    list_boots,
)
from run_tpm_experiment import QmpClient, manifest, read_serial  # noqa: E402

STAGE_MARKERS = [
    ("firmware-bds", r"BdsDxe: loading Boot"),
    ("boot-option-started", r"BdsDxe: starting Boot"),
    ("restoration-dialog", r"Boot Option Restoration"),
    ("reset-announced", r"Reset System"),
    ("kernel-loaded", r"(Loading Linux|Linux version \d|Booting a command list)"),
    ("initramfs", r"(dracut-initqueue|Reached target .*Initrd)"),
    ("multi-user", r"Reached target .*Multi-User System"),
    ("graphical", r"Reached target .*Graphical Interface"),
    ("health-check", r"Finished .*Bunny OS boot health check"),
]

CELLS = {
    "A": {"tpm": False, "vars": "seed", "smp": 4, "memory": 8192,
          "network": True, "expectedResets": 0,
          "description": "ordinary no-TPM cold boot, vars reused after "
                         "normal boot entry exists"},
    "B": {"tpm": True, "tpmState": "seed", "vars": "seed", "smp": 4,
          "memory": 8192, "network": True, "expectedResets": 0,
          "description": "CRB TPM with restored NVRAM, no reset expected"},
    "C": {"tpm": True, "tpmState": "fresh", "vars": "fresh", "smp": 4,
          "memory": 8192, "network": True, "expectedResets": 1,
          "description": "first TPM fallback boot, exactly one shim "
                         "restoration reboot expected"},
    "D": {"tpm": False, "vars": "seed", "smp": 2, "memory": 4096,
          "network": True, "expectedResets": 0,
          "description": "reduced resources: 2 vCPU, 4 GiB"},
    "E": {"tpm": False, "vars": "seed", "smp": 4, "memory": 8192,
          "network": False, "expectedResets": 0,
          "description": "network disconnected at the VM boundary"},
}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def stages_in(text: str) -> list[str]:
    found = [(m.start(), name) for name, regex in STAGE_MARKERS
             if (m := re.search(regex, text))]
    return [name for _, name in sorted(found)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell", required=True,
                        choices=[*CELLS.keys(), "seed-A", "seed-B"])
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--disk-source", type=Path, default=Path(
        "/var/tmp/bunny-installables-g/bunny-os-b9c317d35b85.qcow2"))
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/display-stack/evidence")
    parser.add_argument("--seed-root", type=Path,
                        default=ROOT / "qualification/display-stack/seeds")
    parser.add_argument("--trace-root", type=Path,
                        default=Path("/root/dsq-traces"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--observe", type=int, default=75)
    parser.add_argument("--date-tag", default=None)
    args = parser.parse_args()

    seeding = args.cell.startswith("seed-")
    cell_name = args.cell[-1] if seeding else args.cell
    cell = dict(CELLS[cell_name])
    if seeding:
        # A seed boot is the boot that *creates* the reusable variable
        # store (and TPM state for B) from fresh inputs. Measured on this
        # artifact: shim's fallback chainloads the created boot entry
        # directly when no TPM is attached, and takes its one designed
        # restoration reset only when one is (the tpmq-1 finding).
        cell["vars"] = "fresh"
        cell["expectedResets"] = 1 if cell.get("tpm") else 0
        if cell.get("tpm"):
            cell["tpmState"] = "fresh"

    context = resolve_context()
    artifact_digest = sha256_file(args.disk_source)
    if artifact_digest != context.installationArtifactDigest:
        print(f"REFUSED: {args.disk_source} digests to {artifact_digest}, "
              f"context requires {context.installationArtifactDigest}")
        return 2

    date_tag = args.date_tag or datetime.date.today().strftime("%Y%m%d")
    run_id = (f"DSQ-{date_tag}-seed{cell_name}" if seeding
              else f"DSQ-{date_tag}-cell{cell_name}-{args.sequence:03d}")
    evidence_dir = args.evidence_root / run_id
    if evidence_dir.exists():
        print(f"REFUSED: {evidence_dir} already exists; superseding runs get "
              "new sequence numbers, they do not overwrite")
        return 2
    evidence_dir.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix=f"dsq-{run_id}-"))
    trace_dir = args.trace_root / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    started = now()
    limitations: list[str] = []
    record: dict = {
        "schemaVersion": 1,
        "runId": run_id,
        "cell": cell_name,
        "seeding": seeding,
        "sequence": None if seeding else args.sequence,
        "cellConfiguration": cell,
        "startedAt": started,
        "authority": {k: context.raw.get(k) for k in AUTHORITY_FIELDS},
        "journalCollectorVersion": JOURNAL_COLLECTOR_VERSION,
        "artifact": {"name": args.disk_source.name, "sha256": artifact_digest},
    }

    def finish(status: str, **fields) -> int:
        record.update(fields)
        record["status"] = status
        record["completedAt"] = now()
        record["limitations"] = limitations
        record["evidenceManifest"] = manifest(evidence_dir)
        (evidence_dir / "record.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        shutil.rmtree(work, ignore_errors=True)
        print(f"{run_id}: {status}")
        return 0 if status in ("COLLECTED", "SEEDED") else 1

    # ------------------------------------------------------------- inputs
    overlay = work / "disk-overlay.qcow2"
    subprocess.run(["qemu-img", "create", "-f", "qcow2", "-b",
                    str(args.disk_source.resolve()), "-F", "qcow2",
                    str(overlay)], check=True, capture_output=True)

    vars_copy = work / "OVMF_VARS.qcow2"
    if cell["vars"] == "fresh":
        shutil.copy(context.ovmfVarsTemplatePath, vars_copy)
        record["varsSource"] = {"kind": "template",
                                "sha256": sha256_file(vars_copy)}
    else:
        seed_vars = args.seed_root / f"cell{cell_name}-OVMF_VARS.qcow2"
        if not seed_vars.exists():
            return finish("ABANDONED",
                          reason=f"seed variable store {seed_vars} missing; "
                                 f"run --cell seed-{cell_name} first")
        shutil.copy(seed_vars, vars_copy)
        record["varsSource"] = {"kind": "seed", "path": str(seed_vars),
                                "sha256": sha256_file(vars_copy)}

    swtpm_process = None
    tpm_sock = work / "swtpm.sock"
    tpm_state = work / "tpm-state"
    if cell.get("tpm"):
        tpm_state.mkdir()
        if cell.get("tpmState") == "seed":
            seed_state = args.seed_root / "cellB-tpm-state"
            if not seed_state.is_dir():
                return finish("ABANDONED",
                              reason=f"seed TPM state {seed_state} missing")
            shutil.copytree(seed_state, tpm_state, dirs_exist_ok=True)
            record["tpmStateSource"] = {"kind": "seed", "path": str(seed_state)}
        else:
            record["tpmStateSource"] = {"kind": "fresh"}
        swtpm_stdout = (trace_dir / "swtpm-stdout.log").open("wb")
        swtpm_process = subprocess.Popen(
            ["swtpm", "socket", "--tpmstate", f"dir={tpm_state}", "--tpm2",
             "--ctrl", f"type=unixio,path={tpm_sock}",
             "--log", f"file={trace_dir / 'swtpm.log'},level=1"],
            stdout=swtpm_stdout, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while not tpm_sock.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if not tpm_sock.exists():
            return finish("ABANDONED", reason="swtpm socket never appeared")

    # -------------------------------------------------------------- qemu
    serial_log = evidence_dir / "serial.log"
    qmp_socket = work / "qmp.sock"
    events_path = evidence_dir / "qmp-events.jsonl"
    screenshots = evidence_dir / "screenshots"
    screenshots.mkdir()
    qemu = [
        "qemu-system-x86_64",
        "-machine", f"{context.machineType},accel=kvm",
        "-cpu", context.cpuMode,
        "-smp", str(cell["smp"]),
        "-m", str(cell["memory"]),
        "-drive", f"if=pflash,format=qcow2,readonly=on,file={context.ovmfCodePath}",
        "-drive", f"if=pflash,format=qcow2,file={vars_copy}",
        "-chardev", f"file,id=ser0,path={serial_log}",
        "-serial", "chardev:ser0",
        "-qmp", f"unix:{qmp_socket},server,nowait",
        "-display", "none",
        "-vga", "virtio",
        "-drive", f"file={overlay},format=qcow2,if=virtio",
    ]
    if cell["network"]:
        qemu += ["-netdev", "user,id=n0",
                 "-device", "virtio-net-pci,netdev=n0"]
    else:
        qemu += ["-nic", "none"]
    if cell.get("tpm"):
        qemu += ["-chardev", f"socket,id=chrtpm,path={tpm_sock}",
                 "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                 "-device", "tpm-crb,tpmdev=tpm0"]
    (evidence_dir / "qemu-command.json").write_text(
        json.dumps({"argv": qemu, "startedAt": started}, indent=2) + "\n",
        encoding="utf-8")

    process = subprocess.Popen(qemu, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    qmp: QmpClient | None = None
    shutdown_method = None
    reset_times: list[str] = []
    try:
        deadline = time.monotonic() + 30
        while not qmp_socket.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = (process.stderr.read().decode(errors="replace")
                          if process.stderr else "")
                return finish("ABANDONED",
                              reason=f"QEMU exited immediately: {stderr[:400]}")
            time.sleep(0.2)
        qmp = QmpClient(qmp_socket, events_path)

        def screendump(label: str) -> None:
            try:
                qmp.execute("screendump",
                            {"filename": str(screenshots / f"{label}.ppm")})
            except (TimeoutError, OSError, ConnectionError):
                limitations.append(f"screendump {label} failed")

        seen: set[str] = set()
        graphical_seen_at: float | None = None
        boot_deadline = time.monotonic() + args.timeout
        outcome = "timeout"
        while time.monotonic() < boot_deadline:
            if process.poll() is not None:
                outcome = "qemu-exited"
                break
            text = read_serial(serial_log)
            for stage in stages_in(text):
                if stage not in seen:
                    seen.add(stage)
                    screendump(f"stage-{stage}")
            resets = [e for e in qmp.find_events("RESET")
                      if e.get("data", {}).get("reason") == "guest-reset"]
            reset_times = [e.get("hostTime", "") for e in resets]
            if len(resets) > cell["expectedResets"]:
                outcome = "unexpected-reset"
                screendump("unexpected-reset")
                break
            if "graphical" in seen and graphical_seen_at is None:
                graphical_seen_at = time.monotonic()
                screendump("graphical-reached")
            if graphical_seen_at is not None and \
                    time.monotonic() - graphical_seen_at >= args.observe:
                outcome = "observed"
                screendump("observation-window-end")
                break
            time.sleep(2)
        if outcome == "timeout":
            screendump("boot-timeout")

        record["serialStages"] = sorted(seen)
        record["graphicalTargetOnSerial"] = graphical_seen_at is not None
        record["observationWindowSeconds"] = args.observe
        record["observationWindowCompleted"] = outcome == "observed"
        record["liveOutcome"] = outcome
        record["guestResetCount"] = len(reset_times)
        record["guestResetTimes"] = reset_times
        record["expectedResets"] = cell["expectedResets"]

        # ------------------------------------------------------ shutdown
        if process.poll() is None:
            qmp.shutting_down = True
            try:
                qmp.execute("system_powerdown")
                shutdown_method = "acpi-powerdown"
            except (TimeoutError, OSError, ConnectionError):
                shutdown_method = "acpi-powerdown-send-failed"
            shutdown_deadline = time.monotonic() + 180
            while process.poll() is None and \
                    time.monotonic() < shutdown_deadline:
                time.sleep(1)
            if process.poll() is None:
                try:
                    qmp.execute("quit")
                except (TimeoutError, OSError, ConnectionError):
                    pass
                shutdown_method += "+forced-quit"
                limitations.append(
                    "guest did not power down within 180s; QEMU was quit — "
                    "journal tail may be unflushed")
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            shutdown_method = "guest-exited-before-request"
    finally:
        if qmp is not None:
            qmp.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)
        if swtpm_process is not None:
            swtpm_process.terminate()
            try:
                swtpm_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                swtpm_process.kill()
    record["shutdownMethod"] = shutdown_method
    record["qemuExitCode"] = process.returncode

    # ------------------------------------------------- seed preservation
    if seeding:
        args.seed_root.mkdir(parents=True, exist_ok=True)
        seed_vars_out = args.seed_root / f"cell{cell_name}-OVMF_VARS.qcow2"
        shutil.copy(vars_copy, seed_vars_out)
        seed_note = {"fromRun": run_id, "varsSha256": sha256_file(seed_vars_out)}
        if cell.get("tpm"):
            seed_state_out = args.seed_root / "cellB-tpm-state"
            if seed_state_out.exists():
                shutil.rmtree(seed_state_out)
            shutil.copytree(tpm_state, seed_state_out)
            seed_note["tpmStateManifest"] = manifest(seed_state_out)
        record["seedProduced"] = seed_note

    # ------------------------------------------------ offline collection
    collection: dict = {"journalCollectorVersion": JOURNAL_COLLECTOR_VERSION}
    record["collection"] = collection
    journal_out = work / "journal"
    try:
        var_path = dsq_disk.stateroot_var(overlay)
        root = dsq_disk.root_partition(overlay)
        subprocess.run(
            ["guestfish", "--ro", "-a", str(overlay), "run", ":",
             "mount-ro", root, "/", ":",
             "copy-out", f"{var_path}/log/journal", str(work)],
            check=True, capture_output=True, text=True, timeout=1800)
        journal_out = work / "journal"
        coredump_ls = subprocess.run(
            ["guestfish", "--ro", "-a", str(overlay), "run", ":",
             "mount-ro", root, "/", ":",
             "ls", f"{var_path}/lib/systemd/coredump"],
            capture_output=True, text=True, timeout=900)
        collection["coredumpFiles"] = (
            coredump_ls.stdout.split() if coredump_ls.returncode == 0 else [])
        collection["journalExtraction"] = "ok"
    except (dsq_disk.DiskLayoutError, subprocess.SubprocessError, OSError) as exc:
        collection["journalExtraction"] = f"FAILED: {exc}"
        collection["status"] = "collection-failed"
        return finish("COLLECTION_FAILED")

    try:
        boots = list_boots(journal_out)
        collection["bootsInJournal"] = len(boots)
        target_boot = boots[-1]["boot_id"]
        collection["bootId"] = target_boot
        analysis = analyze_boot(journal_out, target_boot)
        record["analysis"] = analysis
        collection["excerpts"] = excerpts(journal_out, target_boot,
                                          evidence_dir / "journal")
        # Retain the binary journal out-of-tree with its digest recorded.
        journal_keep = trace_dir / "journal"
        if journal_keep.exists():
            shutil.rmtree(journal_keep)
        shutil.copytree(journal_out, journal_keep)
        collection["binaryJournalRetainedAt"] = str(journal_keep)
        collection["binaryJournalManifestSha256"] = sha256_file(
            _write_manifest(journal_keep, trace_dir / "journal-manifest.json"))
        collection["status"] = "ok"
    except (JournalError, OSError, KeyError, IndexError) as exc:
        collection["status"] = "collection-failed"
        collection["analysisError"] = str(exc)[:500]
        return finish("COLLECTION_FAILED")

    return finish("SEEDED" if seeding else "COLLECTED")


def _write_manifest(directory: Path, out: Path) -> Path:
    out.write_text(json.dumps(manifest(directory), indent=2) + "\n",
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
