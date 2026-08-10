# Companion Voice Runtime — phase report

Branch `feature/companion-voice-runtime`.

---

## 1. Starting and final SHAs

| | |
| --- | --- |
| Base branch | `fix/companion-pause-approval-consistency` |
| Expected starting commit | `dfb0cd7` |
| **Resolved starting SHA** | `dfb0cd71239d4ccef2a8821613e87efe4bba9723` |
| Working tree at branch creation | clean (`git status --porcelain` empty, untracked included) |
| **Gate commit** | `0cf81a135b24619f74bbecfcdd48d3a69f33c2fd` |
| **Final SHA** | `be2e3cf9db0fcf966703a0edcd67da38f69f2043` |

**Nothing installed changed after the gate commit.** The analyzer across
`0cf81a1..HEAD` examines seven paths — this report and six evidence artifacts —
and classifies all seven **unreachable** from the build, exit status 0. The code
the gates ran on is the code on the branch.

**Three earlier candidate gate commits were discarded rather than reported.**
Each one had passed the gates; each was thrown away because passing was not the
same as being right.

| Candidate | Gate outcome | Why it was discarded |
| --- | --- | --- |
| `65bdd63` | gates 1 and 3 green | Auditing §19's thirteen races against the suite found one untested and one covered only against a scheduler in isolation. A gate that did not run a test is not evidence for that test. |
| `ecc0afe` | gates 1 and 3 green | **The audio it measured was noise.** See §18a. Every latency figure on it was arithmetic about the wrong sound. |
| `af0025b` | **all three green** — 100/100, 50/50, 20/20 | The §22 thread-delta column showed **+101 threads and +100 live voice workers** across the fifty suite runs, while every test in every run passed. See §18b. |

The completed pause/approval branch was not modified. `feature/companion-voice-runtime`
was created from its exact head and every commit in this phase is on the new
branch.

### Pre-branch verification

1. **SHA resolved** — `dfb0cd71239d4ccef2a8821613e87efe4bba9723`.
2. **Working tree clean** — zero entries from `git status --porcelain --untracked-files=all`.
3. **No code or installed-path change after the gated commit `66652d0`.** The ten
   files changed in `66652d0..dfb0cd7` are two markdown reports and eight
   qualification evidence artifacts:

   ```text
   M COMPANION_LINUX_VALIDATION_REPORT.md
   M COMPANION_PAUSE_APPROVAL_REPORT.md
   M qualification/companion-linux/evidence/gate-installed-slice-20.json
   A qualification/companion-linux/evidence/gate-service-100.json
   A qualification/companion-linux/evidence/gate-suite-50.json
   M qualification/companion-linux/evidence/gtk-animation.json
   A qualification/companion-linux/evidence/linux-companion-suite.log
   A qualification/companion-linux/evidence/stress/06-final-service-100.json
   A qualification/companion-linux/evidence/stress/07-final-suite-50.json
   M qualification/companion-linux/evidence/stress/manifest.json
   ```

4. **Build-input-closure analyzer run across `66652d0..dfb0cd7`** — see §3.
5. **Result recorded** — §3.
6. **Prior evidence preserved** — `qualification/companion-linux/evidence/` is
   untouched by this branch. Nothing under it was modified, moved or deleted;
   `git diff --name-only dfb0cd7..HEAD -- qualification/` is empty.
7. **The completed branch was not modified.**

---

## 2. Branch lineage

```text
main
 └── … ── feature/companion-runtime-core        2f39d58
      └── feature/companion-runtime-integration 8ffc433
           └── feature/companion-character-renderer f6c2c02
                └── feature/companion-linux-validation 4f8ea55
                     └── fix/companion-pause-approval-consistency dfb0cd7
                          └── feature/companion-voice-runtime      (this phase)
```

---

## 3. Build-input closure

The analyzer (`build-input-closure.py`) is **not present on this lineage**. It
was added on `feature/capability-image-integration` and never merged to `main`,
so it was extracted from that branch and run against this tree without being
committed here — the pause/approval branch's working tree was returned to clean
immediately afterwards and the check produced no commit on it.

### `66652d0..dfb0cd7` — the pre-branch check

```text
build context roots: ARCHITECTURE.md, README.md, assets, build, capability,
  companion, config, desktop-integration, docs, installer, schemas, scripts,
  selinux, services, shell, systemd, tools

examined 10 path(s): 0 installed, 0 context-only, 10 unreachable

BUILD-AFFECTING: no installed path found          (exit status 0)
```

All ten paths are **unreachable** — absent from every `COPY` directive in
`build/Containerfile`, so they cannot affect the artifact by any route. This
mechanically confirms step 3: nothing after the gated commit `66652d0` reaches
the image.

The analyzer reported nine `copy_tree`/`copy_file` calls it could not resolve
from the AST (loop-driven destinations). That does not weaken this particular
result — the paths are outside the build *context* entirely, which is a stronger
statement than "not installed" and is decided by the Containerfile alone.

### `dfb0cd7..HEAD` — this branch

The analyzer's own answer:

```text
examined 33 path(s): 1 installed, 22 context-only, 10 unreachable
BUILD-AFFECTING: YES                              (exit status 1)

Installed into the artifact:
  schemas/companion-protocol.schema.json
    -> /usr/share/bunny-os/schemas/companion-protocol.schema.json
```

**That answer is incomplete, and the reason is worth recording.** The analyzer
models `copy_tree` and `copy_file` and does not model `copy_python_package`,
which is the function `install-root.py` actually uses to install the companion:

```python
copy_python_package(source / "companion", Path("/usr/lib/bunny-os/python/companion"))
```

So every `companion/**/*.py` file this branch touched was classified
*context-only* when it is in fact installed. This is precisely the failure the
analyzer was written to prevent — reading one route and stopping — reproduced
one level up, in the analyzer. The correction is recorded here rather than
asserted quietly, and the tool is unchanged on this branch because it does not
live on this lineage.

**The corrected installed set — 20 paths, verified against `install-root.py`
line by line:**

