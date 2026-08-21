# What recovery means for this release class

Written before the Phase 7 recovery journey ran, and committed before the
recovery medium it names was built. The brief's §5: *"First define what
recovery means."* This file is that definition; the journey may pass or fail
against it, and may not redefine it afterwards.

## The claim being qualified

**A machine whose installed system cannot boot normally can be brought back
to a normally booting state using a separately built, independently booting
recovery medium, by a documented operator procedure.**

Nothing broader. In particular, Phase 7 does **not** claim:

- disaster recovery, re-imaging, or restore-from-backup — not implemented;
- automated recovery of an encrypted installation — recovery cannot unlock
  LUKS without the user's credential, by design (`docs/RECOVERY.md`);
- that the interactive recovery console has been driven — it reads from
  `/dev/tty1` and demands a typed `YES`; the journey drives the *documented
  operator steps* through an injected driver unit instead, and says so;
- a signed recovery medium — production signing is an external gate and the
  medium qualified here is **unsigned**; `vm-recovery-test.sh` runs with its
  signature requirement explicitly disabled and marks the run development
  evidence.

## The journey

    installed disk cannot boot normally        (measured: the boot is
          |                                     attempted and fails)
          v
    recovery medium boots independently        (the broken disk attached;
          |                                     recovery reaches its target)
          v
    the installation can be inspected          (deployments and identity
          |                                     read from the broken disk)
          v
    a recovery action is available and taken   (the boot entry is repaired,
          |                                     derived from the disk's own
          v                                     /ostree state, not a stash)
    the outcome is verified                    (the repaired disk boots
                                                normally to a healthy target
                                                on its own deployment)

The breakage is a corrupted BLS entry: the loader entry's kernel and initrd
paths are rewritten to name a checksum directory that does not exist. The
repair must derive the correct paths from what is actually on the broken
disk's boot partition. A repair that copies back a stashed copy of the file
would prove nothing about recovery and is refused by construction — the
harness deletes nothing it could stash.

## The medium's identity (§6)

The recovery medium is its own artifact, not the installation ISO assumed
sideways. Its record must carry: build commit, media digest, base image,
creation method (`build/scripts/build-image.sh recovery`), and boot
environment. The instrumented overlay used to drive the journey is a derived
artifact; both digests are recorded and the derivation script is committed.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| PASS | every journey step above measured, in order, on the named media |
| FAIL | any step contradicted — including the broken disk booting anyway (the breakage control), or the repaired disk failing to boot |
| NOT_RUN | a precondition absent; nothing may move to PASS by absence |

The breakage is itself controlled: if the "broken" disk reaches a healthy
target, the journey is FAIL — a recovery qualified against a disk that was
never broken is the update-harness mistake with new names.
