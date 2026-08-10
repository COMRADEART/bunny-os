# The Bunny Companion voice runtime

Speech is the second rendering of a caption. The caption is the output.

Everything below follows from that one sentence, and the sentence is not a
slogan — it is the reason the architecture is shaped the way it is. A companion
that generated speech and captioned it afterwards would have two renderings that
can disagree, and the one a deaf user reads would be the derived one. Here the
caption comes from the canonical presentation projection, and the utterance is
derived from *it*. A machine with no synthesiser, a broken speaker, a muted
session or a thermal throttle loses the sound and nothing else.

---

## 1. Architecture

```text
canonical presentation state          companion.presentation.PresentationState
        ↓                              (produced by the companion runtime)
speech request builder                companion.voice.captions.CaptionLedger
        ↓                              caption in, VoiceRequest out
voice policy and capability check     companion.voice.policy.VoicePolicy
        ↓                              §11's four outcomes, §12's descent
voice provider registry               companion.voice.provider.ProviderRegistry
        ↓
dedicated voice worker                companion.voice.worker.VoiceWorker
        ↓                              one thread, one utterance at a time
audio artifact or provider playback   companion.voice.providers
        ↓
audio output backend                  companion.voice.audio.AudioRouter
        ↓
playback events ──┬── captions        (already on screen; never rewritten)
                  └── generic visemes companion.voice.visemes
```

The direction of the arrows is the design. Nothing flows back up. The voice
runtime holds no store, no task, no session and no approval object, and
`tests/companion/test_voice_authority.py` asserts that from the import graph
rather than from a reading of the code — a voice module that imported
`companion.runtime`, `companion.store`, `companion.task`, `companion.approvals`
or `companion.executor` fails the suite whatever it did with the import.

### Modules

| Module | What it owns |
| --- | --- |
| `request.py` | The versioned bounded schema; §7's priority ladder; interruption policy |
| `execution.py` | Allowlisted argv-only execution, private workspaces, escalating termination |
| `provider.py` | The provider-neutral contract and the registry |
| `providers.py` | eSpeak NG and Speech Dispatcher — the only two, both real |
| `pcm.py` | WAV inspection and the amplitude envelope |
| `audio.py` | Device discovery, playback, loss handling, backoff and hysteresis |
| `captions.py` | Caption authority, the replay guard, §14's measurements |
| `visemes.py` | Generic mouth shapes with their timing source and confidence |
| `policy.py` | §11's outcomes from the existing capability plan; §12's ladder |
| `queue.py` | The bounded priority queue and every disposition |
| `worker.py` | The one speaking thread and everything an utterance owns |
| `recovery.py` | The journal, the reconciliation and the workspace sweep |
| `service.py` | The eight operations and the assembled runtime |
| `system.py` | The original `SystemVoice` and the microphone boundary, unchanged |
| `vertical_slice.py` | §23's twenty-five steps |

---

## 2. What voice may and may not do

The canonical companion runtime remains authoritative for tasks, sessions,
lifecycle, approvals, privacy, executor ownership, reviewer observations,
presentation state, caption text, task result and cancellation.

**Voice may** receive sanitized speech requests, select an eligible local
implementation, generate audio, play it, emit playback progress, emit generic
viseme timing, cancel playback, and report degradation or failure.

**Voice may not** decide task success, change task state, select an executor,
approve anything, rewrite a caption, read a raw secret payload, run an arbitrary
command, or contact a remote provider.

`VoiceService.boundaries()` answers all of that at runtime, so a gate asserts the
running system rather than this document:

```json
{"captionsAuthoritative": true, "voiceMayChangeTaskState": false,
 "voiceMayResolveApprovals": false, "voiceMaySelectExecutor": false,
 "voiceMayInvokeTools": false, "voiceMayReadSecretPayloads": false,
 "voiceMayRewriteCaptions": false, "voiceFailureFailsTask": false,
 "remoteProviderConfigured": false, "remoteTransmissionPermitted": false,
 "voiceCloningSupported": false, "voiceSampleImportSupported": false,
 "speakerEmbeddingSupported": false, "modelTrainingSupported": false,
 "microphoneUsedByVoiceRuntime": false, "speechRecognitionImplemented": false,
 "physicalSpeakerValidated": false}
```

---

## 3. The request

`VoiceRequest` is the whole of the runtime's input. The absent fields are the
specification: there is nowhere in it for an API key, a credential, a model's
reasoning, a raw tool result, a filesystem destination or a command line.

