# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every shipped SVG can be identified from its content alone.

The defect this exists for, in full, because the recorded diagnosis was wrong
and acting on it would have made things worse.

``gnome-shell`` logged, on every Bunny-session boot of the Alpha Release
Candidate::

    Failed to load background
    'file:///usr/share/backgrounds/bunny-os/bunny-nocturne.svg':
    Unknown image format: application/xml

Phase 4 recorded the cause as "the image has no SVG pixbuf loader"
(``KNOWN_LIMITATIONS.md``). It has one. ``librsvg2-2.62.3-1.fc44`` and
``glycin-loaders-2.1.5-1.fc44`` are both installed in the artifact —
``qualification/phase4/artifact/p4-build.log`` lines 359 and 369 to 371 record
them being downloaded and installed. Adding a package would have changed
nothing.

The loader was never reached. An image loader handed an open stream has no
filename to go on and identifies the format by sniffing the leading bytes.
shared-mime-info matches ``image/svg+xml`` on a literal ``<svg`` occurring at
an offset in the range ``0:256``, and matches ``application/xml`` on the
``<?xml`` at offset 0 regardless of what follows. ``bunny-nocturne.svg``
carried 1.2 KB of provenance comment between the two, putting ``<svg`` at byte
1361 — outside the window. So it sniffed as ``application/xml``, for which no
loader is registered, and was refused.

Measured on the Fedora reference target with ``Gio.content_type_guess``:

===============================  ================  ================
File                             content only      with filename
===============================  ================  ================
``bunny-nocturne.svg`` (before)  application/xml   image/svg+xml
``bunny-arc-dark.svg``           image/svg+xml     image/svg+xml
===============================  ================  ================

The two that worked have ``<svg`` at byte 0. The one that failed did not. That
is the whole mechanism, and the error string names the wrong answer the sniff
gave.

**Why this is a sweep and not a one-line fix.** Repairing the wallpaper alone
would have left ``shell/assets/companion/default-bunny.svg`` with ``<svg`` at
byte 528 and the identical latent defect. Nothing had failed because of it —
that asset is loaded by path, so a filename was always available — but the next
consumer may not pass one. It was found by looking for the *class* of defect
rather than for the reported symptom.

**Why the check is on the byte offset rather than on GIO.** ``python3-gobject``
and shared-mime-info are not present on the Windows development host, and a
test that skips on the machine most edits are made on is a test that finds this
after it ships. The offset is the property the MIME rule is written in terms
of, so asserting it needs nothing but the file. The GIO check runs too, when
GIO is there, so that the offset rule stays tied to the thing it is a proxy for.
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: shared-mime-info's magic for ``image/svg+xml`` is ``<svg`` at offset
#: ``0:256``. Not a value this project chose, and not one it may relax: a
#: larger number here would make the test pass and the desktop still fail.
SNIFF_WINDOW = 256

#: Trees whose SVGs reach the image. Each is a ``COPY`` root in
#: ``build/Containerfile`` with an install route that lands its SVGs on disk.
SHIPPED_TREES = ("shell", "assets", "installer", "desktop-integration")


def shipped_svgs() -> list[Path]:
    found: list[Path] = []
    for tree in SHIPPED_TREES:
        directory = ROOT / tree
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.svg")):
            if "node_modules" in path.parts:
                continue
            found.append(path)
    return found


