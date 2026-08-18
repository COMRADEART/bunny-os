# Known limitations — for Alpha testers

The practical consequences of the project's measured state, translated for
the person actually running this. Everything here is a limitation of **this
exact build** (`e906a48793d7`); nothing is a promise about the next one.

## Treat the machine as an experiment, not a home

* **This build never updates itself — including security fixes.** That is a
  deliberate property of the Alpha class, not a bug. There are known,
  unreviewed security findings in system components. Practical consequence:
  install it on a spare machine or VM, keep nothing on it you cannot lose,
  and do not use it for accounts or data you care about.
* **The installer image is unsigned.** Your browser, OS, or firmware may
  warn you. Check the file's SHA-256 against
  `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`
  yourself before writing it to anything; if it does not match, do not boot
  it — report it.
* **There is no recovery kit.** If the system stops booting, reinstalling is
  the supported path. If you chose disk encryption, your data is exactly as
  recoverable as your passphrase: lose it and nothing can help.

## Hardware: you may be first

* **No physical machine has been qualified yet.** Everything verified so far
  ran in a virtual machine. On real hardware, your report is the first
  evidence for your configuration — that is precisely why it is valuable.
* **On a machine with a TPM, the very first boot may count down five seconds
  ("Boot Option Restoration") and reboot once.** That is designed firmware
  behavior, not a crash. It happens once.
* **Wi-Fi, Bluetooth, microphones, speakers and GPUs are all unverified on
  real hardware.** Voice needs a working microphone; if yours is not
  detected, that is a report, not your mistake.

## The Companion and 3D

* **Expect the 3D character mode to decline politely on most machines.** It
  has only ever been verified with software rendering. Falling back to the
  2D or pre-rendered character with a notice is correct behavior; silent
  wrong rendering is a bug — report which one you saw.

## Accessibility

* **Large text and high contrast work and are verified.** Beyond those two,
  most assistive flows — the installer with a screen reader, keyboard-only
  installation, Orca through onboarding — are **not yet verified**. If you
  rely on assistive technology, expect rough edges and please report them;
  if you cannot complete installation without sight or a mouse, that is a
  known unverified area, not a surprise to the project.

## What to do with all of this

Report against the journeys in the protocol, bind every report to the digest
above, and say what you saw — including things that merely felt wrong.
"Confusing" is evidence.