Three properties are enforced at construction rather than at use.

**Bounded in both units.** 4000 characters *and* 12 000 bytes of UTF-8. The byte
bound is three times the character bound, not four, and the difference matters:
UTF-8 encodes at most four bytes per character, so a byte limit at four times
could never be reached and the check would be decoration. At three times, every
script that encodes in three bytes or fewer — Latin, Greek, Cyrillic, Hebrew,
Arabic, Devanagari, Han, Kana, Hangul, which is to say all prose — keeps the full
character allowance, while text that is mostly four-byte characters is refused.

Over either bound is **refused, never shortened**. A caption cut in half and
spoken is the companion saying something other than what is on the screen beside
it, and the user has no way to tell.

**A derivative of a caption.** `caption_reference` is required. The voice runtime
never invents user-visible content.

**Monotonic expiry.** Compared against `Clock.monotonic()` and never wall time.
An utterance whose expiry could be extended by changing the timezone is an
utterance that can be replayed an hour later into a different task's context.
Monotonic time also does not survive a restart, and recovery relies on that.

---

## 4. Providers

The contract is provider-neutral: nothing in it names a program or a capability
only one implementation has. A provider declares what it can do, reports whether
it can do it right now, and does it.

**An unavailable provider reports unavailable.** It does not raise on
construction and it never succeeds with no audio. That matters more than it
sounds: a provider that "succeeded" emptily would make the worker record an
utterance as *played*, which would make recovery believe there was nothing to
reconcile, which would leave a user who heard nothing unable to tell a broken
synthesiser from a silent one.

### eSpeak NG

Synthesises to a private WAV. That path is preferred because the samples are
ours before they are played, which is what makes amplitude-derived visemes, a
measured caption-to-audio offset, pause, resume and a mid-playback device change
possible.

Fixed at **22 050 Hz mono 16-bit** on the reference target, and the declaration
says exactly that. A request for 48 kHz is refused and degrades; nothing here
resamples, because a resampler is a second audio implementation pretending the
synthesiser can do something it cannot.

**Exit status is not evidence.** Two behaviours measured on eSpeak NG 1.52.0,
not assumed:

* `espeak-ng --stdin -w out.wav` with empty input exits **0** and writes no file;
* `espeak-ng --stdin -w /unwritable/out.wav` exits **0**, prints `Can't write
  to: …` to stderr, and writes no file.

So success means *there is audio in the artifact*, measured by `probe_wav`.

### Speech Dispatcher

Stream-only, by its own design: it is a server with its own queue, its own
priorities and its own audio connection, and a client that also wanted the
samples would be fighting it. §7's ladder is mapped onto `spd-say --priority`
rather than ignored — two queues that disagree about what is urgent produce
speech in an order neither intended. `--wait` on every utterance, because
without it `spd-say` returns as soon as the message is *accepted* and the queue
would run at the speed of the socket rather than the speed of speech.

`cancel()` both signals the client and runs `spd-say --cancel`: the message has
already been handed to the server, which keeps speaking after its client dies.

### What is not here

No OpenAI adapter, no ElevenLabs adapter, no Fish Speech adapter, and no
placeholder shaped like one. A stub reporting "unavailable — no API key" would
put the shape of remote speech into the code and make adding a key the only
remaining step. There is no key field anywhere in the package, and a test walks
every module's syntax tree to keep it that way.

---

## 5. Safe execution

Every command-backed provider goes through `execution.py`, and no provider builds
a `Popen` of its own.

* **Argument arrays only.** `shell=True` appears nowhere; `shell=False` is
  written explicitly and a test asserts it across the whole package.
* **The utterance goes through stdin** wherever the program supports it —
  eSpeak NG's `--stdin`, `spd-say`'s `--pipe-mode`. An argv is readable in
  `/proc` by every process the user runs, so a caption passed as an argument is
  a caption published to the machine. When a slot is unavoidable it is
  *declared*, and the runner refuses a command whose text appears anywhere else.
* **Deterministic resolution.** `/usr/bin`, `/bin`, `/usr/sbin`, `/sbin` in that
  order — never the inherited `PATH`. `/usr/local/bin` is deliberately absent:
  it is the directory most likely to shadow a packaged binary. After symlinks
  the target must still be inside a trusted directory, a regular file,
  executable, and not writable by group or other.
