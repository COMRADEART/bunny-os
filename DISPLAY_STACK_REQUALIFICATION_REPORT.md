# Display-stack requalification (dsq-2)

The corrected archive, measured by logging in.

| | |
|---|---|
| Scenario | `dsq-2` |
| Archive target | Commit O `93d1f6fb4f23f6533be37fe829f670ce0630de86` |
| Archive digest | `38ab0343c16f9528b95bcb180eb6999d406e0bbed96e5684f6f23333751cf3dd` |
| Installed-system target | Commit Q `12b5423b9f1b2fe4938bac393d8d65fb6b9fb47b` |
| Artifact | `bunny-os-93d1f6fb4f23.qcow2` `1290afe9eeb54b1d9f2385bc760d2ce5616d9580bc3b529ead5b55f6aa931249` |
| Evidence | Commit R `227d88290fcddd1c5b1c50829c556772c90c294c` |
| Machine | `pc-q35-10.2`, cpu `host`, QEMU 10.2.2 |

**Verdict: `firstLoginReliability: PASS`, 60 records, 0 unexplained failures.**

---

## 1. Why dsq-1 could not answer this

dsq-1 measured 60 boots and never logged in. `bunny-config-dir.service` and
`bunny-first-boot.service` are *user* units: without a session they do not run,
so the defect that mattered most was visible only as a unit that failed in a
journal nobody was reading — and a collector that read `UNIT` rather than
`USER_UNIT` reported the 60/60 failure as an empty list.

dsq-2 is the same five cells with a login, and with the filesystem read
afterwards to check what the login actually produced.

## 2. Results

```
                      A      B      C      D      E     total
collected            20     10     10     10     10     60/60
first-login PASS     20     10     10     10     10     60/60
second-login PASS    10      -      -      5      5     20/20
graphical.target     20     10     10     10     10     60/60
seat0 created        20     10     10     10     10     60/60
completion marker    20     10     10     10     10     60/60

226/NAMESPACE         0      0      0      0      0        0
chronyd 217/USER      0      0      0      0      0        0
chronyd in window     0      0      0      0      0        0
failed system units   -      -      -      -      -     none
home problems         0      0      0      0      0        0
```

Cells: A ordinary no-TPM cold boot; B TPM CRB with restored NVRAM; C TPM CRB
with fresh NVRAM; D 2 vCPU / 4 GiB; E network unavailable.

Against dsq-1 on the superseded archive: `bunny-first-boot.service` failed
**60 of 60** and chronyd failed **1 of 60**. Both are now zero.

### Unit dispositions, from the user journal

Every one of the 60 boots records both units as `activated-and-succeeded`
under the logged-in uid, read from `USER_UNIT`. On the 20 second logins
`bunny-first-boot` is correctly not re-run — its
`ConditionPathExists=!%h/.config/bunny-os/first-boot-complete.json` is
satisfied once the marker exists — while `bunny-config-dir` runs again and
succeeds, which is what an idempotent guard should do.

### The directory, read from the filesystem

Unit success does not establish what the directory *is*. Read offline from each
run's powered-down overlay, on all 60 boots:

```
.config/bunny-os        directory  0700  uid 4242  gid 4242  config_home_t
.config/systemd/user    directory  0700  uid 4242  gid 4242  systemd_unit_file_t
first-boot-complete.json           0600  uid 4242  374 bytes
```

Both SELinux types are what this image's own policy assigns — the deployment's
`file_contexts.homedirs` carries
`/var/home/[^/]+/\.config(/.*)?  config_home_t` and the more specific
`/var/home/[^/]+/\.config/systemd/user(/.*)?  systemd_unit_file_t`. An earlier
version of this check accepted only "home-ish" types and reported the correctly
labelled systemd directory as a mislabel; the expectation is now per path and
quotes the policy rule it came from.