| Repository path | Installed as | Route |
| --- | --- | --- |
| `companion/voice/__init__.py` and 13 sibling modules | `/usr/lib/bunny-os/python/companion/voice/*.py` | `copy_python_package`, line 72 |
| `companion/character/lipsync.py` | `/usr/lib/bunny-os/python/companion/character/lipsync.py` | same |
| `companion/cli.py` | `/usr/lib/bunny-os/python/companion/cli.py` | same |
| `companion/protocol.py` | `/usr/lib/bunny-os/python/companion/protocol.py` | same |
| `companion/service.py` | `/usr/lib/bunny-os/python/companion/service.py` | same |
| `schemas/companion-protocol.schema.json` | `/usr/share/bunny-os/schemas/…` | `copy_file`, line 173 |
| `docs/companion-voice.md` | `/usr/share/doc/bunny-os/companion-voice.md` | `copy_tree`, line 174 |

**Not installed** (verified): `Makefile` and this report are outside every
`COPY` directive; `tests/**` is excluded by `copy_python_package`'s own
`tests`/`testing` filter *and* is outside the build context;
`scripts/companion_stress.py` and `scripts/voice_measure.py` are not in
`install-root.py`'s fixed `script_names` tuple, so nothing copies them.

There is also an **installed-path removal**: `companion/voice.py` no longer
exists and `companion/voice/` does. On a system built from this branch the file
`/usr/lib/bunny-os/python/companion/voice.py` is absent and the directory is
present. An in-place upgrade that left the old file behind would still import
correctly — CPython's path finder resolves a package directory before a
same-named module — but the stale file would be dead weight on a read-only root.

**Conclusion: this branch is build-affecting through 20 installed paths.**
§26's instruction is followed: no reproducibility candidate was created and no
previous evidence is claimed to cover it.

---

## 4. Voice architecture

Full description in `docs/companion-voice.md`. In brief:

```text
canonical presentation state → speech request builder → policy and capability
check → provider registry → dedicated voice worker → audio artifact or
provider-owned playback → audio output backend → playback events
                                                    ├── captions
                                                    └── generic visemes
```

Fourteen modules under `companion/voice/`, plus the original `SystemVoice` and
microphone boundary preserved unchanged at `companion/voice/system.py`. Every
prior importer of `companion.voice` continues to work.

The direction is one-way. The voice runtime holds no store, no task, no session
and no approval object, and `tests/companion/test_voice_authority.py::ImportBoundaryTests`
asserts that from the import graph — a voice module importing `companion.runtime`,
`companion.store`, `companion.task`, `companion.approvals`, `companion.executor`
or nine others fails the suite whatever it does with the import.

---

## 5. Provider interface

`ProviderDeclaration` declares: provider id, implementation id, languages,
locales, audio formats, sample rates, synthesis support, streaming support,
cancellation support, rate/pitch/volume control, local-or-remote, cost class,
maximum privacy class, authentication requirement, phoneme-timing support,
native-viseme support, and how the executable was resolved.

`VoiceProvider` is: `declaration`, `inventory()`, `health()`, `estimate()`,
`synthesize()`, `stream()`, `cancel()`, `close()`. No method takes a command, a
path or a URL.

`ProviderDeclaration.serves()` gathers **every** reason a provider may not take a
request rather than the first, and refuses a non-local provider outright.
`ProviderHealth` separates available / authenticated / healthy so a provider that
is installed but failing is distinguishable from one that is absent.

An unavailable provider **reports unavailable**. It does not raise on
construction and never succeeds with no audio.

---

## 6. Provider implementations

Two, both real, both exercised against the installed binaries.

**eSpeak NG 1.52.0** — synthesis to a private WAV, plus provider-owned playback.
653 voices enumerated from `espeak-ng --voices` on the reference target. Fixed at
22 050 Hz mono 16-bit, declared as such.

Two behaviours measured rather than assumed, and both are traps:

* empty input → exit **0**, no file written;
* unwritable output path → exit **0**, `Can't write to: …` on stderr, no file.

So success means there is audio in the artifact (`probe_wav`), not that the exit
code was zero.

**Speech Dispatcher 0.12.1** — stream-only through `spd-say`, with §7's ladder
mapped onto `--priority`, `--wait` on every utterance, `--pipe-mode` so the text
travels on stdin, and `cancel()` that both signals the client and runs
`--cancel` because the server keeps speaking after its client dies.

**No commercial adapter and no placeholder shaped like one.** There is no key
field anywhere in the package. A test walks every module's syntax tree with
docstrings removed and fails on any name mentioning a commercial provider; a
second test fails on any import of `socket`, `http`, `urllib`, `ssl`, `ftplib`
or `requests`.

---

## 7. Queue policy

Priorities: critical warning · approval required · task error · direct user
response · task result · progress update · decorative.

* Critical warnings interrupt ordinary speech; approval prompts interrupt
  progress narration; interruption requires **both** the policy and the rank.
* Cancelling a task stops that task's speech, queued and current.
* A **terminal outcome** — result or error — supersedes that task's queued
  narration. An interjection (warning, approval) does not: the task continues and
  what was queued is still true.
* Identical text is coalesced at both the caption ledger and the queue.
* Decorative speech is dropped under pressure rather than queued.
* Bounded at 32; a full queue drops its own least urgent entry and records it.

Ten dispositions, closed set: `queued`, `played`, `interrupted`, `cancelled`,
`superseded`, `dropped_by_policy`, `coalesced`, `failed`,
`degraded_to_captions`, `expired`.

---

## 8. Audio backend

Three backends over the facilities the platform already has — PipeWire
(`pw-play`/`pw-dump`), PulseAudio-compatible (`paplay`/`pactl`), ALSA
(`aplay`) — driven through the same allowlisted argv-only runner. Discovery,
default device, explicit device, health, playback, pause (`SIGSTOP`), resume
(`SIGCONT`), stop, volume, completion, removal, restoration, and a *requested*
output latency reported as requested rather than as measured.

### The host stack, labelled accurately

Fedora Linux 44 (WSL), user `bunny` (uid 1000), ext4 under `/home/bunny`:

