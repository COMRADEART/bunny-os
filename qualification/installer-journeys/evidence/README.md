# Installer-journey evidence

Unattended §53 installation journeys, run on the Fedora WSL builder
(QEMU/KVM, OVMF, 4 vCPU, 6 GiB, virtio disk and display) by
`build/scripts/vm-install-story.sh`. The driver ships on the medium
(`/usr/libexec/bunny-setup-drive`) and walks the real setup surface through
AT-SPI; the harness reads the outcome over serial, powers the machine off,
and `build/scripts/verify-installed-choices.py` reads the disk from outside
with the journey's own expectation (`expected.json`). Nothing below was
recorded from inside a guest that was still running.

## Media provenance

| Runs | Medium | sha256 |
|---|---|---|
| journey-b, journey-c, journey-d, journey-c-offline | `bunny-os-0.3.0-live.b2dffa3380e3-x86_64.iso` (commit `b2dffa33`) | `080b5e074902d965cafe68231dc2b48e6c85ee8ae6795561708fbc17b1b45302` (`iso-digest.txt`) |
| journey-a, first-boot | the run-27 build (commit `72258bc1` with the `b2dffa33` unmount fix in the tree) | not preserved — the build was replaced by the `b2dffa33` medium before its digest was archived |

Journey A was the first completed installation (run 27 of 27; the defect
ledger lives in `INSTALLATION_RUNTIME_REPORT.md`). Its exact medium no
longer exists, so every property it demonstrated is independently re-proven
on the preserved medium: journey B re-ran the encrypted path and journey C
the unencrypted path on the recorded ISO above. `first-boot` boots journey
A's installed disk, which is preserved on the builder.

## Directories

- `journey-a/` — encrypted install, every §53 stage, LUKS opens with the
  typed passphrase, account `alex` on disk. 2026-08-15.
- `journey-b/` — encrypted install at 200 % text, high contrast, reduced
  motion, 1024×768 (the declared minimum screen). 2026-08-15.
- `journey-c/` — unencrypted install, defaults changed nowhere. 2026-08-16.
- `journey-c-offline/` — journey C with **no NIC at all**
  (`BUNNY_INSTALL_NET=none`): the offline-installation evidence. Completed
  in the same wall-clock time as the online run (186 s vs 182 s to driver
  completion). 2026-08-16.
- `journey-d/` — refusal journey: a wrong confirmation phrase leaves the
  destructive button disabled, nothing is installed, and the verifier
  confirms the empty disk (`installed.json` findings say no bootloader and
  no deployment — for this journey that is the expected reading, and the
  harness passes it on `refused-as-expected`, not on the disk gate).
  2026-08-16.
- `first-boot/` — journey A's disk booted twice on one overlay without the
  ISO, the LUKS passphrase typed at the console each time; both boots
  reached `graphical.target` (`result.json`, journal-verified from outside).
  2026-08-15.
- `iso-digest.txt` — the preserved medium's identity.

Each journey directory carries `result.json` (harness verdict and the
driver's event stream), `installed.json` (the verifier's disk record),
`installed.log` (the gate-time verifier output, verbatim), `expected.json`
(what the journey promised the disk would carry), and `screens/` (QMP
screendumps; driven journeys complete in ~3–4 minutes, so only the t60/t150
shots exist — the machine is already powered off and under verification by
t300, and journey D refuses before t60).

## One correction, recorded rather than hidden

The builder-side wrapper that launched journeys B and C re-read each disk
after the harness gate *without* `--expected` and overwrote the gate's
`installed.json` with that weaker record (account evidence read as an empty
username). The gate-time records were intact throughout in `installed.log`.
The staged `installed.json` for B and C was regenerated on 2026-08-16 with
the same verifier, the same disks, and the journeys' own `expected.json`;
both read findings `[]` with `alex` present. The wrapper now passes the
expectation. Nothing in `installed.log` was rewritten.

Evidence files in this tree are append-only and byte-exact (`qualification/**
-text`); they are never re-encoded.
