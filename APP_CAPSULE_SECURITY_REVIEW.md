# Security review — App Capsules and the Bunny Trust layer

**Scope** `trust/`, `capsules/`, `catalog/`, `companion/capsule_bridge.py`,
`companion/trust_surface.py`, `companion/capsule_settings.py`,
`installer/companion_flow.py`, and the three new shell modules.
**Commits** `fc1e58a`, `adce2c5`. **Reviewer** the implementing engineer.
**Date** 2026-08-10.

This is a self-review and is labelled as one. `NEXT_PHASE.md` is already explicit
that a self-review is a self-review; `reviews/security/REQUEST.md` remains the
route to an independent one, and nothing here should be read as substituting for
it.

---

## 1. What is being defended, and against whom

The threat this phase exists to address is **an installed application that is
hostile, compromised, or merely careless**. It runs as the user, so it starts with
the user's rights unless something takes them away. Before this work nothing did.

Three actors, and what each is assumed able to do:

| Actor | Assumed capability |
|---|---|
| A hostile application | Any syscall its sandbox permits; any D-Bus message it can send; any string it can put in a portal request; unlimited attempts |
| A compromised permission surface | Draw anything, return any `UserAnswer`, at any time |
| A compromised AI provider | Propose any tool call, supply any parameter, any number of times |

Explicitly **out of scope**: a kernel-level compromise, a malicious Bunny OS
image, physical access, and a compromised `bunny-system-broker`. Those are
`docs/THREAT_MODEL.md`'s territory and unchanged.

---

## 2. Findings

### 2.1 Two defects found and fixed during implementation

**F-1 — A permission reason could contain a newline. (High, fixed)**

`trust/request.py`'s control-character filter excluded `\x0a` and `\x09`. An
application supplying `"Needs the camera\n\nAllow always (recommended)"` as its
portal-supplied reason would have that text rendered verbatim in the prompt body,
in the same typeface, directly beneath the genuine sentence. A person reading a
permission dialog is exactly the person who would act on a plausible-looking line
of guidance. Fixed at `trust/request.py` — every control character is now refused
and a test asserts it (`tests/trust/test_security.py::test_a_reason_may_not_carry_control_characters`).

Residual: the reason is still attacker-controlled *text*, bounded at 240
characters, quoted and attributed as *"The app says"*. That attribution is the
control; the text itself cannot be trusted and the design does not treat it as
trusted.

**F-2 — A standing allow was re-recorded on every use. (Low, fixed)**

`TrustGate._settle` created a fresh `Grant` whenever the scope was not `once`,
including when the allow came from an existing grant. The store grew by one record
per launch. Not a privilege escalation — every record was an identical allow — but
an unbounded permission database is both a denial-of-service surface and a
Settings page that becomes unreadable. Fixed; a test asserts four checks against
one grant leave one record.

### 2.2 One accepted weakness

**W-1 — `clipboard` and `bluetooth` are recorded and not enforced. (Medium,
accepted, disclosed)**

`CategoryDescriptor.enforced_by_default` is `False` for both. Wayland clipboard
mediation and a filtered BlueZ proxy are real work this phase did not do.

This is the failure mode §7 and §22 care most about, so it is handled by
disclosure at every point a person could form a belief about it: the prompt
carries an enforcement note in plain words *at the moment of deciding*; the
Settings row carries `enforced: false` and the mechanism; the isolation plan
carries `unenforced`; the task workspace carries a warning; and the capsule
overview carries a summary. Four tests assert the disclosure.

The alternative — omitting the categories entirely — was rejected: an application
would then be able to reach the clipboard with no record at all, which is strictly
worse than reaching it with a record and an honest label.

### 2.3 Attacks attempted, with results

§35's list. Each row states what was actually done and, where the answer needed a
kernel, says so instead of claiming a result.

