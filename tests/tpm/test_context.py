# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The TPM context resolver's own refusals.

The resolver is the layer that catches frauds 11 and 12 on the machine that
runs the VMs: a changed OVMF image or swtpm binary under an unchanged
authority record. Those need real files, so the tests build them.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification/tpm/scripts"))

from tpm_context import ContextError, resolve_context, sha256_file  # noqa: E402


def write_context(root: Path, **overrides: object) -> Path:
    tpm = root / "qualification/tpm"
    tpm.mkdir(parents=True, exist_ok=True)
    document = {
        "schemaVersion": 1, "scenarioVersion": "tpmq-1",
        "sourceCommit": "b" * 40,
        "sourceArchiveDigest": "1" * 64,
        "installationArtifactDigest": "2" * 64,
        "qemuDigest": "3" * 64,
        "qemuPath": str(root / "no-such-qemu"),
        "ovmfCodeDigest": "4" * 64,
        "ovmfCodePath": str(root / "no-such-code"),
        "ovmfVarsTemplateDigest": "5" * 64,
        "ovmfVarsTemplatePath": str(root / "no-such-vars"),
        "swtpmDigest": "6" * 64,
        "swtpmPath": str(root / "no-such-swtpm"),
        "swtpmVersion": "0.10.1", "libtpmsVersion": "0.10.2",
        "machineType": "pc-q35-10.2", "cpuMode": "host",
    }
    document.update(overrides)
    path = tpm / "evidence-context.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class Resolver(unittest.TestCase):
    def test_missing_context_is_an_error_not_a_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContextError):
                resolve_context(Path(tmp))

    def test_absent_system_subjects_resolve(self) -> None:
        # The context must be readable on a machine that does not run the
        # VMs; absent subjects are skipped, not defaulted.
        with tempfile.TemporaryDirectory() as tmp:
            write_context(Path(tmp))
            context = resolve_context(Path(tmp))
            self.assertEqual(context.machineType, "pc-q35-10.2")

    def test_11_changed_ovmf_code_is_refused_at_resolve_time(self) -> None:
        # The fraud: the firmware package updated, the context did not.
        # A present subject whose digest differs from the claim is an error,
        # not a warning.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = root / "OVMF_CODE.qcow2"
            code.write_bytes(b"not the pinned firmware")
            write_context(root, ovmfCodePath=str(code))
            with self.assertRaises(ContextError) as caught:
                resolve_context(root)
            self.assertIn("toolchain changed", str(caught.exception))

    def test_12_matching_subject_resolves(self) -> None:
        # The complement that proves test_11 is attributable: the same tree
        # with the digest agreeing resolves cleanly.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = root / "OVMF_CODE.qcow2"
            code.write_bytes(b"pinned firmware bytes")
            write_context(root, ovmfCodePath=str(code),
                          ovmfCodeDigest=sha256_file(code))
            context = resolve_context(root)
            self.assertEqual(context.ovmfCodeDigest, sha256_file(code))

    def test_a_short_digest_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_context(Path(tmp), qemuDigest="abc123")
            with self.assertRaises(ContextError):
                resolve_context(Path(tmp))

    def test_a_missing_scenario_version_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_context(Path(tmp), scenarioVersion="")
            with self.assertRaises(ContextError):
                resolve_context(Path(tmp))


if __name__ == "__main__":
    unittest.main()
