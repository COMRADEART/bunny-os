# Installer architecture report

§55.2. What the setup experience is made of, where the authority sits, and which
claims are backed by a run rather than by a reading.

Commit: `cab7730b`. Evidence: `qualification/installer/*.json`.

---

## 1. The division §2 asks for, and how it is enforced

§2 says the Bunny setup experience owns presentation and the installer engine
owns the disk. Stating that in a document is easy; the question is what stops it
being violated by the next change.

Four separate mechanisms, in increasing order of how hard they are to bypass:

| Boundary | Enforced by | What it would take to break |
|---|---|---|
| The Companion cannot decide a destructive action | `companion_flow.Stage.authority`; `may_proceed` returns `False` for a `user`-authority stage until its named confirmation is present | Adding the confirmation string to a call site — visible in a diff |
| A screen cannot hide a destructive consequence | `setup_view.Screen.__post_init__` refuses to construct a screen whose `danger` warning text is not inside its `announcement` | Removing a constructor invariant |
| A surface cannot name a disk the plan does not target | `confirm_erase_screen` takes a `DiskInfo`, not a string; `storage.safety.confirmation_phrase` derives the phrase from the disk | Passing a different disk object — which the plan would then reject |
| **The process drawing the buttons cannot write to a block device** | Separate processes: the surface runs as the live user, the backend as root behind an `AF_UNIX` socket | Changing the unit and the socket owner |

The fourth is the one that matters most, because it is the only one the kernel
enforces rather than the code. A setup surface that *could* partition a disk has
the authority whatever its source says.

## 2. The processes

```
┌──────────────────────────────────────────┐
│  bunny-setup            (uid 1000)       │   installer/frontend/setup.py
│  GTK4. Draws Screen records. Holds the   │   installer/setup_view.py
│  typed password and passphrase in        │   installer/theme_css.py
│  memory and nowhere else.                │
└───────────────┬──────────────────────────┘
                │  AF_UNIX, 0600, SO_PEERCRED + session token + nonce
                │  installer/frontend/client.py
┌───────────────▼──────────────────────────┐
│  bunny-installer-backend      (root)     │   installer/backend/server.py
│  InstallerService: parses, authenticates,│   installer/backend/service.py
│  validates the plan, re-derives and      │   installer/storage/safety.py
│  compares the confirmation phrase.       │
└───────────────┬──────────────────────────┘
                │  AnacondaAdapter
┌───────────────▼──────────────────────────┐
│  kickstart, rendered from the validated  │   installer/backend/kickstart.py
│  plan; written to tmpfs at 0600.         │
└───────────────┬──────────────────────────┘
                │  org.fedoraproject.Anaconda.Boss (private bus)
┌───────────────▼──────────────────────────┐
│  Anaconda                     (root)     │   the installer engine
│  Partitions, encrypts, deploys, installs │
│  the bootloader, creates the account.    │
└──────────────────────────────────────────┘
```

Nothing in the top box can reach the bottom one except through the two boxes
between, and each of those refuses independently.

## 3. What each layer refuses

Measured over a real socket by `build/scripts/installer-backend-probe.py`
(`qualification/installer/backend-probe.json`), with the recording executor
behind the gate so nothing was written:

| Attempt | Result |
|---|---|
| Connect from a different UID | refused (`SO_PEERCRED`) |
| Request with a wrong session token | refused — `authentication` |
| Replayed request (same nonce) | refused — `authentication` |
| `install.start` with a wrong confirmation phrase | refused — *"destructive confirmation does not match the selected disk"* |
| `install.start` with the correct phrase | accepted, status `installing` |
| Socket file mode | `0o600` |
| Disks named in the rendered kickstart | `--drives=vda`, `--ondisk=vda`, and nothing else |

The fourth row is §12 demonstrated rather than asserted. The phrase is
`ERASE /dev/vda 7D5628`, derived by `storage.safety.confirmation_phrase` from
the disk's own identity and size; the backend re-derives it from the disk in the
plan **it** validated. A surface that enabled its button early produces a refusal,
not an erase.

## 4. The kickstart, and the two things it will not do

The plan becomes a kickstart because that is the form in which Anaconda has
always accepted the division of labour: a document saying what is wanted, which
Anaconda validates and either performs or refuses. It is also the only form that
can be *read before it is run* — by a reviewer, by a test, or by a person
pressing "Installation details".

