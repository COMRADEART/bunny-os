# Live boot root cause: the installer medium had never reached userspace

Status: **BOOT ARTIFACT VALIDATED**. The medium now boots through switch-root
into real userspace, where it meets a second and different fault. See §7a and §9.
**VM BOOT VALIDATED is not claimed.**

Scope: why the Bunny installation ISO reached a GRUB menu and stopped, in every
run ever recorded; the two wrong diagnoses made before anyone opened the
artifact; the repair; and the gates that exist so this class of fault is a build
failure rather than a boot failure.

---

## 1. Symptom

The medium reached GRUB and failed during the initramfs. The one decisive piece
of evidence was plain text on a screen:

```text
Failed to start initrd-switch-root.service
```

Everything up to that point succeeded, which is what made it durable:

| stage | result |
| --- | --- |
| `image-builder build … bootc-generic-iso` | exit 0 |
| ISO produced | 2,846,965,760 bytes |
| GRUB menu | drawn, five entries |
| kernel | loaded |
| `/images/pxeboot/initrd.img` | present, 116 MB |
| userspace | **never reached, in any recorded run** |

An earlier run of the installer harness spent fifty minutes at that menu, wrote
197 KB to an 80 GiB disk and reported `timeout` with no driver events. The
serial log was nineteen kilobytes of GRUB drawing a box.

---

## 2. Wrong hypothesis 1 — the `inst.stage2=` arguments

The boot entries said `inst.stage2=hd:LABEL=Bunny-OS-Beta inst.webui`. The
diagnosis was that the argument was wrong, and the entries were rewritten.

**The evidence that rejects it.** `inst.stage2=` is read by `anaconda-dracut`.
Against the initramfs on the medium:

```text
lsinitrd images/pxeboot/initrd.img | grep -c -i anaconda   ->  0
```

The argument was not failing. It was being ignored, because nothing in that
initramfs read it — and it was never going to be read, because `image-builder`
produces a **LiveOS** ISO (`/LiveOS/squashfs.img`, `/images/pxeboot/`) and not
an Anaconda `boot.iso`. The entries had been written for a medium this is not.

## 3. Wrong hypothesis 2 — `root=live:CDLABEL=`

The correction was to write LiveOS arguments instead:
`root=live:CDLABEL=Bunny-OS-Beta rd.live.image`. That is the right argument for
this medium and it would still not have booted.

**The evidence that rejects it.** `root=live:` is read by `dmsquash-live`:

```text
lsinitrd images/pxeboot/initrd.img | grep -cE "dmsquash|live"  ->  0
```

Two command-line changes, both reasoning about which string to pass to a program
that was not present. Measured afterwards with
`build/scripts/check-live-initramfs.py`, the shipped artifact's own module
manifest holds 63 modules including `ostree`, `qemu` and `qemu-net`, and does
not hold `dmsquash-live`, `livenet` or `overlayfs`.

**No kernel command line could have worked.** That is the useful shape of this
failure: both hypotheses were about the argument, and the fault was that nothing
could consume any argument.

---

## 4. Root cause

The required live-root dracut modules were never requested, and the initramfs
was never regenerated.

Traced rather than assumed. `image-builder` does not build the ISO's initramfs;
osbuild copies it out of the container image:

```text
copying '/run/osbuild/inputs/tree/lib/modules/7.1.5-200.fc44.x86_64/initramfs.img'
     -> '/run/osbuild/tree/images/pxeboot/initrd.img'
```

So the artifact that boots the medium is whatever sits at
`/usr/lib/modules/<kver>/initramfs.img` when the image is committed. Nothing in
the Bunny build ever wrote that file. It arrived prebuilt in
`quay.io/fedora/fedora-bootc:44`, and it records its own provenance:

```text
Arguments: --reproducible -v --add 'ostree' --tmpdir '/tmp/dracut' -f
           --no-hostonly --kver '7.1.5-200.fc44.x86_64'
```

`--add ostree`, and nothing else. No package this build installs triggers a
regeneration, and the repository shipped no dracut configuration at all —
`find . -name '*.conf' -path '*dracut*'` returned nothing.

`image-builder` states the requirement in its own binary:

```text
bootc container initramfs requires ostree, dmsquash-live and livenet modules
add_dracutmodules+=" qemu qemu-net livenet dmsquash-live "
* Rebuild the initramfs so that it includes the dmsquash-live module
```

### Why the configuration alone was not the fix

