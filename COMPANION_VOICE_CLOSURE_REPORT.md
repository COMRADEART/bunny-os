# Companion voice runtime — closure

Two gaps were left open when `feature/companion-voice-runtime` closed at
`b825dd4`, and both were of the same kind: something had been *claimed* by
inspection where it could have been *computed*, and the inspection was wrong.

1. The build-input closure analyser did not model `copy_python_package` and
   reported the voice runtime's build impact as **2 installed paths** when it
   was **22**.
2. Voice-produced viseme events had never been drawn by the real GTK character
   renderer. The voice runtime produced them and the renderer could consume
   them; the only timeline the renderer had ever been given was one a test made
   up.

This branch closes both, and repairs three further things that were found while
doing it — each of which was passing every test at the time.

---

## 1. Starting and final SHAs

| | |
|---|---|
| Branch | `fix/companion-voice-closure` |
| Based on | `b825dd4aa181c30e1f2eceb878c261ec2201b247` (verified: `git rev-parse` at start) |
| Prior gate commit | `0cf81a135b24619f74bbecfcdd48d3a69f33c2fd` |
| **Gate commit** | `60ba76e1176ca04ac44a9df158a1ad89776ec520` — every gate iteration records it |
| **Final SHA** | the evidence-and-report commit that follows the gate commit; §14. The closure over `60ba76e..final` is required to show 0 installed paths, and does. |

Everything the voice-runtime phase recorded is pinned by digest in
`qualification/companion-voice-closure/preserved-evidence.json` **before any
code changed**, and `tests/companion/test_voice_closure_evidence.py` fails if
any of it moves. That covers the 100/100, 50/50 and 20/20 gate records, both
measured defects with their guards, every `NOT_RUN` claim, and the phase report
itself — which may be appended to and not rewritten.

---

## 2. Analyser root cause

`build-input-closure.py` collected install routes by walking `install-root.py`'s
AST for calls named `copy_tree` or `copy_file`:

```python
if node.func.id not in ("copy_tree", "copy_file"):
    continue                       # <- before anything was recorded
```

`companion/` and `capability/` are installed by neither. They are installed by
`copy_python_package`, a third helper. The `continue` above ran **before** the
unresolved-call list was appended to, so the call did not appear in the list
that exists to say "the closure is incomplete". The analyser reported a complete
closure that was missing an entire Python package.

Reproduced mechanically, against `b825dd4`'s own installer, over the voice
branch's range `dfb0cd7..b825dd4`:

| | old analyser | corrected |
|---|---|---|
| installed | **2** | **22** |
| context-only | 22 | 2 |
| build-affecting | reported YES (from two `docs/`+`schemas/` files) | YES |

The twenty missed paths are the entire `companion/voice/` package plus
`companion/service.py`, `companion/protocol.py`, `companion/cli.py` and
`companion/character/lipsync.py`. `context-only` reads as *probably not in the
artifact*; the truth was that all twenty are copied to
`/usr/lib/bunny-os/python/companion/…` at mode 0444.

The failure mode matters more than the count. The analyser was wrong **quietly,
in the reassuring direction**: it did not say it could not tell.

---

## 3. Shared install-declaration design

A fourth name in the tuple would have fixed this instance and left the shape
intact. The install set is now data, in one place, read by both programs:

```text
build/scripts/install_routes.py          the declaration
        ├── build/scripts/install-root.py         executes it
        └── build/scripts/build-input-closure.py  classifies against it
```

* **67 declared routes**, four kinds — `file`, `tree`, `package`, `glob` — each
  carrying its destination, mode, profile set, exclusions and any per-name
  destination override.
* `installed_destination(route, path)` is the **only** implementation of "does
  this repository path reach the image, and where". The installer selects the
  files it copies with it; the analyser classifies changed paths with it. There
  is nothing left for the two to disagree about.
* It is a pure string function, so it answers for a path that no longer exists —
  which the analyser needs, because a *deleted* installed file is build-affecting
  and there is nothing on disk to look at.
* Semantics live on the route `kind`, not on a helper name, so a helper renamed,
  split or inlined moves no route.

