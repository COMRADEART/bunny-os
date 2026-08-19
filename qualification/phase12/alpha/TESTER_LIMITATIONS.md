# Known limitations — read before installing

The authoritative record is
`qualification/phase8/alpha/ALPHA_KNOWN_LIMITATIONS.md`, pinned in
`PHASE8_PINS.json`; this restates it for the current workflow. Everything
here is about **this exact build** (`e906a48793d7`); nothing is a promise
about the next one.

## Treat the machine as an experiment, not a home

* **This build never updates itself — including security fixes.** That is
  a deliberate property of the Alpha class. There are known, unreviewed
  security findings in system components. Install on a spare machine or
  VM, keep nothing on it you cannot lose, and do not sign into accounts
  you care about.
* **The installer image is unsigned.** Your browser, OS, or firmware may
  warn you. Verify the ISO's SHA-256 yourself
  (`ARTIFACT_VERIFICATION.md`) before writing it to anything; if it does
  not match, do not boot it — that mismatch is itself a report.
* **There is no recovery kit.** If the system stops booting, reinstalling
  is the supported path. With disk encryption, your data is exactly as
  recoverable as your passphrase.

## Hardware: you may be first

* No physical machine has been qualified. Your report may be the first
  evidence for your configuration.
* On a machine with a TPM, the very first boot may count down five
  seconds ("Boot Option Restoration") and reboot once. Designed firmware
  behavior, happens once, not a crash.
* Wi-Fi, Bluetooth, microphones, speakers and GPUs are unverified on real
  hardware. If your microphone is not detected, that is a report, not
  your mistake.

## The Companion and 3D

Expect the 3D character to decline politely on most machines and fall
back to 2D or prerendered **with a notice** — that is correct behavior.
Silent wrong rendering is a bug. Report which mode you actually saw.

## Accessibility

Large text and high contrast are verified. Most other assistive flows —
the installer with a screen reader, keyboard-only installation, Orca
through onboarding — are **not yet verified**. If you rely on assistive
technology, expect rough edges and please report them; your observation
is first-class evidence (`REPORTING.md`), not a complaint.

## What to do with all of this

Verify the digest, run the journeys (`GETTING_STARTED.md`), and say what
you saw — including things that merely felt wrong. "Confusing" is
evidence. You do not need to diagnose anything; "I could not install it"
is a complete, valid report.