* **Bounded environment.** Built from an allowlist, never inherited, with `PATH`
  overwritten. `LD_PRELOAD`, `LD_LIBRARY_PATH`, `PYTHONPATH`, proxies and the
  rest are denied even if a provider passes them explicitly.
* **Private storage.** Workspaces are `0o700`, files are `0o600`, created by us
  rather than by the child — a synthesiser writing its own output uses its own
  umask, and `0o022` produces a world-readable recording of whatever the task
  said.
* **Timeouts, escalation, reaping.** `SIGTERM` → grace → `SIGKILL` → grace, to
  the whole process *group* (both `spd-say` and `paplay` fork helpers a signal to
  the leader alone would strand), and a `wait()` in a `finally` on every path.
* **Bounded stderr**, control characters stripped, and redaction that replaces
  the declared text slot with `[speech-text]`.

---

## 6. The worker

One thread. One utterance at a time — not a performance choice: two voices
talking over each other is unusable, and a queue that could start a second
utterance would make the interruption rules meaningless.

`Utterance` holds all ten things §6 requires the worker to own — request,
provider, child, audio stream, playback handle, temporary files, viseme
scheduler, caption timing, cancellation state, completion state — and is released
in a `finally`. If it is not on that object it is not owned; if it is, it is
released.

Release order is deliberate: ticker, then playback, then workspace. A player
still reading the file when its directory is removed is an orphan audio stream,
and on Linux an unlinked open file keeps playing to a path nothing can find.

**Threads.** One worker thread always, plus — on the streaming path only — one
short-lived mouth ticker that is stopped and *joined* before the utterance is
released.

---

## 7. Queue policy

Priorities, most urgent first:

```text
critical warning · approval required · task error · direct user response
task result · progress update · decorative
```

* Critical warnings interrupt ordinary speech.
* Approval prompts interrupt progress narration.
* Cancelling a task stops that task's speech, queued and current.
* A **terminal outcome** — a result or an error — supersedes that task's queued
  narration. A warning or an approval does *not*: those are interjections, the
  task continues, and what was queued is still true. An earlier version
  superseded on anything ranked at or above a result, which meant a warning
  silently emptied the queue of accurate lines.
* Repeated identical text is coalesced, at both the caption ledger and the queue.
* Decorative speech is dropped under pressure rather than queued for later.
* The queue is bounded at 32 and a full queue drops its own least urgent entry.
  That is what makes an unbounded narration loop impossible: a runtime emitting
  faster than speech can deliver does not accumulate a backlog, and the drop is
  recorded.

Every utterance ends with one of `queued`, `played`, `interrupted`, `cancelled`,
`superseded`, `dropped_by_policy`, `coalesced`, `failed`, `degraded_to_captions`
or `expired`. A closed set, so "no utterance was lost" is a count.

Interruption needs **both** the policy and the rank: a decorative line that set
`INTERRUPT` cannot cut off an approval prompt.

---

## 8. Audio backend

Three backends, in the order §12's ladder descends: PipeWire, then
PulseAudio-compatible, then ALSA. Playback is a one-shot player under the same
allowlisted runner; pause and resume are `SIGSTOP`/`SIGCONT` on the group,
because every player in the allowlist is a one-shot process with no control
channel and the kernel's own stop is the only mechanism all three share.

### The reference target, labelled accurately

Fedora 44 under WSL, as user `bunny`:

| Backend | State | Evidence |
| --- | --- | --- |
| PipeWire | present, **zero sinks** | `pw-dump` answers; no node has `media.class = Audio/Sink` |
| Pulse-compatible | **working** | `pactl`: `Server String: unix:/mnt/wslg/PulseServer`, one `RDPSink` |
| ALSA | **no card** | `aplay -l`: `no soundcards found` |

This is the **WSLg audio bridge**: a PulseAudio protocol socket onto an RDP sink
carried to the Windows host. **No physical speaker was validated**, and every
report says so. It is also a useful test bed — two of three backends genuinely
fail, so the fallback and degradation paths are exercised by the machine rather
than by a mock.

`kind` says `pulse-compatible` rather than `pulseaudio` because what is on the
other end of the socket is not knowable from here.

### Loss and recovery

On failure: stop the backend safely, keep the captions, emit a typed degradation
record, fall back to another eligible local backend **once**, otherwise continue
silently with captions. Never restart the task.

* **No rapid retry.** A failed backend is blocked for 2 s, doubling to 60 s, on
  the monotonic clock.