`installer/config/bunny-live-dracut.conf` was added at `20b4d13a` and recorded
there as necessary and not sufficient. That was correct: a `dracut.conf.d` file
is a set of instructions for the next dracut run, and there was no next run. The
file changed no byte of any artifact. Installing it and stopping would have
produced a build whose logs mention dracut modules and whose ISO is identical.

---

## 5. The mechanism, as it actually is

Established by reading dracut 108's own scripts out of the image, not from
memory. This is the authoritative description; competing accounts elsewhere are
superseded.

```text
GRUB   search --no-floppy --set=root -l 'Bunny-OS-Beta'
       linux  /images/pxeboot/vmlinuz root=live:CDLABEL=Bunny-OS-Beta rd.live.image
       initrd /images/pxeboot/initrd.img

parse-dmsquash-live.sh
       root=live:CDLABEL=X  ->  live:/dev/disk/by-label/X
       so X must equal the ISO9660 volume identifier exactly

dmsquash-live-root.sh
       mounts the medium at /run/initramfs/live
       loop-mounts /run/initramfs/live/LiveOS/squashfs.img
                   (rd.live.dir=LiveOS, rd.live.squashimg=squashfs.img, both defaults)
       then chooses a branch by what is inside it:

           if   [ -d …/squashfs/LiveOS ]  expects LiveOS/rootfs.img or ext3fs.img
           elif [ -d …/squashfs/usr    ]  FSIMG=$SQUASHED; overlayfs="required"
           else die "Failed to find a root filesystem in $SQUASHED."

       This medium takes the second branch: osbuild squashes the installer
       image's own root filesystem, so the squashfs has a top-level usr/ and no
       LiveOS/ inside it, and IS the root filesystem.

overlayfs  writable overlay over the read-only squashfs, mounted at /sysroot
switch-root into /sysroot
```

Two consequences worth stating because neither is obvious from the ISO layout:

* **`overlayfs` is required and nothing requests it by name.** It arrives as a
  `dmsquash-live` dependency, and the branch above sets `overlayfs="required"`
  explicitly. `check-live-initramfs.py` therefore asserts it even though
  `bunny-live-dracut.conf` does not ask for it.
* **`hostonly` must be off.** `dmsquash-live`'s own `check()` is
  `[[ ${hostonly-} ]] && return 1`, and `01-dist.conf` in the base sets
  `hostonly="yes"`. A host-only build does not produce a smaller initramfs; it
  produces one without the module that matters.

---

## 6. Repair

| # | change | file |
| --- | --- | --- |
| 1 | request `dmsquash-live`, `livenet`, `ostree`; `hostonly="no"` | `installer/config/bunny-live-dracut.conf` |
| 2 | install it at `/usr/lib/dracut/dracut.conf.d/95-bunny-live.conf` — after the base's 01–59 files, so it adds rather than races | `build/scripts/install_routes.py` |
| 3 | regenerate the initramfs explicitly, fail-closed | `build/scripts/regenerate-live-initramfs.sh` |
| 4 | call it after `install-root.py` and before `finalise-image.sh` | `build/Containerfile` |
| 5 | open the regenerated artifact and assert the capability | `build/scripts/check-live-initramfs.py` |
| 6 | carry the base's appended segment across the regeneration | `build/scripts/preserve-initramfs-tail.py` |
| 7 | qualify the assembled ISO before any VM starts | `build/scripts/check-iso-boot-artifacts.py` |
| 8 | refuse to report success on an unqualified medium | `build/scripts/build-live-image.sh` |

### Why dracut's exit code is not the gate

Measured inside the build container with the stock configuration and no Bunny
change involved at all:

```text
dracut-install: ERROR: installing '/root'
dracut[E]: FAILED: /usr/lib/dracut/dracut-install -D … -f /root
exit=0
```

dracut reports a failed install and returns success. (`dracut[I]: Detected wsl
container.` appears in the same run; the fault is in dracut's container
detection and predates this work.) It *does* return 1 for a module it cannot
find, so its exit code is checked — it is simply not sufficient, and the
artifact has to be opened. Those lines are recorded in
`/usr/share/bunny-os/live-initramfs.json` rather than treated as fatal, because
failing on them would block every build for a fault that does not affect the
artifact.

### What "structural check" means here

Not a grep for a string. Three layers, each able to fail on its own:

1. **dracut's own manifest.** dracut writes the list of modules it included to
   `usr/lib/dracut/modules.txt` inside the image. Membership is checked exactly.