**Fail-closed.** `audit_installer()` reads `install-root.py` and refuses it if it
installs anything the table does not describe:

* an install helper not in `COPY_HELPERS`/`INSTALL_STAGES`;
* a copy issued from outside a route stage — which is what stops `main` from
  installing something off-table;
* a stdlib copy primitive outside a modelled copy helper;
* a generated file written by an undeclared generator.

When it refuses, the analyser exits **2** and makes no claim at all. An
understated closure is worse than no closure: it licenses exactly the sentence
it cannot support. `b825dd4`'s own installer is refused by this audit.

**The installer rewrite changes no image.** Shown rather than argued: the route
table's install set was compared against the set `b825dd4`'s `install-root.py`
would produce, for every profile, as `(destination → source, mode)` triples.

| profile | paths | identical |
|---|---|---|
| developer | 610 | yes |
| minimal | 530 | yes |
| desktop | 610 | yes |
| recovery | 530 | yes |
| shell | 610 | yes |
| shell-test | 610 | yes |
| live | 623 | yes |
| beta | 617 | yes |

Zero differences in destination, source or mode.
`qualification/companion-voice-closure/install-set-equivalence.json`.

One behavioural improvement came with it: `systemd/user/**` used to be copied
into `/usr/lib/systemd/system/user/` and then deleted. The route excludes it, so
it is never written to the wrong place, and `assert_no_stray_user_units()`
asserts the outcome rather than trusting the exclusion.

---

## 4. Analyser mutation tests

`tests/image/test_build_input_closure.py`, 34 tests. The ones that matter are
mutations, because the old analyser also got most answers right and was silent
precisely where it was wrong.

| Requirement | Test |
|---|---|
| a package copied through `copy_python_package` is reported | `test_a_package_copied_through_copy_python_package_is_reported` |
| a changed file beneath that package is reported | `test_a_changed_file_beneath_that_package_is_reported` |
| an excluded test or bytecode file is not reported | `test_an_excluded_test_or_bytecode_file_is_not_reported` |
| a helper rename does not silently remove coverage | `test_renaming_the_helper_changes_no_classification` |
| an unknown copy helper fails closed | `test_an_unknown_copy_helper_fails_closed`, `test_a_refused_installer_produces_exit_two_and_no_claim` |
| a newly added install helper fails until modelled | `test_a_newly_added_install_helper_fails_until_modelled`, `test_the_modelled_helper_set_is_pinned` |
| the voice branch reports the complete installed-path set | `test_the_voice_branch_reports_the_complete_installed_path_set` |
| `66652d0..dfb0cd7` remains non-build-affecting | `test_the_pre_branch_range_remains_non_build_affecting` |
| `0cf81a1..b825dd4` remains non-build-affecting | `test_the_post_gate_range_remains_non_build_affecting` |
| a deliberate mutation to one voice module is reported | `test_a_deliberate_mutation_to_one_voice_module_is_reported` |

The last one edits `companion/voice/worker.py` on disk, runs the analyser over
`HEAD`, asserts exit status 1 and the path in the installed set, then restores
the exact bytes and asserts the restoration. `test_the_installer_selects_exactly
_what_the_analyser_classifies` walks every file the `developer` profile would
install — 500+ — and asserts the analyser agrees on each.

Three existing tests that grepped `install-root.py` for a substring now ask the
declaration instead. A substring is a fact about spelling; a route is a fact
about what gets installed, and the old form is how a test passes while the thing
it is about is broken.

---

## 5. Correct voice build-impact result

Mechanically derived. The manual count of "20 installed paths" recorded in the
voice-runtime phase is superseded by the computed **22**.

`dfb0cd7..b825dd4` — 41 paths examined, **22 installed**, 2 context-only, 17
unreachable:

| route | count | destination |
|---|---|---|
| `companion-package` | 20 | `/usr/lib/bunny-os/python/companion/**` (0444) |
| `documentation` | 1 | `/usr/share/doc/bunny-os/companion-voice.md` |
| `schemas` | 1 | `/usr/share/bunny-os/schemas/companion-protocol.schema.json` |

