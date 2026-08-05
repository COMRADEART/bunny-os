# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The durable writer: what it retries, what it refuses to retry, and what it
never leaves behind.

The store retries exactly one failure — on Windows, a rename refused because
another handle has the destination open. That is transient by construction and
it is the one this store actually meets, because the protocol serves readers
from the same files a worker writes to.

Everything else is reported immediately. Retrying a full disk or a read-only
filesystem would add a delay to an error that was correct the first time, and
would invite a reader to believe the store tried hard enough that the failure
must be real — when the opposite is true.

The failures are injected rather than provoked, so these tests mean the same
thing on Linux, where a real collision cannot be made to happen, as they do on
the host where the defect was found. The two that *can* be provoked really —
concurrent writers and a reader holding the file — are provoked.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import unittest.mock

from companion.errors import StoreError
from companion import store as store_module


def sharing_violation(code: int = 5) -> PermissionError:
    """The exception Windows raises when another handle holds the destination."""
    error = PermissionError(errno.EACCES, "the process cannot access the file")
    error.winerror = code  # type: ignore[attr-defined]
    return error


class WriterBase(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.target = self.root / "document.json"

    def temporaries(self) -> list[Path]:
        return sorted(self.root.glob("*.tmp"))

    def assertNoTemporaries(self) -> None:
        self.assertEqual(
            self.temporaries(), [],
            "a temporary file was left behind; a store that is interrupted often "
            "enough accumulates one orphan per attempt in the directory it scans",
        )


class TransientRetryTests(WriterBase):
    """The one failure that is retried."""

    def setUp(self) -> None:
        super().setUp()
        # The discriminator only retries on Windows, so the platform is
        # simulated where the test does not run on one. The code under test is
        # the same either way; what is substituted is the answer to "which
        # platform is this", which is not the thing being tested.
        self._nt = unittest.mock.patch.object(store_module.os, "name", "nt")
        self._nt.start()
        self.addCleanup(self._nt.stop)

    def test_a_reader_holding_the_destination_is_waited_out(self) -> None:
        self.target.write_text('{"generation": 0}\n', encoding="utf-8")
        real_replace = store_module.os.replace
        refusals = {"left": 3}

        def flaky(source, destination):
            if refusals["left"] > 0:
                refusals["left"] -= 1
                raise sharing_violation()
            return real_replace(source, destination)

        with unittest.mock.patch.object(store_module.os, "replace", flaky):
            store_module._atomic_write_json(self.target, {"generation": 1})

        self.assertEqual(refusals["left"], 0)
        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"generation": 1})
        self.assertNoTemporaries()

    def test_a_destination_never_released_reports_the_original_failure(self) -> None:
        """Bounded. The last refusal is what the caller is told about."""
        self.target.write_text('{"generation": 0}\n', encoding="utf-8")
        attempts = {"count": 0}

        def always(source, destination):
            attempts["count"] += 1
            raise sharing_violation()

        with unittest.mock.patch.object(store_module.os, "replace", always):
            with self.assertRaises(StoreError) as caught:
                store_module._atomic_write_json(self.target, {"generation": 1})

        self.assertEqual(attempts["count"], store_module._REPLACE_ATTEMPTS)
        self.assertIsInstance(caught.exception.__cause__, PermissionError)
        # The old contents stand. A failed write changes nothing.
        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"generation": 0})
        self.assertNoTemporaries()

    def test_a_sharing_violation_code_is_also_retried(self) -> None:
        # A destination has to exist for anything to be holding it open; the
        # writer checks, and refuses to retry a denial with nothing there.
        self.target.write_text("{}\n", encoding="utf-8")
        real_replace = store_module.os.replace
        once = {"done": False}

        def flaky(source, destination):
            if not once["done"]:
                once["done"] = True
                raise sharing_violation(32)
            return real_replace(source, destination)

        with unittest.mock.patch.object(store_module.os, "replace", flaky):
            store_module._atomic_write_json(self.target, {"ok": True})
        self.assertTrue(self.target.exists())


