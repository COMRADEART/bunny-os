# Bunny Companion Speech Input Runtime — Phase Report

This report closes the first Bunny Companion speech-input phase: explicit
push-to-talk, a visible microphone indicator raised before the device opens,
bounded local capture, a provider-neutral local recognition contract with one
genuine adapter, partial and final transcripts with provenance, confirmation
before task creation, device-loss degradation to typed input, recovery that
never resumes capture, and the `100/50/20` stress gates on one exact commit.

Every claim below is bounded to what was executed on the named machines. Where
something was not run, it is listed as NOT_RUN with the reason, not omitted.

---

## 1. Starting and final SHAs

| | |
|---|---|
| Base branch | `fix/companion-voice-closure` |
| Starting commit | `50b1d4d14ddeecb76eca517984fd8e0edbdb749b` (verified head of the base branch) |
| Working branch | `feature/companion-speech-input` |
| Gate commit | `db9e0b1d6cebfa1e9b741feb0ed76e6409857b7d` (every gate iteration records it) |
| Evidence commit | `0a788065358bccc2e2f98614c02adf4ce978e744` |
| Final SHA | `0a788065358bccc2e2f98614c02adf4ce978e744` — the evidence commit is the last substantive commit; the closure commit that follows edits only this report's SHA lines and the §3 post-gate verification, and is non-build-affecting by construction |

Preflight, before the branch was created: the full SHA of `50b1d4d1` was
resolved and matched the branch head; the working tree was clean; and the
corrected build-input analyzer classified `60ba76e1..50b1d4d1` as
non-build-affecting — 0 installed paths, 11 unreachable (the voice-closure
report and its evidence). The completed voice-closure branch was not modified;
its evidence tree (`qualification/companion-voice-closure/`) is untouched by
every commit on this branch.

Post-gate closure: the analyzer over `db9e0b1..0a78806` (everything after the
gate commit) reports **0 installed, 0 context-only, 11 unreachable** — the
evidence files and this report. Nothing the gates measured differs from the
gate commit by anything the build could see. As always, every commit changes
the OCI configuration digest through the revision label; an unchanged layer
digest is not an unchanged image.

## 2. Branch lineage

```
fix/companion-pause-approval-consistency (66652d0)
  └─ feature/companion-voice-runtime (b825dd4)
       └─ fix/companion-voice-closure (50b1d4d)   ← unmodified
            └─ feature/companion-speech-input (this phase)
```

## 3. Build-input impact

The corrected analyzer (`build/scripts/build-input-closure.py`, consuming the
shared route table in `build/scripts/install_routes.py`) classifies this
branch's changes as **build-affecting through the existing
`companion-package` route** — no new install route was needed and none was
added:

* **Installed** (all profiles): the 17 modules of `companion/speech/`,
  `companion/character/listening_link.py`, and the modified
  `companion/protocol.py`, `companion/service.py`, `companion/gtk_shell.py`,
  `companion/cli.py`, `companion/speech/vertical_slice.py` — landing under
  `/usr/lib/bunny-os/python/companion/`; plus
  `schemas/companion-protocol.schema.json` under `/usr/share/bunny-os/schemas/`.
* **Unreachable from the build**: every test, the harness scripts
  (`companion_stress.py` additions, `gtk_speech_input_probe.py`,
  `speech_measure.py` — development tools the installer does not copy), the
  ops scripts, this report and its evidence.
* The recognition **model is not shipped**: `/usr/share/bunny-os/speech-models`
  is a declared search location that the image leaves empty. The installed
  system reports `speech input: typed-input-only — no local recogniser` until
  a model is installed, which is the honest state of the artifact.

## 4. Speech-input architecture

`companion/speech/` mirrors the voice runtime's shape, with the §2 pipeline
implemented end to end:

```
explicit user action → activation gate → device policy → bounded capture
  → local recognition → partial transcripts → final transcript
  → confirmation → canonical task submission (through the gateway)
```