Profiles affected: all eight. `companion/` and `capability/` are installed
unconditionally.

The 2 context-only paths are `scripts/companion_stress.py` and
`scripts/voice_measure.py` — in the build context, installed by no declared
route, and requiring an empirical two-build comparison to be called
non-affecting.

---

## 6. Post-gate closure result

`0cf81a1..b825dd4` — 7 paths examined, **0 installed, 0 context-only, 7
unreachable**. The post-gate commits of the voice-runtime phase touched only the
report and the qualification evidence tree, neither of which is in any `COPY`
directive. Mechanically confirmed, exit status 0, and asserted by a test.

This closure's own post-gate commits are recorded in §14.

---

## 7. Multi-call executable tests

`resolve_executable` already returned the requested path rather than the symlink
target — the fix that stopped the runtime execing `pacat` under `paplay`'s name.
That fix is one line deep and rests entirely on nobody reintroducing symlink
resolution. Nothing downstream ever checked what was about to be started.

**A backend now declares a `PlayerContract`**: the program name `argv[0]` must
carry, the arguments that carry the semantics, the input format it expects, and
its completion floor. `verify_invocation()` checks the command against the
declaration before a process exists.

| backend | program | input format | multi-call siblings | required arguments |
|---|---|---|---|---|
| `pulse` | `paplay` | sound-file | `pacat`, `parec`, `parecord`, `pamon` | `--client-name=`, `--` |
| `pipewire` | `pw-play` | sound-file | `pw-cat`, `pw-record`, `pw-midiplay`, `pw-midirecord` | `--volume=`, `--` |
| `alsa` | `aplay` | sound-file | `arecord` | `-q`, `--` |

A refusal travels as `PlaybackHandle.start_error`, which the worker already
treats as a backend failure: typed degradation, caption retained, task
untouched. `Child` gained a `refusal` argument so a refused player reaches no
`Popen` at all — no process, no group, no pipe, no reader thread.

The synthesiser adapters get the same treatment on the identity axis:
`_program_name` records **which** of `espeak-ng`/`espeak` was resolved (different
programs, different exit-code bug), and `_guarded` refuses a substituted program
or an invocation missing `--stdin`, `--pipe-mode` or `--wait`. Without `--wait`,
`spd-say` returns when the server *accepts* the message, so every duration this
runtime measures would be a socket write rather than an utterance.

**The 60% floor is unchanged.** No measurement supports a tighter rule. What is
new is that a failure carries *which shape* it had:

| shape | when |
|---|---|
| `no-frames-accepted` | zero exit, ≤2% of the audio played |
| `container-read-as-raw-pcm` | zero exit, and the played duration matches the file's byte size at a raw reader's default rate |
| `exited-before-minimum-duration` | zero exit, short, matching neither |

The middle one is computed, not guessed: 123 524 bytes at `pacat`'s raw default
of 176 400 B/s is 0.70 s, and 0.73 s was observed. A named shape separates "a
busy server dropped the tail" from "the wrong half of a multi-call binary ran".

`tests/companion/test_voice_multicall.py`, 27 tests. Including the one that
would fail if the check were too strict: `/usr/bin/paplay` *is* a symlink to
`pacat` on the reference target, that arrangement is correct, and the runtime
must run it — under the name `paplay`.

One real bug was found writing these: the argument-presence rule was a prefix
match, so `--client-name=bunny-companion` satisfied a requirement for a bare
`--`, which is the argument that stops option parsing before a filename. It is
now exact unless the declaration ends in `=`.

---

## 8. Initialization rollback tests

Order is the fix; rollback is the backstop.

```text
1  validate-configuration
2  acquire-singleton
3  bind-endpoint
4  initialise-durable-state
5  construct-voice-worker
6  start-voice-worker
7  publish-readiness
```

The §18b defect was a voice worker started **before** the endpoint bind that
raises `DuplicateRuntime`. It was first fixed by unwinding the worker when the
bind failed — correct, and still here — but that treats a stranded thread as
something to clean up rather than something not to create. Both cheap refusals
now happen before anything owns a thread, a process or a device.

