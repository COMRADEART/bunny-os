# Product-vision host demo walkthrough

This is a **host-runnable** demonstration of the Companion face,
appearance modes, outcome routing, memory boundaries, first-run copy,
and the offline voice story. It is not a booted Fedora guest, not
hardware evidence, and not a stable-release GO.

- Host guest boot: `NOT_RUN` — this capture host had `/dev/kvm` and no QEMU
- Stable release: `NO-GO`
- Pilots: `BLOCKED`

## What to show a reviewer

1. `screenshots/visual-idle.png` / `visual-searching.png` — speech bubble for
   an ordinary action, Bunny stays Bunny, the room accent changes with activity.
2. `screenshots/appearance-laptop.png` / `appearance-embedded-64mb.png` —
   Full 3D / Lightweight 2D / Minimal. Simulated hardware is labelled.
   Embedded cannot force 3D.
3. `screenshots/outcomes.png` — local vs offline refuse vs private-work refuse;
   no model shop.
4. `screenshots/memory.png` — session / durable / cloud off by default.
5. `screenshots/onboarding-hello.png` → `onboarding-ready.png` — “Hi. I'm Bunny.”
   … “Ready.” Source/demo, not a disk write.
6. `screenshots/voice.png` — Vosk→action→TTS with honest `NOT_RUN`.

Reproduce on any development host:

```text
python3 demos/10-product-vision/run.py
# or
make demo-product-vision
```

## Capture result (20260911T022712Z)

- unit tests: 29 run, PASS
- surfaces: PASS
- forbidden labels: none
- screenshots: 13/13 via Chrome `--app` + ffmpeg x11grab
- voice STT: NOT_RUN (`libvosk.so` absent; no packaged model; no mic; no TTS)
- voice intent → `system.get_metric`: PASS (fixture transcript, no shell)

Appearance (simulated machines, labelled as such):

- `gaming-desktop`: recommended `full-3d`, effective `full-3d`
- `laptop`: recommended `full-3d`, effective `full-3d`
- `embedded-64mb`: recommended `minimal`; 3D override effective `minimal` (bounded)

Outcomes:

- summarise this note: `local` — I'll do this on this computer.
- search the web for pasta: `refused` — I can't do that while you're offline.
- summarise this private note: `refused` — This stays on this computer, and it cannot run here right now.
- summarise this note (8 GiB on 64 MB): `refused` — This computer is too busy to do that right now.

## Still needs Fedora + KVM / hardware / reviews / keys

- Guest AT-SPI photograph of these surfaces inside Bunny Shell
- Physical microphone + packaged Vosk model for a live STT PASS
- Physical Secure Boot / TPM / Orca qualification
- Independent security / privacy / accessibility reviews
- Production signing keys

None of those are claimed by this capture. `gate-stable-release` is NO-GO.
Pilots remain BLOCKED.