| Backend | State | Evidence |
| --- | --- | --- |
| PipeWire | present, **zero sinks** | `pw-dump` answers; no `media.class = Audio/Sink` node |
| Pulse-compatible | **working, selected** | `pactl`: `Server String: unix:/mnt/wslg/PulseServer`, sink `RDPSink`, `s16le 2ch 44100Hz` |
| ALSA | **no card** | `aplay -l`: `no soundcards found` |

This is the **WSLg audio bridge** — a PulseAudio protocol socket onto an RDP sink
carried to the Windows host. **No physical speaker was validated.** Every emitted
document carries `physicalSpeakerValidated: false`.

Two of the three backends genuinely fail on this host, so §10's fallback and
degradation paths are exercised by the machine rather than by a mock.

Loss handling: stop safely, keep captions, emit a typed degradation record, fall
back once, otherwise captions. Backoff 2 s doubling to 60 s on the monotonic
clock; restoration needs two consecutive healthy discoveries.
`DegradationRecord` *refuses construction* with `task_affected=True`.

---

## 9. Caption synchronisation

Captions are authoritative. Speech consumes the caption or a sanitized
derivative and carries `caption_reference` back to it. Which sentence is the
caption follows `bubble_request_for`'s order exactly, so the bubble and the voice
say the same thing.

Measured per utterance: caption-to-audio offset, viseme-to-audio offset,
synthesis latency, time to first audio, neutral-reset delay, caption
finalisation delay. An unmeasured offset is `None`, never zero.

Tolerances (development environment, RDP audio hop): caption leads audio by
0–2000 ms; viseme within ±120 ms; neutral within 250 ms; caption finalised within
1000 ms.

Replay does not re-speak: `speak_once` refuses a caption already spoken, and only
an explicit `replay: true` from a person overrides it.

---

## 10. Viseme integration

Generic shapes from the existing renderer vocabulary. Every event carries request
id, sequence, monotonic offset, duration, mouth shape, confidence and source
method.

| Source | Confidence | Produced here |
| --- | --- | --- |
| provider-native | 0.95 | **No** — `from_provider_timing` raises |
| phoneme | 0.90 | **No** — `from_phoneme_timing` raises |
| amplitude | 0.60 | **Yes** — RMS of the samples that will be played |
| text-estimate | 0.35 | **Yes** |
| speaking-state | 0.15 | **Yes** |

The two that raise do so rather than fabricating: eSpeak NG prints phoneme
*names* without times, and labelling an estimate `phoneme` would claim the
second-highest confidence in the table for arithmetic no better than
`text-estimate`.

Ordered offsets, bounded at 8192 events, terminal neutral on every path,
cancellation, drift detection that degrades to speaking-state after three
consecutive readings beyond tolerance, and a renderer restart that re-enters the
timeline at the current index rather than replaying it.

`smile` is never generated — it is an expression, and the canonical phase already
drives expression.

`companion/character/lipsync.py` gained one source name, `text-estimate`, and a
`LIP_SYNC_SOURCES` constant. That is the only change to the renderer.

---

## 11. Capability degradation

Signals read from `capability_bridge.capability_signals` — the same reading the
router used — plus audio availability and provider availability. Nothing
re-measured.

Outcomes: `local-neural-or-system-voice`, `local-lightweight-voice`,
`captions-only`, `silent-text-only`. No named machine modes.

Descent: no provider → captions; no sample-yielding provider → lightweight with
text-derived visemes; no device → captions; <192 MiB → lightweight; <64 MiB →
captions; low CPU or ≥2 running tasks → concurrency 1 and results-only; thermal →
no decorative; battery <25 % → errors and above; battery <10 % → captions;
screen reader → silent-text-only.

Accessibility raises the *priority floor* back up but never the outcome.

Degradation is immediate; recovery needs three consecutive readings. A user
changing a setting takes effect at once in both directions.

`remote_permitted` is `False`, not computed and not configurable.

---

## 12. Privacy boundary

* Every classification may be spoken **locally**; `may_speak_remotely()` returns
  `False` for every classification.
* Local command providers receive only the sanitized utterance, scrubbed by
  `companion.privacy.scrub_text` with markup and control characters removed.
* Logs, events and the journal carry a digest and bounded metadata, never words.
  A test asserts no emitted event contains the utterance.
* Temporary audio: `0o600` inside `0o700`, removed on every path.
* Crash recovery validates ownership before deleting: symlinks, foreign-uid
  directories and group/world-writable directories are skipped with a reason.
* Speech history is not stored separately; the journal holds identity and
  disposition only and is truncated rather than archived.
* `PresentationState.speaking` is the privacy indicator, already canonical and
  already rendered.

---

## 13. No-cloning enforcement

No recording import, no sample upload, no training, no speaker embedding, no
impersonation workflow, no hidden upload. `VoiceDescriptor` has nowhere to put a
sample, an embedding or a model reference. `voice_list` answers
`voiceCloningSupported: false`, `voiceImportSupported: false`,
`voiceTrainingSupported: false`, `remoteVoicesAvailable: false`.

A test asserts that no module in the package defines a name like `clone_voice`,
`train_voice`, `speaker_embedding` or `import_voice_sample`.

**User-created and cloned voices require a separate consent and ownership
design.** `docs/companion-voice.md` §13 lists the five questions it would have to
answer; none has a default, which is why none is answered by omission.

---

## 14. Cancellation model

A `CancellationSignal` per utterance, owned by the worker, observed by the
subprocess runner while the child runs — so a cancel takes effect during
synthesis rather than after it. Escalation is `SIGTERM` → grace → `SIGKILL` →
grace on the process group, with a `wait()` in a `finally` on every path.

A cancellation token binds a cancel to *this* request rather than to a reused id.
Cancelling twice is not an error. Cancelling a task cancels its queued and
current speech.

---

## 15. Recovery model

A journal line on start and on settle. On restart, a start with no settle is
**uncertain**, and uncertain resolves to `interrupted` — true, and in the *heard*
set, so it is not replayed.

**"No child process remains" is evidence of nothing** after a crash. Completion is
recorded, not inferred; that is why the journal exists.