2. **The files each module installs.** A name in a manifest is a claim;
   `var/lib/dracut/hooks/cmdline/30-parse-dmsquash-live.sh` is the thing that
   runs. Every path was read out of a generated artifact, not guessed.
3. **The kernel objects the mechanism loads.** `squashfs.ko`, `isofs.ko`,
   `overlay.ko`, `loop.ko`. Without `squashfs.ko` every module is present and
   the medium still does not boot.

Plus kernel association: exactly one release, and the one GRUB will boot.

### Two bugs found by running the checker against real artifacts

Both would have produced confident wrong answers, and neither would have been
found by fixtures alone:

* **An initramfs is not one archive.** The shipped one is three concatenated,
  with mixed compression — plain cpio at offset 0 (microcode), zstd at
  17,084,416, and a 171-byte gzip at 121,009,564. The first version of the
  reader decompressed "the part after the early cpio" and stopped. It failed
  outright on the shipped artifact and passed on the regenerated one, which
  happened to have no third segment; had a required module lived in an appended
  segment it would have been reported missing from an image containing it.
* **`/usr/lib/modules/keys/` is not a kernel release.** It holds signing
  certificates and is a sibling of the release directories. Counting it made a
  correct artifact report two kernels and fail the mapping check.

A third was found by the tests: a truncated cpio was read as a complete short
one, which is the same failure mode as the first — a partial file table read as
a whole one. The reader now requires the `TRAILER!!!` entry.

### The segment that regeneration would have dropped

dracut writes the microcode and the main archive and knows nothing about the
third, so regenerating loses it. It carries `dev/random` and `dev/urandom` as
character devices; a systemd initrd shadows both the moment it mounts devtmpfs,
so dropping them would very likely have changed nothing. They are carried across
anyway, because the intended change is "add the missing modules" and quietly
removing something else on the way is a second, undeclared change.

---

## 7a. What the repaired medium did, and the second fault

The first boot of the rebuilt ISO (commit `d6047b6`, ISO
`e7374d39c45d13f5fb9be7d7d2a529ae95042a437a8f1389edffaad430ad94df`) got six
rungs further than anything before it:

| | | |
| --- | --- | --- |
| BOOT-1 | firmware starts the medium | PASS |
| BOOT-2 | GRUB renders its menu | PASS — five entries, 43 s left on the timeout |
| BOOT-3 | the kernel starts | PASS — `Linux version 7.1.5-200.fc44.x86_64` |
| BOOT-4 | the initramfs starts | PASS — `dracut-cmdline`, `dracut-initqueue` |
| BOOT-5 | the live root is located | PASS — `Reached target initrd-root-fs.target` |
| BOOT-6 | `initrd-switch-root.service` | **PASS — this had never happened** |
| BOOT-7 | real userspace is PID 1 | FAIL |
| BOOT-8 | the graphical target | NOT-REACHED |
| BOOT-9 | the Bunny setup surface | NOT-REACHED |

The initramfs repair did what it was for. systemd re-executed in the real root,
loaded SELinux policy in 108 ms, printed

```text
Welcome to Bunny OS 0.3.0-beta (development)!
```

and then froze at 7.3 seconds:

```text
systemd[1]: Failed to set SELinux security context
            system_u:object_r:systemd_unit_file_t:s0 for /run/systemd/units:
            Permission denied
systemd[1]: Failed to allocate manager object: Permission denied
systemd[1]: Freezing execution.
```

### Root cause of the second fault

A bootc container carries no SELinux labels. Measured in the image:
`ls -Z /usr/bin/bash` prints `?`, and `getfattr` reports
`security.selinux: No such attribute`. ostree applies labels when it deploys,
and nothing deploys a live medium — so the squashfs of that tree is unlabelled
and the overlay root is `unlabeled_t`, which the guest's own audit records show:

```text
avc: denied { module_load } for pid=1 comm="systemd"
     path="/usr/lib/modules/…/vsock.ko.xz" dev="overlay"
     tcontext=system_u:object_r:unlabeled_t:s0 permissive=0
```

`/etc/selinux/config` says `enforcing`, so PID 1 cannot label the `/run`
directories it needs before it has a manager to do it with, and it freezes
before any unit starts.

### The evidence that decided it

Not a guess about SELinux. image-builder's own generated kernel options, present
identically in this build and in the archived one from before
`installer/config/iso.yaml` existed:

```json
"kernel": { "dir": "/images/pxeboot", "opts": [
    "root=live:CDLABEL=Bunny-OS-Beta", "rd.live.image",
    "quiet", "rhgb", "enforcing=0" ] }
```

