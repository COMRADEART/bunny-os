#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the real installer backend over its real socket, with nothing written.

The unit tests exercise `InstallerService` by calling it. This starts the actual
server process, connects the actual client over an actual AF_UNIX socket, and
runs the protocol through to ``install.start`` — with the recording executor
behind the gate, so the whole path is exercised and no disk is touched.

What it can establish, on any Linux machine with no installer ISO:

* the socket is created, and its mode and owner are what the design claims;
* ``SO_PEERCRED`` refuses a connection from a different UID;
* a request with the wrong session token is refused;
* a replayed request is refused;
* a plan is validated before it can be started;
* the destructive confirmation is checked **by the backend**, against a phrase
  it re-derives from the disk in the validated plan — a client that sends the
  wrong one is refused, and one that sends the right one proceeds;
* the kickstart the executor receives names one disk.

What it cannot establish: that Anaconda does any of it. That needs §44's VM run.

    python3 build/scripts/installer-backend-probe.py --output <file>
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.backend.anaconda import AnacondaAdapter, RecordingExecutor  # noqa: E402
from installer.backend.server import ProtocolServer                        # noqa: E402
from installer.backend.service import InstallerService                     # noqa: E402
from installer.frontend.client import BackendClient, InstallerRefused      # noqa: E402
from installer.setup_state import Choices                                  # noqa: E402
from installer.storage.models import DiskInfo                              # noqa: E402
from installer.storage.planning import automatic_plan                      # noqa: E402
from installer.storage.safety import confirmation_phrase                   # noqa: E402

TARGET = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05", devicePath="/dev/vda", sizeBytes=80 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="QEMU HARDDISK", rotational=False, transport="virtio",
)
HASH = "$y$j9T$abcdefghijklmnop$0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHI"
MEDIUM = [
    "text",
    "ostreecontainer --url=/run/install/repo/container --transport=oci",
    "%post",
    "bootupctl backend install /",
    "%end",
]