* **Hysteresis on the way back.** Two consecutive healthy discoveries before a
  backend is restored, because a server that is restarting answers once and then
  goes away again.

`DegradationRecord` carries `captionsRetained: true` and `taskAffected: false` on
every record, and the type *refuses to be constructed* with `task_affected=True`.

---

## 9. Capability integration and degradation

Signals come from `companion.capability_bridge.capability_signals` — the same
reading the router made its decision on — plus two facts the capability runtime
does not hold: whether an audio backend can reach a device, and whether a local
synthesiser is installed. Nothing is re-measured here.

Outcomes, most capable first:

```text
local-neural-or-system-voice · local-lightweight-voice · captions-only · silent-text-only
```

`captions-only` is the machine's answer; `silent-text-only` is the user's. Telling
somebody their speaker is broken when they turned speech off would be wrong.

There are **no named machine modes**. A mode is a bundle of decisions somebody
has to keep in step with the signals; these outcomes are computed every time.

The descent:

| Pressure | Effect |
| --- | --- |
| No local provider | captions-only |
| No provider that yields samples | lightweight; text-derived visemes; no pause |
| No reachable audio device | captions-only |
| < 192 MiB available | lightweight, provider-owned playback |
| < 64 MiB available | captions-only |
| CPU below the capability threshold | concurrency 1; results and above only |
| Two or more tasks running | speech gives way to the work |
| Thermally throttled | decorative speech off |
| Battery < 25 % | errors and above only |
| Battery < 10 % | captions-only |
| Screen reader active | silent-text-only |

**Accessibility raises the floor back up** — but only the priority floor, never
the outcome. For a user who relies on speech, progress narration is not
decoration; a missing speaker is still a missing speaker.

**Degradation is immediate; recovery needs three consecutive readings.** The
asymmetry is the mechanism: symmetric thresholds oscillate, and a companion that
alternates between speaking and silent is worse than one that stays quiet. A user
changing a *setting* takes effect at once in both directions — the hysteresis is
about machines flapping, and somebody who just turned speech on and had to wait
three cycles would reasonably conclude the switch was broken.

**Local incapability never authorises remote speech.** `remote_permitted` is not
computed and not configurable.

---

## 10. Captions and synchronisation

Which of the projection's sentences is *the* caption follows
`companion.character.integration.bubble_request_for` exactly — approval, then
error, then result, then status — so the speech bubble and the voice say the same
thing.

The ledger holds a copy of the text so a request can be derived from it, the
timings, and what has already been spoken. It is **not a second caption store**:
no surface reads it and no protocol operation returns its text.

`speak_once` refuses in four cases: the caption has already been spoken (§20's
no-automatic-replay), the same words are already queued at the same rank, there
is nothing speakable, or the text cannot be reduced to a valid request. Refusals
are returned, never raised.

### Tolerances

Development-environment figures, on a host whose audio makes an RDP hop:

| Measurement | Tolerance |
| --- | --- |
| Caption shown before audio | ≥ 0 ms (never negative) and ≤ 2000 ms |
| Viseme against audio | ± 120 ms |
| Mouth back to neutral after audio | ≤ 250 ms |
| Caption finalised after audio | ≤ 1000 ms |

An unmeasured offset is `None`, never zero: "we did not measure this" must not
average in as a perfect score.

---

## 11. Visemes

Shapes are the renderer's own — `neutral`, `closed`, `open-small`, `open-medium`,
`open-wide`, `rounded`, `smile`. This module adds *timing*, and every event says
how its timing was arrived at:

| Source | Confidence | Status |
| --- | --- | --- |
| `viseme` (provider-native) | 0.95 | **Not produced.** `from_provider_timing` raises |
| `phoneme` | 0.90 | **Not produced.** `from_phoneme_timing` raises |
| `amplitude` | 0.60 | Produced. RMS of the samples that will be played |
| `text-estimate` | 0.35 | Produced. Characters spread across the duration |
| `speaking-state` | 0.15 | Produced. The floor |

The two that raise do so rather than fabricating: eSpeak NG prints phoneme
*names* with `-x` and does not print the times they occur at, and turning names
into times would produce a timeline labelled `phoneme` — the second-highest
confidence — from an estimate no better than `text-estimate`. §13 forbids exactly
that.