Abandoned workspaces are swept after ownership validation and an age threshold.
Captions and the task result are untouched. `replayed` is always empty and the
document says `automaticReplay: false`.

---

## 16. Protocol operations

`voice_health`, `voice_list`, `voice_status`, `voice_speak`, `voice_cancel`,
`voice_pause`, `voice_resume`, `voice_explain` — declared in
`companion.protocol.OPERATIONS` beside every other operation, so the review
surface is still one list. Added to `schemas/companion-protocol.schema.json`.

No operation takes an executable, argument list, output path, provider module,
URL or device handle. **`voice_speak` takes a caption identifier, not text.** An
undeclared parameter is refused.

`CompanionGateway` delegates all eight in one line each and answers "no voice
runtime" when there is none, rather than failing.

---

## 17. systemd integration

**Inside the canonical companion service, in an isolated worker. No second unit,
no second task runtime.** The five §18 criteria are argued in
`docs/companion-voice.md` §16 and in `companion/voice/service.py`'s module
docstring; the short version is that the components that crash are already
separate processes, and a second service would put a socket between a task event
and the `SIGTERM` that releases an audio device.

Validated: startup, shutdown, restart (`restart_worker`), crash recovery, no
orphan providers, no orphan audio, the task continuing across a voice restart
(vertical slice steps 22–23), and captions remaining available throughout.

No systemd unit file changed. The voice runtime starts and stops with
`bunny-companion.service` because it is part of it.

---

## 18. Security results

| Check | Result |
| --- | --- |
| Shell invocation | None. `shell=False` explicit; asserted across every module by AST |
| Argument injection | Hostile text (`--version; $(id) \`whoami\` && rm -rf /`) round-trips as data through stdin |
| Executable allowlist | 10 names; `bash`, `sh`, `curl`, `python3`, `rm` refused |
| Path traversal in a program name | Refused |
| Executable substitution via `PATH` | Refused — trusted directories only |
| Symlink out of a trusted directory | Refused with "executable substitution" |
| Group/world-writable binary | Refused |
| Environment inheritance | Allowlist only; `LD_PRELOAD`, `PYTHONPATH`, proxies denied even if a provider passes them |
| Utterance in the process table | Prevented — stdin preferred, undeclared placement refused |
| Redaction index off-by-one | Tested: the executable at position zero is accounted for |
| Workspace escape via a file name | Refused |
| Temporary file permissions | `0o700` directory, `0o600` files |
| Sweep of a foreign directory | Skipped with a reason; symlinks not followed |
| Network reachability | No module imports `socket`, `http`, `urllib`, `ssl`, `ftplib` or `requests` |
| Commercial provider names | Absent from every non-docstring name and string |
| Voice-cloning surface | Absent |
| Microphone use by the voice runtime | Absent |
| Task-authority reachability | Absent from the import graph |
| Child process refusal of `SIGTERM` | Escalated to `SIGKILL` and reaped, bounded |
| Zombie children | Zero across the gate runs |

---

## 18a. The defect the gates could not see

Worth its own section because it is the most instructive result of the phase.

`/usr/bin/paplay` is a **symlink to `pacat`**, a multi-call binary that decides
what it does from `argv[0]`: invoked as `paplay` it parses a sound file; invoked
as `pacat` it reads **raw PCM**. `resolve_executable` resolved the symlink and
returned the target, so the runtime exec'd `pacat`, which played a WAV's RIFF
header and its mono 22 050 Hz samples as stereo 44 100 Hz raw data.

**0.73 seconds of noise where 2.80 seconds of speech belonged. Exit code 0.**

Everything downstream agreed it had worked:

* the playback outcome said `succeeded`, because the player exited zero;
* the disposition was `played`;
* the vertical slice passed 24 of 25 steps on it, including "start audio",
  "complete playback" and "emit generic visemes";
* the 100-run and 20-run gates passed on it, with zero deltas on every column;
* every §24 latency figure it produced was arithmetic about the wrong audio.

No test in the suite could tell, because no test asked **how long it took**. The
only symptom was a number that did not add up: a lifecycle which speaks a
2.8-second utterance completing in 0.9 seconds, next to a direct measurement
showing `paplay` blocks for exactly the audio duration.

Two changes:

1. `resolve_executable` returns the trusted path that was **asked for** rather
   than the symlink target. The target is still resolved and still checked for
   being inside a trusted directory, a regular file, executable and not
   group-writable — nothing about the substitution defence is weakened. What is
   preserved is the program's own idea of which program it is.
2. `PlaybackHandle` refuses to call a playback successful when the player exited
   zero having spent less than `PLAYBACK_COMPLETION_FLOOR` (0.6) of the audio's
   duration on it. Exit status alone cannot distinguish "played" from "played
   the wrong thing". The floor is 0.6 rather than something tighter because a
   server may legitimately drop the tail of a stream, and the case this catches
   is off by a factor of four rather than a few percent.

After the fix: `paplay` runs **2.823 s** for **2.799 s** of audio — ratio 1.009.

**This was not a quirk of one program.** On the reference target:

```text
lrwxrwxrwx  /usr/bin/paplay  -> pacat
lrwxrwxrwx  /usr/bin/pw-play -> pw-cat
-rwxr-xr-x  /usr/bin/aplay            (and /usr/bin/arecord -> aplay)
```

**Two of the three players in the allowlist are multi-call symlinks**, and the
third is the target of one. `pw-play` had the identical defect and would have
shown it on any host with a working PipeWire sink — this one has none, so the
PipeWire path was never taken and the bug was invisible there. The fix is
uniform and covers all of them.

The general lesson is recorded because it will recur: **a green gate is evidence
that nothing crashed, not that anything worked.** Multi-call binaries are
ordinary on a Linux system, and any code that canonicalises a path before
exec'ing silently changes what they do.

## 18b. The leak the tests could not see

`af0025b` passed all three gates — 100/100, 50/50, 20/20, zero failures. The
columns beside the pass/fail counts said something else:

```text
gate 2 (50 complete companion-suite runs)
  per-iteration delta   threads +2 .. +3      liveVoiceWorkers +2 .. +2
  since baseline        threads +101          liveVoiceWorkers +100
                        rssBytes +117,559,296
  final thread names    100 x companion-voice
```