Three changes made that order possible:

* **`CompanionServer` accepts a deferred gateway.** The socket binds with
  nothing behind it; `attach()` supplies the gateway before `serve_forever`
  runs. Requests cannot reach a protocol with no gateway, and `start()` refuses
  without one rather than answering every request with an internal error — which
  reads to a client exactly like a runtime that is up and broken.
* **`RuntimeSingleton`** takes an exclusive advisory lock on `<endpoint>.lock`
  before the stale-endpoint probe. The probe alone is racy and the race is real:
  two services starting together both find no endpoint, both unlink, both bind,
  and the second unlinks the first's socket. The lock is held by an open
  descriptor, so a process that dies releases it and there is no stale state to
  reconcile; the file's continued existence is never consulted.
* **`VoiceService(start_worker=False)`** at step 5, started at step 6. A
  constructed worker owns a queue and no thread.

**The release order is not reverse-creation order**, and a test fails if somebody
simplifies it into one:

```text
endpoint → consent → voice-runtime → task-worker → durable-state → singleton
```

Each departure was measured. Endpoint first: a client connecting mid-teardown
should get a refusal, and releasing it last cost ten seconds of `socketserver`
poll intervals across the protocol suite. Consent before the task worker: a
plain reverse-creation unwind took that suite **from 16 s to 86 s**, because a
service with a pending approval waited out the whole consent timeout before it
could join its worker. Voice before the task worker, so shutdown is bounded by
the player's termination escalation.

`tests/companion/test_service_startup_order.py`, 19 tests. Failure is injected
after each of the seven steps by overriding the step method — no production
hook — and the same seven columns are asserted every time: no worker thread, no
child process, no socket, no lock, no temporary file, no audio handle, no timer.
Child processes are read from `/proc/self/task/*/children`; `waitpid(WNOHANG)`
would reap what it measured.

Voice preference ranges are now validated at step 1. `_build_voice` swallows
every exception on purpose — a missing synthesiser must never stop the service —
which also swallowed a volume of 4.0 into a silently voiceless companion.

---

## 9. Voice-to-renderer architecture

```text
canonical PresentationState
    → CompanionService.announce
    → VoiceService → VoiceWorker
    → a local synthesiser (eSpeak NG) → a private WAV, probed
    → companion.voice.visemes.from_amplitude  (40 ms windows over the samples)
    → VoiceEvent("viseme_timeline")  ── the whole timeline, once, live-only
    → companion.character.speech_link.VisemeLink   ← the new join
    → CharacterPresenter.start_lip_sync / advance_lip_sync
    → companion.character.lipsync.LipSyncController   ← decides the shape drawn
    → Animated2DRenderer.set_mouth_shape
    → Gtk.Picture.set_filename                        ← on the compositor
```

`VisemeLink` decides — ordering, staleness, bounds — on the **worker's** thread
and hands the survivor to `dispatch`, which is `GLib.idle_add` under a
compositor and direct invocation in a test. GTK is touched from the main loop
only. Nothing is scheduled with a timer: a mouth driven by a timer is a resource
that outlives whatever created it.

The worker gained the `viseme_timeline` event because a controller cannot be
driven from the frame stream alone — it takes a timeline and advances against a
playback position, and that is what makes its drift arithmetic mean anything.
Like `viseme`, it is delivered live and never retained: a few hundred mouth
events in a bounded ring would push out the events a person wants to read.

`CharacterRendererController.finish_lip_sync()` was added because completion is
not expressible as advancing past the end. An inactive controller's `advance()`
returns its current status, whose shape is the last shape it held, and the
renderer would be told to draw the mouth mid-syllable again.

**Authority.** The link imports no store, no runtime, no approval object and no
voice module; it may call exactly four presenter methods, all of them mouth. Both
are asserted from the import graph and the call graph.

---

## 10. Actual GTK viseme result

Run by `scripts/gtk_voice_viseme_probe.py` on the WSLg Wayland compositor, GTK
4.22.4, GLib 2.88, as user `bunny` from ext4, at the gate commit. eSpeak NG
1.52.0 through `paplay` onto one `RDPSink`. **Not a GNOME session, not physical
hardware, no physical speaker.** Full record:
`qualification/companion-voice-closure/evidence/gtk-voice-viseme.json`, gate
`passed: true`, zero failures.

