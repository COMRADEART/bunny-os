# Live boot root cause: the installer medium had never reached userspace

Status: **BOOT ARTIFACT VALIDATED** at commit `7d33297`.
**VM BOOT VALIDATED is not claimed.** See §9.

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

## 7. Prevention

**Build-time.** `build-live-image.sh` fails if the regeneration record is
missing from the image, or if the assembled ISO does not pass
`check-iso-boot-artifacts.py`. Against the ISO that never booted, that check
returns 23 failures in **0.7 seconds**, naming both faults. An hour of VM time
is not the right instrument for a question an artifact can answer.

It checks what only the assembled medium can answer:

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

**Tests.** 58 across `tests/image/test_live_initramfs.py`,
`tests/image/test_iso_boot_artifacts.py` and
`tests/boot/test_boot_checkpoints.py`. The failure cases are the point: a
missing `dmsquash-live`; a missing `livenet`; a module named in the manifest
whose files are absent; a missing `squashfs.ko`; two kernel releases; a wrong
kernel/initrd mapping; a truncated archive; a stale initrd on an otherwise
perfect medium; `inst.stage2=` on a LiveOS medium; a label the command line does
not match; a missing live payload; a payload that is not a squashfs; a blank
frame where a menu should be; and an initramfs-only boot whose `Reached target
basic.target` must not be read as real userspace.

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
| IMPLEMENTED | dracut configuration and explicit regeneration exist |
| UNIT/BUILD TESTED | **met** — 58 tests; the checker fails the shipped artifact and passes the regenerated one |
| BOOT ARTIFACT VALIDATED | **met** — the ISO gate runs in the build and refuses an unqualified medium |
| VM RUNTIME VALIDATED | **not met** — no rebuilt ISO has been booted yet |
| INSTALLATION VM RUNTIME VALIDATED | **not met** — Journey A has not run |

**BOOT-CHAIN REPAIR STATUS = INCOMPLETE.** Bunny Setup has not appeared from a
rebuilt ISO.

**INSTALLER PHASE STATUS = INCOMPLETE.**

A boot menu is not a booted operating system. A dracut configuration file is not
an initramfs. An initramfs file is not enough unless it contains the capability
the kernel arguments depend on. And an ISO that builds is not evidence that it
boots.