`enforcing=0` is a literal string in the image-builder binary. `iso.yaml`
replaces the generated entries wholesale, so it replaced that too — silently,
because nothing had ever booted far enough for it to matter.

This is a property of the installation medium only. The system the medium
installs is an ostree deployment, labelled at deployment, running SELinux
enforcing. Nothing here changes that.

### Why the ladder was worth building

The previous harness had one outcome. On this run it would have said `timeout`,
after fifteen minutes, about a machine whose PID 1 had stopped at 7.3 seconds —
and the repair that had just succeeded would have been indistinguishable from
one that had not.

---

## 7b. The third fault: a unit cannot create the directory its own sandbox needs

With `enforcing=0`, run 2 (ISO `229dad10…`, commit `7502331`) reached BOOT-7.
It went on to a **text login prompt**: multi-user, not graphical.

```text
[FAILED] Failed to start bunny-live-session.service
[DEPEND] Dependency failed for bunny-installer-backend.service
[FAILED] Failed to start bootloader-update.service
[  OK  ] Started gdm.service - GNOME Display Manager
```

The name of a unit and nothing else, because a unit writes its reason to the
journal and the journal does not reach a serial console unless asked. So the one
thing a serial-reading harness could not see was *why* — which is what a
boot-diagnosis harness is for. `BUNNY_BOOT_APPEND` was added for it, and the
first version, which typed into GRUB's editor, did not work: GRUB's own
sixty-second timeout booted the selected entry first and the run came out as an
ordinary boot. The self-check is the only reason that is known rather than
assumed — the kernel prints the command line it was given, the appended text was
not in it, and the run exited 6 instead of being read as the run that was asked
for. It now extracts the medium's kernel and initramfs and boots them directly.

Run 4, a diagnostic boot of the same medium, answered it in one line:

```text
bunny-live-session.service: Failed to set up mount namespacing:
    /run/bunny-installer: No such file or directory
bunny-live-session.service: Failed at step NAMESPACE spawning
    /usr/libexec/bunny-live-session: No such file or directory
bunny-live-session.service: Main process exited, code=exited, status=226/NAMESPACE
```

systemd builds a unit's mount namespace **before** it runs `ExecStart`. A
`ReadWritePaths=` naming a path that does not exist fails the unit — and it
fails whether or not the program would have created that path, because the
program never runs. `/usr/libexec/bunny-live-session` begins by creating
`/run/bunny-installer`.

Everything visible on screen was three consequences away from that. The unit
creates the `bunny-live` account; without it GDM had nobody to log in,
`bunny-installer-backend` failed on a dependency, `graphical.target` was never
reached, and the medium offered a text login. Run 2 reported "BOOT-8 failed",
which was true and was not the fault.

`RuntimeDirectory=` instead, which systemd creates before the namespace,
preserved because the session unit is a `oneshot` whose marker file the backend
reads afterwards.

**The same shape, twice more, found by the gate written for it.**
`tests/boot/test_unit_runtime_directories.py` checks every unit in `systemd/`,
and found both within a second of being written:

* `bunny-installer-backend.service` named `/run/bunny-setup`, which nothing in
  the repository creates at all. It would have failed `226/NAMESPACE` the moment
  the session unit started working — that is, the moment anyone could have seen
  it.
* `bunny-update-agent@.service` named `/run/ostree-booted`. ostree-prepare-root
  creates that before switch-root on a deployment, and an installation medium is
  not one. `-` prefixed, which is what systemd provides for a path a unit wants
  only if it exists.

None of these three had ever run. That is the thread through this whole phase:
the initramfs modules, the SELinux argument, and these units were all shipped,
all plausible on inspection, and none had ever been executed by anything.

## 7c. The fourth fault: a file-level ReadWritePaths grants the part useradd does not use

With the namespace corrected, run 5's audit records show the proctitle as
`(bunny-live-session)` rather than a process that never spawned — the program
ran for the first time. It failed one line further on, and run 6's diagnostic
boot has it:

```text
bunny-live-session[1255]: useradd: cannot lock /etc/passwd; try again later.
KeyError: "getpwnam(): name not found: 'bunny-live'"
```

`ReadWritePaths=/etc/passwd /etc/shadow /etc/group /etc/gshadow` bind-mounts
those four inodes and leaves `/etc` itself read-only. `useradd` does not write
the databases in place: it takes a lock by creating `/etc/.pwd.lock` and
`/etc/passwd.lock`, and replaces each file by writing `passwd+` and renaming.
Every one of those needs the **directory**.

