<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stage 2 — Voice Release Closure

Contract: `VOICE_RELEASE_CONTRACT.md`. Matrix and evidence:
`qualification/voice-release/`. Discovery candidate **`72ff8063`**; fix
commits `c1cbf98f` (protocol + bridge), `a858cf5a` (probe unit), `24168fbc`
(contract + matrix), `375fa830` (stale-test repair). Final artifact:
`shell-test` built at **`24168fbc`**, qcow2 sha256
`e302c16d8095835ffa96d48db0520082b179af4d96674849cd3dc6f2dc0f71af`, base from
the verified retention mirror (quay no longer serves the locked digest — the
retention store was the point, and this is the first build that needed it).

Everything below was measured in a QEMU/KVM guest on the Fedora 44 reference
builder: emulated HDA speaker recorded to a host WAV, a PipeWire pipe-source
microphone fed by a hold-open daemon, states read from the accessibility tree,
truthfulness cross-checked by an independent poller of capture streams, sink
state and player processes. **No physical speaker or microphone, and no human
ear, appears anywhere in this evidence.**

## 1. What was already implemented

Stage 2 rewrote nothing that worked. The stack it inspected and qualified:
push-to-talk capture (`companion/speech/`, 18 modules) through in-process
Vosk; the TTS runtime (`companion/voice/`, 20 modules) with the provider
ladder pocket → kitten → espeak-ng → speech-dispatcher and the backend ladder
PipeWire → PulseAudio → ALSA; one semantic authority (presentation phases +
microphone flags → `CharacterState` through one mapper — no second state
machine was added); transcripts entering the runtime through the same
`_submit_runtime_task` typed input uses; approvals derived from tool
declarations and resolved through the one `resolve_approval` operation; the
GNOME shell extension's voice service driving `bunny-shell-assistant` over
NDJSON. The E2E milestone of 2026-08-10 had proven the spoken loop — on an
overlaid image, never on an exact artifact, with the build blocked by a full
host disk. Stage 2's job was to make the claims artifact-grade, and the
artifact promptly earned its keep (§8).

## 2. What was changed

**Product (2 defects, both cross-boundary, both invisible to per-side suites):**

* `companion/protocol.py` — an optional identifier whose declared default is
  the empty string now accepts the empty string as absent. `voice_cancel`
  declared `requestId`/`cancellationToken` with `default=""` and refused `""`
  on the wire; the shipped bridge always sent `requestId=""` beside the real
  taskId, so **every interruption the desktop ever requested — the on-screen
  stop control included — was refused** with "requestId is not a usable
  identifier" while the audio played to its end. A required identifier still
  refuses to be empty.