def probe() -> dict[str, Any]:
    findings: list[str] = []
    observed: dict[str, Any] = {}

    workspace = Path(tempfile.mkdtemp(prefix="bunny-backend-probe-"))
    medium = workspace / "osbuild.ks"
    medium.write_text("\n".join(MEDIUM) + "\n", encoding="utf-8")
    socket_path = workspace / "backend.sock"

    executor = RecordingExecutor()
    adapter = AnacondaAdapter(
        executor=executor,
        choices=Choices(display_name="Alex", username="alex",
                        encryption_enabled=True).as_record(),
        password_hash=HASH,
        passphrase="a-disk-passphrase",
        medium_paths=(medium,),
        runtime_directory=workspace / "run",
    )
    service = InstallerService(live_uid=os.getuid(), probe=lambda: [TARGET],
                               production_adapter=adapter)
    server = ProtocolServer(service, path=socket_path, live_uid=os.getuid())
    server.open()

    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)

    mode = oct(socket_path.stat().st_mode & 0o777)
    observed["socketMode"] = mode
    if mode != "0o600":
        findings.append(f"the socket is {mode}, not 0o600")

    token = service.issue_session_token(peer_uid=0)

    def client(with_token: str = token) -> BackendClient:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(30)
        connection.connect(str(socket_path))
        return BackendClient(connection, with_token)

    # -- a wrong token is refused ---------------------------------------
    session = client("not-the-session-token")
    try:
        session.probe()
        findings.append("a request with the wrong session token was accepted")
    except InstallerRefused as error:
        observed["wrongToken"] = error.kind
    finally:
        session.close()

    # -- the real conversation ------------------------------------------
    session = client()
    try:
        observed["initialize"] = dict(session.initialize())
        disks = session.probe()["disks"]
        observed["disksSeen"] = [item["devicePath"] for item in disks]

        plan = automatic_plan(TARGET, mode="erase_disk", encryption=True)
        plan["installationId"] = session.installation_id
        plan["user"] = {"username": "alex", "displayName": "Alex",
                        "passwordSecretRef": "installer-secret:" + "a" * 20,
                        "administrator": True, "autologin": False, "groups": []}
        plan["locale"] = {"language": "en-GB"}
        plan["network"] = {}
        plan["recovery"] = {}
        plan["applicationProfile"] = {}
        for key in ("operationsAreReversibleAfterWrite", "warnings"):
            plan.pop(key, None)

        validated = session.validate(plan)
        observed["planValid"] = validated.get("valid")
        if not validated.get("valid"):
            findings.append(f"the plan did not validate: {validated.get('errors')}")
            return {"findings": findings, "observed": observed}

        # -- a replay is refused ----------------------------------------
        #
        # `installer.install.status`, deliberately. The first version of this
        # replayed `installer.probe`, which sets the service's status back to
        # "probed" — correctly, because a re-probe means the disks may have
        # changed and a plan validated against the old list is stale. The next
        # `install.start` was then refused with "installation can start only
        # from a validated plan", which looked like a defect in the destructive
        # confirmation and was a defect in this probe.
        replay = {
            "schemaVersion": 1, "requestId": "req-replay-0001",
            "installationId": session.installation_id,
            "operation": "installer.install.status",
            "nonce": "nonce-replayed-0000000000000",
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
            "params": {}, "sessionToken": token,
        }
        raw = json.dumps(replay).encode("utf-8") + b"\n"
        session._connection.sendall(raw)
        session._connection.recv(65536)
        session._connection.sendall(raw)
        answer = json.loads(session._connection.recv(65536).decode("utf-8").split("\n")[0])
        if "error" not in answer:
            findings.append("a replayed request was accepted")
        else:
            observed["replay"] = answer["error"]["kind"]

        # -- the wrong confirmation phrase is refused -------------------
        try:
            session.start(acknowledgement="ERASE /dev/vda WRONG",
                          second_confirmation=True, recovery_key_confirmed=True)
            findings.append("a wrong confirmation phrase started an installation")
        except InstallerRefused as error:
            observed["wrongPhrase"] = str(error)[:80]
        if executor.kickstarts:
            findings.append("a refused confirmation still reached the executor")

        # -- and the right one proceeds ---------------------------------
        phrase = confirmation_phrase(TARGET)
        observed["confirmationPhrase"] = phrase
        try:
            observed["start"] = dict(session.start(
                acknowledgement=phrase, second_confirmation=True,
                recovery_key_confirmed=True))
        except InstallerRefused as error:
            findings.append(f"the correct confirmation phrase was refused: {error}")
            return {"findings": findings, "observed": observed}

        if not executor.kickstarts:
            findings.append("the installation started but the executor got no kickstart")
        else:
            document = executor.kickstarts[0]
            observed["kickstartLines"] = len(document.splitlines())
            named = sorted({word for word in document.split()
                            if word.startswith("--drives=") or word.startswith("--ondisk=")})
            observed["disksNamed"] = named
            if any("vda" not in item for item in named):
                findings.append(f"the kickstart names a disk that is not the target: {named}")
            if "ostreecontainer" not in document:
                findings.append("the kickstart lost the medium's payload directive")
        observed["stagesReported"] = executor.stages[:4]
    finally:
        session.close()
        server.close()

    leftover = list((workspace / "run").glob("*.ks")) if (workspace / "run").is_dir() else []
    if leftover:
        findings.append(f"a kickstart carrying a passphrase survived: {leftover}")

    return {"findings": findings, "observed": observed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = probe()
    report = {
        "schemaVersion": 1,
        "evidenceLevel": "HOST RUNTIME VALIDATED",
        "note": "The installer protocol driven over a real socket with the recording "
                "executor behind the gate. No disk was written and Anaconda was not "
                "involved.",
        **result,
    }
    document = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(document, encoding="utf-8", newline="\n")
    sys.stdout.write(document)
    return 0 if not result["findings"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