`smile` is never generated. It is an expression, not a mouth position for a
sound, and the canonical phase already drives the character's expression. A
generator that emitted it would be forming an opinion about how the task was
going.

**Neutral is terminal on every path** — completion, cancellation, drift beyond
tolerance, renderer restart, worker teardown. A character left mid-syllable is
the most visible symptom of a runtime that lost track of itself.

**Drift degrades rather than lies.** Three consecutive readings beyond 120 ms and
the scheduler switches down to speaking-state. One reading over is a scheduling
hiccup; several in a row is a timeline that has come apart from its audio, and a
mouth moving to *wrong* timing reads as broken in a way an open mouth does not.

A renderer restart resets the mouth to neutral and re-enters the timeline **at
the current index**, not from zero: replaying from the start would run the whole
utterance's mouth movement against audio that is nearly finished.

---

## 12. Privacy

* Speech text is classified before dispatch and every classification may be
  spoken **locally** — a local synthesiser is a process on this machine with no
  network path, the same trust boundary the executor already runs inside.
* `may_speak_remotely()` returns `False` for every classification. It is a
  function rather than a constant so that adding the first remote provider means
  arguing with a docstring rather than deleting a line.
* Local command providers receive only the sanitized utterance, which has been
  through `companion.privacy.scrub_text` and had markup and control characters
  removed.
* Diagnostic logs, events and the journal carry a digest and bounded metadata —
  never the words. A test asserts no event carries the utterance.
* Temporary audio is `0o600` inside a `0o700` directory and is removed after
  playback or cancellation, on every path.
* Crash recovery removes abandoned workspaces **after validating ownership**: a
  prefix is a convention, not a proof, so a symlink, a directory owned by another
  uid, and a group- or world-writable directory are each skipped with a reason.
* Speech history is not stored separately. The journal holds identity and
  disposition only, and is truncated rather than archived.
* `PresentationState.speaking` is the privacy indicator, already in the canonical
  projection and already rendered by the client.

---

## 13. No voice cloning

No recording import. No voice sample upload. No model training. No speaker
embedding. No impersonation workflow. No generation of a voice from anybody's
recordings. No hidden provider upload.

Voice identity is selected only from voices the installed provider already has.
`VoiceDescriptor` has nowhere to put a sample, an embedding or a model reference,
and a test asserts that no module defines a name like `clone_voice`,
`train_voice`, `speaker_embedding` or `import_voice_sample`.

**User-created and cloned voices need a separate consent and ownership design
that this phase does not attempt.** At minimum it would have to answer: who owns
a voice derived from a recording, how consent from the speaker is obtained and
recorded, how a cloned voice is distinguishable from a real one to a listener,
what happens when consent is withdrawn after the model exists, and how the model
is prevented from leaving the machine. None of those is a technical question with
a default answer, which is why none of them is answered by omission here.

---

## 14. Cancellation and recovery

Cancellation reaches a queued utterance, one in synthesis, one between synthesis
and playback, and one mid-playback. A cancellation token binds a cancel to *this*
request rather than to a reused id, so a late cancel for a finished utterance
cannot silence the one that replaced it. Cancelling twice is not an error.

After a restart:

* **completed speech is not replayed**, ever, automatically;
* an utterance with a start line and no settle line is **uncertain**, and
  uncertain resolves to `interrupted` — which is true, and is in the *heard* set,
  so it is not replayed either;
* the mouth returns to neutral;
* abandoned workspaces are removed after ownership validation;
* captions and the task result are untouched;
* an explicit replay is permitted, as a new request, from a person.

**"No child process remains" is evidence of nothing.** After a crash there is no
child either way — the kernel reaped it along with everything else — so
completion is *recorded* rather than inferred. That is the whole reason the
journal exists.

---

## 15. Protocol

Eight operations: `voice_health`, `voice_list`, `voice_status`, `voice_speak`,
`voice_cancel`, `voice_pause`, `voice_resume`, `voice_explain`. They live in
`companion.protocol.OPERATIONS` beside every other operation, so reviewing what a
client can reach is still a matter of reading one list.

No operation takes an executable, an argument list, an output path, a provider
module, a URL or a device handle. **`voice_speak` does not take text** — it takes
a caption identifier, and the runtime derives the utterance from the caption it
already published. A client cannot make the companion say something the user was
not shown. An undeclared parameter is refused, not ignored.