Reading offline is deliberate. An in-guest check would run as the account under
test, through the session whose correctness is the question, and be reported by
the journal that is already the subject of the assertion.

### Second-login idempotence

20 runs performed a second login (A×10, D×5, E×5) by rebooting the same
overlay — a fresh overlay would have been a second *first* login. On all 20 the
directory inode, ownership and mode were unchanged and
`first-boot-complete.json` was preserved byte for byte. The inode is compared
as well as the content because a directory removed and recreated with identical
content is not a preserved directory, and that is the case a content-only check
cannot see.

## 3. chronyd ordering, stated as timestamps

dsq-1 could only observe the absence of a failure at a 1-in-60 base rate. Every
dsq-2 boot records the authselect apply window and chronyd's start request, so
the ordering is asserted from two measurements:

```
                          80 boots with both timestamps
chronyd start minus       min +0.009s   median +0.029s   max +0.254s
  authselect window end
authselect window width   min  0.070s   median  0.224s   max  0.773s
inversions                0
```

Per cell, the reduced-resource cell has the **largest** margin (median +0.103s
against cell A's +0.027s) and the highest minimum. That is the opposite of what
a fragile ordering would show, and it follows from the mechanism: the drop-in
makes chronyd wait on `nss-user-lookup.target` rather than race it, so a slower
machine delays chronyd along with everything else instead of narrowing a gap.

The margins are small in absolute terms and should not be read as headroom.
What makes the result solid is that the window is 0.07–0.77s wide — far larger
than any margin — and produced zero inversions across 80 boots. An accidental
ordering would invert as the window widened.

## 4. Firmware behaviour is unchanged

```
cell   expected resets   observed
A      0                 0 on 20 first boots, 0 on 10 second boots
B      0                 0 on 10
C      1                 1 on all 10
D      0                 0 on 15
E      0                 0 on 15
```

Cell C is the only cell whose firmware path differs, and it took exactly one
shim boot-option-restoration reset per boot and then completed the first login
normally — so the designed reset does not disturb the corrected path. Cell A's
second logins taking zero resets confirms a restored variable store stays
restored across a reboot.

## 5. The login fixture

Every boot injects a qualification-only account into its own copy-on-write
overlay: one account, a random password generated and discarded inside one
function, GDM automatic login, and an empty home. The product artifact ships no
account and no default credential, and that was verified in the disk under
test — `dsq-test` appears in neither `/etc/passwd` nor `/usr/lib/passwd`, no
`/etc/gdm/custom.conf` exists, and `/etc/skel/.config` contains only `mozilla`.

Every record states the account is test-injected and not part of the Bunny
artifact, and the gate refuses a record that does not.

## 6. Limitations

* **One host.** 60 independent boots, not 60 independent environments. The same
  distinction the reproducibility work draws between repeatability and
  independence applies here, and nothing in this pass establishes behaviour on
  another machine.
* **A test-injected login is not a user.** Automatic login is not the path a
  person takes; it exercises the session and the user units, not the greeter's
  credential flow. GDM greeter reliability is carried from the dsq-1 result.
* **Physical hardware remains NOT_RUN.** Everything here is QEMU with software
  TPM.
* **The NSS window is wider than chronyd.** Any unit whose `User=` resolves
  through the `altfiles` source during the authselect rewrite is subject to the
  same race. This pass corrects and measures the one unit that was observed
  failing; the sweep is recorded in `KNOWN_LIMITATIONS.md` and is not done.

## 7. Relationship to dsq-1

dsq-1's records are untouched and remain evidence about the b9c317d archive,
where the defect was real and measured. The two scenarios carry separate
authorities and separate evidence trees, and each gate refuses a record bound
to the other's artifact — so neither can be read as evidence about the other's
disk. `display-stack-reliability-gate` continues to report BLOCKED against
dsq-1's evidence, correctly: that gate is a statement about the superseded
archive. The corrected archive's verdict is the dsq-2 gate above.
