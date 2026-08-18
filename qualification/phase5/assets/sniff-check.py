#!/usr/bin/python3
"""Content-only mime sniffing, which is the question the loader actually asks.

`gio info` and `xdg-mime query filetype` both take the *filename* into account,
and shared-mime-info has a `*.svg` glob, so both answer `image/svg+xml` for a
file that content sniffing alone would reject. Three libwacom SVGs in this
image carry `<svg` at bytes 255, 259 and 262 and still come back
`image/svg+xml` through those tools -- which is exactly how a check can pass
while the property it was written for is broken.

A loader handed a byte stream has no filename. `g_content_type_guess(None,
data)` is that case, and it is the one that failed.

Usage: sniff-check.py <file> [<file> ...]
"""
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402


def sniff(path: str) -> None:
    with open(path, "rb") as handle:
        data = handle.read(4096)
    offset = data.find(b"<svg")
    with_name, uncertain_name = Gio.content_type_guess(path, data)
    content_only, uncertain_content = Gio.content_type_guess(None, data)
    name_only, uncertain_nameonly = Gio.content_type_guess(path, None)
    print(f"{path}")
    print(f"    '<svg' at byte {offset if offset >= 0 else 'NONE'} of the first {len(data)}")
    print(f"    filename only:      {name_only} (uncertain={uncertain_nameonly})")
    print(f"    content only:       {content_only} (uncertain={uncertain_content})")
    print(f"    filename + content: {with_name} (uncertain={uncertain_name})")
    verdict = "PASS" if content_only == "image/svg+xml" else "FAIL"
    print(f"    content-only verdict: {verdict}")


for argument in sys.argv[1:]:
    sniff(argument)