The message names `/etc/passwd`, which is the one thing that *was* writable.
That is the trap in miniature — a file-level `ReadWritePaths` looks like it
grants exactly what the program needs, and grants the part it does not use.

`ReadWritePaths=/home /etc`. `ProtectSystem=strict` still holds everywhere else,
and this unit's whole job is to add an account on ephemeral media.

## 7d. The fifth fault: `/home` is a symlink to `/var/home`

The `/etc` repair worked. Run 8's diagnostic boot shows `useradd` getting all
the way through the databases before it stopped:

```text
useradd[1266]: new group: name=bunny-live, GID=1000
useradd[1266]: new user: name=bunny-live, UID=1000, home=/var/home/bunny-live
bunny-live-session[1266]: useradd: cannot create directory /var/home/bunny-live
useradd[1266]: failed adding user 'bunny-live', exit code: 12
```

On an ostree system `/home` is a symlink to `/var/home`.
`ReadWritePaths=/home` grants the symlink's own path, not the directory anything
is created in, so `useradd` resolved the home to `/var/home/bunny-live` and met
a read-only mount. It then rolled its own work back — which is why `getpwnam`
still raised `KeyError` for an account whose passwd entry had just been written,
and why the surface error never named the real path.

`ReadWritePaths=/home /var/home /etc`.

### The family

Faults three, four and five are one mistake in three costumes: a sandbox
declared against the paths the code *appears* to use rather than the ones it
uses.

| | declared | actually needed |
| --- | --- | --- |
| namespace | `ReadWritePaths=/run/bunny-installer` | `RuntimeDirectory=` — the path must exist before ExecStart |
| lock | `ReadWritePaths=/etc/passwd …` | `/etc`, for `.pwd.lock` and rename-replacement |
| home | `ReadWritePaths=/home` | `/var/home`, which is what the symlink resolves to |

Each was invisible to inspection, each was found by the first thing that ever
executed it, and each surfaced only after the one before it was fixed.

---

## 7. Prevention

**Build-time.** `build-live-image.sh` fails if the regeneration record is
missing from the image, or if the assembled ISO does not pass
`check-iso-boot-artifacts.py`. Against the ISO that never booted, that check
returns 23 failures in **0.7 seconds**, naming both faults. An hour of VM time
is not the right instrument for a question an artifact can answer.

It checks what only the assembled medium can answer:

* every `root=live:` entry carries `enforcing=0` or `selinux=0` — the second
  fault above, made permanent, because the requirement lives in image-builder's
  defaults and Bunny overrides those defaults;

* GRUB's kernel and initrd exist on the medium and are one pair;
* the kernel release in the bzImage header matches the release the initramfs
  carries modules for;
* `root=live:CDLABEL=X` where X is the actual ISO9660 volume identifier, and
  GRUB's own `search -l` label agrees with it — a mismatch here is not an error
  on screen, it is a hang waiting for a `/dev/disk/by-label` entry that never
  appears;
* `/LiveOS/squashfs.img` exists and is a shape `dmsquash-live` accepts;
* both `EFI/BOOT/grub.cfg` and `boot/grub2/grub.cfg`, because an entry fixed in
  one and not the other is a medium that boots differently depending on the
  firmware it meets.

**Boot-time.** `build/scripts/vm-live-boot-checkpoints.sh` boots the medium with
**no disk attached** and classifies how far it gets across BOOT-1…BOOT-9, with a
screenshot before the first keypress. The previous harness had one outcome —
`timeout` — which cannot distinguish a machine that never started from one that
reached a session and idled.

**Unit sandboxes.** `tests/boot/test_unit_runtime_directories.py` fails any unit
naming a `/run` path in `ReadWritePaths=` without a matching
`RuntimeDirectory=`. It found two of the three instances itself.

**Tests.** 73 across `tests/image/test_live_initramfs.py`,
`tests/image/test_iso_boot_artifacts.py`,
`tests/boot/test_boot_checkpoints.py` and
`tests/boot/test_unit_runtime_directories.py`. The failure cases are the point: a
missing `dmsquash-live`; a missing `livenet`; a module named in the manifest
whose files are absent; a missing `squashfs.ko`; two kernel releases; a wrong
kernel/initrd mapping; a truncated archive; a stale initrd on an otherwise
perfect medium; `inst.stage2=` on a LiveOS medium; a label the command line does
not match; a missing live payload; a payload that is not a squashfs; a blank
frame where a menu should be; a live entry missing `enforcing=0`; and an
initramfs-only boot whose `Reached target basic.target` must not be read as real
userspace.

