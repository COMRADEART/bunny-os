# Update and rollback, run for the first time

Both gates have read `NOT_RUN` since they were written. The recorded blockers
named missing inputs — a signed manifest, a previous disk — and both were true.
Neither was the reason. **The project had one build**, and "update to the next
one" is not a question a single artifact can be asked.

Phase 5 built a second one, so the questions can be asked. Some of the answers
are not the ones the tracker expected.

| | image | disk sha256 |
| --- | --- | --- |
| N | `localhost/bunny-os-beta:e906a48793d7` | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| N+1 | `localhost/bunny-os-beta:e501218f2fe0` | `b4dd95f3cb3f7d4b4419c120e04e4375f4a176f0fd0a0ee5f2c91ba5de99dcef` |

N's digest is the one Phase 4's own `BUNNY-MANIFEST.json` records, so the
archived artifact is the artifact — verified rather than assumed.

---

## 1. The update path is inert, by design, and that is the result

Both images ship:

```
/etc/bunny-os/update.json
  { "enabled": false,
    "channel": "developer",
    "manifestUrl": "https://updates.invalid.bunny-os.example/…/manifest.json",
    "imageRepositories": ["quay.io/comradeart/bunny-os"] }

/usr/share/bunny-os/update-keys/
  revoked-keys.json     {"schemaVersion": 1, "revokedKeyIds": []}
```

**No trusted signing key is installed.** `build/scripts/install_routes.py` has
exactly one route into that directory — `revoked-update-keys` — so the empty
trust store is by construction.

The shipped agent, run in a container made from the image so the code and the
paths are the device's:

| action | answer |
| --- | --- |
| `status` | `{"configured": true, "state": "idle"}` |
| `check` | `{"error": {"code": "not_configured", "message": "OS update checks are disabled"}}` |
| `stage` | `{"error": {"code": "not_configured", "message": "OS update checks are disabled"}}` |

It refuses at the first gate. Had it not, `_verify_signature` would refuse every
manifest at the second: `KEY_DIR / f"{key_id}.pem"` cannot exist for any key id.

**This is fail-closed and it is right** — §13 and §19 say there is no production
signing key and that creating one would be wrong. But the honest status is not
"blocked on infrastructure". It is: *the Alpha does not update, by design, and
the refusal is verified.*

### Two defects behind the recorded blocker

* `vm-upgrade-test.sh` **manifest mode could never have passed**. It looks for
  `validate_manifest`, `_validate_manifest` or `verify_manifest` and calls
  `validator(document)`. The one that exists is
  `_validate_manifest(manifest, config, enforce_new_sequence)` — three
  parameters. A supplied manifest would have produced a `TypeError`, not a
  verdict. The agent also reads `/etc/bunny-os/update.json` and
  `/usr/share/bunny-os/update-keys/` as absolute paths, so the mode cannot run
  on a builder at all.
* `status` reports **`"configured": true`** on an image where updates are
  disabled. The field is `CONFIG_PATH.exists()` — it means *the file is there*
  and reads as *this machine is set up to update*. Recorded, not fixed: the
  built artifact would no longer match its commit.

---

## 2. A real staged update

`stage-update.sh` boots N with N+1 attached on a second drive and lets the
**shipped `bootc`** stage it. Nothing is simulated.

```
BUNNY-P5-STAGE: attempt 1: bootc switch --transport oci /run/p5update/candidate:e501218f2fe0
BUNNY-P5-STAGE: attempt 1 SUCCEEDED
…
deployment entries: 2
```

The disk went from one deployment to two. That is the input both harness modes
have always wanted and never had.

**`--transport oci-archive` is advertised and does not work.** It is in
`bootc switch --help` alongside `oci`, `registry` and the rest; the guest
answered

```
Error: unsupported transport "oci-archive" for looking up local images
```

