# First-login product correction

Scope: the correction of `bunny-first-boot.service`, which failed on 60 of 60
fresh homes in the dsq-1 diagnostic pass. Branch
`feature/first-login-product-corrections`, from the display-stack merge
`54907c30255c79f834fca2b71760b17ad78fed96`.

Status of this document: the correction and its mechanism are measured and
recorded below. Whether the correction *works on a booted installed system* is
the dsq-2 matrix (Stage 8), which is separate evidence and is not claimed here.

---

## 1. The defect

`bunny-first-boot.service` is a user unit. It declares:

```ini
ProtectHome=read-only
ReadWritePaths=%h/.config/bunny-os %h/.config/systemd/user
```

systemd builds the mount namespace **before** `ExecStart`. A path named in
`ReadWritePaths=` that does not exist makes namespace setup fail, the unit
exits `226/NAMESPACE`, and its `ExecStart` never runs.

Nothing on the b9c317d image created either directory. There is no
`/etc/skel/.config/bunny-os`, and no user-tmpfiles rule. The program the unit
runs, `/usr/libexec/bunny-first-boot`, creates the directory itself — with
`mkdir(parents=True)` — but it is never reached, because the unit dies on the
absence of the directory it was about to create.

Journal signature, from dsq-1:

```
Failed to set up mount namespacing:
/run/gdm/home/gnome-initial-setup/.config/bunny-os: No such file or directory
```

Occurrence: 60 activated boots, 60 failures, 0 successes, across all five
cells. Recorded in `qualification/display-stack/evidence/unit-dispositions.json`
as `GRAPHICAL_SESSION_DEFECT` / `CONFIRMED`.

**A second, unreported half.** The unit names *two* `ReadWritePaths`. The
second, `%h/.config/systemd/user`, is equally absent on a fresh home and fails
identically. dsq-1 only ever saw the first path named in the error because
namespace setup stops at the first failure. A correction that created only
`%h/.config/bunny-os` would have produced the same 226/NAMESPACE with a
different path in the message.

---

## 2. What the operating system actually does

Both facts below were measured on `quay.io/fedora/fedora-bootc:44`, systemd
259, before any correction was written. Both contradict a plausible design.

### 2.1 `/usr/lib/user-tmpfiles.d` is not a search path

`tmpfiles.d(5)` lists the `--user` search path as the XDG data and config
directories plus `/usr/share/user-tmpfiles.d/`. `/usr/lib/user-tmpfiles.d` is
**not among them**. Measured in the image:

```
/usr/share/user-tmpfiles.d       MISSING
/usr/lib/user-tmpfiles.d         MISSING
/etc/xdg/user-tmpfiles.d         MISSING
```

None of the three existed. A rule installed to `/usr/lib/user-tmpfiles.d`
would never be read, and nothing reports that a directory was not searched:
the failure is indistinguishable from having written no rule at all.

The rule is therefore installed to `/usr/share/user-tmpfiles.d/bunny-os.conf`,
and `build/scripts/install-root.py` refuses the build if it is absent.

### 2.2 The user-manager tmpfiles unit is enabled, but only by preset

`systemd-tmpfiles-setup.service` exists in the user manager with
`Before=basic.target` and `WantedBy=basic.target`. It is **not** enabled by a
`.wants` symlink shipped with systemd; it is enabled by
`/usr/lib/systemd/user-preset/90-systemd.preset`, which materialises
`/etc/systemd/user/basic.target.wants/systemd-tmpfiles-setup.service`.

Verified present in the built image. But it is `Wants=`, not `Requires=`, so a
tmpfiles failure does not stop `basic.target` being reached — the directories
can be absent while the boot proceeds normally.

### 2.3 `systemd-tmpfiles --user` exits 0 when it refuses

Measured against the candidate rule, one condition at a time
(`/root/ops/stage1-tmpfiles-probe.sh`):

| target state | tmpfiles exit | result |
|---|---|---|
| absent | 0 | created 0700, correct owner |
| valid directory with content | 0 | preserved, content intact |
| empty directory | 0 | unchanged |
| **owned by another uid** | **0** | **left as-is, ownership not corrected** |
| mode 0777 | 0 | corrected to 0700 |
| **regular file** | **0** | refused, not replaced |
| **symlink into the home** | **0** | refused, not followed |
| **dangling symlink** | **0** | refused |
| **symlink escaping to /root** | **0** | refused; target verified untouched |
| inaccessible parent (0000) | 73 | failed, directory absent |

Two consequences, and they are the whole reason the correction is two
components rather than one:

* For every unsafe path type, tmpfiles **refuses correctly but reports
  success**. `systemd-tmpfiles-setup.service` would be `activated-and-succeeded`
  with the directory absent, and `bunny-first-boot` would then fail
  `226/NAMESPACE` again — with no unit anywhere naming a cause.
* For a directory owned by another uid, tmpfiles **accepts it silently**. In
  `--user` mode it cannot `chown`, so it has no way to correct it and does not
  report that it declined to.

The refusals themselves are safe: nothing was written through the symlink that
pointed at `/root/secret-target`, which stayed empty.

---

## 3. The correction

Three parts.

### 3.1 `/usr/share/user-tmpfiles.d/bunny-os.conf`

```
d %h/.config/bunny-os 0700 - - -
d %h/.config/systemd/user 0700 - - -
```

Both `ReadWritePaths` entries, not just the one dsq-1 happened to name. Owner
and group are `-` so tmpfiles uses the invoking user: in `--user` mode there is
no other correct answer, and a literal user would bake a test identity into
the image. `%h` anchors every path on the home of whoever logs in.

This runs from the user manager before `basic.target`, for every user, at every
login — so it repairs an existing account that lacks the directory. `/etc/skel`
would not: skel is copied when an account is created and can never reach an
account that already exists.

### 3.2 `bunny-config-dir.service`

The assertion that the rule worked, and the component that handles what
tmpfiles silently declines to. It:

* creates either directory if absent, so it is also correct if tmpfiles never
  ran at all;
* **refuses a symlink** rather than following it — following would place Bunny
  configuration, and a bind mount writable by a sandboxed service, wherever the
  link points;
* **refuses a non-directory** rather than replacing it — it does not delete
  user data;
* **refuses a directory owned by another uid** rather than adopting it;
* corrects **only the mode**, which is a property of the directory alone and
  needs no recursion;
* never recurses, never deletes, never chowns.

Path safety is enforced with `lstat` followed by `O_NOFOLLOW|O_DIRECTORY`, and
ownership is judged from the `lstat` before any open — a directory owned by
another user is commonly 0700 and cannot be opened at all, so opening first
would report a bare permission error and lose the one fact that explains it.

The unit deliberately declares **no path-dependent sandbox directive** — no
`ProtectHome=`, no `ReadWritePaths=`, no `WorkingDirectory=`. Its entire purpose
is to make those paths exist; a path-dependent sandbox here would reintroduce
the same 226/NAMESPACE one unit earlier, where nothing is left to report it.
Its safety comes from its own code: two fixed relative paths, no recursion, no
deletion. `tests/first_login/test_corrections.py` fails the build if any such
directive appears.

Ordering is stated in both directions and does not rely on inheritance:

```ini
Wants=systemd-tmpfiles-setup.service
After=systemd-tmpfiles-setup.service
Before=bunny-first-boot.service
```

`Wants=` is load-bearing. The tmpfiles unit's presence depends on a preset this
repository does not own, and an `After=` on a unit absent from the transaction
orders nothing at all.

### 3.3 `bunny-first-boot.service`

```ini
Requires=bunny-config-dir.service
After=bunny-config-dir.service
Environment=XDG_CONFIG_HOME=%h/.config
```

`Requires=` rather than `Wants=`: if the directories cannot be made safe, the
unit must not start. A dependency failure names the unit that refused and why;
`226/NAMESPACE` names a path and explains nothing.

`ProtectHome=read-only` is unchanged and `ReadWritePaths=` is not widened —
neither to `%h`, nor to `%h/.config`.

The `XDG_CONFIG_HOME` pin closes a latent inconsistency found while reading the
program: `bunny-first-boot` resolves its destination from `$XDG_CONFIG_HOME`,
falling back to `~/.config`, while `ReadWritePaths=` can only name a path fixed
at unit load. A user with that variable set elsewhere would have the program
write outside the only writable path in its own sandbox. Pinning it makes the
sandbox, the tmpfiles rule and the program resolve to one directory.

---

## 4. Behaviour under every required condition

Measured end-to-end — tmpfiles then guard, as the boot runs them
(`/root/ops/stage1-guard-probe.sh`):

| condition | guard exit | outcome |
|---|---|---|
| absent (fresh home) | 0 | both directories created 0700, correct owner |
| valid directory with content | 0 | preserved; `first-boot-complete.json` intact |
| empty directory | 0 | reused |
| owned by the wrong uid | 1 | refused, ownership untouched, reason named |
| mode 0777 | 0 | corrected to 0700; contents' modes untouched |
| regular file | 1 | refused; file not deleted |
| symlink within the home | 1 | refused; link intact; target not written |
| dangling symlink | 1 | refused; missing target not created |
| symlink escaping the home | 1 | refused; `/root/secret-target` verified empty |
| inaccessible parent | 1 | refused with the parent named |

