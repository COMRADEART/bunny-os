# What this Alpha is qualified on

The authoritative scope is the committed Phase 8 record,
`qualification/phase8/alpha/RELEASE_SCOPE.md`, pinned by sha256 in
`PHASE8_PINS.json` — this file restates it for the tester workflow and
adds nothing. If the two ever disagree, the pinned Phase 8 record wins and
the tooling fails closed. "Works on PCs" appears in neither.

## The artifact

One artifact: `e906a48793d7` — ISO
`823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`
(`bunny-os-0.3.0-live.e906a48793d7-x86_64.iso`), **unsigned**, frozen.
Every report is about these exact bytes (`ARTIFACT_VERIFICATION.md`).

## Where journeys have actually run

QEMU/KVM virtual machines only: q35, UEFI (OVMF), virtio disk/net/vga,
4 vCPU / 4–6 GB RAM, 1920×1080, software GL (llvmpipe). Installation,
first boot, login, desktop, Companion, voice, Trust, rollback and
recovery have run there and nowhere else.

## Physical machines

**Zero physical machines are qualified**
(`qualification/phase8/hardware-matrix.json`: empty machines list). On
real hardware you are the first person to try your configuration — that
is exactly why your report is valuable, and exactly why nothing about
your hardware is promised. Every GPU, Wi-Fi and Bluetooth adapter,
microphone and speaker path, discrete TPM, multi-monitor and HiDPI
configuration is untested until someone tests it.

## Companion renderer modes

Four modes, tracked separately and never merged into "graphics passed":

    prerendered      qualified (VM, llvmpipe)
    2D               qualified (VM, llvmpipe)
    3D native        NOT verified on any real GPU
    3D fallback      qualified as fallback-on-unsupported (VM)

On most real machines the correct behavior is a polite fallback to 2D or
prerendered **with an announcement**. Silent wrong rendering is a bug;
report which mode you actually saw.

## Updates, recovery, signing, security

* Updates: **NOT_SUPPORTED for this release class** — an installed Alpha
  never receives updates, including security updates (recorded decision,
  `UPDATE_TRUST_ARCHITECTURE_DECISION.md`).
* Recovery: no recovery media ships; encrypted installations are exactly
  as recoverable as your passphrase.
* Signing: unsigned; the digest is the artifact's only identity.
* Security: 8 Critical and 36 High findings are inventoried and
  undispositioned, awaiting independent review
  (`qualification/phase11/security-review/`).
