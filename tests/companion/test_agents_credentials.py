# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Credentials: the value exists for one call and refuses every other channel.

The §5 tests here are absence proofs, which is why so many of them assert what
a string does *not* contain: a :class:`Secret` that leaked through ``repr``,
``to_json``, a dictionary key, a status record or a refusal message would pass
every presence-shaped test and still be the defect. The file-source tests
write a known sentinel into each refused file precisely so the refusal can be
searched for it. POSIX-only markers cover the checks that are meaningless on
NTFS — mode bits, symlinks, ownership — and those tests run on the Linux gate
host; everything else runs everywhere.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from companion.agents.credentials import (
    MAX_SECRET_BYTES,
    CredentialReference,
    Secret,
    credential_status,
    resolve_credential,
)
from companion.agents.errors import AgentSchemaError, CredentialRefused


class SecretRefusesToBeWrittenDown(unittest.TestCase):
    def test_repr_and_str_are_the_word_secret(self) -> None:
        secret = Secret("hunter2-but-longer")
        self.assertEqual(repr(secret), "<secret>")
        self.assertEqual(str(secret), "<secret>")

    def test_serialization_is_a_refusal_not_a_redaction(self) -> None:
        with self.assertRaises(CredentialRefused):
            Secret("hunter2-but-longer").to_json()

    def test_a_secret_is_not_hashable_so_it_cannot_be_a_dictionary_key(self) -> None:
        with self.assertRaises(TypeError):
            hash(Secret("hunter2-but-longer"))

    def test_reveal_is_the_one_sanctioned_read(self) -> None:
        self.assertEqual(Secret("hunter2-but-longer").reveal(), "hunter2-but-longer")

    def test_an_empty_value_is_not_a_secret(self) -> None:
        with self.assertRaises(CredentialRefused):
            Secret("")

    def test_an_oversized_value_is_not_a_credential(self) -> None:
        with self.assertRaises(CredentialRefused):
            Secret("a" * (MAX_SECRET_BYTES + 1))


class ReferenceCoherence(unittest.TestCase):
    """A reference names where a credential would come from — coherently or not at all."""

    def test_kind_none_with_a_locator_is_a_contradiction(self) -> None:
        with self.assertRaises(AgentSchemaError):
            CredentialReference(kind="none", locator="SOME_VARIABLE")

    def test_every_other_kind_requires_a_locator(self) -> None:
        with self.assertRaises(AgentSchemaError):
            CredentialReference(kind="environment", locator="")

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            CredentialReference(kind="keychain", locator="something")


class EnvironmentSource(unittest.TestCase):
    def _set_environment(self, name: str, value: str) -> None:
        previous = os.environ.get(name)
        os.environ[name] = value
        if previous is None:
            self.addCleanup(os.environ.pop, name, None)
        else:
            self.addCleanup(os.environ.__setitem__, name, previous)

    def test_an_absent_variable_is_a_refusal_not_an_empty_secret(self) -> None:
        name = "BUNNY_TEST_AGENTS_ABSENT_KEY"
        self.assertNotIn(name, os.environ)
        with self.assertRaises(CredentialRefused):
            resolve_credential(CredentialReference(kind="environment", locator=name))

    def test_a_present_variable_resolves_to_its_stripped_value(self) -> None:
        name = "BUNNY_TEST_AGENTS_PRESENT_KEY"
        self._set_environment(name, "  env-secret-value \n")
        secret = resolve_credential(CredentialReference(kind="environment", locator=name))
        self.assertEqual(secret.reveal(), "env-secret-value")

    def test_a_name_that_is_not_a_plain_identifier_is_refused(self) -> None:
        with self.assertRaises(CredentialRefused):
            resolve_credential(CredentialReference(kind="environment", locator="PATH;rm"))