A hundred voice worker threads, two per suite run, accumulated while every test
in every run passed.

The cause: `CompanionService.__init__` builds the voice runtime — which starts a
thread — and *then* binds the endpoint, where a second service pointed at a live
endpoint is refused with `DuplicateRuntime`. That refusal is supported and
tested. The half-built service is discarded by the caller, so nothing held a
reference to the worker and nothing could ever stop it. Before this branch a
half-built service leaked nothing, because there was no thread in it to leak.

Everything after the voice runtime is built now runs inside a `try` that closes
it and re-raises, and a test asserts the thread count is unchanged across a
refused construction rather than trusting the arrangement.

**This is the entire argument for §22's resource columns.** The gate's pass
criterion is test outcomes, and by that criterion the run was clean. What made
the leak visible was counting something the tests never look at, across enough
repetitions for two per run to become a hundred.

---

## 19. Stress-gate results

**All three gates pass on one commit: `0cf81a135b24619f74bbecfcdd48d3a69f33c2fd`.**

Every iteration of every gate records the commit it ran on, and all 170 agree.
Run as `bunny` (uid 1000) from ext4 under `/home/bunny`, under `systemd-run` so a
dropped client or a WSL idle-stop could not truncate it.

| Gate | Required | Result | Longest consecutive | Exit |
| --- | --- | --- | --- | --- |
| 1 — voice-worker lifecycle | 100 | **100 / 100** | 100 | 0 |
| 2 — complete companion-suite | 50 | **50 / 50** | 50 | 0 |
| 3 — installed voice vertical slice | 20 | **20 / 20** | 20 | 0 |

Durations:

| Gate | min | median | max | total |
| --- | --- | --- | --- | --- |
| 1 | 2.992 s | 3.002 s | 3.503 s | 300.9 s |
| 2 | 27.363 s | 28.109 s | 28.613 s | 1404.5 s |
| 3 | 4.617 s | 4.630 s | 4.748 s | 92.7 s |

Gate 1 at 3.0 s per lifecycle and gate 3 at 4.6 s per slice are the durations of
utterances that were **actually spoken** — the figure that exposed §18a was a
gate-1 median of 0.9 s.

### Resource deltas — §22's columns

Every column below is per iteration, min..max across all iterations of that gate.

| Column | Gate 1 (100) | Gate 2 (50) | Gate 3 (20) |
| --- | --- | --- | --- |
| Process delta (live services / runtimes) | +0 | +0 | +0 |
| Thread delta | +0 | +0 | +0 |
| Non-daemon thread delta | +0 | +0 | +0 |
| File-descriptor delta | +0 | +0 | +0 |
| Child-process delta | +0 | +0 | +0 |
| Zombie children | +0 | +0 | +0 |
| Audio-handle delta | +0 | +0 | +0 |
| Temporary-workspace delta | +0 | +0 | +0 |
| Live voice workers | +0 | +0 | +0 |
| Live voice services | +0 | +0 | +0 |
| Queue depth *(absolute between iterations)* | 0 | 0 | 0 |
| Active request count *(absolute)* | 0 | 0 | 0 |

Queue depth and active request count are recorded as **absolutes**, not
differences: either being non-zero between iterations is wrong whatever it was
before, and a delta of zero against a dirty baseline would read as clean.

**One non-zero figure, and it is not a leak.** Gate 2 ends one thread above its
baseline: `review-local.slow-reviewer`, a lazily-built fixture in
`tests/companion/support.py`. It is created on iteration 1 and 49 of the 50
iterations have a thread delta of exactly zero. The manifest separates the two
cases by counting how many iterations moved a column rather than by whether the
total is non-zero — a resource allocated once and then stable is a fixture, and
a gate that called it a leak would cry wolf until nobody read it. The same
pattern was recorded in the pause/approval phase.

RSS grows across every gate (13–117 MB) and is deliberately excluded from the
leak criterion: CPython does not return freed arenas to the operating system, so
a rising RSS with flat object, thread, descriptor and child counts is the
allocator, not the runtime. The object counts are the ones that would move.

The evidence, with sha256 digests, is in
`qualification/companion-voice/evidence/manifest.json`.

---

## 20. Installed vertical-slice result

Run on the reference target as `bunny`, against a real `CompanionService` over
its socket, with a real synthesiser and a real audio backend.

**24 PASS · 1 NOT_RUN · 0 FAIL.** Provider `espeak-ng`, backend `pulse`
(`RDPSink`), outcome `local-neural-or-system-voice`, visemes from `amplitude`.

| # | Step | Result |
| --- | --- | --- |
| 1 | start the canonical companion runtime | PASS |
| 2 | start the client transport | PASS — the real socket |
| 3 | load the validated character package | PASS — `org.bunny-os.default-bunny` (animated-2d) |
| 4 | submit a harmless task | PASS |
| 5 | display planning and working states | PASS |
| 6 | request and resolve approval | PASS — 2 approvals granted |
| 7 | complete the task | PASS — phase `success` |
| 8 | produce canonical caption text | PASS |
| 9 | submit a local speech request | PASS |
| 10 | select a real available local provider | PASS — `espeak-ng` |
| 11 | start captions before speech | PASS |
| 12 | start audio | PASS — `pulse` |
| 13 | emit generic visemes | PASS — source `amplitude`, confidence 0.6 |
| 14 | animate the character mouth | **NOT_RUN** — needs a compositor |
| 15 | complete playback | PASS — `played` |
| 16 | return the mouth to neutral | PASS |
| 17 | cancel a second utterance mid-playback | PASS |
| 18 | preserve captions | PASS |
| 19 | simulate backend loss | PASS — all three backends |
| 20 | degrade to captions only | PASS — `local-neural-or-system-voice` → `captions-only` |
| 21 | restore with hysteresis | PASS — restored after 4 readings; the first held |
| 22 | restart the voice worker | PASS |
| 23 | task identity and result unchanged | PASS — same id, state `completed` |
| 24 | restart the client, replay the presentation | PASS |
| 25 | completed speech not automatically replayed | PASS — 0 new utterances |