Nothing in the chain is a fixture: the caption is a real `PresentationState`,
the audio is what eSpeak NG produced on the machine (91 523 frames — the sample
count), the timeline is the worker's own, and the file handed to
`Gtk.Picture.set_filename` is the asset the character package declares for the
shape the controller chose.

| §5 requirement | recorded |
|---|---|
| ≥2 distinct non-neutral shapes drawn | **4**: `closed`, `open-medium`, `open-small`, `open-wide` |
| frame changes while audio active | **58** mouth changes during the utterance |
| events ordered | sequences strictly increasing; asserted per frame |
| audio and viseme request IDs match | one request id across all timeline frames |
| renderer consumes the current revision | every frame at revision 1; after `publish(2)`, **132** stale frames refused, 0 drawn |
| cancellation stops further changes | 0 mouth changes after neutral |
| completion returns to neutral | `endedNeutral: true`, origin `neutral-on-completion` |
| worker restart returns to neutral | last shape `neutral` |
| renderer restart resumes or degrades explicitly | `degraded-to-neutral`, stated |
| no stale mouth state | teardown last shape `neutral` |
| zero GLib criticals | **0** critical or error records |
| no timer/callback survives teardown | 67 idle sources created, **0** surviving; 0 timeout sources; 0 voice threads remaining |
| captions correct regardless | present and matching for every scenario |

---

## 11. Synchronization measurements

All times are milliseconds from the probe's own monotonic origin, on the WSLg
host, one utterance (§15 says why this is not a distribution):