`voice_explain` exists for the user rather than the machine. "It stopped talking"
has a dozen causes — a policy floor, a thermal state, a missing sink, a provider
that failed once — and a surface that could only say "no audio" would send
somebody to check their speakers when the answer was that the battery is at 8 %.

---

## 16. systemd integration

**Voice runs inside the canonical companion service, in an isolated worker.**
There is no second unit and no second task runtime.

A separate user service is justified only when it materially improves crash
isolation, resource control, audio lifecycle, provider restart or a security
boundary. Measured against those five:

* *Crash isolation* — what crashes is a synthesiser or a player, and both are
  already separate processes. A second service would isolate the worker from the
  companion, not the companion from the thing that fails.
* *Resource control* — the worker's own footprint is a thread and a bounded
  queue. The memory is in the synthesiser, which is a child process either way.
* *Audio lifecycle* — the argument that looks strongest, and reverses on
  inspection: the handle must be released when the presentation moves on, and
  separating them puts a socket between a task event and a `SIGTERM` to a player.
* *Provider restart* — a new child. No service boundary needed.
* *Security boundary* — real, and answered without a second unit. The worker
  cannot mutate task state because it holds nothing that could, enforced by the
  import graph. That is stronger than a socket with a protocol that could grow an
  operation.

`VoiceService.restart_worker()` restarts voice alone. The task runtime is not
touched — this object has no reference to one.

---

## 17. Known limitations

1. **No physical speaker has been validated.** Audio on the reference target
   reaches an RDP sink through the WSLg bridge. Latency figures include a hop a
   sound card would not have.
2. **No provider-native or phoneme viseme timing.** The best available source is
   amplitude at confidence 0.6, which knows how loud each 40 ms is and nothing
   about which sound it is — so it cannot produce `rounded`.
3. **Text-derived timing assumes even pacing**, which no synthesiser honours. It
   drifts on long utterances; §14 measures the drift and degrades rather than
   hiding it.
4. **Streaming is provider-owned playback, not incremental delivery.** Nothing
   here delivers partial audio, and a "streaming" provider costs amplitude
   visemes, pause and resume.
5. **The GTK widget layer is not exercised by the voice slice.** It needs a
   compositor; step 14 is recorded `NOT_RUN`.
6. **CPU during synthesis and during playback are not separable.** The figure is
   the parent's own user+system time across both, and the child's CPU is not in
   it.
7. **`spd-say --cancel` cancels the server's whole queue**, not one message.
   Speech Dispatcher's client offers no per-message cancel, and this is the
   honest consequence.
8. **Speech Dispatcher's inventory needs a running server.** Without one it
   reports no voices and becomes unselectable, which is correct but means the
   provider looks absent rather than idle.
9. **Pause and resume are unavailable on the streaming path**, because the
   provider owns the audio.
10. **`espeak` (the older binary) is a declared fallback but has not been
    exercised**; only `espeak-ng` was available on the reference target.

## 18. Unverified assumptions

1. That `SIGSTOP` pausing a player produces silence promptly on every audio
   server. It was observed on the WSLg bridge; a server with a large buffer would
   keep playing what it already has.
2. That `paplay`'s `--latency-msec` is honoured. It is passed and reported as
   *requested*; nothing here measures what the server delivered.
3. That the amplitude-to-shape thresholds in
   `companion.character.lipsync.amplitude_to_shape` look right to a viewer. They
   are the renderer's own and were not re-derived from a perceptual study.
4. That 40 ms analysis windows suit every synthesiser. Chosen against eSpeak NG's
   output; a slower or breathier voice might want a different window.
5. That eSpeak NG's `Pty` column orders voices the way a user would. It is
   inverted into a preference and used only to break ties.
6. That two consecutive healthy observations is the right hysteresis for an audio
   server restart. It is enough for the observed case and is not tuned against a
   population of servers.

---

## 19. Running it

```sh
make companion-voice-health     # what can speak here, and why anything cannot
make companion-voice-slice      # §23's twenty-five steps
make companion-voice-measure    # §24's figures
make test-companion             # the whole suite, voice included

python3 scripts/companion_stress.py --target voice       --runs 100
python3 scripts/companion_stress.py --target suite       --runs 50
python3 scripts/companion_stress.py --target voice-slice --runs 20
```

Self-checks must run as a **non-root user from an ext4 filesystem**. As root a
read-only directory is still writable and every file is "ours", so two permission
checks cannot fail and two tests pass for the wrong reason — which is exactly
what happened on the first Linux run of this phase.