| Attack | Result | Evidence |
|---|---|---|
| Path traversal in an artefact name (`../../etc/passwd`, `..`, `a/b`) | **Refused** at the boundary; an artefact is a *name*, not a path | `test_a_traversal_in_the_artefact_name_is_refused` |
| Path traversal in an application id (`../../etc`, `/etc/passwd`, `a/b`) | **Refused**; an id must match reverse-DNS before a directory name is derived | `test_an_application_id_can_never_become_a_path` |
| Symlink from a granted path to another file | **Resolved before storing**; one file is one grant | `test_a_symlink_resolves_to_its_target_before_anything_is_stored` *(skipped on Windows — see §4)* |
| Symlinked *parent* directory | **Resolved**; every component, not only the last | `test_a_symlinked_parent_directory_is_resolved_too` *(skipped on Windows)* |
| Symlinked artefact pointing out of the capsule | **Refused** by post-resolution containment | `test_a_symlinked_artefact_pointing_out_of_the_capsule_is_refused` *(skipped on Windows)* |
| Prefix confusion (`/home/bunny-evil` vs `/home/bunny`) | **Not contained**; comparison is by path component | `test_a_neighbouring_directory_with_a_shared_prefix_is_not_inside` |
| Granting a path inside another capsule | **Raises**, launch does not proceed | `test_a_path_inside_another_capsule_raises_rather_than_being_skipped` |
| Granting a credential directory (18 names) | **Refused at plan time** even with a user grant | `test_every_named_credential_directory_is_refused` |
| Environment-variable injection (`LD_PRELOAD`, `PYTHONPATH`, `http_proxy`) | **Absent**; the environment is a fixed eight-key map, built not filtered | `test_the_environment_is_built_rather_than_inherited` |
| Ticket replay | **Refused**, `replayed` | `test_an_answer_cannot_be_used_twice` |
| Answering a question that was not asked | **Refused**, `answer-mismatch` | `test_a_surface_cannot_answer_a_question_that_was_not_asked` |
| Widening a scope the prompt never offered | **Refused**, `scope-not-offered` | `test_a_surface_cannot_widen_a_scope_beyond_what_was_offered` |
| Stale approval after a timeout | **Refused**, `expired` | `test_an_expired_ticket_denies` |
| Permission surface crash | **Denies**, `surface-failed`, **writes no grant** | `test_a_surface_that_raises_denies_and_is_not_recorded_as_the_user` |
| Corrupt grant store | **Denies**, `store-unreadable`, checked *before* every other rule | `test_an_unreadable_store_denies_and_says_so` |
| Grant-store schema downgrade/upgrade | **Refused** rather than guessed | `test_a_store_from_a_newer_schema_is_refused` |
| Undeclared permission request | **Refused before any surface sees it**, `not-declared` | `test_an_undeclared_category_never_reaches_a_prompt` |
| Network-ceiling bypass (internet when allowlisted) | **Refused**, `beyond-ceiling` | `test_a_network_class_above_the_declared_ceiling_is_refused` |
| Allowlist widening (one host → two) | **Refused** | `test_a_wider_allowlist_than_declared_is_refused` |
| Lattice confusion (allowlist implies local network) | **Refused**; not a total order | `test_local_network_is_not_subsumed_by_an_allowlist` |
| Read grant used for a write | **Refused**; purpose widens one way only | `test_a_read_grant_does_not_authorise_a_write` |
| Export overwriting its own input | **Numbered instead**, original byte-identical | `test_an_export_with_the_same_name_does_not_replace_the_input` |
| Export outside the user's own folders (`/etc`, `~`, `~/.ssh`) | **Refused** | `test_a_destination_outside_the_users_own_folders_is_refused` |
| Export into another capsule | **Refused** | `test_a_destination_inside_another_capsule_is_refused` |
| Cross-capsule grant reuse | **Impossible**; grants key on application id | `test_a_grant_never_carries_between_applications` |
| `rm -rf` via a manipulated capsule root | **Refused**; three containment checks before any delete | `test_destroy_refuses_a_layout_whose_directory_is_not_its_own` |
| Reason forged by the model | **No such field exists**; four sources, none of them a model | `test_there_is_no_reason_source_for_a_model` |
| Newline-forged prompt line | **Refused** (F-1) | `test_a_reason_may_not_carry_control_characters` |
| User path leaking into a log | **Absent**; digest and short display only | `test_no_resource_identifier_reaches_the_activity_file` |
| Caller metadata leaking into a log | **Absent** | `test_request_metadata_never_reaches_the_record` |
| Silent sandbox downgrade to unconfined | **Refused**; explicit opt-in required | `test_the_non_confining_backend_is_never_selected_automatically` |
| Grant surviving into another login session | **Dropped on load** | `test_a_session_grant_does_not_survive_into_another_session` |
| Grant surviving an uninstall/reinstall | **Revoked first**, before the directory | `test_uninstalling_revokes_every_grant_and_removes_the_directory` |
| Shell injection through argv | **No shell anywhere**; every vector is a list to `execve` | `test_the_argument_vector_is_a_list_with_no_shell_anywhere` |