| measurement | value |
|---|---|
| audio started | 3469.104 |
| first viseme (worker event) | 3469.356 |
| first rendered mouth frame | 3469.933 |
| first-frame drift | 0.829 ms |
| **median presentation drift** | **2.797 ms** |
| **maximum presentation drift** | **5.708 ms** |
| median dispatch latency (main-loop marshal) | 2.788 ms |
| maximum dispatch latency | 5.510 ms |
| final neutral | 7659.410 |
| cancellation → neutral | **52.013 ms** (headless slice: 23.5 ms; the delta is the compositor's frame cadence) |
| sample count | 91 523 frames |
| scheduler-reported drift | 0 — structural, not a measurement (below) |

The timing method is **measured amplitude** over the synthesiser's own samples
in 40 ms windows. No phoneme boundary is measured anywhere in this build and no
phoneme-accurate lip sync is claimed.

Three things get called "drift" and only one of them is a measurement:

* **scheduler-reported drift** is structurally **zero** on the file-playback
  path. A one-shot player exposes no clock, so the worker passes the playback
  handle's position as both the timeline position and the audio clock. Reported
  with that stated, so nobody reads the zero as a result.
* **presentation drift** is the real one: how far a drawn mouth frame sat from
  the point in the audio it belongs to, from the audio start on this machine's
  clock. It includes synthesis-to-draw, the main loop and the compositor.
* **dispatch latency** is the part of that the probe added by marshalling onto
  the main loop.

---

## 12. Cancellation and neutral-reset results

On the compositor: cancellation was requested mid-utterance while the mouth was
moving; the neutral frame was drawn **52 ms** later; **zero** mouth changes
after it; the viseme that arrived after cancellation was refused with reason
`after-cancellation` and drew nothing. In the headless slice the same path is
23.5 ms. Every path that ends an utterance returns the mouth to neutral, and each is
covered twice — once on the compositor and once as a unit test:

| path | origin recorded |
|---|---|
| the utterance completes | `neutral-on-completion` |
| the utterance is cancelled | `neutral-on-cancellation` |
| the voice worker restarts | `neutral-on-restart` |
| the renderer restarts | `neutral-on-restart`, decision `degraded-to-neutral` |
| the link is closed | `neutral-on-teardown` |

A renderer restart **degrades explicitly** rather than resuming. The timeline
arrived in an event that has already been consumed, so resuming from an unknown
position would be a mouth moving to timing nobody measured. Asking for a resume
returns the degradation *with that reason*, so a caller is told rather than
silently given something else.

---

## 13. Negative renderer tests

`tests/companion/test_voice_renderer_link.py`, 32 tests. Every rejection is
counted under a name from a closed set — "the mouth did not move" and "a viseme
arrived after the utterance was cancelled" are different facts, and only the
second is useful.

| §6 case | reason recorded |
|---|---|
| renderer absent | `renderer-absent` |
| renderer disconnected | (frames stop; nothing drawn) |
| unsupported mouth shape | `unsupported-shape`, controller substitutes |
| character package lacks mouth assets | mouth holds neutral, frames still accepted |
| renderer crashes during speech | `renderer-failed`, counted, speech continues |
| renderer restarts during speech | `after-renderer-restart` |
| viseme after cancellation | `after-cancellation` |
| old request timeline during a new request | `stale-request` |
| out-of-order viseme | `out-of-order` |
| duplicate viseme | `duplicate` |
| excessive viseme count | `count-exceeded` (bound 4096) |
| audio completes before final viseme | `after-completion`, mouth already neutral |
| final neutral event lost | the settle emits neutral anyway |

In every one of them the caption and the task result are untouched, asserted
against a running worker rather than against the design.

Three of these reasons only exist because the first compositor run reported
counts that were not true — see §15.

---

## 14. Test results

Everything below ran on the reference target (Fedora 44 WSL, user `bunny`, ext4)
at the gate commit `60ba76e`, in one transcript
(`qualification/companion-voice-closure/evidence/gates.log`). Every §7 suite is
in it.

**The four stress gates** — installed voice, renderer *and* protocol/service
code changed, so §7 required the full rerun, on one exact commit:

| gate | result | per-iteration deltas | duration (median) |
|---|---|---|---|
| 100 consecutive voice-worker lifecycle runs | **100/100** | every column 0 | 3.02 s |
| 50 consecutive complete companion-suite runs | **50/50** | every column 0; one settled fixture (`review-local.slow-reviewer`, allocated once) | 35.07 s |
| 20 consecutive installed voice vertical slices | **20/20** | every column 0 | 4.73 s |
| 20 consecutive installed voice-to-renderer slices | **20/20** | every column 0 | 4.18 s |

All four `gateMet: true`, `singleCommit: true`, `commitsObserved: [60ba76e…]`.
Gate 1's `sinceBaseline` shows `tempDirectories: −5`: the machine got *cleaner*
— five stale workspaces left by gate runs killed mid-flight earlier in the day
were swept by `companion.voice.recovery`. Recorded under
`cleanupOfPriorResidue`, distinct from growth, because a gate that failed when
the machine got cleaner would be a gate nobody could satisfy twice.

**Suites, same commit, same transcript:**

| suite | result |
|---|---|
| repository validation | PASS — 15 validators, ShellCheck included on this host |
| build-input closure tests (34) | OK |
| analyser over `66652d0..dfb0cd7` | 0 installed — non-build-affecting |
| analyser over `0cf81a1..b825dd4` | 0 installed — non-build-affecting |
| analyser over `dfb0cd7..b825dd4` | 22 installed — build-affecting, all profiles |
| analyser over `b825dd4..60ba76e` | 13 installed — build-affecting, all profiles (this closure) |
| voice tests (311) | OK |
| renderer tests (247) | OK |
| start-up ordering tests (19) | OK |
| complete companion suite (961) | OK |
| capability suite (697) | OK |
| installed voice slice | 25 steps, passed |
| installed voice-to-renderer slice | 18 steps, passed, 2 stated NOT_RUN (pixels → probe; speaker → nobody) |
| compositor viseme probe | passed, zero failures, zero GLib criticals |

On Windows the same suites pass (3474 tests; one pre-existing, unrelated
display-stack test errors on `os.symlink` without privilege — it needs the
Linux run, which is the one §7 counts).

The two commits after the gate commit — the evidence and this report — are
confirmed non-build-affecting by the analyser (§6), which is the same closure
discipline the analyser itself was repaired to enforce.

---

## 15. Known limitations

**The three things the first compositor run said that were not true.** It passed
and its own counters disagreed with what had happened:

* `speech_degraded` was treated as terminal. It is emitted *during* an utterance
  and the utterance carries on; marking the request complete stopped the mouth
  for the rest of the speech — **146 frames** refused as `after-completion` while
  the audio was playing.
* A repeated sequence number was called a duplicate. The scheduler repeats a
  sequence whenever it is holding a shape, which is the ordinary case: **107**
  were counted and none was a duplicate of anything.
* The drift number was structurally zero and presented as a measurement.

And one that was true but useless: the first run put the first mouth frame
**500 ms** behind its audio and the ten after it within 0.4 ms of each other —
a compositor realising a window and then the queue draining at once, not a
synchronisation figure. The probe now warms the main loop before timing and
reports first-frame latency separately.

**Standing limitations:**

* No physical speaker has been validated, anywhere. The only working audio path
  on the reference target is the WSLg bridge onto one `RDPSink`.
* PipeWire and ALSA playback remain unexercised: the graph has zero `Audio/Sink`
  nodes and there is no ALSA card. The `pw-play`→`pw-cat` contract is declared
  and checked, and its playback has never been observed to work.
* The compositor is WSLg, not a GNOME session and not target hardware. No
  performance claim is made from it.
* The renderer restart degrades rather than resumes. Resuming would need the
  timeline carried across the restart, which this build does not do.
* Presentation drift is measured on one machine, one utterance length, one run.
  It is not a distribution.
* On Windows the child-process column of the start-up rollback tests reads zero
  because there is no `/proc`; the Linux run is the one that counts.

---

## 16. Remaining NOT_RUN items

Carried forward from the voice-runtime phase and **not** rewritten:

| item | status |
|---|---|
| a physical speaker | NOT_RUN — nothing in this build has ever driven one |
| PipeWire playback | NOT_RUN — no sink on the reference target |
| ALSA playback | NOT_RUN — no soundcard on the reference target |
| Speech Dispatcher as the *selected* provider | NOT_RUN — eSpeak NG wins selection on this host |
| phoneme or provider-native viseme timing | NOT_RUN — no provider in this build returns either |

Closed by this branch:

| item | now |
|---|---|
| compositor mouth animation driven by voice-produced visemes | **RUN** — §10, §11 |

New NOT_RUN items introduced here:

| item | why |
|---|---|
| the voice-to-renderer path on a GNOME session | the compositor available is WSLg |
| the mouth drawn from a *streaming* provider's utterance | Speech Dispatcher owns its playback and returns no samples; the estimated timeline is exercised by unit tests only |
| two runtimes racing the singleton on one endpoint | the lock is exercised directly; the race it closes has not been reproduced under load |

---

## 17. Reproducibility implications

**No reproducibility or release qualification is claimed by this branch.**

What can be said mechanically:

* The installer was rewritten and the install set is **byte-identical for all
  eight profiles** — same destinations, same sources, same modes (§3). The
  rewrite alone changes no image.
* The voice runtime's own change **is** build-affecting: 22 installed paths, all
  eight profiles. That was true at `b825dd4` and was misreported; it is now
  computed.
* This branch changes installed runtime code — 13 installed paths over
  `b825dd4..60ba76e`: `companion/service.py`, `companion/protocol.py`,
  `companion/cli.py`, `companion/vertical_slice.py`, four `companion/voice/`
  modules, four `companion/character/` modules and
  `/usr/libexec/bunny-companion-service` — so it is build-affecting on all
  eight profiles, and any reproducibility claim about it would need a fresh
  two-build comparison that has not been run.
* Every commit changes the OCI configuration digest through the revision label
  and `/usr/lib/bunny-os/release.json`. An unchanged layer digest is not an
  unchanged image.
* `build/scripts/install_routes.py` and the analyser are themselves
  **context-only** — visible to the build, installed by no route — the same
  classification `install-root.py` has always had.

The three-builder reproducibility result recorded elsewhere is about a different
commit and is neither extended nor invalidated here.
