# Installer storage safety report

§55.4. What stands between a person and an erased disk, and which of it has been
exercised.

Commit `cab7730b`. Evidence: `qualification/installer/backend-probe.json`,
`qualification/installer/setup-states.json`, `tests/installer/test_kickstart.py`,
`tests/installer/test_setup_flow.py`.

---

## 1. The chain, and where each link would break

A disk is erased only if **all** of these succeed. Each was checked
independently.

| # | Gate | Where | Exercised |
|---|---|---|---|
| 1 | The disk is not the installation medium, not read-only, not mounted, ≥40 GiB, plain (not RAID/multipath), and has a qualified sector size | `storage.safety.assess_target` | unit + rendered into the storage screen |
| 2 | A blocked disk is shown but **not selectable** | `setup_view.storage_screen` | `test_installation_media_is_shown_and_refused` |
| 3 | Review does not start an installation; it leads to the confirmation screen | `frontend/setup.on_action` | `test_review_does_not_start_an_installation` |
| 4 | The confirmation names *that* disk, because it is handed a `DiskInfo` | `setup_view.confirm_erase_screen` | `test_the_confirmation_screen_names_the_disk_the_plan_targets` |
| 5 | The typed phrase must equal one derived from the disk | `storage.safety.confirmation_phrase` | host-runtime, over the socket |
| 6 | **The backend re-derives and compares it against the plan it validated** | `storage.safety.assert_confirmed` | host-runtime: a wrong phrase was refused |
| 7 | The plan validates: target identity unchanged since probe, EFI+boot+system roles present, UEFI, LUKS2 if encrypted | `plans.validation.validate_plan` | host-runtime: `planValid: true` |
| 8 | The rendered kickstart names one disk and carries the medium's payload | `backend.kickstart.render` | unit + host-runtime |
| 9 | Anaconda parses the kickstart without error | `AnacondaDBusExecutor.install` | **not exercised** |

Gate 6 is the one that makes the rest safe. The surface sends the phrase as
typed; the backend re-derives it from the disk in the plan **it** validated. A
surface bug that enabled the button early produces a refusal, not an erase. From
the socket probe:

```
wrongPhrase: "destructive confirmation does not match the selected disk"
```

## 2. Nothing is preselected

`_installer_context` sets `selectedDisk` to `None`. A preselected disk is one a
hurried person confirms without reading, and §11 asks for a conservative storage
UI.

Entering the confirmation screen also **forgets any previously typed phrase**
(`self.secrets.pop("phrase", None)`), so a phrase typed for one disk cannot
unlock the button for another — `test_entering_the_confirmation_forgets_a_
previous_phrase`.

## 3. Blocked disks are visible, not hidden

A disk that cannot be installed to appears in the list, unselectable, with the
reason attached:

```
SanDisk Ultra USB 3.0 — 32.0 GiB — /dev/sdb
  available: false
  note: "The selected disk contains the running installation media."
```

Filtering it out would be a consequence hidden by omission — the person goes
looking for the disk they expected and finds an unexplained absence.

The same screen also surfaced a crash: with **zero** disks it built a `choice`
field with no options, which `Field.__post_init__` refuses. A machine with no
usable disk is a real state and §25 asks that it be explained; it is a screen
now, with a blocking warning, rather than an exception.

## 4. The words

§11 forbids hiding destructive consequences behind friendly language. The
confirmation screen says, in the danger role and in the announcement:

> Everything on QEMU HARDDISK — 80.0 GiB — /dev/vda will be erased. This cannot
> be undone.

and, when another operating system is present:

> It currently holds: Windows 11 Professional — Local Disk.

The Companion's line on that screen is *"This is the part I can't decide for you.
Read what's about to happen, then confirm it yourself."* — authored in
`companion_flow.py` as a `user`-authority stage, which `may_proceed` will not let
anything past without the named confirmation.

The story harness renders both the ordinary and the long-name cases (a 4 TB
retail SSD with an existing Windows installation) in all seven accessibility
configurations, so the sentence naming the disk is checked for clipping at 200 %
text and under high contrast rather than assumed to fit.

## 5. Encryption

LUKS2 only. The plan requires `recoveryKeyRequired` when encryption is enabled,
and the screen states plainly:

> If you forget the passphrase and lose the recovery key, the data is gone. Bunny
> cannot recover it and neither can anyone else.

`render` refuses a mismatch in either direction: an encrypted plan with no
passphrase, or a passphrase supplied for a plain plan. Both would otherwise
produce a document that either prompts unexpectedly at boot or leaves a disk
unencrypted while the review screen said otherwise.

## 6. The kickstart

Asserted as an **absence** as well as a presence — a document naming the right
disk *and* another one passes a presence-only check and erases two disks:

```
ignoredisk --only-use=vda
clearpart --all --drives=vda --initlabel
part /boot/efi --fstype=efi --size=1024 --ondisk=vda
part /boot      --fstype=ext4 --size=2048 --ondisk=vda
part /          --fstype=ext4 --grow --ondisk=vda --encrypted
                --luks-version=luks2 --passphrase='[redacted]'
```

`test_only_the_planned_disk_is_named` walks every `clearpart`, `part` and
`ignoredisk` line and fails on any mention of another device.

Injection is refused rather than escaped: kickstart is word-split, so a quote in
a display name is a new directive. `A'; reboot` is rejected at render, as are a
newline, a carriage return, an invalid username, a hostname with spaces, and a
target that is not a plain `/dev/<name>` device.

No `reboot` directive is emitted — §27 gives the restart to the person on the
completion screen, and a kickstart that rebooted would take the machine away
while they were still reading what happened.

## 7. §43, the disposable test disk

Checked on both sides of the boundary, and neither side is "the harness said so":

**Host** (`vm-install-story.sh`) creates the qcow2 itself, at a path under
`build/out`, and **refuses to reuse one that exists**. Reusing is how a run
reports a pass left over from the previous one.

**Guest** (`setup-drive.py`) independently refuses unless all three hold:
exactly one candidate matches the expected model; its size parses out of the
identity string and is within a GiB of what the host created; and the
installation medium is present in the list and not selectable. There is no branch
that proceeds without all three.

Journey D types a deliberately wrong phrase and asserts the destructive button
stays insensitive — a negative control inside the qualification run rather than
beside it.

## 8. What is not established

Gate 9 and everything after it. Anaconda has never parsed one of these
kickstarts, no partition table has been written, and no encrypted volume has been
created by this code. The §43 machinery has been written and not run.

The claim this report supports is narrow and worth stating exactly: **the
decision to erase a disk has been driven end to end over a real socket, and
refused when it should be.** Whether the erase then happens correctly is
untested.