### 2.4 Attacks NOT attempted, and why

These are on §35's list and have **no result** here. Each needs a running kernel,
and a weaker test standing in for one would be worse than the gap.

| Attack | Why not attempted | What would settle it |
|---|---|---|
| Mount escape from a live `bwrap` sandbox | No sandbox has been started | VM procedure §3 |
| User-namespace escape | Same | VM procedure §3 |
| seccomp filter bypass | This phase installs no seccomp filter of its own; it relies on bubblewrap's and Flatpak's | VM procedure §3, plus a decision on whether Bunny should add one |
| Portal misuse (a capsule reaching a portal it was not granted) | No portal has been called | VM procedure §4 |
| D-Bus destination filter bypass | The `--talk-name` set is rendered, never applied | VM procedure §4 |
| IPC spoofing between capsules | Same | VM procedure §4 |
| Clipboard abuse | **Known unenforced** (W-1) | Implementation, then VM |
| Credential leak through the Secret Service proxy | The proxy destination is named in the plan; no proxy exists yet | Implement, then VM |
| Privileged-broker misuse via `sensitive_system` | No capsule has called the broker | VM procedure §5 |
| Malicious application metadata reaching a person | Catalogue entries are reviewed commits, not fetched — but a *hostile curated entry* is possible and is not modelled | A catalogue review process; currently one reviewer |

---

## 3. Design decisions that carry security weight

**The plan is additive.** `capsules/isolation.py` starts from nothing and only
grants add. The alternative — start from the user's home and subtract — fails open
on every forgotten check. This is the single most load-bearing choice in the
phase.

**Fail-closed paths write nothing.** A denial caused by a broken surface, a
corrupt store or an undeclared category creates no grant. The opposite would let a
transient dialog crash become a durable "the user said no", which is a denial of
service against the person and looks like their own decision in Settings.

**Enforcement and recording are separate fields.** `enforced_by_default` exists so
the honest answer is expressible. A model that could only say "restricted" would
force either a lie or a silent omission.

**The trust layer enforces nothing.** If `trust/` crashes, no permission widens,
because it was never what held one closed. §22's requirement is met structurally.

**`TrustGate.block()` can only deny.** There is exactly one way to write a grant
without a prompt and it produces a `deny`. A test asserts no `allow`-shaped method
exists on the gate.

---

## 4. Coverage gaps in the evidence itself

**Three symlink tests are `NOT_RUN`, not `PASS`.** They were skipped on this
Windows host, which does not grant symlink privilege unelevated. The symlink
attacks are among the most important in the table and their results above are
therefore *design claims*, not measurements, until the suite runs on Linux. This
project's own record (`source-gate-reference-measurement`) says a Windows host
hides real failures; this is that situation.

**Nothing has been observed enforcing anything.** Every row in §2.3 is a property
of a value — a plan, an argv, a store record. The claim "the home directory is not
mounted" is currently "no bind mount naming the home directory appears in the
plan". Those are different sentences and the second one is what is true.

**One reviewer.** The catalogue's `differences` paragraphs, the seventeen
categories' risk assignments and the credential-directory list are one person's
judgement with no second reader.

---

## 5. Recommendations, in order

1. **Run the suite on Linux, as `bunny`, on ext4.** Turns three `NOT_RUN` rows
   into results. Costs one command on the existing Fedora builder.
2. **Start one capsule for real** with `SubprocessExecutor` and verify from
   *inside* the sandbox: no home directory, the granted file present and
   read-only, `/dev/video0` absent, `LD_PRELOAD` unset. This converts §2.3 from
   design claims into measurements and is the highest-value single action
   available.
3. **Implement clipboard and Bluetooth enforcement, or move them behind a feature
   flag that hides them.** The disclosure is honest; two unenforced categories in
   a shipped permission model is still a liability.
4. **Add a second reader for the catalogue.** A curated entry is a security
   artefact and currently has one author.
5. **Send `reviews/security/REQUEST.md`.** This document does not substitute for
   it and says so.

---

## 6. Verdict

**No Blocker or High finding is open.** One High was found and fixed (F-1); one
Medium is accepted with disclosure at five surfaces (W-1); one Low was found and
fixed (F-2).

The design is sound on inspection and the fail-closed behaviour is thorough and
tested. **It has not been observed defending anything**, and until recommendation
2 is done, that is the honest summary of this review.
