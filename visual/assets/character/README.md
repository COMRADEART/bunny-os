# Bunny guide assets

Production-ready transparent PNGs live in `bunny-guide/v1/`. The manifest is
the source of truth for filenames, intended states, dimensions, and integrity
hashes. All assets use a 1024 × 1536 RGBA canvas with transparent padding.

Implementations should select a state explicitly, size by available layout
height while preserving aspect ratio, and keep the character out of the
keyboard focus order. Do not crop the head, hands, interface prop, or shoes.

The images were generated as a consistent pose family with OpenAI image
generation, using a user-provided visual reference and written character
direction, then locally converted from a chroma-key source to alpha PNGs.
Source-key images and review sheets are build artifacts and are not packaged.

See [CHARACTER_GUIDE.md](CHARACTER_GUIDE.md) for product usage and
[../LICENSE.md](../LICENSE.md) for provenance and distribution status.

