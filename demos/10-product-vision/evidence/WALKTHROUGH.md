# Product-vision host demo walkthrough

This is a **host-runnable** demonstration of the Companion face,
appearance modes, outcome routing, memory boundaries, first-run copy,
and the offline voice story. It is not a booted Fedora guest, not
hardware evidence, and not a stable-release GO.

- Host guest boot: `NOT_RUN` — this demo does not start a guest
- Stable release: `NO-GO`
- Pilots: `BLOCKED`

## What to show a reviewer

1. Visual Keys in `frames/visual-*.html` — speech bubbles for ordinary
   actions, plus permission / warning / offline / disconnected.
2. Appearance in `frames/appearance-*.html` — Full 3D / Lightweight 2D /
   Minimal, recommended from simulated hardware, override bounded.
3. Outcomes in `frames/outcomes.html` — local vs offline refuse vs
   memory pressure; no model shop.
4. Memory in `frames/memory.html` — session/durable/cloud off by default.
5. First run `frames/onboarding-hello.html` → `onboarding-ready.html`.
6. Voice `frames/voice.html` — Vosk→action→TTS with honest NOT_RUN.
7. Settings `frames/settings.html` — Appearance, Bunny, Voice, AI,
   Privacy, Memory, Apps, Permissions, Accessibility, System, Updates.
8. Status `frames/error.html`, `offline.html`, `disconnected.html`.
9. Permission `frames/trust.html` — who / what / why / how long;
   Allow once / Don't allow; deny focused.

## Unit tests

- tests run: 46
- result: PASS

## Surfaces

- pages: PASS
- forbidden labels: none
- onboarding: Hi. I'm Bunny. → Ready
- voice STT: ['NOT_RUN']

Appearance (simulated machines, labelled as such):

- `gaming-desktop`: recommended `full-3d`, effective `full-3d`; 3D override effective `full-3d` (bounded=False)
- `laptop`: recommended `full-3d`, effective `full-3d`; 3D override effective `full-3d` (bounded=False)
- `embedded-64mb`: recommended `minimal`, effective `minimal`; 3D override effective `minimal` (bounded=True)

Outcomes:

- summarise this note: `local` — I'll do this on this computer.
- search the web for pasta: `refused` — I can't do that while you're offline.
- summarise this private note: `refused` — This stays on this computer, and it cannot run here right now.
- summarise this note: `refused` — This computer is too busy to do that right now.

## Still needs Fedora + KVM / hardware / reviews / keys

- Guest AT-SPI photograph of these surfaces inside Bunny Shell
- Physical microphone + packaged Vosk model for a live STT PASS
- Physical Secure Boot / TPM / Orca qualification
- Independent security / privacy / accessibility reviews
- Production signing keys

None of those are claimed by this run. `gate-stable-release` is NO-GO.
Pilots remain BLOCKED.
