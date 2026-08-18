# Physical hardware qualification protocol

One machine, one identity, one record. A passing machine qualifies **that
machine configuration** and nothing broader; nothing is inferred from the VM,
and the VM's green history buys no row here.

## Hardware identity

Each machine gets `HW-NNN` (sequential, permanent). Before first boot, its
record is created with every field below — written before results exist, so
the record cannot be tailored to them:

    manufacturer, model, CPU, RAM, GPU, storage,
    firmware mode (UEFI/CSM), Secure Boot state,
    display (panel + resolution), Wi-Fi, Bluetooth (where relevant),
    audio output, microphone

## Media verification, both ends

The installation medium is the subject ISO:
`823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`
(`bunny-os-0.3.0-live.e906a48793d7-x86_64.iso`). Its digest is verified **on
the writing host** before writing and **from the written medium** after —
both hashes recorded in the machine's record. A journey run from unverified
media binds to no artifact and is discarded by blocking condition 6.

## The journey

    boot installation media
      → installation
      → encrypted boot
      → login
      → Bunny desktop
      → Companion: pre-rendered
      → Companion: 2D
      → Companion: 3D where supported
      → voice
      → Trust (allow AND deny, outcomes verified)
      → reboot
      → persistence

Each step lands as one or more dimension rows in
`qualification/phase8/hardware-matrix.json`, status one of
`PASS / FAIL / NOT_RUN / NOT_SUPPORTED`, each PASS citing evidence
(photograph, journal excerpt, or recorded output — a step nobody can show
happened is NOT_RUN).

## Distinctions the matrix preserves (§8)

* A machine that boots but has no working microphone is **not** PASS for
  `voice-microphone` — it is FAIL if the hardware record says a microphone
  exists, NOT_SUPPORTED if it does not.
* A machine where 3D correctly falls back is PASS for
  `companion-3d-fallback` **without** being PASS for `companion-3d-native`;
  the two are separate rows and stay separate.
* `NOT_SUPPORTED` is a statement about the machine (no such device), never a
  euphemism for "did not work".

## Known first-boot behavior, so it is not misfiled

With a TPM present and empty NVRAM, the first boot shows a five-second "Boot
Option Restoration" countdown and reboots once — designed shim 16.1
behavior, recorded in `KNOWN_LIMITATIONS.md`, not a defect and not a FAIL.

## What one machine proves

One qualified machine is one qualified hardware data point. The supported
hardware set the Alpha declares (`qualification/phase8/alpha/RELEASE_SCOPE.md`)
may list only configurations with complete journey records here.
