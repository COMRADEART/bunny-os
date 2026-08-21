# Physical hardware qualification — Phase 5 addendum

**Status: NOT RUN. No physical machine has ever booted Bunny OS.**

Every result this project has ever produced is from QEMU with software
rendering. That sentence is not new and it is not softened here.

`PHYSICAL_HARDWARE_EVIDENCE_PLAN.md` (2026-07-30) already specifies the first
target device, the characteristics that unblock the most evidence, and the
collector. **This document does not restate it.** It adds the three things §14
to §16 ask for that the earlier plan predates — a boot chain, voice on real
hardware, and a GPU/renderer matrix — and binds the whole track to a candidate.

---

## 1. What binds this track to an artifact

The earlier plan named no artifact, because when it was written there was no
qualified one. There is now.

| | |
| --- | --- |
| Candidate | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Installation medium | `bunny-os-0.3.0-live.e906a48793d7-x86_64.iso` |
| ISO digest | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |

**The digest must be verified on the writing host and again from the written
medium**, before the machine is powered on. Phase 4's install journey hashed
its own ISO before installing from it, and that is the property that makes
"installed from the candidate" a measurement rather than an assumption. A USB
stick written from a corrupted download would produce a hardware report about
something that is not the candidate.

Any Phase 5 artifact supersedes this and its own digests go here. §24: never
attach new evidence to the old artifact.

---

## 2. §13 — the device record

Recorded **before** the first boot, because a machine described after a
failure is described by somebody with a theory.

| Field | Why it is on the list |
| --- | --- |
| Exact model and firmware version | The only stable identifier. "A Dell laptop" is not a hardware result. |
| CPU, RAM | The VM had 4 vCPU and 6 GiB; the performance baseline is not transferable without them. |
| GPU | Decides §16 entirely, and every VM renderer result is llvmpipe. |
| Storage — type, controller, size | NVMe against real firmware is an installation scenario the VM cannot run. |
| Boot mode, Secure Boot state, TPM version | Secure Boot and TPM 2.0 unblock evidence categories no virtual result substitutes for. |
| Network hardware | Real Wi-Fi firmware, which QEMU's virtio-net does not model. |
| Audio hardware, microphone | §15 depends on it, and the VM used a synthetic pipe source. |
| Display — panel, native resolution, scaling | The desktop is laid out by a solver; 1920×1080 and 1366×768 are the only two sizes ever tested. |

**§13's rule, kept: do not generalise from one device to all hardware.** One
machine produces one row. The support matrix stays as it is until there are
enough rows to say something about a class.

---

## 3. §14 — the boot chain, and where it is expected to break first

    ISO → USB medium → physical machine → boot → installer → install
      → first boot → login

Each arrow is a separate result. The project has learned twice that adjacent
states are not the same state:

* "ISO generated" and "installer boot validated" became distinct states with a
  build gate between them after a 2.0 GB ISO that image-builder exited 0 on
  reached GRUB and died in the initramfs (`LIVE_BOOT_ROOT_CAUSE.md`).
* The live medium boots to Bunny Setup only after six faults were cleared
  (`memory/live-boot-chain-state`).

**The most likely first failure is firmware, not software.** Every UEFI result
this project has is from `OVMF_CODE.secboot.fd`, which is one implementation.
Real firmware differs in USB enumeration order, in whether it honours the
removable-media path, and in Secure Boot enrolment. A machine that will not
boot the medium is a *hardware compatibility finding*, and §14 is explicit
about what may not follow from it:

> Do not change the software solely to accommodate one unsupported machine
> without documenting the compatibility requirement.

So a boot failure produces a documented requirement first, and a change only if
the requirement is one the product intends to meet.

**Evidence per step**: a photograph of the screen, the firmware's own boot
menu, the installer's log, and the installed system's journal. Photographs
rather than screenshots — there is no QMP on a physical machine, and this is
the point at which the harness this project has built stops applying.

---

## 4. §15 — voice on hardware

Voice is a **PASS** in the VM: `voice-phase3-b`, exit 0, 19 stages, on real
audio through a synthetic source. What that does not establish is anything
about a microphone.

| Check | Why the VM result does not carry |
| --- | --- |
| Microphone enumerated and selectable | The VM used a null-sink loopback and a pipe source. A real capture device has a different card, profile and default. |
| Audio input level and noise floor | Not modelled at all. This is where "Bunny did not hear me" comes from. |
| Audio output | HDA in the VM; real codecs and real mixers. |
| STT accuracy | Vosk on real speech in a real room, not on a wav file. |
| TTS | eSpeak NG through a real DAC. |
| Interruption | Barge-in depends on capture and playback overlapping on real devices. |
| Permissions | The microphone permission prompt against a device that can actually be opened. |
| Offline behaviour | With the radio actually off, not with a virtual link down. |

**Latency is compared, not equated.** §15: *"Do not expect identical
timings."* The VM figure is the reference; the hardware figure is a new
measurement, and a difference is a fact about hardware rather than a
regression — unless the hardware is *faster*, which would mean the VM number
was measuring the harness.

---

## 5. §16 — GPU and renderer

The renderer has three modes and a capability rung, and **they are two
different values** — a lesson the renderer-modes phase paid for. The matrix
below tests the pair, not either alone.

| Condition | Required behaviour |
| --- | --- |
| GPU available, 3D selected | 3D runs. |
| GPU unavailable, 3D selected | Falls back — **and the user's preference is retained**, not rewritten. |
| Capability restored | 3D recovers without the user having to re-choose it. |
| GPU unavailable, pre-rendered | Works. This is the mode that must remain the cheapest CPU path. |
| GPU unavailable, 2D | Works. |

**The retained-preference row is the one most likely to be got wrong**, and it
is the one §11 names: *"Do not silently downgrade the user's preference."* A
fallback that writes `renderMode: prerendered` into the settings file has
destroyed the information needed to recover. The check is on the settings file
after the fallback, not on the screen.

**Every 3D measurement this project has is on llvmpipe** — software rendering,
no GPU (`memory/companion-3d-renderer-state`). So the *first* row of that table
is the one no result exists for, in either direction: nobody has seen the 3D
renderer on a GPU, and nobody has seen it refuse one.

---

## 6. What Phase 5 delivers here, and what it does not

**Delivers**: the track, bound to a candidate digest, with the three sections
the earlier plan predates and the failure modes named in advance so that a run
can be graded rather than narrated.

**Does not deliver**: any hardware result. There is no machine.

`scripts/release.py gate` reports `PENDING_HARDWARE` and that is accurate. It
is one of the four required gates that cannot be closed from inside this
repository, and the only one of the four whose blocker is a purchase rather
than a person.