| Module | Owns |
|---|---|
| `request.py` | The versioned, bounded `SpeechInputRequest` — the whole of the runtime's input. Activation sources are a closed set of four explicit interactions; there is no wake-word member and no field that could carry a model path, a recording destination or a remote endpoint. |
| `execution.py` | The capture allowlist (`parec`, `pw-record`, `arecord`, `pactl`, `pw-dump`) and `CaptureChild`, which reads recorder stdout on an owned thread into a caller-supplied sink. No pause: `SIGSTOP` on a recorder is an open device the indicator would lie about. |
| `capture.py` | Recorder contracts (multi-call refusals — `parec`→`pacat`, `arecord`→`aplay` are real symlinks on the reference target), the bounded frame buffer that counts what it drops, three real backends, and the router with backoff and restore hysteresis. |
| `activity.py` | The energy gate, clocked by the samples themselves. Explicitly not a biometric; its own description says so. |
| `recognizer.py` / `recognizers.py` | The provider-neutral contract (declaration/health/session) and the genuine Vosk adapter. A remote declaration is refused by the contract itself. |
| `transcript.py` / `confirmation.py` | Partials provisional by type with monotonic revisions; finals with provenance and the user-edited mark; the ledger where one yes, about the right words, in the right session, becomes submittable text. |
| `policy.py` | §10's four outcomes from the existing capability signals, hysteresis on restore, no rung that leaves the machine. |
| `indicator.py` | The listening indicator: raise fails without a displaying sink; clear refuses while the capture handle is open. |
| `worker.py` | One capture at a time, owning everything it touches, released in a `finally`. No persistent thread: a worker with no capture holds nothing the gates could count. |
| `coordination.py` | §19: output speech quiesced before the microphone opens, recorded, resumed only on the cancellation path. |
| `recovery.py` | The journal and the ownership-validated sweep. `captureResumed: false` is written into every recovery report. |
| `service.py` | Assembly and the eight operations, validated against the same `SPEECH_OPERATIONS` table the protocol validates clients against. |
| `vertical_slice.py` | §24's 28 steps against a real `CompanionService`. |

Authority boundaries are structural: no module under `companion/speech/`
imports `companion.runtime`, `companion.store`, `companion.task`,
`companion.approvals`, `companion.executor`, `companion.tools`,
`companion.session` or `companion.reviewer`, and
`tests/companion/test_speech_authority.py` asserts that from the AST of every
file in the package. The single seam where a confirmed transcript becomes a
task is `CompanionGateway.speech_input_confirm`, which holds the runtime that
the speech service never sees.

## 5. Activation gate

§4's conditions each produce a distinct refusal, in order, before anything
costly exists: a disabled preference, an expired activation, a missing
recognizer, and a duplicate or conflicting capture are refused synchronously
in `start_capture` with the reason in the reply; the indicator raise and the
device open happen inside the session with the ordering
`quiesce output → start recognizer → raise indicator → open microphone →
capture`. The two §4 sentences with teeth are branches, not conventions:

* a failed indicator raise returns before any device call exists
  (`test_an_undisplayable_indicator_keeps_the_microphone_shut`: zero opens);
* `ListeningIndicator.clear` refuses while the handle reports open, and the
  worker passes the handle's own `closed` fact.

No microphone initialisation occurs during service startup: the
`construct-speech-input` startup step builds objects only — no thread, no
device, no model — and the §21 recovery pass runs inside it, before any
capture can exist. `health.microphoneActive` is read from the live worker and
is `false` at startup by construction.

An immediate-submission request without the user preference is refused
outright rather than silently served with confirmation.

## 6. Capture backend

The three real backends and what each did on the reference target
(Fedora 44 WSL2, WSLg audio bridge):

| Backend | Recorder | On the reference target |
|---|---|---|
| `pipewire` | `pw-record` (symlink to `pw-cat`) | Installed, no daemon: `the PipeWire graph contains no audio source` — a genuine fallback exercise on every run |
| `pulse` | `parec` (symlink to `pacat`) | The working path: `RDPSource` (host microphone, never opened by gates), `RDPSink.monitor`, and the harness's own null-sink monitor |
| `alsa` | `arecord` (symlink to `aplay`) | `no soundcards found` — the real no-device-at-startup case |