Synchronisation on that run: caption led audio by **30 ms**, viseme-to-audio
**0 ms**, synthesis latency **21 ms**, time to first audio **30 ms**, all within
tolerance.

Repeated three times independently to confirm it was not a one-off: identical
result each time (24/25, `espeak-ng`, `pulse`, amplitude, 29–31 ms caption lead).

**No network and no commercial provider were involved.** The report carries
`networkRequired: false` and `commercialProviderRequired: false`.

---

## 21. Memory measurements

Fedora Linux 44 (WSL), user `bunny`, commit `0cf81a13`, 30 utterances, all 30
spoken through eSpeak NG to the `pulse` backend. **PSS is included wherever the
kernel exposes `smaps_rollup`**, which it does here.

| Metric | n | min | median | p95 | max |
| --- | --- | --- | --- | --- | --- |
| Voice worker idle RSS | 1 | 28.395 MiB | — | — | — |
| Voice worker idle PSS | 1 | 21.649 MiB | — | — | — |
| Provider process RSS | 4 | 8.008 | 8.209 | 8.383 | 8.383 MiB |
| Provider process PSS | 4 | 5.156 | 5.360 | 5.489 | 5.489 MiB |
| Playback backend RSS | 14 098 | 5.539 | 5.727 | 5.918 | 5.969 MiB |
| Playback backend PSS | 14 098 | 1.604 | 3.063 | 3.131 | 3.279 MiB |
| Companion + voice RSS | 30 | 28.789 | 31.242 | 31.703 | 31.703 MiB |
| Companion + voice PSS | 30 | 21.929 | 24.406 | 24.866 | 24.866 MiB |
| Temporary storage peak | 30 | 0.060 | 0.153 | 0.614 | 0.616 MiB |

**`n` is honest and two of these are small.** The idle figure is a single
reading by construction — it is taken once, before anything speaks. The provider
figure has only **4** samples because eSpeak NG synthesises in ~22 ms and the
10 ms sampling loop rarely catches it alive; with n=4 the median and p95 are
almost the same number and are reported rather than smoothed. The playback
backend has 14 098 samples because `paplay` is alive for the length of every
utterance.

**None of this is Bunny OS memory usage.** "Companion + voice" is one Python
interpreter holding the companion runtime and the voice runtime. A desktop, a
compositor, a shell and a browser are not in it. The emitted document carries
that caveat too.

**The renderer is not in these figures.** No compositor runs here; the character
renderer's own measurements are in the renderer phase's report.

## 22. Latency measurements

| Metric | n | min | median | p95 | max |
| --- | --- | --- | --- | --- | --- |
| Synthesis latency | 30 | 21 | 22 | 25 | 25 ms |
| Time to first audio | 30 | 29 | 38 | 48 | 51 ms |
| Caption-to-audio offset | 30 | 29 | 38.5 | 48 | 51 ms |
| Viseme-to-audio offset | 30 | 0 | 0 | 0 | 0 ms |
| Cancellation latency | 10 | 1.349 | 1.403 | 1.767 | 1.767 ms |
| Device-loss degradation latency | 10 | 0.068 | 0.073 | 0.191 | 0.191 ms |
| Worker restart time | 10 | 0.164 | 0.183 | 0.725 | 0.725 ms |
| Process CPU during an utterance | 30 | 330 | 785 | 3300 | 3310 ms |

Every figure is inside §14's tolerances: the caption leads the audio by 29–51 ms
(tolerance 0–2000 ms) and the mouth starts within 0 ms of the audio (tolerance
±120 ms).

Reading them honestly:

* **Caption-to-audio and time-to-first-audio are the same number** because the
  slice marks the caption shown immediately before building the request. On a
  real client the caption is displayed by a compositor first, and the offset
  would be larger. This is the *runtime's* contribution, not the whole path.
* **Viseme-to-audio is 0 ms and that is arithmetic, not precision.** The worker
  starts the scheduler in the same millisecond it records the audio start, so
  the measurement confirms nothing is *inserted* between them — it does not
  measure how well a mouth on screen tracks a sound in a room, which needs a
  compositor and a microphone.
* **The p95 for the four smaller samples is at or near the maximum by
  construction.** With n=10 there is no 95th percentile; the emitted document
  says so on each row rather than printing a number that looks like one.
* **CPU is not separable between synthesis and playback.** It is the parent
  process's own user+system time across the whole utterance, and the child's CPU
  is not in it. The wide spread (330 ms to 3.3 s) tracks utterance length.
* **The audio path makes an RDP hop.** Latency here includes the WSLg bridge and
  would differ on a machine with a sound card.

## 23. Complete test results

**869 tests, 0 failures**, on both platforms:

| | Windows 11 (Python 3.14.3) | Fedora 44 WSL as `bunny` (Python 3.14.3) |
| --- | --- | --- |
| Ran | 869 | 869 |
| Failures | 0 | 0 |
| Skipped | 25 | 1 |

The skip difference is the point of running both: 24 of the Windows skips are
POSIX-only checks — file modes, symlinks, ownership, process groups, `SIGTERM`
refusal — that only Linux can express.

New tests added by this phase: **300**.

| Module | Tests | Covers |
| --- | --- | --- |
| `test_voice_schema.py` | 33 | §21 schema and requests |
| `test_voice_queue.py` | 51 | §21 queue, §11 capability, §12 hysteresis |
| `test_voice_captions.py` | 57 | §21 captions and visemes, §14 synchronisation, PCM |
| `test_voice_providers.py` | 51 | §21 providers, §5 safe execution and security |
| `test_voice_worker.py` | 40 | §6 worker, §19 cancellation races, §10 device loss |
| `test_voice_authority.py` | 38 | §21 authority, §20 recovery, §17 protocol |
| `test_voice_character.py` | 30 | the pre-existing voice/character tests, extended |

Every §21 category is covered:

* **Schema** — valid, oversized (both units), invalid language, invalid voice,
  expired, duplicate, conflicting duplicate, secret classification, malformed.
* **Providers** — available, unavailable, crash, timeout, unsupported language,
  unsupported format, cancellation, child-process refusal, bounded stderr,
  argument injection.
