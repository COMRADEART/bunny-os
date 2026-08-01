<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# BrlAPI requalification and installed-boot closure

Date: 2026-08-01
Status: **BrlAPI key generation, service activation and engineering
integration all PASS on the corrected image. Qualification candidate remains
BLOCKED at 3 of 14. Stable release remains NO-GO.**

## The four commits

```text
Commit G — corrected archive qualification target
  b9c317d35b85aa082904ecd40c4a54c81aded99a

Commit H — corrected archive three-builder evidence
  257c782177dabdbf18182cf6eab58be89d9389d0

Commit I — BrlAPI installed-system delta target
  3bbb0c54d3cd2027b0db97228929a0aacca49b01

Commit J — BrlAPI installed-system evidence import
  5e9e279ac29db89b8bb9b78ef98980e5622f29aa
```

The previous pass is untouched. Commit E (`d496e77`), Commit F (`f314864`)
and its summary (`5e1550e`) are ancestors of `main` through merge commit
`e32bb19`, unedited and unrelabelled. The archive they describe,
`619065e`, remains qualified as exactly one thing: the artifact that
exhibited the failure. Its disk artifacts still exist under their own names
and were not overwritten.

## The defect had three layers, and two passes found only one each

```text
layer 1   the unit's ExecStart named a program the build never installed
          — visible to CI, fixed in the previous pass

layer 2   nothing enabled the unit, and systemd disables what no preset
          names — invisible until an installed system was booted and its
          journal read, fixed at the start of this pass

layer 3   ConditionPathExists=!/etc/brlapi.key meant the unit skipped
          itself whenever the file existed, so an empty or malformed key
          was never repaired — found by reading the unit and the generator
          together, and only reachable because layers 1 and 2 were closed
```

Each layer alone was sufficient to leave a braille user without an
authorisation key for the whole session. The third was the most quietly
dangerous: it would have looked correct in every code review, and it
disabled the recovery path precisely when a key was corrupt.

## What was executed

```text
Source validation           validate, test, test-installer, test-phase5,
                            phase7 source-gate — every one exit 0
Adversarial tests           52 tests over the 20 specified cases, the static
                            half mutation-checked so it cannot pass vacuously
Local repeatability         run 15, 17 of 17, both builds shipped 9c328d04…
Three builders              local + hosted 30714175121 + hosted 30714176083,
                            all producing 29e54aaf…, all three pairs
                            REPRODUCIBLE, independence PASS
Archive verification        the correction read out of the archive's own
                            layers before any disk existed
Installations               three from the corrected artifact: two blank,
                            one offline with the container's network removed
Boots                       four: two first boots, an offline-installed
                            boot, a reduced-resource boot at 2 vCPU / 4 GiB,
                            and a reboot of installation A
```

## What it found

**Key generation: PASS.** Every installation minted a key. Thirteen
assertions pass on each: the unit enabled in the deployed filesystem, the
helper installed at mode 0555 root-owned and not writable, the unit executed
this boot and succeeded, the key present at 33 bytes, well formed, mode
0640, root-owned, and absent from the journal.

**Uniqueness and stability: PASS.**

```text
installation-a               b570c485048542d1…
installation-b               f41e4d7df5572015…
installation-offline         63c6dc02805bd1d8…
installation-a after reboot  b570c485048542d1…   unchanged
```

Three installations of one archive, three different keys. A reboot did not
rotate one. Both decided from SHA-256 digests; no key value was read,
compared or stored anywhere in this repository.

**Service activation: PASS.** The activation symlink exists in the built
filesystem, and `install-root.py` now refuses to produce an image where it
does not — the build fails where it is cheap rather than on a device where
it is silent.

**Engineering integration: PASS, with the limit stated.** No braille display
is attached, so this establishes key generation and service integration and
nothing about physical braille hardware.

```text
KEY_GENERATION_PASS
SERVICE_INTEGRATION_PASS
PHYSICAL_BRAILLE_DEVICE_NOT_RUN
```

**Failed units: recorded, classified, not dismissed.** Four boots of one
image disagreed about which units failed, which is itself the finding — the
previous pass booted once and could not have seen it.

```text
gdm.service                       intermittent, carried-over
avahi-daemon.service              intermittent, newly-observed
1.2-org.gnome.Shell.Screencast    carried-over
1.3-org.gnome.Shell.Screencast    newly-observed
bunny-first-boot.service          scenario-specific (offline install)
gnome-session-manager@…setup      scenario-specific (offline install)
```

A unit that fails in one boot and succeeds in another, from one image at one
commit, cannot have been caused by a change identical in both. That argument
is written into the record rather than left to the reader, and it applies to
`gdm` and `avahi` — not to the two offline-only failures, which are a real
finding this pass surfaced and the next one owns.

**TPM control: unchanged, as expected.** No TPM boots; a software TPM 2.0
still resets at GRUB. The BrlAPI correction did not affect it, and it remains
the next blocker rather than this pass's work.

**Applied SELinux delta:** the key is labelled `system_u:object_r:etc_t:s0`
on every installation, and 81,780 labels were collected. The global SELinux
prerequisite stays BLOCKED — this focused result does not resolve the
12,369-path backlog and is not offered as if it did.

## Gate position, calculated from evidence

```text
Source gate                     PASS      exit 0
Archive reproducibility         PASS      REPRODUCIBLE, independent
BrlAPI key generation           PASS
BrlAPI service activation       PASS
BrlAPI engineering integration  PASS
Physical braille hardware       NOT_RUN
TPM-attached boot               FAIL      unchanged, reproduced with control
Global applied SELinux          BLOCKED
Encryption                      NOT_QUALIFIED
Update / rollback / recovery    NOT_RUN
Physical hardware               NOT_RUN
Independent reviews             PENDING
Production signing              BLOCKED
Qualification candidate         BLOCKED — 3 of 14
Stable release                  NO-GO
Pilots                          BLOCKED
```

The count did not move. Closing an accessibility defect does not satisfy the
global accessibility prerequisite, which needs assistive-technology sessions
this pass did not run, nor any of the twelve others. The gate calculated 3
of 14 from the evidence; nothing here was arranged to make it say otherwise.

## Ordered work after this pass

```text
1. TPM 2.0 GRUB reset
2. GDM and GNOME screencast boot failures, now known to be intermittent
3. encrypted unlock reproducibility and KDF calibration
4. SELinux unresolved-path classification
5. test-only desktop login injected by the harness, never by the image
6. GNOME and Bunny desktop smoke tests
7. engineering accessibility flows
8. signed update staging and rollback
9. recovery ISO creation and execution
10. physical hardware
11. independent reviews
12. production signing
```