Every recorder is invoked through the multi-call contract check before any
process exists; monitors are enumerated and labelled but never selected by
default (an explicitly named monitor is honoured — the controlled loopback
path the slice uses, visible in every event's `deviceId`). The bounded frame
buffer enforces the lag ceiling (drop and count — §7's overrun) and the
capture byte budget (stop) at the point the bytes arrive.

## 7. Recognition provider contract

`RecognizerDeclaration` declares identity, implementation, locality,
languages, streaming/partial/timestamps/confidence support, accepted formats
and rates, and a resource estimate read by §10 before any load happens.
Undeclared is unavailable; `local: false` is refused by the contract itself;
`cost_class != "free"` is refused. The registry selects in declared order,
honours a named preference exactly (an unknown name is a refusal, not a
substitution), and reports every rejection with all its reasons.

A recogniser **locale is a preference, not a requirement** — the one deliberate
divergence from the voice provider's rule, measured into existence: the only
installed model declares `en-US`, the default preference is `en-GB`, and the
inherited rule refused every capture on the reference target. A recogniser
trained on another region still transcribes the language; §13's confirmation
step is where the accuracy cost is caught.

## 8. Local provider implementation

One genuine adapter: **Vosk** (`vosk` python library over a Kaldi model),
in-process — chosen partly so recogniser state dies with the process and no
subprocess is ever handed audio and a model path in one argv. On the
validation host: `vosk-model-small-en-us-0.15` (68 MiB on disk) under
`~/.local/share/bunny-os/speech-models/`, one of exactly two trusted search
locations — a fixed tuple, not configuration, with ownership and permission
validation before a byte is parsed (world-writable and symlinked model
directories are refused, tested). The model loads on the first capture that
needs it, never at service start, and is kept across sessions.

Where the library or model is absent the adapter reports unavailable with the
reason and the policy outcome is `typed-input-only`. No fake adapter exists;
`AbsentSpeechRecognition`'s refusal in `voice/system.py` remains for the
machine with nothing installed.

## 9. Capability integration

`companion.speech.policy` reads the same `capability_signals` document every
other subsystem reads — nothing is re-measured — plus the facts only this
subsystem holds: capture reachability, recogniser availability and the
declared model memory requirement. Outcomes are §10's four; memory pressure
degrades streaming→batch→capture-disabled against the model's own declared
requirement; degradation is immediate and restoration needs three consistent
readings; a user preference change takes effect at once. `remote_permitted`
is a constant `False` with no configuration that could change it — local
incapability produces `typed-input-only`, never a remote path.

## 10. Partial transcript behavior

Partials are provisional by construction: `PartialTranscript.provisional` is
always true and on the wire; revisions are strictly monotonic per request and
the client folds by replacement; text is bounded at the transcript ceiling
(4000 characters — deliberately under the event-payload string bound, which a
worker fault during this phase's validation proved matters); at most 256
partial events per capture, after which suppression is a typed degradation
and final recognition is untouched. The poll-based GTK client additionally
reads the newest partial from `speech_input_status`, since partial events are
live-only and never retained in the ring. In GTK the partial label renders
via `set_text` — no markup-interpreting widget exists on the transcript path
— and the model's markup accessor escapes through `pango_escaped`.

## 11. Final confirmation behavior

The default flow is §13's: the final transcript (text, provider,
implementation, language, confidence, audio boundaries, audio digest,
streaming/batch mode) waits in the `ConfirmationLedger`; the client shows it
editable; confirm/retry/cancel are distinct protocol operations. The
confirmation names the session and may name the reviewed digest; replay,
cross-session, stale-digest, missing-token, lapsed and superseded
confirmations are each refused with the fact. An edit is marked user-edited
and the task receives the confirmed text, not the recogniser's version
(§24 step 14 exercised this against the real recogniser's imperfect hearing).
Immediate submission exists only behind the user preference **and** the
per-request flag, is recorded as `confirmed by immediate-preference`, and the
submission still flows through the same gateway seam.

## 12. Device-loss handling

§17's sequence is the worker's, in order: stop capture, close the device,
clear the indicator only after the handle closed, cancel recognition, remove
private audio, preserve a safe provisional transcript marked `incomplete`
(streaming path only — a truncated batch file is removed unrecognised),
offer retry and typed input, create no task. Transport stall (a live recorder
delivering nothing for 3 s) is treated as loss — on the reference target it
*is* the loss signal, since the bridge ends streams rather than erroring.
The router penalises the backend with doubling monotonic backoff and restores
only after two consecutive healthy observations. The measurement harness
produced a real loss by killing the recorder mid-capture: shutdown in ~40 ms
with the indicator ordering held.

## 13. Voice-output coordination

`VoiceOutputCoordinator` is the one file where speech input touches speech
output. Before the indicator rises, the current utterance is quiesced —
noncritical speech cancelled, essential speech paused where the playback path
supports it — and the record (`outputAudioWasActive`, action, request id)
travels with the capture. Nothing resumes after task submission;
`release(resume_paused=True)` exists only on the cancellation path, where no
task was created and the user's last act was "never mind". Echo cancellation
does not exist in this build and the description says so; scheduling, not
signal processing, is the §19 mechanism. The coordinator reaches the voice
worker through a live proxy so a voice-worker restart cannot leave it holding
a dead object.

## 14. Renderer integration

`companion/character/listening_link.py` is the mirror of the viseme link for
the opposite direction of audio, and its first rule is §18's asymmetry:
**microphone input never drives the mouth** — no lip-sync method is called
anywhere in the file, asserted from the AST. It maps capture events to the
three postures the character mapper already models (`listening`,
`transcribing`, `waiting_for_user`), decides on the worker thread, draws via
`dispatch` (`GLib.idle_add` under a compositor), counts every rejection under
a closed reason set, and resets to neutral on renderer restart while the
capture continues (§16's GTK-restart race, tested at the link and exercised
live in the probe). The persistent text indicator remains authoritative
throughout; a renderer failure is a counted rejection, never a capture fault.

On the compositor (WSLg, GTK 4.22.4), `scripts/gtk_speech_input_probe.py`
drove the §5 indicator as a real `Gtk.Label` and the listening posture as
real files into `Gtk.Picture`: indicator on the widget before the microphone
opened (raise→open ≈ 9 ms), cleared ~0.05 ms after close, postures
`listening → transcribing → waiting-for-user` drawn, a real final transcript
from the loopback, cancellation to cleared ≈ 48 ms, renderer restart survived
by the capture, zero GLib criticals, zero surviving idle sources, zero
capture threads after teardown.

## 15. Privacy and audio retention

* Raw audio is retained only for active recognition. The streaming path holds
  frames only inside the recogniser; the batch path writes to a
  `SpeechWorkspace` (0700 directory, 0600 files, unpredictable names, its own
  `bunny-speech-` prefix) deleted in the finalisation `finally`.
* The record keeps the audio digest (`sha256:`), never the audio. Events
  refuse byte payloads by type; the privacy layer's forbidden-name rule
  removes `rawAudio`-shaped fields and records the removal; the journal holds
  identity and disposition only — each of these is a test.
* Transcripts default to the `personal` classification. An unconfirmed
  transcript does not survive a restart; a confirmed one is a task in the
  canonical store, subject to the store's existing rules.
* The indicator displays retention (`audio not retained`) as data, and the
  preference that would retain audio refuses `True` at construction in this
  build.
* `retain_audio` aside, §22's log test: worker events, journal lines and
  dispositions were checked for audio-shaped content on every gate iteration
  by construction (events cannot carry bytes).

## 16. Cancellation and recovery

Cancellation is honoured at every §16 stage with barriers, not sleeps:
before the microphone opens (no device call ever happens), after the
indicator (cleared, nothing opened), during capture (closed before cleared),
during recognition (the finished answer is discarded — a person who said
"never mind" while the machine was thinking did not ask for a transcript),
and after the final transcript (the pending entry is rejected). Duplicate
activation and duplicate cancellation are idempotent refusals. A
worker restart mid-capture journals `cancelled`, releases everything, and
the §21 recovery marks unsettled captures `cancelled-uncertain`, sweeps
`bunny-speech-` workspaces with ownership validation, never opens a
microphone, and reports `captureResumed: false` in a field a gate asserts.
Orphan recorders end themselves on `EPIPE` at their next write — the
mechanism is documented where it is relied on. Recognisers are in-process;
their state dies with the process.

## 17. Protocol operations

Eight operations — `speech_input_health`, `speech_input_devices`,
`speech_input_start`, `speech_input_status`, `speech_input_stop`,
`speech_input_cancel`, `speech_input_confirm`, `speech_input_retry` — in
`companion.protocol.OPERATIONS` with `SPEECH_OPERATIONS` as a derived view,
mirrored in the JSON schema and the `RuntimeGateway` protocol. None takes an
executable, a model path, a recording destination, raw-audio retrieval, a
URL, or an arbitrary device command; undeclared parameters are refused by the
existing strict validator (tested over the wire). `speech_input_start`
validates the session exists before any microphone work. `speech_input_retry`
names the explicit activation the user just performed and supersedes the
waiting transcript, making the stale-final refusal part of the flow.

## 18. Security results

All §22 items have deterministic tests (Windows and Linux, in
`test_speech_security.py`, `test_speech_schema.py`,
`test_speech_service_protocol.py`, and the suites they lean on):

| Attack | Refusal |
|---|---|
| Silent activation | Closed activation-source set at the type; protocol test over the wire |
| Activation without visible indicator | No displaying sink → no device call, zero opens |
| Unauthorized local protocol client | The transport's existing three defences (dir mode, socket mode, `SO_PEERCRED`), unchanged and re-listed |
| Device-name injection | Bounded device-id shape at the request; protocol parameter bounds |
| Model-path injection | No path field exists anywhere; model search is a fixed tuple; unsafe model directories refused |
| Argument injection | argv-only capture allowlist; recorder contracts; the utterance-in-argv refusals inherited from voice execution |
| Recording-path traversal | Workspace names reduced to safe characters, confinement asserted |
| Temporary-file symlink | Ownership-validated sweep refuses symlinks (POSIX test) |
| Oversized audio | Buffer lag ceiling + capture byte budget, enforced at arrival |
| Oversized transcript | 4000-char/12000-byte refusal, protocol text bound to match |
| Malformed frame | Detector survives odd/hostile/random bytes |
| Unsupported format | Closed format/rate/channel sets at the request |
| Recognizer output injection | Control characters refused by the transcript type → recognition_failed, nothing leaks |
| GTK markup injection | `set_text`-only transcript path + `pango_escaped` for markup contexts |
| Stale transcript replay | Reviewed-digest binding; superseded/expired refusals |
| Cross-session confirmation | Session binding at the ledger, tested over the wire |
| Microphone open after failure | Handle closed in every ending's `finally`; indicator cannot clear before it |
| Raw audio in logs/events | Bytes refused by the event type; journal schema closed; forbidden-name scrub |
| Remote provider selection | `local: false` refused by the contract; locality `device-only` is the only representable value |

## 19. Stress-gate results

All three §23 gates ran sequentially in one `systemd-run --user` unit on the
reference target, on **one exact commit** —
`db9e0b1d6cebfa1e9b741feb0ed76e6409857b7d` — recorded per iteration (170
iterations, one commit value, asserted by the collector). Total wall time
40 minutes. Every §23 counter — thread delta, file-descriptor delta,
child-process delta, audio-input-handle delta, temporary-file delta, active
capture count, open recogniser-session count, listening-indicator state,
buffer depth, exit status, duration — is recorded per iteration in the gate
reports.

| Gate | Result | Consecutive | Per-iteration | Resources |
|---|---|---|---|---|
| 100 capture-worker lifecycles (`--target speech`) | **100/100** | 100 | median 1.28 s, max 2.58 s | zero growth, zero settled fixtures, zero absolute violations, indicator never lit between iterations |
| 50 complete companion suites (`--target suite`, 1,136 tests each) | **50/50** | 50 | ≈41 s | zero growth; one cleanup event (−1 stale `bunny-speech-` workspace swept by recovery — `cleanupOfPriorResidue`, never a failure) |
| 20 installed speech-input slices (`--target speech-slice`, 28 steps each) | **20/20** | 20 | median 11.6 s, max 11.9 s | zero growth, zero absolute violations |

Each gate-1 lifecycle is the whole capture-worker lifetime against the real
backends: a silence capture that opens and closes a real `parec` on the
default source, a capture cancelled mid-stream, a simulated device loss with
its policy descent and restoration, a worker restart, and a close — with the
recogniser present and its sessions counted (zero open between iterations,
every iteration).

Honest creep note: process RSS grows across gate runs (gate 1 ended
+195 MiB over its baseline, gate 3 +241 MiB) — the recognition model's
resident arena, loaded per iteration's service and not fully returned by the
allocator. Every *tracked* resource — threads, descriptors, children,
handles, workspaces, sessions, captures, buffers — is zero-delta per
iteration; the creep is an allocator/model property recorded here rather than
hidden in an average.

## 20. Installed vertical-slice result

The 28-step slice ran 20 consecutive times under gate 3 (no failures) and
once more as the recorded representative run (`evidence/slice.json`):
**27 of 28 steps PASS, 1 NOT_RUN, 0 FAIL.**

The one NOT_RUN is step 20 — the renderer animating voice visemes — which
needs a compositor no headless slice has; the compositor probe covers it and
the slice says NOT_RUN rather than passing it silently. Everything else ran
against the real stack: canonical `CompanionService` over its real socket;
microphone verified closed at startup; push-to-talk over the protocol;
indicator on before `pulse` opened `bunny-speech-loop.monitor` (the slice's
own null sink carrying the voice runtime's real espeak-ng playback);
speech detected; a partial available while capture ran; endpoint silence;
close-then-clear ordering; recognition finalised by **vosk**; the final
transcript edited by one word and confirmed; **exactly one task** created
(counted, before and after); the task through capability and approval to
completion; the result spoken by the voice runtime (disposition `played`);
a second capture cancelled mid-stream with **zero** tasks created from it
(counted); device loss simulated on all three backends with the policy
degrading to `typed-input-only`; the speech worker and a fresh client
restarted; the microphone still closed; the confirmed task unchanged; and no
capture restarted automatically (`captureResumed: false` in the recovery
record). No network provider was involved anywhere.

## 21. Memory measurements

From `scripts/speech_measure.py` on the reference target (process RSS/PSS
from `/proc`, staged so differences attribute cost; **not** full Bunny OS
memory):

| Stage | RSS | PSS |
|---|---|---|
| Process baseline (interpreter + companion imports) | 28 MiB | 24 MiB |
| + voice runtime constructed | 35 MiB | 30 MiB |
| + speech-input subsystem constructed, idle (no model) | 47 MiB | 42 MiB |
| + first recognition (Vosk small-en model loaded) | 174 MiB | 170 MiB |
| End of 12 captures + 6 cancellations + restarts | 175 MiB | 171 MiB |

The recognition model dominates (~127 MiB resident for a 68 MiB-on-disk
model); the speech-input machinery itself is ~12 MiB over the voice runtime.
Peak in-memory capture buffering was 0 bytes above the read path (the
consumer kept pace); temporary batch storage peaked at 6 KB. Capture+
recognition CPU: median 0.87 s process-CPU per ~3.5 s capture (n=12).

## 22. Latency measurements

Monotonic, measured where the events happen (`CaptureMeasurement`), n=12
captures on the null-sink loopback unless stated:

| Measurement | Median | p95 | Max |
|---|---|---|---|
| Indicator raise (request → shown) | 37 ms | 42 ms | 282 ms |
| Microphone open (request → recorder started) | 55 ms | 62 ms | 289 ms |
| First frame (request → first PCM) | 2.11 s | 2.13 s | 2.13 s |
| Speech-start detection (first frame → speech) | 378 ms | 377 ms | 377 ms |
| First partial (speech → partial) | 568 ms | 577 ms | 577 ms |
| Final transcript (capture stop → final) | 13 ms | 31 ms | 33 ms |
| Cancellation (request → settled, n=6) | 40 ms | 51 ms | 51 ms |
| Device-loss shutdown (recorder killed → settled, n=1) | 40 ms | — | — |
| Worker restart (n=5) | <1 ms | 3 ms | 3 ms |
| Indicator-before-open / cleared-after-close ordering | 12/12 held | | |

The ~2.1 s first-frame latency is the pulse monitor-stream connect on this
host, measured identically across all 12 captures; it is a property of the
loopback source, not of push-to-talk against a real microphone, and is
reported as what it is. Compositor-side (probe): raise→open 9 ms on the
widget path, close→cleared 0.05 ms, cancel→cleared 48 ms.

## 23. Complete test results

* **Windows 11 (development host, Python 3.14)**: 1,136 tests, 0 failures,
  32 skipped (POSIX-only semantics). Includes the ~200 new speech tests:
  schema, capture, worker lifecycle, §16 races, §22 security, confirmation,
  authority boundaries, recognizer adapter, listening link, and the
  end-to-end protocol suite.
* **Fedora 44 WSL2 (reference target, Python 3.14.3)**: 1,136 tests, 0
  failures, 1 skipped — and the same suite 50 more times under gate 2.
* Compositor probe: passed, zero GLib criticals (details in §14).
* Test-fixture defects found by the Linux run and fixed: six protocol tests
  passed on Windows only because no real recogniser existed to collide with
  (now they name the scripted recogniser through the provider preference);
  the pure-silence test now scripts a recogniser that heard nothing, which is
  what a real one returns.

## 24. Known limitations

1. **No physical microphone was validated.** The recognition-bearing paths
   (slices, probe, measurements) all captured a null-sink or RDP monitor
   carrying synthesised speech. Gate 1's silence captures did open
   `RDPSource` — the WSLg-bridged host microphone, as the default device —
   one hundred times, exercising the real open/close/journal lifecycle
   against it; but no gate depended on acoustic content, no audio from it was
   retained (digests only), and no claim about microphone audio quality is
   made. An automated gate cannot speak into a room.
2. **The image ships no recognition model**, so an installed system is
   `typed-input-only` until one is placed in a trusted model directory. The
   validation host's model was installed by hand and the report says so.
3. **Recognition accuracy is what a 68 MiB model gives over a loopback**: the
   canonical sentence was consistently transcribed as
   "come to that where did this out please" — wrong words, right plumbing.
   This phase claims transcription *worked*, not that it was good; §13's
   editable confirmation is the mitigation and was exercised on every slice.
4. **One recogniser adapter.** Whisper-family engines, platform APIs and
   locale-aware selection between multiple installed models are future work.
5. **The energy gate is deliberately crude** (RMS with a calibrated floor).
   Its two measured failure modes — saturation when speech begins inside the
   calibration window, and authority over the recogniser — were fixed during
   validation (saturation keeps the configured floor; the recogniser decides
   whether speech occurred), but it remains a heuristic bound, not a VAD.
6. **The WSLg host audio path is quirky**: a monitor stream that lives
   through a sink suspend→resume transition receives silence permanently
   (isolated by a process matrix, held off with a keep-alive sink-input in
   the harness), and the RDP monitor served silence to some client
   constellations. Both are documented host behaviors the harness routes
   around with its own null sink; neither is a runtime defect.
7. **Batch-path partials do not exist** (by design), and the batch path was
   exercised with scripted recognisers only — the installed model supports
   streaming, so no real batch recognition occurred on the target.

## 25. NOT_RUN items

* Physical microphone capture; any acoustic (through-the-air) audio path.
* GNOME session, physical hardware, booted-image validation of speech input.
* PipeWire and ALSA capture playback paths (both backends genuinely fail on
  the target and exercised only their refusal/fallback behavior).
* Slice step 20 inside the headless slice (renderer visemes need a
  compositor; the probe covers it and the slice says NOT_RUN rather than
  passing it silently).
* Speech Dispatcher as the injection's synthesis provider (espeak-ng was
  always selected).
* Real batch-mode recognition (see limitation 7).

## 26. Remaining work for wake word

Not implemented, deliberately (§26.9). What a future phase would need: a
standing low-power detector with its own §10 outcome and its own **always-on
indicator semantics** (§5's indicator covers sessions, not standing
listening); a new activation source added to the closed set — which is the
review point the tuple exists to force; retention rules for the pre-trigger
ring buffer; and a second look at `MicrophoneBoundary.start`'s
`continuous_enabled` gate, which already refuses always-listening today.

## 27. Remaining work for remote recognition

Every layer currently refuses it independently: the request type refuses any
locality but `device-only`, the recogniser contract refuses `local: false`,
policy hard-codes `remote_permitted: false`, and no operation can carry an
endpoint. A future phase would need to change all four *and* route the
decision through the approval system with a per-utterance consent shaped like
the remote-dispatch approvals — audio is `personal` data at minimum. The
boundary statements in `speech_input_health` are the places a reviewer would
watch.

## 28. Remaining work for speaker identification

None is present and none is planned by this phase: the detector computes
energy only, the contract has no field for a voiceprint, and the §22 suite
asserts the disclaimers (`voiceBiometricsSupported: false`,
`speakerIdentificationSupported: false`). Any future work would be a new
phase with its own consent design; nothing in this codebase provides a
starting point, which is the intended state.

## 29. Reproducibility implications

**No reproducibility or release qualification is claimed by this phase**
(§26.15). The build-input impact is §3's: the installed set changed, so the
image changes, and the three-builder reproducibility evidence pinned at
`225a5e1`/`f65b65c` does not cover artifacts built from this branch. The new
Python sources are byte-stable inputs through the existing
`copy_python_package` route (0444, no bytecode, no fixtures); nothing in this
phase adds a build-time generator or a non-deterministic input. A future
qualification would need to re-run the reproducibility comparison on a
candidate containing this branch; nothing here forecloses it.

---

*Evidence: `qualification/companion-speech-input/evidence/` — the three gate
reports with per-iteration resource records, the gate verdicts, the
compositor probe report, the measurement series, the environment record, and
a manifest binding every file by SHA-256 to the candidate commit.*
