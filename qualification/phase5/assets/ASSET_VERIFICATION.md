# The two repaired assets, verified in the image

**Subject.** `localhost/bunny-os-beta:e501218f2fe0`, image id
`70f677701e1a16efd740f075cb05b14a6a04304e38141576e893b23655543d58`, from source
commit `e501218f2fe0105e5fc92bdf94fd6b3c87d6c470`. See `../build/BUILD_IDENTITY.md`.

## The defect

`shell/assets/wallpapers/bunny-nocturne.svg` and
`shell/assets/companion/default-bunny.svg` both opened with several lines of
SPDX headers and licence prose before the `<svg` root element. shared-mime-info
matches `image/svg+xml` on the literal `<svg` within **bytes 0–256**, and
matches `application/xml` on `<?xml` at byte 0. Past 256 bytes the second rule
wins alone, and a loader handed the bytes gets `application/xml` — not an image
type — so it declines to decode them.

The repair moves the prose inside the `<svg` element. `<svg` now begins at byte
**139** in both.

## The instrument, and why the obvious one is wrong

`file --mime-type`, `xdg-mime query filetype` and `gio info` all answer
`image/svg+xml` for **both** the broken and the repaired file, because
shared-mime-info also carries a `*.svg` filename glob and those tools use the
name. Three libwacom SVGs shipped in this same image carry `<svg` at bytes 255,
259 and 262 and come back `image/svg+xml` through every one of them.

A loader handed a byte stream has no filename. The question is
`g_content_type_guess(NULL, data)` — content only — and `sniff-check.py` asks
exactly that, reporting all three forms side by side so the difference stays
visible.

## Result

Against the image's own `/usr/share/mime/mime.cache` (160164 bytes), with
`XDG_DATA_DIRS` pointed at the mounted image rather than the builder:

| file, as installed | `<svg` at | filename only | **content only** |
| --- | ---: | --- | --- |
| `/usr/share/backgrounds/bunny-os/bunny-nocturne.svg` | 139 | `image/svg+xml` | **`image/svg+xml`** |
| `/usr/share/bunny-shell/companion/default-bunny.svg` | 139 | `image/svg+xml` | **`image/svg+xml`** |
| `/usr/share/backgrounds/bunny-os/bunny-arc-dark.svg` | 0 | `image/svg+xml` | `image/svg+xml` |
| `/usr/share/backgrounds/bunny-os/bunny-arc-light.svg` | 0 | `image/svg+xml` | `image/svg+xml` |

Both repaired files also parse as XML, root element
`{http://www.w3.org/2000/svg}svg` — the check that catches a file which passes
the offset rule while being malformed, which is how the first attempt at this
repair broke both files with a `--` inside an XML comment.

## Negative control

The same two files as they were at the Phase 4 candidate commit
`e906a48793d7`, recovered with `git show` and sniffed identically:

| file at `e906a48793d7` | `<svg` at | filename only | **content only** |
| --- | ---: | --- | --- |
| `bunny-nocturne.svg` | 1361 | `image/svg+xml` | **`application/xml`** |
| `default-bunny.svg` | 520 | `image/svg+xml` | **`application/xml`** |

The control fails where the repair passes, and it fails only on the
content-only question — which is both the proof that the repair does something
and the proof that the filename-aware tools could never have found it.

## Reproducing

```
bash /home/bunny/p5-ops/sniff-verify.sh localhost/bunny-os-beta:e501218f2fe0
```

`sniff-verify.sh` and `sniff-check.py` are copied here; `sniff.log` is the run
above, `mime-database.log` the wider survey of every SVG the image installs.

## What this does not show

That GNOME Shell renders them. This is the loader's *first* question answered
correctly, on the real artifact, with a control. Whether the wallpaper appears
on a booted desktop is a display-stack observation and is not made here.