* **Queue** — priority, interruption, coalescing, supersession, bounded queue,
  decorative drop, cancellation.
* **Audio** — device unavailable, removed, restored, format mismatch, playback
  failure, completion, pause and resume, backend restart.
* **Captions and visemes** — caption before speech, partial captions, final
  caption, voice failure retains caption, ordered visemes, viseme cancellation,
  drift, neutral reset, renderer restart.
* **Recovery** — crash before synthesis, during synthesis, during playback,
  stale temporary file, orphan provider, in-flight request after restart, no
  automatic replay.
* **Authority** — voice cannot change task state, cannot resolve approval,
  cannot invoke tools, cannot access a raw secret payload, and voice failure
  does not fail a task.

All thirteen §19 cancellation races are present, each pinned to a barrier or an
injected clock rather than a sleep. The one exception is documented in
`voice_support.py`: whether a child that ignores `SIGTERM` is escalated and
reaped is a property of signal delivery, so that test starts a real interpreter
that really refuses.

---

## 24. Known limitations

Listed in full in `docs/companion-voice.md` §17. The material ones:

1. No physical speaker validated; audio reaches an RDP sink through WSLg.
2. No provider-native or phoneme viseme timing exists; amplitude at 0.6 is the
   best available and cannot produce `rounded`.
3. Text-derived timing assumes even pacing and drifts on long utterances.
4. "Streaming" means provider-owned playback, not incremental delivery.
5. The GTK widget layer is not exercised by the voice slice (no compositor).
6. CPU during synthesis and during playback are not separable.
7. `spd-say --cancel` cancels the server's whole queue, not one message.
8. Speech Dispatcher's inventory needs a running server.
9. Pause and resume are unavailable on the streaming path.
10. The older `espeak` binary is a declared fallback and was not exercised.

## 25. NOT_RUN items

Everything that was not exercised, with the reason. None is a failure and none
is claimed as a pass.

| Item | Why |
| --- | --- |
| **Vertical slice step 14 — animate the character mouth** | Needs a compositor. The viseme timeline drives `companion.character.lipsync`, which the *character* slice exercises against the renderer; no compositor runs in the voice slice. |
| **Physical speaker validation** | Audio reaches an RDP sink through the WSLg bridge. No speaker was involved anywhere, and every emitted document carries `physicalSpeakerValidated: false`. |
| **PipeWire playback path** | `pw-play` is installed and PipeWire runs, but the graph has **zero `Audio/Sink` nodes** on this host, so the backend is correctly not-ready and was never selected. The `pw-play`→`pw-cat` multi-call defect (§18a) was fixed by the same change but has not been *observed* to work, because there is no sink to play to. |
| **ALSA playback path** | `aplay -l` reports no soundcards. Correctly not-ready; never selected. |
| **The older `espeak` binary** | Declared as a fallback for `espeak-ng`; only `espeak-ng` is installed on the reference target. |
| **Speech Dispatcher as the *selected* provider** | It is installed, healthy and enumerates 653 voices, and its adapter is tested — but eSpeak NG is preferred by the registry order, so the streaming path was never the one a slice or gate actually took end to end. It is reached in tests through scripted providers and in the code through the fallback path. |
| **Provider-native viseme timing** | No provider produces it; `from_provider_timing` raises. |
| **Phoneme viseme timing** | No provider produces boundaries; `from_phoneme_timing` raises. |
| **Speech recognition** | Not implemented; §26. |
| **Remote voice providers** | Not implemented and refused structurally; §27. |
| **3D rendering** | Not implemented; §28. |
| **Reproducibility candidate** | Forbidden by §26 during initial implementation; §29. |
| **24 POSIX-only tests on Windows** | File modes, symlinks, ownership, process groups and `SIGTERM` refusal cannot be expressed there. All 24 run on Linux. |
| **systemd unit-level restart** | The voice runtime has no unit of its own by design (§17). Worker restart is exercised through `restart_worker`, and service startup/shutdown through the slice; no `systemctl restart bunny-companion.service` was run on an installed image. |

---

## 26. Remaining work for speech recognition

Unchanged and still absent. `MicrophoneBoundary` is the activation rule and is
tested; `AbsentSpeechRecognition` refuses rather than returning an empty
transcript, because an empty transcript is indistinguishable from a recogniser
that heard nothing. The voice runtime added by this phase is **output only** and
touches no microphone.

What a recognition phase would need, none of which exists:

1. A tested local recogniser. Nothing in Fedora's default set has been evaluated
   for accuracy, latency or memory on the target hardware.
2. A model acquisition and integrity story — where the weights come from, how
   they are pinned, and how that interacts with reproducible builds.
3. Push-to-talk and continuous-listening as *separate* consents, with the
   indicator raised before the device is opened (the boundary already enforces
   the ordering; there is nothing behind it).
4. A transcript privacy classification, and a decision about whether a transcript
   is a task event at all.
5. An answer to partial transcripts: a recogniser that revises what it heard, and
   a canonical runtime that has already acted on the first version.
6. Wake-word detection, which is a continuous-listening design and needs its own
   consent, its own indicator and its own false-positive budget.

## 27. Remaining work for remote voice providers

Nothing in this phase. `may_speak_remotely()` returns `False` for every
classification and `ProviderDeclaration.serves()` refuses a non-local provider
outright.

What a remote phase would need:

1. Approval binding per utterance, through `companion.approvals`, naming the
   destination and the classification — the same shape as remote *execution*,
   not a voice setting.
2. A cost model. The request already carries `cost_ceiling_units`; nothing spends
   it.
3. A privacy ceiling that is actually enforced at dispatch: secret text may never
   leave, and "the user turned on a nicer voice" must not become the route.
4. Credential storage that the voice runtime cannot read. The request schema has
   nowhere to put a key and that should stay true.
5. Network failure as a degradation rung, with the local ladder below it.
6. A latency budget: a remote round trip is longer than the caption's useful life
   for progress narration.
7. A visible indicator that speech is leaving the machine, distinct from the
   speaking indicator.

## 28. Remaining work for 3D rendering