**Line endings.** `installer/config/** -text`. Under `core.autocrlf=true` four
of the six files there were already CRLF in the working tree and LF in the
index. `bunny-live-dracut.conf` is *sourced by dracut as shell*, so a trailing
CR makes `hostonly="no"` assign the non-empty string `no\r` — and
`dmsquash-live`'s `check()` is `[[ ${hostonly-} ]] && return 1`. A Windows
checkout would have produced a build that refused the one module the medium
depends on, and called it a module that cannot be found.

---

## 8. Correcting the prior record

Stated plainly, because the failed reasoning is the qualification evidence:

* **Prior ISO evidence proved GRUB and menu construction only.** It did not
  prove live userspace boot. No recorded run of this medium had ever reached a
  session.
* **"A 2.0 GB bootable ISO"** in `KNOWN_LIMITATIONS.md` (Public Alpha pass,
  2026-08-08) overstated what was measured. `image-builder` exited 0 and the
  Secure Boot binaries were byte-identical to their rpm-owned originals — both
  true, both about ISO *generation*. The medium was not booted. Corrected in
  place.
* **The first serious boot qualification is what found this.** The gap was not
  visible from the build, which succeeded, and not from the ISO, which was the
  right size and contained the right filenames.
* **Two kernel-argument diagnoses were made and rejected before the artifact was
  opened.** Neither was careless — each was correct about what its argument
  means. Both were reasoning about a program that was not in the initramfs. That
  is precisely why the new gate opens the artifact instead of reading the
  configuration that was supposed to produce it.

Nothing here was obvious from the start, and this document does not pretend
otherwise.

---

## 9. Evidence maturity

| level | state |
| --- | --- |
| IMPLEMENTED | dracut configuration, explicit regeneration, `enforcing=0`, corrected unit sandboxes |
| UNIT/BUILD TESTED | **met** — 73 tests; the checker fails the shipped artifact and passes the regenerated one |
| BOOT ARTIFACT VALIDATED | **met** — the ISO gate runs in the build and refuses an unqualified medium |
| VM RUNTIME VALIDATED | **partial** — BOOT-1…BOOT-7 met on a real boot. BOOT-8 and BOOT-9 not met |
| INSTALLATION VM RUNTIME VALIDATED | **not met** — Journey A has not run |

The fourth row is the one worth reading carefully. "The initramfs repair works"
is established: a real machine read `root=live:CDLABEL=`, assembled the live
root, switched into it and reached real userspace. "The medium boots to Bunny
Setup" is not, and they are different claims about the same run.

### Where each run got to

| run | commit | ISO | reached | stopped on |
| --- | --- | --- | --- | --- |
| 1 | `d6047b6` | `e7374d39…` | BOOT-6 | SELinux: PID 1 froze, `Failed to allocate manager object` |
| 2 | `7502331` | `229dad10…` | BOOT-7 | `bunny-live-session.service` failed; no graphical session |
| 3 | `6758090` | `229dad10…` | — | harness self-check: the appended arguments never reached the kernel |
| 4 | `6758090` | `229dad10…` | diagnostic | named the fault: `226/NAMESPACE` |
| 5 | `138201b` | rebuilt | BOOT-7 | the unit ran at last, and `useradd` could not lock `/etc/passwd` |
| 6 | `138201b` | run 5's | diagnostic | named the fault: `cannot lock /etc/passwd` |
| 7 | `d93c674` | rebuilt | BOOT-7 | `useradd` wrote the databases, then could not create the home |
| 8 | `d93c674` | run 7's | diagnostic | named the fault: `/var/home/bunny-live` |
| 9 | `7e822fe` | pending | pending | pending |

Each run reached one rung further than the last, and each fault was found by the
first thing that ever executed the code carrying it.

Every run's evidence is kept under `build/out/boot/<run>` — serial log,
screenshots, `run.txt` binding it to a commit and an ISO digest, and
`checkpoints.json`. No run's evidence was overwritten by the next (§18).

**BOOT-CHAIN REPAIR STATUS = INCOMPLETE.** Bunny Setup has not appeared from a
rebuilt ISO.

**INSTALLER PHASE STATUS = INCOMPLETE.**

A boot menu is not a booted operating system. A dracut configuration file is not
an initramfs. An initramfs file is not enough unless it contains the capability
the kernel arguments depend on. And an ISO that builds is not evidence that it
boots.
