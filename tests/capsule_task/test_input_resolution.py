# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one place a request's words become a path.

``CompanionGateway._capsule_inputs_for_request`` is the only code in the product
that turns what somebody typed into a file an application will be handed. Every
other layer carries a width, an operation id and an approval — a plan has no
field for a file, and an executor has no channel to one.

That makes this function the whole of the attack surface for "which file did
Bunny open", so the tests are about what it *refuses*:

* a name with a separator, a traversal or a tilde — refused upstream by the
  recogniser, and refused again here if one ever arrives;
* a symlink pointing out of Pictures — resolved, then rejected on its real
  parent, because the check that matters is where the bytes are;
* a file that is not an image, or not a regular file at all;
* a request that is not an application task.

And one thing it must *do*: with no name at all, resolve "this" to the most
recently modified image, which is what a person means when they have just been
looking at one.

The function is called on the class rather than through a live service. It reads
one attribute — the capsule support, for its ``bind_inputs`` — and otherwise
depends only on the environment, so a fixture that stood up a whole service
would be testing the service.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest


class _Support:
    """Just enough to be the thing that has ``bind_inputs``."""

    def bind_inputs(self, task_id, paths):  # noqa: ANN001, D102
        return None


class InputResolution(unittest.TestCase):
    def setUp(self) -> None:
        from companion.service import CompanionGateway

        self.resolve = CompanionGateway._capsule_inputs_for_request
        self.gateway = type("G", (), {"capsules": _Support()})()

        self.home = Path(tempfile.mkdtemp())
        self.pictures = self.home / "Pictures"
        self.pictures.mkdir()
        self.outside = self.home / "Secrets"
        self.outside.mkdir()
        self._previous = os.environ.get("XDG_PICTURES_DIR")
        os.environ["XDG_PICTURES_DIR"] = str(self.pictures)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._previous is None:
            os.environ.pop("XDG_PICTURES_DIR", None)
        else:
            os.environ["XDG_PICTURES_DIR"] = self._previous

    def _image(self, name: str, *, where: Path | None = None) -> Path:
        path = (where or self.pictures) / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        return path

    def _resolved(self, request: str):
        return self.resolve(self.gateway, request)

    # -- what it does ------------------------------------------------------

    def test_a_named_image_resolves_to_that_image(self) -> None:
        wanted = self._image("holiday.png")
        self._image("other.png")
        self.assertEqual(self._resolved("make holiday.png 100 pixels wide"), (wanted,))

    def test_this_resolves_to_the_most_recent_image(self) -> None:
        older = self._image("older.png")
        newer = self._image("newer.png")
        os.utime(older, (1, 1))
        os.utime(newer, (2_000_000, 2_000_000))
        self.assertEqual(self._resolved("Resize this to 100 pixels wide."), (newer,))

    def test_an_empty_pictures_directory_resolves_to_nothing(self) -> None:
        self.assertEqual(self._resolved("Resize this to 100 pixels wide."), ())

    # -- what it refuses ---------------------------------------------------

    def test_a_request_that_is_not_an_application_task_resolves_to_nothing(self) -> None:
        self._image("holiday.png")
        for request in ("Open Files", "what can you do", "How much memory am I using?"):
            with self.subTest(request=request):
                self.assertEqual(self._resolved(request), ())

    def test_a_traversal_never_reaches_here_and_would_be_refused(self) -> None:
        """The recogniser refuses a subject with a separator, so this returns
        nothing because there is no intent — and if a future recogniser were
        looser, the parent check below is what would still hold."""
        self._image("holiday.png", where=self.outside)
        self.assertEqual(self._resolved("make ../Secrets/holiday.png 100 pixels wide"), ())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_a_symlink_out_of_pictures_is_refused(self) -> None:
        """The one that a name check alone would miss: a plain, innocent-looking
        name inside Pictures whose bytes are somewhere else."""
        secret = self._image("private.png", where=self.outside)
        link = self.pictures / "holiday.png"
        try:
            link.symlink_to(secret)
        except OSError as error:  # pragma: no cover - Windows without privilege
            self.skipTest(f"symlinks unavailable: {error}")
        self.assertEqual(self._resolved("make holiday.png 100 pixels wide"), ())

    def test_a_name_that_is_not_an_image_is_refused(self) -> None:
        (self.pictures / "notes.txt").write_text("hello", encoding="utf-8")
        self.assertEqual(self._resolved("make notes.txt 100 pixels wide"), ())

    def test_a_directory_is_not_a_file_this_task_may_name(self) -> None:
        (self.pictures / "album.png").mkdir()
        self.assertEqual(self._resolved("make album.png 100 pixels wide"), ())

    def test_a_missing_named_file_resolves_to_nothing(self) -> None:
        self._image("holiday.png")
        self.assertEqual(self._resolved("make absent.png 100 pixels wide"), ())

    def test_no_support_means_no_resolution(self) -> None:
        """A build with capsules disabled must not resolve a file for a route
        that does not exist."""
        self._image("holiday.png")
        gateway = type("G", (), {"capsules": None})()
        self.assertEqual(self.resolve(gateway, "make holiday.png 100 pixels wide"), ())


if __name__ == "__main__":
    unittest.main()
