#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The program that runs *inside* a capsule and resizes one image.

It lives in ``scripts/`` with the other ``/usr/libexec`` programs rather than
inside ``companion/`` deliberately. A capsule gives its process no Bunny code on
its import path at all, so a program that imported the Companion would be one
that could not run in the sandbox it exists to be run in — and the import error
would only surface on a machine where the sandbox worked. Being outside the
package makes that structural rather than remembered, and
``tests/capsule_task/test_image_tool.py`` asserts it.

This is the application in the first vertical slice. It is deliberately small
and deliberately Bunny's own, for three reasons that all point the same way:

* **it exists in the image already.** GdkPixbuf arrives with ``gtk4`` and its
  typelib with ``python3-gobject``, both of which the shell profile installs and
  the Companion window already needs. §30 asks not to add a large dependency for
  a demonstration when something already present can do the deterministic work,
  and adding ImageMagick to the image would add a package, its CVE surface, and
  a supply-chain input, to prove a wiring change.
* **it is a real confined process.** It runs under the same bubblewrap plan,
  the same transient unit, the same cgroup and the same SELinux context as any
  other capsule. Nothing about the sandbox is special-cased for it. When a third
  party application replaces it, the plan does not change.
* **it can be wrong in the interesting way.** It reads a file it was given and
  writes a file where it was told, and it can be pointed at a file it was not
  granted — which is exactly what the isolation has to refuse. A tool that
  produced its output by copying its input outside the sandbox could not.

**It trusts nothing it is given.** Both paths must be inside the capsule's own
namespace, the input must be a regular file, the width must parse to a bounded
integer, and the output must not already exist. It does not read the user's
request, does not take a format from an argument, and has no code path that
executes anything.

**It writes PNG, always.** The output format is a property of the operation, not
of the input's name and not of an argument: a program that chose an encoder from
a string it was handed is a program with a decoder-selection bug waiting in it.
PNG is lossless, so a resize followed by a comparison is a comparison of the
resize.
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import sys

#: Where a capsule's own directories appear inside its namespace. Anything
#: outside these is refused, so a path that escaped a bind — or was never bound
#: — fails here rather than being read.
_SANDBOX_ROOTS = ("/run/bunny/app/", "/run/bunny/files/")

#: The same bounds :mod:`companion.capsule_tasks` validates against. Repeated
#: rather than imported: this program runs inside a sandbox with no Bunny code
#: on its path, and a check that depends on an import that is not there is not a
#: check. Duplication is the point — two independent bounds, both must hold.
_MIN_PIXELS = 16
_MAX_PIXELS = 16384


def _inside_sandbox(path: str) -> bool:
    """Whether a path names somewhere inside this capsule's own namespace.

    Compared as POSIX text against the argument as given, not through
    :class:`pathlib.Path`. This program only ever runs on Linux, but its tests
    run wherever the suite does, and ``Path`` on Windows rewrites the separators
    — so a check written through ``Path`` refused every path on a developer
    machine, for the wrong reason, and four tests passed vacuously because of
    it. Text in, text compared.

    ``..`` is refused outright rather than resolved: resolution here would
    consult the *developer's* filesystem in a test and the sandbox's in
    production, which are different questions.
    """
    if ".." in PurePosixPath(path).parts:
        return False
    return any(path.startswith(root) for root in _SANDBOX_ROOTS)


def _fail(message: str) -> int:
    print(f"bunny-image-tool: {message}", file=sys.stderr)
    return 2


def resize(input_path: Path, output_path: Path, width: int) -> int:
    """Scale to ``width``, preserving aspect ratio, and write a PNG."""
    try:
        import gi  # type: ignore

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib  # type: ignore
    except (ImportError, ValueError) as error:
        return _fail(f"no image library available inside the sandbox: {error}")

    try:
        source = GdkPixbuf.Pixbuf.new_from_file(str(input_path))
    except GLib.Error as error:
        return _fail(f"could not read the image: {error.message}")

    if source.get_width() <= 0 or source.get_height() <= 0:
        return _fail("the image has no pixels")

    # Height from the source's own ratio, never from an argument. An operation
    # that took both would be able to distort, which is not what was asked for
    # and not what the prompt told the user would happen.
    height = max(1, round(source.get_height() * width / source.get_width()))
    try:
        scaled = source.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    except GLib.Error as error:
        return _fail(f"could not resize the image: {error.message}")
    if scaled is None:
        return _fail("the resize produced nothing")

    try:
        # `compression` fixed so that the same input and width produce the same
        # bytes: the qualification compares digests across runs, and a default
        # that changed with a library version would read as a changed result.
        scaled.savev(str(output_path), "png", ["compression"], ["6"])
    except GLib.Error as error:
        return _fail(f"could not save the result: {error.message}")
    print(f"bunny-image-tool: wrote {output_path.name} at {width}x{height}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunny-image-tool", description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    resize_parser = subparsers.add_parser("resize", help="write a scaled copy")
    resize_parser.add_argument("--input", required=True)
    resize_parser.add_argument("--output", required=True)
    resize_parser.add_argument("--width", required=True, type=int)
    arguments = parser.parse_args(argv)

    if arguments.operation != "resize":
        return _fail(f"unknown operation {arguments.operation!r}")

    input_path = Path(arguments.input)
    output_path = Path(arguments.output)

    # Both paths inside the capsule's own namespace. This is not the isolation —
    # bubblewrap is — it is the program refusing to be the thing that carries a
    # bad path across a boundary somebody else is enforcing.
    for label, given, path in (
        ("input", arguments.input, input_path),
        ("output", arguments.output, output_path),
    ):
        if not _inside_sandbox(given):
            return _fail(f"the {label} path is outside this app's own space")
        if path.is_symlink():
            return _fail(f"the {label} path is a symbolic link")

    if not _MIN_PIXELS <= arguments.width <= _MAX_PIXELS:
        return _fail(f"width must be between {_MIN_PIXELS} and {_MAX_PIXELS}")
    if not input_path.is_file():
        return _fail("the input is not a file this app can see")
    if output_path.exists():
        return _fail("the output already exists")
    if not output_path.parent.is_dir():
        return _fail("the output directory does not exist")

    return resize(input_path, output_path, arguments.width)


if __name__ == "__main__":
    raise SystemExit(main())