class EverySvgIsIdentifiableFromItsBytesTests(unittest.TestCase):
    def test_there_are_svgs_to_check(self) -> None:
        """A sweep that found nothing would pass silently for ever."""
        self.assertGreaterEqual(len(shipped_svgs()), 5)

    def test_the_root_element_is_inside_the_sniffing_window(self) -> None:
        late: list[str] = []
        for path in shipped_svgs():
            data = path.read_bytes()
            offset = data.find(b"<svg")
            if offset < 0 or offset >= SNIFF_WINDOW:
                late.append(f"{path.relative_to(ROOT)}: <svg at byte {offset}")
        self.assertEqual(
            late,
            [],
            "these files sniff as application/xml and no image loader will accept them; "
            "move the prose inside the <svg> element",
        )

    def test_nothing_but_the_declaration_and_spdx_precedes_the_root(self) -> None:
        """The rule stated positively, so a near-miss is caught before it is one.

        A file with ``<svg`` at byte 250 passes the offset check and is one
        added copyright line away from failing on somebody else's afternoon.
        What is allowed above the root element is the XML declaration and the
        two SPDX lines, and that is a fixed, small budget.
        """
        for path in shipped_svgs():
            with self.subTest(path=str(path.relative_to(ROOT))):
                header = path.read_bytes().split(b"<svg", 1)[0].decode("utf-8", "replace")
                lines = [line for line in header.splitlines() if line.strip()]
                for line in lines:
                    self.assertTrue(
                        line.startswith("<?xml") or line.startswith("<!-- SPDX-"),
                        f"unexpected content above the root element: {line[:70]!r}",
                    )
                self.assertLessEqual(
                    len(lines), 3, "only the XML declaration and two SPDX lines belong above <svg>"
                )

    def test_every_file_is_still_well_formed_xml(self) -> None:
        """Moving prose inside an element is easy to get wrong.

        An XML comment may not contain ``--``, and the first attempt at this
        very fix produced a file that no parser would read. The offset check
        would have passed it.
        """
        for path in shipped_svgs():
            with self.subTest(path=str(path.relative_to(ROOT))):
                ElementTree.parse(path)

    def test_the_wallpaper_the_desktop_actually_asks_for_is_covered(self) -> None:
        """``10-bunny-shell`` names one file. This is that file.

        A sweep over a directory would keep passing if the dconf key were
        pointed at something the sweep does not cover.
        """
        dconf = (ROOT / "shell" / "components" / "dconf" / "10-bunny-shell").read_text(
            encoding="utf-8"
        )
        self.assertIn("bunny-nocturne.svg", dconf)
        wallpaper = ROOT / "shell" / "assets" / "wallpapers" / "bunny-nocturne.svg"
        self.assertTrue(wallpaper.is_file())
        self.assertLess(wallpaper.read_bytes().find(b"<svg"), SNIFF_WINDOW)


class TheOffsetRuleMatchesWhatGioActuallySaysTests(unittest.TestCase):
    """Ties the proxy to the thing it stands for, where GIO is available.

    Skipped on hosts without ``python3-gobject`` — which is the Windows
    development host, and is why the offset check above exists and is not
    skipped anywhere.
    """

    def setUp(self) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
        except (ImportError, ValueError) as error:
            self.skipTest(f"GIO is not available here: {error}")
        self.Gio = Gio

    def test_gio_identifies_every_shipped_svg_from_content_alone(self) -> None:
        wrong: list[str] = []
        for path in shipped_svgs():
            data = path.read_bytes()[:4096]
            content_type, _ = self.Gio.content_type_guess(None, data)
            if content_type != "image/svg+xml":
                wrong.append(f"{path.relative_to(ROOT)}: {content_type}")
        self.assertEqual(wrong, [], "GIO cannot identify these from their content")

    def test_the_negative_control_still_fails(self) -> None:
        """The check has to be able to reject something.

        A header long enough to push the root element past the window is built
        here and handed to the same call. If this ever stops sniffing as
        ``application/xml``, the rule above has stopped meaning anything and the
        window constant needs re-measuring rather than trusting.
        """
        padding = b"<!-- " + b"x" * 400 + b" -->\n"
        forged = b'<?xml version="1.0" encoding="UTF-8"?>\n' + padding + b"<svg/>\n"
        content_type, _ = self.Gio.content_type_guess(None, forged)
        self.assertEqual(content_type, "application/xml")
        self.assertGreater(forged.find(b"<svg"), SNIFF_WINDOW)


if __name__ == "__main__":
    unittest.main()
