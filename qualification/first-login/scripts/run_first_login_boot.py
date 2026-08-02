#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run one dsq-2 first-login boot and collect its evidence.

dsq-2 is dsq-1's five cells plus the thing dsq-1 could not do: log in. The
corrected units are user units, so without a session they never run, and the
defect this pass closes is invisible.

Per run:

 1. Verify the artifact digest against the dsq-2 authority. A run against any
    other disk is refused, which is what stops dsq-1's artifact — or dsq-1's
    evidence — being carried into this scenario.
 2. Create a fresh overlay and inject the qualification-only login fixture
    into it. The source disk is never written.
 3. Boot. Watch serial for stages; count guest resets over QMP.
 4. Hold the observation window after graphical.target, then shut down over
    ACPI. A forced quit is recorded, never silent.
 5. On a second-login run, boot the same overlay again. A second boot rather
    than a logout, because it also answers "reboot followed by login" and
    because automatic login makes it the honest way to get a second session.
 6. Offline, with the guest powered down: copy the journal out, analyse each
    boot ID separately, and read the home directory's real ownership, mode,
    type and SELinux context from the filesystem.

A collection failure never becomes a passing assertion: the fields stay null
and the record says why.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
DSQ_SCRIPTS = ROOT / "qualification/display-stack/scripts"
sys.path.insert(0, str(DSQ_SCRIPTS))
sys.path.insert(0, str(ROOT / "qualification/tpm/scripts"))

import dsq_disk  # noqa: E402
import home_assertions  # noqa: E402
import login_fixture  # noqa: E402
from dsq_context import JOURNAL_COLLECTOR_VERSION, sha256_file  # noqa: E402
from journal_analysis import (  # noqa: E402
    JournalError, analyze_boot, excerpts, list_boots,
)
from run_boot import CELLS, stages_in  # noqa: E402
from run_tpm_experiment import QmpClient, manifest, read_serial  # noqa: E402

SCENARIO_VERSION = "dsq-2"

#: Second-login coverage required by Stage 8, per cell.
SECOND_LOGIN_PLAN = {"A": 10, "D": 5, "E": 5, "B": 0, "C": 0}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def load_context(path: Path) -> dict:
    context = json.loads(path.read_text(encoding="utf-8"))
    if context.get("scenarioVersion") != SCENARIO_VERSION:
        raise SystemExit(
            f"REFUSED: {path} declares scenarioVersion "
            f"{context.get('scenarioVersion')!r}; this harness only produces "
            f"{SCENARIO_VERSION} evidence. dsq-1 records and dsq-2 records "
            "describe different archives and must not share an authority.")
    return context


class Boot:
    """One power-on of the overlay, with its own serial log and screenshots."""

    def __init__(self, evidence_dir: Path, label: str):
        self.label = label
        self.serial = evidence_dir / f"serial-{label}.log"
        self.events = evidence_dir / f"qmp-events-{label}.jsonl"
        self.screenshots = evidence_dir / "screenshots" / label
        self.screenshots.mkdir(parents=True, exist_ok=True)
        self.result: dict = {"label": label}


