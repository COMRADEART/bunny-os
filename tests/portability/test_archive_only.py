"""An archive-only build must never be accepted as a release candidate.

`BUNNY_ARCHIVE_ONLY=1` stops after the normalised OCI archive so a hosted Ubuntu
runner can be a real second builder — `image-builder` is Fedora-only. The mode is
a genuine capability reduction whose danger is that its artifact looks ordinary:
same name, same digest discipline, same provenance shape, no disk image. Nothing
was installed, nothing booted, no recovery media was written, no hardware was
exercised.

So the mode is declared in the artifact's own provenance and refused by both
protected gates, rather than being inferred later from which files are missing.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.buildmode import (  # noqa: E402
    ARCHIVE_ONLY_CANNOT_QUALIFY,
    BuildModeError,
    evaluate_build_mode,
    require_candidate_capable,
)

WRITER = ROOT / "build/scripts/write-build-provenance.py"


def provenance(*, archiveOnly: bool, disks: list[str] | None = None,
               declare: bool = True, recordedDisks: list[str] | None = None) -> dict:
    disks = disks if disks is not None else ([] if archiveOnly else ["bunny-os.qcow2"])
    artifacts = [{"path": "bunny-os.oci.tar", "size": 1, "sha256": "a" * 64}]
    artifacts += [{"path": name, "size": 1, "sha256": "b" * 64} for name in disks]
    document = {
        "schemaVersion": 1,
        "profile": "beta",
        "sourceCommit": "a" * 40,
        "artifacts": artifacts,
        "diskImages": recordedDisks if recordedDisks is not None else disks,
    }
    if declare:
        document["archiveOnly"] = archiveOnly
    return document


class BuildModeEvaluationTests(unittest.TestCase):
    def test_an_archive_only_build_is_not_candidate_capable(self) -> None:
        capability = evaluate_build_mode(provenance(archiveOnly=True))
        self.assertTrue(capability.archiveOnly)
        self.assertEqual(capability.diskImages, ())
        self.assertTrue(capability.hasOciArchive)
        self.assertFalse(capability.candidateCapable)

    def test_a_full_build_is_candidate_capable(self) -> None:
        capability = evaluate_build_mode(provenance(archiveOnly=False))
        self.assertFalse(capability.archiveOnly)
        self.assertTrue(capability.candidateCapable)

    def test_an_undeclared_build_mode_is_unknown_not_full(self) -> None:
        # Failing open here would let any pre-existing record pass as a full
        # build, which is the inference this module exists to remove.
        capability = evaluate_build_mode(provenance(archiveOnly=False, declare=False))
        self.assertFalse(capability.declared)
        self.assertFalse(capability.candidateCapable)
        self.assertTrue(any("build mode is unknown" in r for r in capability.reasons))

    def test_a_record_that_contradicts_itself_is_refused(self) -> None:
        capability = evaluate_build_mode(
            provenance(archiveOnly=True, disks=["bunny-os.qcow2"])
        )
        self.assertFalse(capability.candidateCapable)
        self.assertTrue(any("claims archiveOnly but carries disk images" in r
                            for r in capability.reasons))

    def test_a_disk_image_list_disagreeing_with_the_artifacts_is_refused(self) -> None:
        capability = evaluate_build_mode(
            provenance(archiveOnly=False, disks=["bunny-os.qcow2"], recordedDisks=[])
        )
        self.assertFalse(capability.candidateCapable)
        self.assertTrue(any("disagrees with itself" in r for r in capability.reasons))

    def test_a_full_build_with_no_disk_image_is_refused(self) -> None:
        capability = evaluate_build_mode(provenance(archiveOnly=False, disks=[]))
        self.assertFalse(capability.candidateCapable)


class GatesRefuseArchiveOnlyTests(unittest.TestCase):
    def test_the_candidate_gate_refuses_and_says_what_was_not_done(self) -> None:
        with self.assertRaises(BuildModeError) as caught:
            require_candidate_capable(provenance(archiveOnly=True), gate="qualification-candidate")
        message = str(caught.exception)
        self.assertIn("archive-only build", message)
        self.assertIn("nothing booted", message)
        for claim in ("installation", "recovery-media", "hardware"):
            self.assertIn(claim, message)

    def test_the_stable_gate_refuses(self) -> None:
        with self.assertRaises(BuildModeError):
            require_candidate_capable(provenance(archiveOnly=True), gate="stable-release")

    def test_the_refusal_enumerates_every_unqualifiable_claim(self) -> None:
        self.assertIn("stable-artifact", ARCHIVE_ONLY_CANNOT_QUALIFY)
        self.assertIn("recovery-media", ARCHIVE_ONLY_CANNOT_QUALIFY)
        self.assertIn("hardware", ARCHIVE_ONLY_CANNOT_QUALIFY)

    def test_a_full_build_is_not_refused(self) -> None:
        capability = require_candidate_capable(provenance(archiveOnly=False))
        self.assertTrue(capability.candidateCapable)


class LiveGateRefusalTests(unittest.TestCase):
    """The real gate command, against a real archive-only provenance on disk."""

    def _gate(self, kind: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "scripts/release.py", "gate", "--kind", kind],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_both_protected_gates_refuse_an_archive_only_artifact_on_disk(self) -> None:
        target = ROOT / "build/out/archive-only-probe"
        target.mkdir(parents=True, exist_ok=True)
        record = target / "provenance.json"
        record.write_text(
            json.dumps(provenance(archiveOnly=True), indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        try:
            for kind in ("qualification-candidate", "stable-release"):
                with self.subTest(gate=kind):
                    result = self._gate(kind)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("archive-only build", result.stdout)
        finally:
            record.unlink(missing_ok=True)
            target.rmdir()

    def test_the_gates_still_refuse_for_their_own_reasons_without_any_artifact(self) -> None:
        # Removing the archive-only artifact must not turn a gate green: the
        # build-mode check is an additional refusal, not the only one.
        for kind in ("qualification-candidate", "stable-release"):
            with self.subTest(gate=kind):
                self.assertEqual(self._gate(kind).returncode, 2)


class ProvenanceWriterTests(unittest.TestCase):
    """The writer must refuse to record a mode the artifacts contradict."""

    def _write(self, *, archive_only: bool, files: dict[str, bytes]) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for name, payload in files.items():
                (output / name).write_bytes(payload)
            command = [
                sys.executable, str(WRITER),
                "--profile", "beta",
                "--output", str(output),
                "--source-commit", "a" * 40,
                "--source-date-epoch", "1700000000",
                "--base-image", "quay.io/fedora/fedora-bootc:44@sha256:" + "f" * 64,
                "--image-reference", "localhost/bunny-os-beta:abc",
            ]
            if archive_only:
                command.append("--archive-only")
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                result.stdout = (output / "provenance.json").read_text(encoding="utf-8")
            return result

    def test_an_archive_only_build_records_archive_only_true(self) -> None:
        result = self._write(archive_only=True, files={"bunny-os.oci.tar": b"x"})
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertIs(document["archiveOnly"], True)
        self.assertEqual(document["diskImages"], [])
        self.assertIn("No qcow2", document["buildModeNote"])

    def test_a_full_build_records_archive_only_false(self) -> None:
        result = self._write(
            archive_only=False,
            files={"bunny-os.oci.tar": b"x", "bunny-os.qcow2": b"y"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertIs(document["archiveOnly"], False)
        self.assertEqual(document["diskImages"], ["bunny-os.qcow2"])

    def test_archive_only_with_a_disk_image_present_is_refused(self) -> None:
        # The mode did not take effect; recording it would make the record false.
        result = self._write(
            archive_only=True,
            files={"bunny-os.oci.tar": b"x", "bunny-os.qcow2": b"y"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("produced disk images", result.stderr)

    def test_archive_only_with_no_archive_is_refused(self) -> None:
        result = self._write(archive_only=True, files={"oci-build.log": b"x"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no OCI archive", result.stderr)

    def test_a_full_build_with_no_disk_image_is_still_refused(self) -> None:
        result = self._write(archive_only=False, files={"bunny-os.oci.tar": b"x"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no recognized disk artifact", result.stderr)


class BuildScriptWiringTests(unittest.TestCase):
    def test_the_build_script_passes_the_flag_when_the_mode_is_set(self) -> None:
        source = (ROOT / "build/scripts/build-image.sh").read_text(encoding="utf-8")
        self.assertIn('if [[ "${archive_only}" == "1" ]]; then', source)
        self.assertIn("provenance_arguments+=(--archive-only)", source)

    def test_the_build_script_skips_image_builder_in_archive_only_mode(self) -> None:
        source = (ROOT / "build/scripts/build-image.sh").read_text(encoding="utf-8")
        self.assertIn("skipped image-builder; no qcow2 or raw image produced", source)

    def test_image_builder_is_not_required_in_archive_only_mode(self) -> None:
        source = (ROOT / "build/scripts/build-image.sh").read_text(encoding="utf-8")
        self.assertIn('if [[ "${archive_only}" != "1" ]]; then', source)
        self.assertIn("required_commands+=(image-builder)", source)

    def test_the_hosted_workflow_sets_archive_only(self) -> None:
        workflow = (ROOT / ".github/workflows/independent-builder.yml").read_text(encoding="utf-8")
        self.assertIn('BUNNY_ARCHIVE_ONLY: "1"', workflow)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