**It never composes a payload directive.** `ostreecontainer` decides which
operating system is written. Guessing how image-builder tagged the ISO would
produce an installer that writes something other than the system on the medium
and looks correct doing it. `payload_directives` extracts it from the medium's
own kickstart and `render` refuses outright if none is found. There is no
fallback string in the module.

**It refuses a document that sets any command twice.** Kickstart takes the last
occurrence, so a duplicate is not untidiness — it is a setting that reads one way
and behaves another. This was a real defect: the first render kept the medium's
`firewall --disabled` after its own `firewall --enabled`, and the document read
as hardened. `_assert_no_duplicate_commands` checks the **rendered output**
rather than the list of commands to suppress, because that list can fall behind
the list of commands emitted and the drift is invisible; output cannot drift from
itself.

## 5. Secrets

| Secret | Where it lives | Where it never goes |
|---|---|---|
| Account password | Hashed with libxcrypt (yescrypt) before it enters the document; `--iscrypted` | Protocol payloads (`protocol._contains_secret_field` refuses), setup state (`setup_state` refuses), audit log (`audit.redact`) |
| LUKS passphrase | In the rendered kickstart in the clear, because kickstart has no indirection for one — written to **tmpfs** at 0600 and unlinked in a `finally` | Any real disk; the redacted document used for logs and the advanced disclosure |
| Session token | `/run/bunny-installer/session-token`, 0400, owned by the live user | The socket's greeting — a client that could read the token from the socket it authenticates to would make the token pointless |

The passphrase file is destroyed on the failure path as well as the success one,
which is the case `test_the_passphrase_file_does_not_survive_a_failure` exists
for.

**Python 3.14 removed the `crypt` module** and Fedora 44 ships 3.14, so the
obvious import is gone on exactly the platform this executes on. Hashing goes
through libxcrypt by `ctypes` — the same library `/etc/shadow` is verified
against, so a hash it produces is a hash that logs in. A Python reimplementation
would be a second opinion about a password, which is not a thing to have two of.

## 6. Progress, and why there is no percentage

Two stage vocabularies exist and both are correct.
`backend.state.STAGES` has twelve entries because `WRITE_BOUNDARY` indexes into
them, and that index decides whether a failure screen says *"your data is
unchanged"* or *"your data is gone"*. `companion_flow.PROGRESS_STAGES` has seven
plain phrases because §23 also asks that the experience be understandable.

Unmapped they drift invisibly — Bunny says "Copying the system" while a partition
is formatted, and both are plausible. `backend/progress.py` maps them, is total
over the engine's stages, and fails at import if either list grows without the
other.

`InstallationState` exposes `overallProgress`. **Nothing in the setup surface
reads it.** `installing_screen` has no percentage field and
`test_no_progress_row_carries_a_percentage` asserts it stays that way. Per-task
detail comes from Anaconda's own `Progress` property, whose message is the
engine's sentence about what it is doing; the step number is not converted.

## 7. The Anaconda contract

Verified against **anaconda-core 44.30-2.fc44** by downloading the package and
reading `pyanaconda/modules/boss/boss_interface.py` and
`pyanaconda/modules/common/task/task_interface.py` — not by booting:

```
ReadKickstartFile(path: Str) -> Structure        (a KickstartReport)
CollectRequirements()        -> List[Structure]
InstallWithTasks()           -> List[ObjPath]

Task: Name, Progress, Steps, IsRunning (properties)
      Start, Cancel, Finish (methods)
```

`ReadKickstartFile` returning a report rather than nothing found a real defect:
the adapter discarded it, so a kickstart Anaconda could not parse produced no
error and the run continued to `InstallWithTasks` regardless. The report is now
read — `error-messages` non-empty means refuse, name the line, and state that no
disk was touched.

`AnacondaDBusExecutor.preflight()` still introspects the live Boss before acting.
Verifying against a downloaded package says what *this* Anaconda offers; the one
on the medium is what decides, and it need not be the same version. The refusal
names both what was wanted and what is offered.

## 8. What is not proven

§52's ladder, honestly applied:

| Claim | Level |
|---|---|
| Screens render, scale, and carry accessible names | HOST RUNTIME VALIDATED |
| The protocol authenticates, refuses replays, and refuses a wrong phrase | HOST RUNTIME VALIDATED |
| The kickstart names one disk and carries the medium's payload | UNIT TESTED |
| Anaconda accepts the kickstart | **not established** |
| A disk is partitioned, encrypted, deployed and made bootable | **not established** |
| The installed system boots and the choices persisted | **not established** |

`AnacondaDBusExecutor` has never run. Everything downstream of
`InstallWithTasks` is a design, not a result.