def run_one_boot(boot: Boot, qemu_base: list[str], work: Path, cell: dict,
                 observe: int, timeout: int, limitations: list[str]) -> dict:
    qmp_socket = work / f"qmp-{boot.label}.sock"
    if qmp_socket.exists():
        qmp_socket.unlink()
    qemu = qemu_base + [
        "-chardev", f"file,id=ser0,path={boot.serial}",
        "-serial", "chardev:ser0",
        "-qmp", f"unix:{qmp_socket},server,nowait",
    ]
    process = subprocess.Popen(qemu, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    qmp: QmpClient | None = None
    reset_times: list[str] = []
    shutdown_method = None
    try:
        deadline = time.monotonic() + 30
        while not qmp_socket.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = (process.stderr.read().decode(errors="replace")
                          if process.stderr else "")
                boot.result.update(outcome="qemu-exited-immediately",
                                   detail=stderr[:400])
                return boot.result
            time.sleep(0.2)
        qmp = QmpClient(qmp_socket, boot.events)

        def screendump(name: str) -> None:
            try:
                qmp.execute("screendump",
                            {"filename": str(boot.screenshots / f"{name}.ppm")})
            except (TimeoutError, OSError, ConnectionError):
                limitations.append(f"screendump {boot.label}/{name} failed")

        seen: set[str] = set()
        graphical_at: float | None = None
        outcome = "timeout"
        boot_deadline = time.monotonic() + timeout
        while time.monotonic() < boot_deadline:
            if process.poll() is not None:
                outcome = "qemu-exited"
                break
            for stage in stages_in(read_serial(boot.serial)):
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
            if "graphical" in seen and graphical_at is None:
                graphical_at = time.monotonic()
                screendump("graphical-reached")
            if graphical_at is not None and \
                    time.monotonic() - graphical_at >= observe:
                outcome = "observed"
                screendump("observation-window-end")
                break
            time.sleep(2)
        if outcome == "timeout":
            screendump("boot-timeout")

        boot.result.update(
            serialStages=sorted(seen),
            graphicalTargetOnSerial=graphical_at is not None,
            observationWindowSeconds=observe,
            observationWindowCompleted=outcome == "observed",
            outcome=outcome,
            guestResetCount=len(reset_times),
            guestResetTimes=reset_times,
        )

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
                    f"{boot.label}: guest did not power down within 180s; "
                    "QEMU was quit and the journal tail may be unflushed")
        else:
            shutdown_method = "guest-exited-before-request"
    finally:
        if qmp is not None:
            qmp.close()
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
    boot.result["shutdownMethod"] = shutdown_method
    boot.result["qemuExitCode"] = process.returncode
    return boot.result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell", required=True,
                        choices=[*CELLS, "seed-A", "seed-B"])
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--second-login", action="store_true")
    parser.add_argument("--disk-source", type=Path, required=True)
    parser.add_argument("--context", type=Path,
                        default=ROOT / "qualification/first-login/"
                                       "evidence-context.json")
    parser.add_argument("--evidence-root", type=Path,
                        default=ROOT / "qualification/first-login/evidence")
    parser.add_argument("--seed-root", type=Path,
                        default=ROOT / "qualification/first-login/seeds")
    parser.add_argument("--trace-root", type=Path,
                        default=Path("/root/flq-traces"))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--observe", type=int, default=75)
    parser.add_argument("--date-tag", default=None)
    args = parser.parse_args()

    context = load_context(args.context)
    seeding = args.cell.startswith("seed-")
    cell_name = args.cell[-1] if seeding else args.cell
    cell = dict(CELLS[cell_name])
    if seeding:
        # A seed boot is the boot that creates the reusable variable store —
        # and, for B, the TPM state — from fresh inputs. The corrected archive
        # is a different disk, so the dsq-1 seeds do not describe it: their
        # boot entries name another deployment. Cells A, B, D and E all boot
        # from a seed, so this has to run first.
        #
        # Measured in tpmq-1: shim's fallback chainloads the created boot
        # entry directly with no TPM attached, and takes its one designed
        # restoration reset only when one is present.
        cell["vars"] = "fresh"
        cell["expectedResets"] = 1 if cell.get("tpm") else 0
        if cell.get("tpm"):
            cell["tpmState"] = "fresh"

    digest = sha256_file(args.disk_source)
    if digest != context["installationArtifactDigest"]:
        print(f"REFUSED: {args.disk_source} digests to {digest}; the dsq-2 "
              f"authority requires {context['installationArtifactDigest']}. "
              "A first-login run against the superseded archive would measure "
              "the defect, not the correction.")
        return 2

    date_tag = args.date_tag or datetime.date.today().strftime("%Y%m%d")
    run_id = (f"FLQ-{date_tag}-seed{cell_name}" if seeding
              else f"FLQ-{date_tag}-cell{cell_name}-{args.sequence:03d}")
    evidence_dir = args.evidence_root / run_id
    if evidence_dir.exists():
        print(f"REFUSED: {evidence_dir} exists; a superseding run takes a new "
              "sequence number, it does not overwrite")
        return 2
    evidence_dir.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix=f"flq-{run_id}-"))
    trace_dir = args.trace_root / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    limitations: list[str] = []
    record: dict = {
        "schemaVersion": 1,
        "scenarioVersion": SCENARIO_VERSION,
        "runId": run_id,
        "cell": cell_name,
        "seeding": seeding,
        "sequence": None if seeding else args.sequence,
        "cellConfiguration": cell,
        "secondLoginPlanned": args.second_login,
        "startedAt": now(),
        "authority": {k: context.get(k) for k in sorted(context)},
        "journalCollectorVersion": JOURNAL_COLLECTOR_VERSION,
        "artifact": {"name": args.disk_source.name, "sha256": digest},
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

    # ------------------------------------------------------------- overlay
    overlay = work / "disk-overlay.qcow2"
    subprocess.run(["qemu-img", "create", "-f", "qcow2", "-b",
                    str(args.disk_source.resolve()), "-F", "qcow2",
                    str(overlay)], check=True, capture_output=True)
    try:
        root = dsq_disk.root_partition(overlay)
        listing = subprocess.run(
            ["guestfish", "-a", str(overlay), "run", ":", "mount", root, "/",
             ":", "glob-expand", "/ostree/deploy/*/deploy/*.0"],
            check=True, capture_output=True, text=True).stdout.strip()
        deploy = listing.splitlines()[0].rstrip("/")
    except (dsq_disk.DiskLayoutError, subprocess.SubprocessError,
            IndexError) as exc:
        return finish("ABANDONED", reason=f"cannot read the overlay: {exc}")

    leaks = login_fixture.verify_absent_from_artifact(args.disk_source, root,
                                                      deploy)
    if leaks:
        return finish("ABANDONED",
                      reason="the fixture account is present in the artifact "
                             "under test: " + "; ".join(leaks))
    try:
        provenance = login_fixture.inject(overlay, root, deploy,
                                          second_login=args.second_login)
    except login_fixture.FixtureError as exc:
        return finish("ABANDONED", reason=f"login fixture failed: {exc}")
    record["loginFixture"] = provenance
    record["deployment"] = deploy

    # ---------------------------------------------------------------- vars
    vars_copy = work / "OVMF_VARS.qcow2"
    if cell["vars"] == "fresh":
        shutil.copy(context["ovmfVarsTemplatePath"], vars_copy)
        record["varsSource"] = {"kind": "template",
                                "sha256": sha256_file(vars_copy)}
    else:
        seed_cell = cell.get("varsSeedCell", cell_name)
        seed_vars = args.seed_root / f"cell{seed_cell}-OVMF_VARS.qcow2"
        if not seed_vars.exists():
            return finish("ABANDONED",
                          reason=f"seed variable store {seed_vars} missing")
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
        swtpm_process = subprocess.Popen(
            ["swtpm", "socket", "--tpmstate", f"dir={tpm_state}", "--tpm2",
             "--ctrl", f"type=unixio,path={tpm_sock}",
             "--log", f"file={trace_dir / 'swtpm.log'},level=1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while not tpm_sock.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if not tpm_sock.exists():
            return finish("ABANDONED", reason="swtpm socket never appeared")

    qemu_base = [
        "qemu-system-x86_64",
        "-machine", f"{context['machineType']},accel=kvm",
        "-cpu", context["cpuMode"],
        "-smp", str(cell["smp"]),
        "-m", str(cell["memory"]),
        "-drive", f"if=pflash,format=qcow2,readonly=on,"
                  f"file={context['ovmfCodePath']}",
        "-drive", f"if=pflash,format=qcow2,file={vars_copy}",
        "-display", "none",
        "-vga", "virtio",
        "-drive", f"file={overlay},format=qcow2,if=virtio",
    ]
    if cell["network"]:
        qemu_base += ["-netdev", "user,id=n0",
                      "-device", "virtio-net-pci,netdev=n0"]
    else:
        qemu_base += ["-nic", "none"]
    if cell.get("tpm"):
        qemu_base += ["-chardev", f"socket,id=chrtpm,path={tpm_sock}",
                      "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                      "-device", "tpm-crb,tpmdev=tpm0"]
    (evidence_dir / "qemu-command.json").write_text(
        json.dumps({"argv": qemu_base, "startedAt": record["startedAt"]},
                   indent=2) + "\n", encoding="utf-8")

    # --------------------------------------------------------------- boots
    boots: list[dict] = []
    try:
        first = Boot(evidence_dir, "login-1")
        boots.append(run_one_boot(first, qemu_base, work, cell, args.observe,
                                  args.timeout, limitations))
        if args.second_login and first.result.get("outcome") == "observed":
            # The second boot reuses the same overlay, so it sees the state
            # the first login wrote. A fresh overlay here would be a second
            # first login, which measures nothing about idempotence.
            second = Boot(evidence_dir, "login-2")
            # Only the first boot of a fresh variable store takes the shim
            # restoration reset; the second must take none.
            second_cell = dict(cell, expectedResets=0)
            boots.append(run_one_boot(second, qemu_base, work, second_cell,
                                      args.observe, args.timeout, limitations))
        elif args.second_login:
            limitations.append(
                "second login not attempted: the first boot did not complete "
                "its observation window")
    finally:
        if swtpm_process is not None:
            swtpm_process.terminate()
            try:
                swtpm_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                swtpm_process.kill()
    record["boots"] = boots

    # ------------------------------------------------- seed preservation
    if seeding:
        args.seed_root.mkdir(parents=True, exist_ok=True)
        seed_vars_out = args.seed_root / f"cell{cell_name}-OVMF_VARS.qcow2"
        shutil.copy(vars_copy, seed_vars_out)
        seed_note = {"fromRun": run_id,
                     "varsSha256": sha256_file(seed_vars_out)}
        if cell.get("tpm"):
            seed_state_out = args.seed_root / "cellB-tpm-state"
            if seed_state_out.exists():
                shutil.rmtree(seed_state_out)
            shutil.copytree(tpm_state, seed_state_out)
            seed_note["tpmStateManifest"] = manifest(seed_state_out)
        record["seedProduced"] = seed_note
        # A seed boot establishes firmware state. It is not a measured login
        # and must never fill a matrix cell, so it stops here rather than
        # producing analyses a gate could count.
        return finish("SEEDED")

    # -------------------------------------------------- offline collection
    collection: dict = {"journalCollectorVersion": JOURNAL_COLLECTOR_VERSION}
    record["collection"] = collection
    try:
        var_path = dsq_disk.stateroot_var(overlay)
        subprocess.run(
            ["guestfish", "--ro", "-a", str(overlay), "run", ":",
             "mount-ro", root, "/", ":",
             "copy-out", f"{var_path}/log/journal", str(work)],
            check=True, capture_output=True, text=True, timeout=1800)
        coredump_ls = subprocess.run(
            ["guestfish", "--ro", "-a", str(overlay), "run", ":",
             "mount-ro", root, "/", ":",
             "ls", f"{var_path}/lib/systemd/coredump"],
            capture_output=True, text=True, timeout=900)
        collection["coredumpFiles"] = (
            coredump_ls.stdout.split() if coredump_ls.returncode == 0 else [])
    except (dsq_disk.DiskLayoutError, subprocess.SubprocessError,
            OSError) as exc:
        collection["status"] = "collection-failed"
        collection["journalExtraction"] = f"FAILED: {exc}"
        return finish("COLLECTION_FAILED")

    journal_out = work / "journal"
    try:
        journal_boots = list_boots(journal_out)
        collection["bootsInJournal"] = len(journal_boots)
        expected = len(boots)
        if len(journal_boots) < expected:
            collection["status"] = "collection-failed"
            collection["analysisError"] = (
                f"the run performed {expected} boots but the journal holds "
                f"{len(journal_boots)}; the missing one cannot be asserted "
                "about")
            return finish("COLLECTION_FAILED")
        # The last N journal boots are this run's, oldest first.
        targets = [b["boot_id"] for b in journal_boots[-expected:]]
        collection["bootIds"] = targets
        analyses = []
        for index, boot_id in enumerate(targets):
            analysis = analyze_boot(journal_out, boot_id)
            analysis["label"] = boots[index]["label"]
            analyses.append(analysis)
        record["analyses"] = analyses
        collection["excerpts"] = excerpts(journal_out, targets[0],
                                          evidence_dir / "journal")
        if len(targets) > 1:
            collection["excerptsSecondLogin"] = excerpts(
                journal_out, targets[-1], evidence_dir / "journal-login-2")
        journal_keep = trace_dir / "journal"
        if journal_keep.exists():
            shutil.rmtree(journal_keep)
        shutil.copytree(journal_out, journal_keep)
        collection["binaryJournalRetainedAt"] = str(journal_keep)
        collection["status"] = "ok"
    except (JournalError, OSError, KeyError, IndexError) as exc:
        collection["status"] = "collection-failed"
        collection["analysisError"] = str(exc)[:500]
        return finish("COLLECTION_FAILED")

    # ------------------------------------------------- filesystem evidence
    home = provenance["home"]
    try:
        record["homeAssertions"] = home_assertions.assert_home(
            overlay, root, home, login_fixture.TEST_UID, login_fixture.TEST_GID)
        record["firstRunPreferences"] = home_assertions.read_marker(
            overlay, root, home)
    except home_assertions.HomeReadError as exc:
        record["homeAssertions"] = None
        collection["homeAssertionError"] = str(exc)[:400]
        collection["status"] = "collection-failed"
        return finish("COLLECTION_FAILED")

    return finish("COLLECTED")


if __name__ == "__main__":
    raise SystemExit(main())
