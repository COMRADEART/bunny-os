# Checked-in host capture

These files are a successful run of `python3 demos/08-visible-trust/run.py` on
the 2026-09-11 cloud development host. They are **not** a booted Fedora guest,
not AT-SPI evidence, and not a stable-release GO.

| File | What it is |
|---|---|
| `WALKTHROUGH.md` | Reviewer notes for this capture |
| `report.json` | Slim machine-readable result (stableRelease `NO-GO`) |
| `screenshots/*.png` | Chrome `--app` frames on `DISPLAY`, grabbed with ffmpeg |
| `frames/waiting_for_approval.html` | The Trust prompt as drawn (Deny focused) |

Re-run the demo to refresh `out/<stamp>/`. Do not treat a missing QEMU/Podman
probe as a guest PASS.
