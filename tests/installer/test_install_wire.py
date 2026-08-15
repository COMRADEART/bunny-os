# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The wire from a confirmed plan to a rendered kickstart, over a real socket.

Journey A run 10 walked all fifteen setup stages and ended at "This installer
cannot write to a disk": the surface, the client, the server, the service and
the adapter each existed, and the links between them — the ``submit`` callable,
the descriptor-delivered secrets, the per-installation adapter completion —
did not. These tests run the completed chain end to end: a real AF_UNIX
socket, the real client sending secret material as a memfd over ``SCM_RIGHTS``,
the real service resolving the plan's references, and the recording executor
capturing the kickstart that Anaconda would have been given.

Linux-only: AF_UNIX, memfd and SO_PEERCRED do not exist on Windows, and the
password hash needs libxcrypt.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.storage.models import DiskInfo  # noqa: E402

if not hasattr(os, "memfd_create"):
    raise unittest.SkipTest("the secret channel needs memfd_create; not this platform")

from installer.backend.anaconda import AnacondaAdapter, RecordingExecutor  # noqa: E402
from installer.backend.server import ProtocolServer  # noqa: E402
from installer.backend.service import InstallerService  # noqa: E402
from installer.frontend.client import BackendClient, InstallerRefused  # noqa: E402
from installer.storage.planning import automatic_plan  # noqa: E402
from installer.storage.safety import confirmation_phrase  # noqa: E402
import socket as socket_module  # noqa: E402

TARGET = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05", devicePath="/dev/vda", sizeBytes=80 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="QEMU HARDDISK", rotational=False, transport="virtio",
)


class InstallWireTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="bunny-install-wire-")
        self.addCleanup(self.directory.cleanup)
        self.executor = RecordingExecutor()
        # The same shape the backend binary builds: an adapter constructed
        # empty, completed per-installation by the service.
        adapter = AnacondaAdapter(
            executor=self.executor, choices={}, password_hash="",
            runtime_directory=Path(self.directory.name) / "runtime")
        # Kickstart rendering refuses to run without the medium's own payload
        # directive, so the test supplies a medium kickstart the way the ISO
        # would.
        medium = Path(self.directory.name) / "medium.ks"
        medium.write_text(
            "ostreecontainer --url=/run/install/repo/container --transport=oci\n",
            encoding="utf-8")
        adapter.medium_paths = (medium,)

        self.service = InstallerService(
            live_uid=os.getuid(), probe=lambda: [TARGET], production_adapter=adapter)
        self.token = self.service.issue_session_token(peer_uid=0)
        self.socket_path = Path(self.directory.name) / "backend.sock"
        self.server = ProtocolServer(self.service, path=self.socket_path,
                                     live_uid=os.getuid())
        self.server.open()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.close)

    def client(self) -> BackendClient:
        connection = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
        connection.settimeout(30)
        connection.connect(str(self.socket_path))
        session = BackendClient(connection, self.token)
        self.addCleanup(session.close)
        return session

    def plan_for(self, session: BackendClient, *, encryption: bool,
                 password_ref: str) -> dict:
        plan = automatic_plan(TARGET, mode="erase_disk", encryption=encryption)
        plan.pop("operationsAreReversibleAfterWrite", None)
        plan.pop("warnings", None)
        plan["installationId"] = session.installation_id
        plan["user"] = {"username": "alex", "displayName": "Alex",
                        "passwordSecretRef": password_ref,
                        "administrator": True, "autologin": False, "groups": []}
        plan["locale"] = {"language": "en-GB", "keyboardLayout": "gb",
                          "timezone": "Europe/London"}
        plan["network"] = {}
        plan["recovery"] = {}
        plan["applicationProfile"] = {}
        return plan

    def test_the_whole_wire_installs_and_the_kickstart_carries_the_choices(self) -> None:
        session = self.client()
        session.initialize()
        disks = session.probe()["disks"]
        self.assertEqual([item["devicePath"] for item in disks], ["/dev/vda"])

        password_ref = "installer-secret:" + "a" * 24
        passphrase_ref = "installer-secret:" + "b" * 24
        plan = self.plan_for(session, encryption=True, password_ref=password_ref)
        outcome = session.validate(plan)
        self.assertTrue(outcome.get("valid"), outcome)

        result = session.start(
            acknowledgement=confirmation_phrase(TARGET),
            second_confirmation=True,
            recovery_key_confirmed=True,
            passphrase_secret_ref=passphrase_ref,
            secret_values={password_ref: "a-real-password",
                           passphrase_ref: "bunny-disk-passphrase"},
        )
        self.assertEqual(result.get("status"), "complete", result)

        self.assertEqual(len(self.executor.kickstarts), 1)
        document = self.executor.kickstarts[0]
        self.assertIn("user --name=alex", document)
        self.assertIn("--iscrypted", document)
        self.assertNotIn("a-real-password", document)
        self.assertIn("--luks-version=luks2", document)
        self.assertIn("bunny-disk-passphrase", document)
        self.assertIn("ostreecontainer", document)
        verified = session.call("installer.install.verify")
        self.assertTrue(verified.get("verified"), verified)

    def test_a_start_without_the_secret_material_is_refused_before_any_write(self) -> None:
        session = self.client()
        session.initialize()
        session.probe()
        plan = self.plan_for(session, encryption=False,
                             password_ref="installer-secret:" + "c" * 24)
        self.assertTrue(session.validate(plan).get("valid"))
        with self.assertRaises(InstallerRefused) as refusal:
            session.start(acknowledgement=confirmation_phrase(TARGET),
                          second_confirmation=True, recovery_key_confirmed=False)
        self.assertIn("protected channel", str(refusal.exception))
        self.assertEqual(self.executor.kickstarts, [])


if __name__ == "__main__":
    unittest.main()
