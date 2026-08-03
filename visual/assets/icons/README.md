# Bunny icon system

`icons.json` defines Bunny-owned symbolic and full-color application icons.
`make visual-build` renders system SVGs to `build/visual/icons/` and stages them
under the standard hicolor theme paths.

Symbolic icons use a 16 px optical grid, rounded geometry, and `currentColor`.
Full color is limited to the five Bunny applications and large identity use.
Standard third-party application icons are left unchanged.