Idempotence, driven twice over a populated directory: same inode before and
after, `first-boot-complete.json` byte-identical.

Wrong-owner refusal message, verbatim:

```
bunny-config-dir: /home/bunnyprobe1/.config/bunny-os: is owned by uid 0, not by
uid 1001 who is logging in. Refused: this service does not take ownership of
another account's directory, and systemd-tmpfiles in --user mode does not
correct it either — it accepts such a directory silently and reports success,
which is why this check exists.
```

---

## 5. What the build now refuses

`build/scripts/install-root.py` fails the image build when any of these is
missing from the built filesystem, rather than trusting that the command which
should have created them exited zero:

* `/etc/systemd/user/graphical-session.target.wants/bunny-config-dir.service`
* `/etc/systemd/user/graphical-session.target.wants/bunny-first-boot.service`
* `/usr/share/user-tmpfiles.d/bunny-os.conf`

The tmpfiles rule is included for the same reason as the unit symlinks: it is
read from one search path, systemd never reports that it looked, and a rule in
the wrong directory is indistinguishable from no rule until a fresh home fails.

`build/scripts/ci-verify-units.sh` installs `bunny-config-dir` and copies
`*.service.d/` directories, both of which its explicit globs previously skipped.

---

## 6. Verification in the built image

From the archive built at Commit O
(`36736f369646e73a8c831578b267f72148f15e16af318677e13b870c72b84d08`):

```
/usr/share/user-tmpfiles.d/bunny-os.conf                     present
  d %h/.config/bunny-os 0700 - - -
  d %h/.config/systemd/user 0700 - - -
/usr/libexec/bunny-config-dir                                present, 0555
/usr/lib/systemd/user/bunny-config-dir.service               present
/etc/systemd/user/graphical-session.target.wants/            both units linked
/etc/systemd/user/basic.target.wants/                        tmpfiles unit linked
```

`bunny-first-boot.service` as shipped:

```ini
After=graphical-session.target
Requires=bunny-config-dir.service
After=bunny-config-dir.service
Environment=XDG_CONFIG_HOME=%h/.config
ProtectHome=read-only
ReadWritePaths=%h/.config/bunny-os %h/.config/systemd/user
```

CR bytes in every shipped unit and the tmpfiles rule: 0.

---

## 7. Tests

`tests/first_login/` — 46 tests, all passing on the Linux builder (one skip:
an inaccessible-parent case that root bypasses by definition).

* `test_corrections.py` — the rule creates every `ReadWritePaths` entry, is
  installed to a path systemd reads, hard-codes no user, is not skel-only;
  `ProtectHome=read-only` survives; `ReadWritePaths` is not widened; the
  dependency is pulled into the transaction as well as ordered; the guard
  declares no path-dependent sandbox directive; the guard never recurses,
  deletes or chowns.
* `test_config_dir.py` — the ten conditions above, driven against the real
  program, plus a mutation class that disables one refusal at a time and
  requires the unsafe state to then be accepted.
* `test_evidence_gate.py` — the dsq-2 gate rejections, including 226/NAMESPACE
  and a second login that repeats the first-run flow.

Source-reading tests strip comments and docstrings before matching. Without
that, the guard's docstring — which explains that tmpfiles cannot chown — read
as the guard calling `chown`, and install-root.py's diagnostic naming the wrong
tmpfiles directory read as installing there.

---

## 8. Limitations

* **Not yet observed on a booted system.** Everything above is the mechanism
  and its behaviour under direct test. The claim that a first login now
  succeeds on an installed system is Stage 8's, and is not made here.
* **SELinux context is asserted, not yet measured.** The guard does not set a
  context; it relies on the policy's default for a directory created under a
  home. `qualification/first-login/scripts/home_assertions.py` reads the actual
  context from each run's overlay and accepts `config_home_t`, `user_home_t` or
  `gconf_home_t`, always recording the measured value. Until the matrix runs,
  no context has been observed.
* **The guard runs as the user, in the user's own home.** Its `lstat`-then-open
  sequence closes the window between check and use, but it is not a privilege
  boundary: the account already owns everything under its home. The refusals
  exist to stop the *service* being pointed somewhere unintended, not to defend
  against the account itself.
