# Launcher demo

Open with Super+Space. Search for Terminal and Files, launch each, then enter `Open network settings`, `Show active tasks`, `Check for system updates`, and `Ask Bunny to review this project`. Verify result kinds and that the update route opens confirmation rather than executing. Super+A must still open GNOME's application grid.

Negative test: install a fixture desktop entry containing `/bin/sh -c` or an unsupported URI handler and verify it is absent from Bunny results.
