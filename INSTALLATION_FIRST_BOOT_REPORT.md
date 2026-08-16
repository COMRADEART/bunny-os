# First-boot persistence report

Date: 2026-08-16 (runs on 2026-08-15)  
Harness: `build/scripts/vm-first-boot.sh`  
Evidence: `qualification/installer-journeys/evidence/first-boot/`  
Result: **journey A's installed disk boots on its own. Twice.** Both boots
reached `graphical.target`; findings empty.

## Mechanics

The harness boots the installed disk **without the ISO** on a single
throwaway qcow2 overlay — one overlay across both boots, because persistence
between boot one and boot two is the thing under test. Each boot:

1. waits, then types the LUKS passphrase at the console through QMP
   (delays 35 s and 90 s, with a screenshot taken *before* typing so the
   prompt the passphrase answered is on the record);
2. waits for the guest to settle, then shuts down by ACPI;
3. after both boots, extracts the journal from the disk with guestfish
   (through the same writable-LUKS discipline the verifier uses) and reads
   it with `journalctl --directory` from outside.

The verdict is journal-derived, not screenshot-derived: two distinct boot
IDs, each reaching `graphical.target`.

```
bootsRequested 2   bootsObserved 2
boot 1  ecd3ad07…  reachedGraphical true
boot 2  e3534fbf…  reachedGraphical true
findings []
```

## What the screenshots show

`b1-t300.png` and `b2-t300.png`: the GDM greeter with the account created
during installation — **Alex** — and a focused password field, on both boots.

## What this does and does not prove

Proven: the installed system is self-sufficient (no medium present), the
LUKS volume opens with the passphrase chosen during setup on every boot, the
boot entry written by the installer is the one the firmware finds, and the
graphical session target is reached repeatably.

Not proven here: **nobody logged in.** The greeter is on screen and the
account exists on disk (`installed.json`), but an interactive login, the
first-run experience, and the personalization handoff
(`/var/lib/bunny-setup/choices.json`, absent — see the runtime report's open
findings) remain NOT ESTABLISHED. One disk (journey A's) was boot-tested;
journeys B and C's disks were verified from outside but not boot-cycled.