* `shell/services/bin/bunny-shell-assistant` — `_wait_for_speech` now treats
  a *settled* degradation (a `speech_degraded` event carrying a
  `disposition`) as terminal, and `watch()` surfaces its reason as a warning
  while the text answer stands. Before this, "no TTS provider available" —
  which the worker reports honestly within a second — was indistinguishable
  from a hang until a 60-second deadline lapsed. A mid-utterance degradation
  carries no disposition and still does not end the wait (the voice-closure
  phase's 146-frame frozen-mouth lesson, preserved).

**Harness:**

* `build/scripts/desktop-inject.sh` — the injected desktop probe is
  `Type=exec`, not `Type=oneshot`: a oneshot is "activating" for its whole
  life, so systemd's start timeout killed the guest command channel 15m45s
  into every boot (it ended a Stage 2 session mid-case).
* The interruption instruments were rebuilt: the stop-latency poll now names
  `pw-play` (the player the PipeWire backend actually spawns — the old list
  never matched anything), reads the sink state from the last column (the
  old `awk $5` read "2ch" out of the sample spec, making the check vacuous),
  captures `voice-cancel`'s verbatim answer, and reaps its background listen
  client. **The prior milestone's "interruption 116 ms" was fiction produced
  by those two parsing defects**; the truthfulness poller/checker written
  this phase had the same two bug shapes on its first run and was fixed the
  same way.

**Tests:** 7 new regressions (empty-optional-identifier contract ×4, a
bridge-shaped `voice_cancel` dispatch through a real service, settled- vs
mid-utterance-degradation waits ×2), each verified to fail on the unfixed
tree — the degraded-wait one fails by sitting out its whole deadline, the
defect's exact shape. Plus one repair: `ShellVoiceBoundaryTests` asserted the
Allow/Deny literals in `panel.js`, which stopped carrying them when the
permission question became a component; it had been failing on both
platforms since, unnoticed because nobody ran the full suite.

## 3. What was measured

On the exact artifact, from recorded runs (AT-SPI-sampled upper bounds,
grain ~0.15 s):

| Measurement | Value |
|---|---|
| Pointer press → visible LISTENING (indicator up) | 0.60–0.70 s |
| End of utterance → THINKING (STT + accept) | 2.18–2.36 s |
| THINKING → spoken reply begins (agent + synthesis) | 2.9–3.0 s (no approval) |
| **End of utterance → spoken reply (round trip)** | **5.1–5.4 s** |
| Interruption: cancel → audio silent | 130 ms (real `pw-play` + sink state; nothing played afterwards) |
| Pocket synthesis, warm | RTF ≈ 0.30 (1.1–1.2 s for 3.7–3.8 s audio) |
| Pocket cold (first utterance, includes worker load) | 6.7 s (RTF 4.8) |
| Kitten warm | RTF 0.18–0.40 |
| Idle: companion CPU / RSS | 0.3 % of one core / 238 MiB |
| Idle: neural worker CPU / RSS | 0.0 % / 9.3 MiB |
| Listening + STT: companion CPU | 12–25 % of one core |
| Synthesis: neural worker CPU | ~100–160 % (multi-threaded) |
| Neural worker RSS during synthesis | withheld — the reader matches a 13 MiB process, which cannot hold a PyTorch model; a wrong number is worse than none (same withholding as the E2E report) |

CPU figures are /proc utime+stime deltas inside a WSL2-hosted VM; treat them
as this environment's numbers, not the product's floor.

## 4. Test results

```text
baseline  72ff8063   5727 tests   8 failures, 22 skipped   (Linux, as bunny, ext4)
current   24168fbc   5734 tests  10 failures, 22 skipped   (+7 = the new regressions)
final     375fa830   5734 tests   7 failures, 22 skipped   (delta vs baseline: -1)
```

**The 8 baseline failures are all pre-existing and none are voice-functional:**
two evidence-preservation pins outrun by the installer/Orca phases' legitimate
edits, two licensing findings (one `installer/` file without an SPDX header),
three ShellCheck/validator findings in installer-phase scripts, and the stale
voice-boundary assertion (repaired this phase, `375fa830`; the rest belong to
their owning phases and are recorded, not silently absorbed). The current
run's two extra entries are `test_character_cli_vertical` timing steps
("presentation pressure", "hysteresis") that flip under host load — the same
pair the companion-experience phase characterised at ~2-in-12 under load. The
controls: they fail identically at the *baseline* commit when cherry-picked,
and the whole module passes 19/19 on an idle host at the fix commit — so they
are order/load-coupled and not a Stage 2 regression.

## 5. Voice qualification matrix

`qualification/voice-release/matrix.json` carries all 59 rows with evidence
pointers. Summary: **56 PASS · 1 FAIL · 2 NOT_SUPPORTED.** The FAIL is RM-4
(a render-mode switch mid-utterance has no defined mouth disposition at the
library level — `set_mode` never calls the links' `restart_renderer`);
recorded rather than fixed because the shipped surface renders a single mode
and the path is unreachable there. The NOT_SUPPORTED rows are cross-task
conversational memory and hands-free barge-in (§10). Rows carrying an
additional honest NOT_RUN sub-note: zero-capture-device (the emulated HDA
always exists), per-request microphone override, live sink-removal
mid-playback, per-mode compositor pixels.

The primary release gate (EE-1) on the final artifact: **PASS** — pointer
press on the visible microphone button at (1784, 624) → LISTENING +0.7 s
with the indicator up → transcript "open files" (Vosk, 1.0) → the approval
question drawn and allowed on screen → Files verifiably launched (process,
unit, bus name, showing frame) → "Files is open." spoken by Pocket →
SUCCESS +24.2 s → idle; the emulated speaker's own recording recognized
back as "files is open"; the truthfulness poller found zero violations and
zero capture streams outside claimed listening.

## 6. Offline matrix

Measured with every non-loopback link down and ping unreachable, in one run
(spoken "Open Terminal", approval granted on the wire, Terminal verifiably
opened, reply spoken):

| Component | Online | Offline |
|---|---|---|
| Microphone capture | PASS | PASS |
| STT (Vosk, in-process, local model) | PASS | PASS |
| Agent (local intents) | PASS | PASS |
| TTS (Pocket, local) | PASS | PASS |
| Playback (PipeWire → HDA) | PASS | PASS |

Nothing in the voice path needs a network; the neural worker pins
`HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` and synthesis children get
`BUNNY_VOICE_NETWORK=disabled`. Remote *agent providers* remain a separate,
consent-gated capability outside this path.

## 7. Failures discovered (all on the exact artifact)

1. **Interruption was a no-op, product-wide** — the §2 protocol/bridge
   mismatch. Cascade, all observed live: audio continued while the shell
   claimed idle; the next reply queued behind the un-cancelled utterance
   (QUEUE policy) and the bridge's 60 s speech deadline expired ("Bunny could
   not speak: speech output did not finish within its time limit"); the
   queued reply then played as a ghost, minutes late, to a person who had
   moved on. Found because the instrumented repro captured `voice-cancel`'s
   stderr, which every earlier run had discarded — and py-spy (staged into
   the guest through the 9p share) showed the worker parked in the
   mouth-drive loop of an utterance whose cancellation flag was never set.
2. **"No TTS provider" looked like a 60-second hang** — §2's second fix.
3. **The guest command channel died 15m45s into every boot** — the probe
   unit's type (harness).
4. **Both interruption latency instruments measured nothing** — `pw-play`
   missing from the player list, sink state read from the wrong column
   (harness; also the shape of the E2E's 116 ms figure, now corrected in
   that report's memory record).
5. `bunny-first-run.service` sits failed on the booted session — outside
   voice scope, inherited from the Stage 1 "first-run never driven" gap,
   recorded for that phase.

## 8. Failures fixed

1–4 above: fixed at `c1cbf98f`/`a858cf5a` plus builder-side instrument
rewrites (archived in `qualification/voice-release/evidence/*/harness/`),
each with a regression test or corrected instrument, and re-verified on the
rebuilt artifact: the cancel answers `speech_output_cancelled` naming the
cancelled request, audio stops in **130 ms** with nothing playing afterwards,
the next interaction speaks normally (21 s whole-flow wall against 72+ s of
silent stall before), the on-screen stop is truthful under the poller, and
the no-provider case settles honestly in **11 s** with the new warning
("no eligible local voice provider; the caption is the whole of the
output") instead of 70+ s of fake hang.

## 9. What remains NOT_RUN

* Compositor pixels for the mouth (the installed slice's step 17 names it:
  the probe that proves pixels needs a display; slice-level evidence is
  16/18 PASS with this and the next step honestly NOT_RUN).
* A physical speaker or microphone, anywhere; no human has heard this audio.
* Real GPU rendering (all 3D/renderer measurements are llvmpipe).
* Wayland keyboard shortcut end-to-end (QMP cannot deliver Super; the
  shortcut is rebindable and the button path is the proven one).
* Multi-language STT (one English model ships; `language` is validated to
  `automatic|en`).

## 10. What is NOT_SUPPORTED (by design, stated plainly)

* **Hands-free barge-in.** Push-to-talk is the product: no always-open
  microphone, no acoustic echo cancellation
  (`companion/speech/coordination.py` refuses simultaneous capture instead).
  Stopping Bunny is supported — the stop control, a new press, `voice_cancel`
  — and now actually works (§8).
* **Wake word** — the seam exists and settings refuse any value but
  `"disabled"`; the settings page says so on screen.
* **Cross-task conversational memory** — "Now close it." falls to help text.
  Voice and text are exactly equal here (same session record, same submit
  path — one "Bunny Desktop" session held all 29 tasks of the discovery run,
  typed included); neither modality carries prior turns into a new task.

## 11. Ledger of documented, unfixed observations

* The shell's JS character map has no waiting-for-approval state and shows
  "warning" during the question (the presentation text says "Waiting for
  permission..." correctly; the approval controls are right and deny-first).
* `desktopShell.js` keeps a second ad-hoc `_voicePhase` machine; the Python
  side remains the single semantic authority.
* `attention.py`'s always-visible-while-listening rule is enforced by tests,
  not by any production caller.
* `CharacterRendererController.set_mode()` does not notify the viseme or
  listening links; a mode switch mid-utterance is undefined at the library
  level (not reachable in the shipped window, which renders one mode).
* Vosk small-model confidence is not a rejection gate: German gibberish
  transcribed at 0.736. Noise-mixed speech degrades to wrong words
  ("how much memory and i use") rather than refusing.
* The two `test_character_cli_vertical` timing steps flip under host load
  (§4); their harness owns that.

## 12. Commits

```text
c1cbf98f  fix(voice): an interruption the protocol refused, and a silence the bridge sat out
a858cf5a  harness: the desktop probe is a server, not a oneshot
24168fbc  voice: the release contract, and a matrix that starts honest   ← the artifact
375fa830  test(voice): the approval buttons are asserted where they actually live
plus the evidence commit carrying this report, the completed matrix, and
qualification/voice-release/evidence/ (66 final + 92 discovery files, each
tree digest-manifested at its source before the copy)
```

Every commit after `24168fbc` (the artifact) touches only `tests/`,
`qualification/`, and root-level reports — none of which the image build
copies — so the artifact's identity survives the evidence landing, which is
the same zero-installed-paths discipline every prior phase closed under.

## 13. Stage 2 status

**COMPLETE.** Against the release gate in `VOICE_RELEASE_CONTRACT.md` §10:
voice input and output work on the exact built artifact from a real pointer
press (1); every truthfulness promise held under an independent poller (2);
STT and TTS behave across the phrase, noise, device-loss and provider-failure
sets (3); allow and deny were both driven and voice cannot bypass an approval
(4); every failure path recovered and the next interaction worked (5);
offline is PASS on all five components from a links-down run (6); performance
is measured, with two numbers honestly withheld rather than wrong (7); the
full suites ran with baseline/current/delta and a −1 delta (8); and all
evidence binds to the artifact's digests with source-side manifests (9).

What keeps this honest: the qualification found that **interruption had
never worked** — on this artifact and on the milestone before it — and the
proof of the fix is a real 130 ms measured by instruments that were
themselves repaired after being caught measuring nothing. No physical
speaker, microphone, or human ear appears anywhere in this evidence; that
boundary is stated on every claim it touches.