Nothing in this phase; unchanged from the renderer phase. `full-3d` remains
*eligible* on a capable machine and is never *selected*, because no renderer
implements it.

For voice specifically, a 3D character would need viseme timing better than
amplitude — a mouth with visible tongue and teeth positions makes the gap between
`open-medium` and an actual phoneme obvious in a way a 2D mouth does not. That
puts phoneme timing on the critical path for 3D, and this phase establishes that
no installed provider gives it.

## 29. Reproducibility implications

**No reproducibility candidate was created and none is claimed.** §26 forbids one
during initial implementation, and this phase does not attempt one.

**No previous evidence covers this branch.** The capability, integration,
renderer and Linux-validation evidence trees all predate it and are about
different trees. `qualification/companion-linux/evidence/` is preserved
unmodified and continues to describe the pause/approval phase, not this one; the
new evidence is in `qualification/companion-voice/evidence/` and says which
commit it is about.

What a future reproducibility candidate would have to account for:

1. **Twenty new installed paths**, listed in §3. Fourteen of them are Python
   source under `/usr/lib/bunny-os/python/companion/voice/`, which participates
   in the same byte-comparison as every other installed file.
2. **An installed-path removal.** `/usr/lib/bunny-os/python/companion/voice.py`
   no longer exists; the directory replaces it. A comparison against an artifact
   built before this branch will show the file absent, which is correct and not a
   defect.
3. **No new build inputs.** The voice runtime adds no package to the image and no
   file to `build/inputs/`. eSpeak NG and Speech Dispatcher are *runtime*
   dependencies discovered on the host at run time and refused honestly when
   absent — nothing here installs them, and the artifact is byte-identical
   whether or not the building machine has them.
4. **No non-determinism introduced into the build.** Nothing in this branch runs
   during image construction. The Python sources are copied verbatim by
   `copy_python_package`.
5. **The `__pycache__` question is unchanged.** `copy_python_package` filters
   `__pycache__`, so the fourteen new modules add no compiled artifacts to the
   image and cannot contribute a timestamp.
6. The usual caveat still applies: every commit changes the OCI configuration
   digest through the revision label and `/usr/lib/bunny-os/release.json`, so an
   unchanged layer digest is not an unchanged image.

The reproducibility position established at the three-builder phase is unaffected
by this branch and is not re-validated by it.

---

## Completion standard

| # | Requirement | Status |
| --- | --- | --- |
| 1 | A real local provider speaks canonical caption text | **Met.** eSpeak NG 1.52.0 speaks the caption the canonical projection produced, through `paplay` to `RDPSink`; 30/30 utterances spoken in the measurement run, 24/25 slice steps, 20/20 slices under gate 3. |
| 2 | Voice cannot mutate task authority | **Met.** Enforced by the import graph and asserted from it; the worker holds no store, runtime, session or approval object. Slice step 23 checks task id, state and result across a voice restart. |
| 3 | Captions remain available when voice fails | **Met.** Slice steps 18 and 20; every `DegradationRecord` carries `captionsRetained: true` and the type refuses `task_affected=True`. |
| 4 | Cancellation stops provider and playback resources | **Met.** Five §19 cancellation points tested; child-process, audio-handle and workspace deltas are +0 across 170 gate iterations. |
| 5 | No child process, thread, descriptor, timer or temporary file leaks | **Met**, and it took two attempts — §18b. All columns +0 per iteration across all three gates; the single thread above gate 2's baseline is a test fixture allocated once. |
| 6 | Audio-device loss degrades to captions | **Met.** Slice steps 19–21; `local-neural-or-system-voice` → `captions-only` → restored after hysteresis. |
| 7 | Generic visemes animate the existing renderer | **Partly met.** The timeline is produced from measured amplitude and converted to the renderer's own `LipSyncEvent`, and `LipSyncController` accepts it — but no compositor draws it in this phase. Slice step 14 is `NOT_RUN`. |
| 8 | Renderer returns to neutral after completion or cancellation | **Met.** Terminal neutral on every path, asserted in tests and at slice step 16. |
| 9 | Completed speech does not replay after restart | **Met.** Slice step 25; recovery reports `replayed: []` and `automaticReplay: false`. |
| 10 | Voice cloning and remote transmission absent | **Met.** No cloning surface, no network import, no credential field, no remote provider; asserted from the syntax tree. |
| 11 | The 100/50/20 stress gates pass on one commit | **Met** on `0cf81a13`; all 170 iterations record that commit. |
| 12 | Linux memory and latency measured | **Met.** §21 and §22, with `n` on every row and `NOT_RUN` where a figure could not be taken. |
| 13 | The provider-free installed vertical slice passes | **Met.** 24 PASS, 1 NOT_RUN, 0 FAIL; no network and no commercial provider. |
| 14 | No release or reproducibility qualification claimed | **Met.** §29. |

**Item 7 is the one qualification.** The viseme pipeline is complete and
measured; what has not happened is a compositor drawing the mouth. That is the
character renderer's own validated surface and is deliberately not re-claimed
here.

---

## 30. Superseded by the closure

Two claims in this report were superseded by `fix/companion-voice-closure`, and
the rest stands. Nothing above this line has been edited; every byte of it is
pinned by digest in `qualification/companion-voice-closure/preserved-evidence.json`.

* **§3 build-input closure.** The "20 installed paths" counted by hand there is
  superseded by a mechanically derived **22**. The analyser of the day did not
  model `copy_python_package` and reported 2. See
  `COMPANION_VOICE_CLOSURE_REPORT.md` §2 and §5.
* **§25 NOT_RUN, "compositor mouth animation".** Run. Voice-produced visemes now
  drive a real GTK character renderer on the WSLg compositor; see
  `COMPANION_VOICE_CLOSURE_REPORT.md` §10-§12. Every other NOT_RUN item in §25
  is still NOT_RUN and is carried forward unchanged.

The §18a multi-call defect and the §18b stranded-worker defect are both still
described as they were. Their fixes were not undone: §18a gained a declared
player contract around it, and §18b gained an ordering that makes the stranded
thread unreachable rather than only recoverable.