The drive therefore carries an OCI *directory*, converted with `skopeo copy`,
and `--transport oci` works. Worth knowing before designing an update route
around a flag that parses.

### `vm-upgrade-test.sh` staged mode: PASS

> Staged update PASSED: the new deployment boots and a rollback target is
> retained.

Attributed independently: the boot reports
`os-release commit=e501218f2fe0105e5fc92bdf94fd6b3c87d6c470`, which is N+1, and
`bootc rollback=localhost/bunny-os-beta:e906a48793d7`, which is N retained.

---

## 3. `vm-rollback-test.sh deployment-rollback` was passing without rolling back

This is the finding that matters most in this document.

The mode reported, three consecutive runs:

> Rollback PASSED: the previous deployment was selected and reached a healthy
> target.

It was not selecting anything. Every one of those boots came up on the
**default** deployment:

```
os-release commit=e501218f2fe0105e5fc92bdf94fd6b3c87d6c470   (N+1, every time)
cmdline    ostree=/ostree/boot.0/default/2d358243…/0          (identical, every time)
bootc      booted=/run/p5update/candidate:e501218f2fe0
           rollback=localhost/bunny-os-beta:e906a48793d7
```

The rollback target was sitting there, named, the whole time, and was never
booted.

**Cause.** The selection was:

```sh
guestfish --rw -a "${test_disk}" -m /dev/sda3 \
    write /grub2/grubenv "# GRUB Environment Block
saved_entry=1
"
```

A GRUB environment block is a fixed **1024-byte** record padded with `#`. A
40-byte file is not one, so GRUB ignored it and the machine booted its default.

**Why it passed anyway.** The only check was `bunny_boot_health` — *did the
machine reach a healthy target?* It did. A machine that never rolled back
reaches one perfectly well. This is §5 of the Phase 5 brief word for word:
*the grader must never interpret "the machine survived" as "the journey
succeeded".*

### The repair, and its negative control

Two halves, because fixing only the first would have produced a harness that
still could not tell:

1. the environment block is written in the format GRUB requires — a proper
   1024-byte padded record, uploaded rather than `write`-n;
2. **the deployment that booted is identified**, from the `ostree=` argument on
   the kernel's own command line, which the kernel prints to the serial console.
   `bunny_deployment_checksums` reads the candidates from the BLS entries and
   `bunny_require_booted_deployment` asserts which one came up.

The comparison is on the 64-character checksum, not the whole `ostree=` string:
bootc rewrites the `boot.N` component when the deployment order changes, so the
same deployment is `boot.0/<checksum>/0` in the BLS entry and
`boot.1/<checksum>/0` after a rollback. Comparing whole strings would report a
correct rollback as a failure.

Run against the same staged disk, the repaired harness says:

```
  booted the wrong deployment
    expected: dd33960330844f1ec11b6e93710464634d03be77bbcb9580480b16cfa08c892d
    observed: 2d358243c59de6e5a0e6672ca1ae3eec1f2972a8ac33907467cd6d9ffa657404
```

The false PASS is caught. **Even with a correctly padded block the selection
does not take on these images** — so the mode now exits **5, NOT_RUN**, and
names the route that works. Reporting a harness limitation as a product failure
would be the mirror image of the mistake being fixed.

---

## 4. A real rollback, by the route a device uses

`rollback-real.sh` does what the product documents: `bootc rollback`, then
reboot.

**Boot 1** — on N+1:

```
BUNNY-P5-STATE: os-release commit=e501218f2fe0105e5fc92bdf94fd6b3c87d6c470
BUNNY-P5-STATE: cmdline ostree=/ostree/boot.0/default/2d358243…/0
BUNNY-P5-ROLLBACK: running bootc rollback
BUNNY-P5-ROLLBACK: rollback exit=0
```

**Boot 2** — on N:

```
BUNNY-P5-STATE: os-release commit=e906a48793d74544b39c14cc3e35e0654f5311e2
                build=e906a48793d7.1786986334
BUNNY-P5-STATE: cmdline ostree=/ostree/boot.1/default/dd339603…/0
BUNNY-P5-STATE: bootc booted=localhost/bunny-os-beta:e906a48793d7
                      rollback=/run/p5update/candidate:e501218f2fe0
```

Three independent readings agree — the per-deployment `os-release`, the kernel
command line, and `bootc status` — and the booted/rollback roles have swapped.
**The product rolls back.**

---

## 5. §20's actual criterion: user state

> *A rollback that boots but loses user state is not automatically a PASS.*

State was written **before** the switch, in the places that matter, and read
back on every subsequent boot by a unit that reports to the serial console:

| file | stands for |
| --- | --- |
| `/var/home/p5-user-data.txt` | user data |
| `/var/lib/bunny-os/p5-settings.txt` | settings |
| `/var/lib/bunny-os/companion/p5-mode.json` | companion modes |
| `/var/lib/bunny-os/voice/p5-settings.json` | voice settings |
| `/var/lib/bunny-os/trust/p5-grants.json` | permissions and Trust state |

| boot | deployment | all five present? |
| --- | --- | ---: |
| staged deployment (`vm-upgrade-test.sh`) | N+1 | yes |
| rollback default | N+1 | yes |
| after `bootc rollback` | **N** | **yes** |

Nothing was lost. The mechanism is ostree's, and it is structural rather than
lucky: `/var` belongs to the *stateroot*, which every deployment of that
stateroot shares, so user state is not per-deployment and a rollback does not
reach it.

**One honest caveat.** The staging unit stayed enabled and ran again on the
first boot of the rollback run, rewriting the five files — so the copies read
after the rollback carry a `03:32` timestamp rather than the original `03:15`.
The pre-switch write is observed surviving the *switch* (the staged and default
boots read the `03:15` content); the post-rollback reading is of state written
on N+1 surviving the rollback to N. Both halves of the property are measured;
they are measured on two different writes. The unit that performs a one-shot
action should disable itself when it is done — `rollback.sh` does, and
`stage.sh` should.

---

## 6. What this closes and what it does not

| | |
| --- | --- |
| Boot parity, N and N+1 | **PASS** |
| Staged update exists, `bootc switch` | **PASS** |
| `vm-upgrade-test.sh` staged | **PASS** |
| `vm-rollback-test.sh` deployment-rollback | **NOT_RUN** — the harness cannot select; repaired to say so |
| Rollback by `bootc rollback` | **PASS** — attributed three ways |
| User state across the rollback | **PASS** — five of five |
| Manifest verification | **NOT_RUN** — no trusted key in the image, by design |
| `interrupted-download`, `expired-metadata` | **NOT_RUN** — need a reachable registry |

Neither gate is closed. The update gate cannot close while the image ships no
trust root, and that is the correct posture until a production key exists.
What has changed is that both now fail for reasons that were measured rather
than inherited, and one harness has stopped reporting a PASS it had not earned.

---

## 7. Reproducing

```
qualification/phase5/update/rollback-parity.sh    # N and N+1 both boot
qualification/phase5/update/stage-update.sh       # stage N+1 onto a copy of N
qualification/phase5/update/staged-tests.sh       # both harness modes
qualification/phase5/update/rollback-real.sh      # bootc rollback, two boots
qualification/phase5/update/update-probe.sh       # the agent, on the image
```

`state-fragment.sh` is the state written before the switch;
`reinject-state-report.sh` replaces the reporting unit in every deployment of an
existing staged disk, which is how the attribution was added without
re-staging.

Logs are under `logs/`. The staged disk itself
(`sha256:30209d0a7fc1a98a82ef1975051390737a016235d6a5c65e38680aa9dd6b6459` at
the time of the runs) is 2.9 GB and stays on the builder at
`/home/bunny/p5-work/stage/staged.qcow2`.