class PermanentFailureTests(WriterBase):
    """Everything that must be reported at once rather than retried."""

    def _assert_not_retried(self, error: OSError) -> None:
        attempts = {"count": 0}

        def failing(source, destination):
            attempts["count"] += 1
            raise error

        with unittest.mock.patch.object(store_module.os, "replace", failing):
            with self.assertRaises(StoreError):
                store_module._atomic_write_json(self.target, {"ok": True})
        self.assertEqual(
            attempts["count"], 1,
            "a permanent failure was retried; the delay is added to an error that "
            "was already correct",
        )
        self.assertNoTemporaries()

    def test_a_full_disk_is_not_retried(self) -> None:
        self._assert_not_retried(OSError(errno.ENOSPC, "no space left on device"))

    def test_a_read_only_filesystem_is_not_retried(self) -> None:
        self._assert_not_retried(OSError(errno.EROFS, "read-only file system"))

    def test_a_posix_permission_denial_is_not_retried(self) -> None:
        """On POSIX a rename over an open file succeeds, so EACCES means EACCES."""
        with unittest.mock.patch.object(store_module.os, "name", "posix"):
            self._assert_not_retried(sharing_violation())

    def test_a_windows_denial_with_no_destination_is_not_retried(self) -> None:
        """Nothing is holding a file that does not exist."""
        with unittest.mock.patch.object(store_module.os, "name", "nt"):
            self.assertFalse(self.target.exists())
            self._assert_not_retried(sharing_violation())

    def test_a_read_only_destination_is_not_retried(self) -> None:
        """Permanent: the mode does not change because we waited."""
        self.target.write_text("{}\n", encoding="utf-8")
        self.target.chmod(stat.S_IRUSR)
        self.addCleanup(self.target.chmod, stat.S_IRUSR | stat.S_IWUSR)
        with unittest.mock.patch.object(store_module.os, "name", "nt"):
            self._assert_not_retried(sharing_violation())

    def test_a_read_only_directory_fails_before_any_replacement(self) -> None:
        """The temporary cannot be created, so no rename is ever attempted.

        This is also why the retry is safe: by the time a replacement is tried,
        the directory has already accepted a file, so a refusal cannot be a
        permissions problem with the directory.
        """
        if os.name == "nt":
            self.skipTest("Windows directory ACLs do not deny a file create by mode")
        locked = self.root / "locked"
        locked.mkdir()
        target = locked / "document.json"
        locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(locked.chmod, stat.S_IRWXU)

        attempts = {"count": 0}

        def counting(source, destination):  # pragma: no cover - must not run
            attempts["count"] += 1

        with unittest.mock.patch.object(store_module.os, "replace", counting):
            with self.assertRaises((StoreError, OSError)):
                store_module._atomic_write_json(target, {"ok": True})
        self.assertEqual(attempts["count"], 0)


class InterruptionTests(WriterBase):
    """An interrupted write leaves nothing behind."""

    def test_an_interruption_during_the_backoff_cleans_up(self) -> None:
        with unittest.mock.patch.object(store_module.os, "name", "nt"):
            self.target.write_text("{}\n", encoding="utf-8")

            def refuse(source, destination):
                raise sharing_violation()

            def interrupt(_seconds):
                raise KeyboardInterrupt("the operator stopped the process")

            with unittest.mock.patch.object(store_module.os, "replace", refuse):
                with unittest.mock.patch.object(store_module.time, "sleep", interrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        store_module._atomic_write_json(self.target, {"generation": 1})

        self.assertNoTemporaries()
        # And the previous contents are intact: the replacement never happened.
        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {})


class ConcurrentWriterTests(WriterBase):
    """Two writers, one destination. Both atomic; the last one wins."""

    def test_concurrent_writers_leave_one_valid_document_and_no_temporaries(self) -> None:
        writers = 8
        ready = threading.Barrier(writers)
        failures: list[BaseException] = []

        def write(index: int) -> None:
            try:
                ready.wait(timeout=10)
                for round_number in range(5):
                    store_module._atomic_write_json(
                        self.target, {"writer": index, "round": round_number}
                    )
            except BaseException as error:  # noqa: BLE001 - collected and asserted
                failures.append(error)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(failures, [])
        # Whatever landed last is a complete document, never a half-written one.
        document = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertIn("writer", document)
        self.assertIn("round", document)
        self.assertNoTemporaries()

    def test_a_reader_sees_only_whole_documents_while_a_writer_works(self) -> None:
        """The property the atomic replacement exists for, provoked for real.

        The reader polls at 1 ms. That is deliberately faster than anything the
        product does — the vertical slice polls at 50 ms and the window at
        several hundred — and slow enough to leave the writer a gap.

        **A reader that never yields at all can starve the writer**, and this
        test found that rather than assuming it: an unbroken reopen loop on
        Windows refused every one of the writer's five attempts and the write
        failed. The bounded retry answers a reader that reads and closes, which
        is the access pattern this store has; it is not a lock, and nothing here
        claims it defeats a spin loop. The limitation is recorded in
        COMPANION_PAUSE_APPROVAL_REPORT.md rather than hidden by slowing the
        writer down until the test passes.
        """
        store_module._atomic_write_json(self.target, {"generation": 0})
        stop = threading.Event()
        seen: list[int] = []
        failures: list[BaseException] = []

        def read() -> None:
            try:
                while not stop.is_set():
                    text = store_module._read_text_stable(self.target)
                    seen.append(json.loads(text)["generation"])
                    stop.wait(0.001)
            except BaseException as error:  # noqa: BLE001
                failures.append(error)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            for generation in range(1, 60):
                store_module._atomic_write_json(self.target, {"generation": generation})
        finally:
            stop.set()
            reader.join(timeout=10)

        self.assertEqual(failures, [], "a reader saw something that was not a document")
        self.assertTrue(seen)
        self.assertNoTemporaries()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
