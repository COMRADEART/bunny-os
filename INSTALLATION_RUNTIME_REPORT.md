# Installation runtime report

Date: 2026-08-16  
Harness commits: journeys at `b2dffa33`–`24c6dae1`; journey A completed at run 27 on the `72258bc1` build  
Evidence: `qualification/installer-journeys/evidence/` (provenance in its `README.md`)  
Result: **five unattended installations completed and verified; one deliberate
refusal refused.** The §44 sentence — *render is not done; installed and
rebooted is done* — is now satisfied by runs, not by source.

## What ran

`build/scripts/vm-install-story.sh` boots the live medium in QEMU/KVM (OVMF,
4 vCPU, 6 GiB, virtio disk and display), presses Return past the GRUB menu,
and waits. The driver — `/usr/libexec/bunny-setup-drive`, shipped *on the
medium* — walks the real setup surface through AT-SPI: every stage of §53,
including typing the destructive confirmation phrase by hand
(`ERASE /dev/vda A0EDDF`). The harness reads the outcome over serial, powers
the machine off, and `build/scripts/verify-installed-choices.py` reads the
disk from outside against the journey's own `expected.json`. Completion is
claimed by the guest and proven by the disk; neither side is trusted alone.

## The journeys

| Journey | Choice under test | Driver outcome | Disk verdict |
|---|---|---|---|
| A | encrypted install, every stage | complete, 15 stages | findings `[]`; LUKS opens with the typed passphrase; boot entry; account `alex`; root locked |
| B | 200 % text, high contrast, reduced motion, 1024×768, encrypted | complete, 15 stages | findings `[]`; same properties as A |
| C | unencrypted, defaults changed nowhere | complete, 15 stages | findings `[]`; no LUKS, boot entry, `alex` |
| C-offline | journey C with **no NIC at all** | complete, 15 stages | findings `[]` — see `INSTALLATION_OFFLINE_REPORT.md` |
| D | wrong confirmation phrase | **refused-as-expected**, 14 stages | empty disk confirmed: no bootloader entry, no deployment — for this journey that reading is the pass |

First boot is a separate harness and report
(`INSTALLATION_FIRST_BOOT_REPORT.md`): journey A's disk booted twice without
the ISO, the passphrase typed at the console each time, both boots reaching
`graphical.target`.

## What it cost to get here

Journey A completed on run 27. The 26 runs before it were not noise; each
failed run surfaced a defect that is now fixed and regression-guarded. The
classes, briefly (details in the commit history between `352924c7` and
`b2dffa33`):

1. **The executor had never run.** `AnacondaDBusExecutor` fired storage tasks
   and forgot them — Gio proxy property caches never see task completion, so
   the choreography now subscribes to task signals before starting them and
   falls back to live `Properties.Get` polling.
2. **The medium fought the flow.** The `/mnt` → `var/mnt` symlink re-rooted
   `systemctl enable --root`; `chronyd` enable failed for a reason that was
   never mechanistically explained and is tolerated only when the unit is
   already preset-enabled on the target's own filesystem, with stderr
   captured (`installer/overlays/pyanaconda-core-service.py`).
3. **Anaconda assumes a human reboots.** Without that reboot the last `/etc`
   writes sat committed-in-journal but never checkpointed: the disk booted
   correctly while read-only inspection saw the past. The executor now runs
   both modules' `TeardownWithTasks` (on the base-module interface) and
   explicitly unmounts the target through `systemd-run`, because the
   backend's sandbox namespace is not the machine's.
4. **The verifier lied before the installer did.** qemu's write lock, a
   read-only LUKS mapping that silently blocks journal replay, list-filesystems
   omitting `crypto_LUKS`, and argon2id at default appliance memory each
   produced a confident wrong reading. The verifier now kills qemu first,
   reads through a throwaway qcow2 overlay with a writable `luks-open`
   mapping, detects LUKS by `vfs-type`, and retries once at 3 GiB.

## Supersession and one correction

The matrix rows `empty-uefi-disk`, `unencrypted-installation` and
`encrypted-uefi-installation` previously rested on direct `bootc install`
records (`qualification/installed-system/evidence/installs/`). They now rest
on these journeys — the same claims, established through the shipped
installer rather than around it. The old records stand untouched.

Journeys B and C briefly carried a weaker `installed.json` than they had
earned: the builder-side wrapper re-read each disk after the gate without
`--expected` and overwrote the gate's record. The gate-time output was intact
in `installed.log` throughout; the records were regenerated from the same
disks with the journeys' own expectations, and the wrapper now passes the
expectation. The evidence README records this correction in full.

## Open findings, carried forward honestly

- `/etc/locale.conf`, `/etc/vconsole.conf` and `/etc/hostname` are absent on
  installed targets. No gate fails because `expected.json` does not yet carry
  locale expectations; localization application is not proven.
- `/var/lib/bunny-setup/choices.json` is absent on targets — the §45
  first-run handoff has not crossed the reboot. First-login personalization
  is therefore still NOT ESTABLISHED (`INSTALLER_MATURITY_MATRIX.md`).
- The anaconda logs copied to the target are empty: anaconda's module
  processes have no log handlers. Failure evidence comes from the backend's
  own capture instead (`INSTALLATION_FAILURE_RECOVERY_REPORT.md`).
- The `encryption/luks-password-unlock` matrix row remains FAIL: it is bound
  to the installed-system harness and its (now-drifted) context, and clearing
  it takes a fresh installed-system round. Its *substance* no longer
  reproduces: both markers the FAIL recorded as absent — target reached and
  the boot health check finished healthy — are present on both boots of the
  journey-installed disk (`INSTALLATION_FIRST_BOOT_REPORT.md`).
- Journey A's exact medium was rebuilt away before its digest was archived;
  every property it demonstrated is re-proven by B and C on the preserved
  medium (sha256 `080b5e07…`, `iso-digest.txt`).

## Related

- `INSTALLATION_QUALIFICATION_REPORT.md` — the matrix view (5 of 12 scenarios
  resolved, 0 failing)
- `INSTALLER_MATURITY_MATRIX.md` — every §56 claim and its evidence level