class FileSource(unittest.TestCase):
    """The four §5 file rejections, each with its own message and no value in any."""

    SENTINEL = "sentinel-credential-3f9a17"

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.approved = Path(self._directory.name) / "credentials"
        self.approved.mkdir()

    def _write(self, name: str, content: str, *, mode: int = 0o600,
               directory: Path | None = None) -> Path:
        path = (directory if directory is not None else self.approved) / name
        path.write_text(content, encoding="utf-8")
        os.chmod(path, mode)
        return path

    def _resolve(self, locator: str) -> Secret:
        return resolve_credential(
            CredentialReference(kind="credential-file", locator=locator),
            approved_directories=(self.approved,),
        )

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_a_private_file_in_an_approved_directory_resolves(self) -> None:
        path = self._write("key", "file-secret-value\n", mode=0o600)
        self.assertEqual(self._resolve(str(path)).reveal(), "file-secret-value")

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_a_group_or_world_readable_file_is_refused(self) -> None:
        path = self._write("key", self.SENTINEL, mode=0o644)
        with self.assertRaises(CredentialRefused) as caught:
            self._resolve(str(path))
        self.assertIn("group- or world", str(caught.exception))
        self.assertNotIn(self.SENTINEL, str(caught.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_a_symlink_is_refused_before_anything_follows_it(self) -> None:
        target = self._write("real", self.SENTINEL, mode=0o600)
        link = self.approved / "link"
        os.symlink(target, link)
        with self.assertRaises(CredentialRefused) as caught:
            self._resolve(str(link))
        self.assertIn("symlink", str(caught.exception))
        self.assertNotIn(self.SENTINEL, str(caught.exception))

    def test_a_file_outside_the_approved_directories_is_refused(self) -> None:
        outside = Path(self._directory.name) / "elsewhere"
        outside.mkdir()
        path = self._write("key", self.SENTINEL, directory=outside)
        with self.assertRaises(CredentialRefused) as caught:
            self._resolve(str(path))
        self.assertIn("approved", str(caught.exception))
        self.assertNotIn(self.SENTINEL, str(caught.exception))

    def test_a_relative_path_is_refused(self) -> None:
        with self.assertRaises(CredentialRefused) as caught:
            self._resolve("relative/key")
        self.assertIn("absolute", str(caught.exception))

    def test_an_empty_file_is_refused(self) -> None:
        path = self._write("empty", "")
        with self.assertRaises(CredentialRefused) as caught:
            self._resolve(str(path))
        self.assertIn("empty", str(caught.exception))

    def test_an_oversized_file_is_refused_and_its_content_stays_out_of_the_message(self) -> None:
        filler = self.SENTINEL * (MAX_SECRET_BYTES // len(self.SENTINEL) + 2)
        path = self._write("big", filler)
        with self.assertRaises(CredentialRefused) as caught:
            self._resolve(str(path))
        self.assertIn("exceeds", str(caught.exception))
        self.assertNotIn(self.SENTINEL, str(caught.exception))

    def test_no_approved_directories_means_no_file_credentials_at_all(self) -> None:
        path = self._write("key", "irrelevant")
        with self.assertRaises(CredentialRefused) as caught:
            resolve_credential(
                CredentialReference(kind="credential-file", locator=str(path)),
                approved_directories=(),
            )
        self.assertIn("no approved", str(caught.exception))


class StatusNeverCarriesTheValue(unittest.TestCase):
    """Presence is the report; the value has no field to travel in."""

    def test_a_resolvable_credential_reports_presence_and_nothing_else(self) -> None:
        name = "BUNNY_TEST_AGENTS_STATUS_KEY"
        os.environ[name] = "status-secret-71bc"
        self.addCleanup(os.environ.pop, name, None)
        status = credential_status(CredentialReference(kind="environment", locator=name))
        self.assertTrue(status.present)
        self.assertNotIn("status-secret-71bc", json.dumps(status.to_json()))

    def test_kind_none_is_present_by_vacuity(self) -> None:
        status = credential_status(CredentialReference())
        self.assertTrue(status.present)
        self.assertEqual(status.kind, "none")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
