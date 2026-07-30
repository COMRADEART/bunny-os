from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/scripts/normalise-oci-archive.sh"


class ArchiveNormalisationTests(unittest.TestCase):
    """Source-level guards for the OCI archive normaliser.

    The behaviour itself is verified on the Fedora builder, where two
    previously divergent archives converged to one digest and skopeo, syft and
    grype all still read the result. These tests keep the specific mistakes
    that were made during that work from coming back.
    """

    def setUp(self) -> None:
        self.source = SCRIPT.read_text(encoding="utf-8")

    def test_the_script_exists_and_is_wired_into_the_build(self) -> None:
        self.assertTrue(SCRIPT.is_file())
        build = (ROOT / "build/scripts/build-image.sh").read_text(encoding="utf-8")
        self.assertIn("normalise-oci-archive.sh", build)

    def test_it_never_archives_a_bare_dot(self) -> None:
        # Archiving "." emits a leading "./" on every entry and syft rejects
        # that outright: "potential path traversal attack with entry: ./".
        # podman save does not emit it, so normalisation must not introduce it.
        self.assertNotIn("--numeric-owner \\\n    .\n", self.source)
        self.assertIn("mapfile -t entries", self.source)
        self.assertIn('"${entries[@]}"', self.source)

    def test_every_source_of_nondeterminism_is_pinned(self) -> None:
        for flag in ("--sort=name", "--mtime=", "--owner=0", "--group=0", "--numeric-owner"):
            with self.subTest(flag=flag):
                self.assertIn(flag, self.source)

    def test_varying_pax_timestamps_are_dropped(self) -> None:
        # GNU tar emits atime and ctime as extended headers, which vary between
        # runs even when mtime is pinned.
        self.assertIn("delete=atime", self.source)
        self.assertIn("delete=ctime", self.source)

    def test_the_epoch_is_validated_rather_than_trusted(self) -> None:
        # An empty epoch silently produced an unnormalised archive during
        # development, which looked like the fix not working.
        self.assertIn("SOURCE_DATE_EPOCH is required", self.source)
        self.assertIn("[0-9]+$", self.source)

    def test_an_empty_unpack_is_refused(self) -> None:
        self.assertIn("archive unpacked to nothing", self.source)

    def test_the_working_directory_is_always_cleaned_up(self) -> None:
        self.assertIn("trap 'rm -rf", self.source)

    def test_the_reason_for_the_script_is_recorded(self) -> None:
        # The measured cause, so nobody removes this as apparently redundant.
        self.assertIn("wall-clock time", self.source)


if __name__ == "__main__":
    unittest.main()
