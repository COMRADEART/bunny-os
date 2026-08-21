<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny OS Voice Release Contract (Stage 2)

Candidate: `feature/bunny-companion-capsules-trust` at **`72ff8063`**.
Artifact under qualification: the `shell-test` image built from that commit on
the Fedora 44 reference builder, base sourced from the verified retention
mirror (`sha256:1f08084a…`, locked upstream digest `sha256:c466de53…` — the
upstream tag has been rebuilt away, so retention is the only honest source).

This document states what "release-grade voice" means for Bunny, in the
vocabulary the code actually uses. Every claim in it is either bound to
evidence in `qualification/voice-release/` or marked `NOT_RUN` /
`NOT_SUPPORTED`. The matrix is the gate; this contract is its dictionary.

## 1. The interaction the contract covers

```text
User speaks (push-to-talk)
  → microphone activates          speech_input_start, indicator raised
  → speech is captured            companion/speech/capture.py (parec/pw-record/arecord)
  → STT produces a transcript     companion/speech/recognizers.py (Vosk, local)
  → the transcript becomes a task CompanionGateway.speech_input_confirm
                                  → _submit_runtime_task — the same call typed
                                    input reaches; there is no voice-only path
  → the agent plans and acts      approvals derived from tool declarations,
                                  resolved through resolve_approval
  → a reply is produced           text first; the caption is authoritative
  → TTS speaks it                 companion/voice/worker.py, provider ladder
  → the user hears it             PipeWire → PulseAudio → ALSA backend ladder
  → the companion returns to idle presentation phase → CharacterState.IDLE
```

Activation is **push-to-talk only** (button, keyboard shortcut, protocol
request, accessibility control — the closed set in
`companion/speech/request.py`). Wake-word and always-listening capture are
**NOT_SUPPORTED by design**: the seam exists (`companion/speech/wakeword.py`)
and settings refuse any value but `"disabled"`. This is a privacy decision,
not a gap.

## 2. State machine

There is one semantic authority. The presentation phase
(`companion/presentation.py`, 18 phases) plus the microphone flags
(`listening`, `transcribing`, `speaking`) map through
`companion/character/mapper.py` to the 27-value `CharacterState`. The voice
and speech runtimes never write character state directly; they emit events,
and the mapper is the only translator. Stage 2 adds no second machine.

The voice path produces, in the canonical vocabulary:

```text
IDLE → LISTENING → TRANSCRIBING → UNDERSTANDING/PLANNING
     → WAITING_FOR_APPROVAL (when an approval is required)
     → WORKING → SPEAKING → SUCCESS → IDLE
errors:   → ERROR → IDLE          (recoverable, §8)
```

"Thinking" and "talking" are shell-side display names for
UNDERSTANDING/PLANNING and SPEAKING; `waiting_for_permission` is the attention
projection's name for WAITING_FOR_APPROVAL. The matrix uses the canonical
names and records the shell's renderings where they differ.

**Truthfulness promises** (each is a matrix row, not an assumption):

* The companion never claims it is listening while the capture handle is
  closed — the indicator refuses to clear while the handle is open
  (`companion/speech/indicator.py`), and the shell keeps the MIC chrome up
  until the companion confirms `microphoneClosed` (`voice.js`).
* The companion never claims it is speaking after playback stopped — the
  worker's `speech_finished`/`speech_error` events and the sink's own state
  are the evidence, not a timer.

## 3. Input contract

| Requirement | Mechanism |
|---|---|
| Microphone discovery | `speech_input_devices`; PipeWire metadata `default.configured.audio.source` (`companion/pipewire.py`) |
| Microphone selection | `settings_voice_set.deviceId`; capture backend receives the id |
| Microphone permission | Speech policy (`companion/speech/policy.py`) + activation-source allowlist; the persistent indicator is part of the permission story. For capsules, the `microphone` trust category allows `once`/`session` only — a sensor never gets "Always allow". |
| Audio capture | Recorder over `parec`/`pw-record`/`arecord` under the multicall player contract |
| Speech detection | RMS energy gate with self-calibrating floor (`companion/speech/activity.py`) |
| Speech-to-text | Vosk, in-process, model from a fixed three-root tuple — a writable model path is code injection with extra steps |

## 4. Processing contract

* A confirmed transcript reaches the agent through
  `CompanionGateway.speech_input_confirm → _submit_runtime_task` — the
  identical function typed input uses. Same session store, same task
  lifecycle, same path-context binding.
* Voice requests obey the existing permission system: approvals derive from
  tool declarations (`companion/approvals.py`); a voice task's approval
  question is the same binary **Allow / Deny** prompt every task gets, with
  deny as the default, initial-focus, and escape action. Decisions:
  `granted / denied / expired / pending`, TTL 900 s. The four-scope
  vocabulary ("Allow once / Allow while using / Always allow / Don't allow")
  belongs to the capsule trust broker (`trust/explain.py`) and applies when a
  voice-initiated action reaches a capsule capability — both vocabularies are
  verified where they actually apply.
* Session continuity: voice and text share the session record and task list.
  **Cross-task conversational memory does not exist in any modality** — the
  agent context carries prior operations of the same task, not prior turns.
  The contract therefore claims *parity*, and marks follow-up-by-reference
  `NOT_SUPPORTED` (equally for voice and for text) rather than inventing a
  voice-only memory.

## 5. Output contract

| Requirement | Mechanism |
|---|---|
| Text response | The caption is authoritative; speech is a second rendering of it (`companion/voice/captions.py`) |
| TTS generation | Provider ladder `pocket → kitten → espeak-ng → speech-dispatcher`, one-directional fallback from the preference onward |
| Audio playback | Backend ladder PipeWire → PulseAudio → ALSA; router with failure hysteresis |
| Playback interruption | `voice_cancel` (requestId / taskId / token); interruption honoured by priority ladder; renderer gets `speech_cancelled → neutral` |
| Return to idle | `speech_finished` → presentation phase → IDLE; quiescence may then settle |
| TTS failure | The text answer stays; the character never enters SPEAKING; no crash — proven previously on an overlaid image, re-proven here on the artifact |

## 6. Interruption

Stopping Bunny mid-speech is supported: the on-screen control
("Stop Bunny speaking"), `voice-cancel`, and a new push-to-talk press each
stop playback (target < 250 ms to silence). **True barge-in — speaking over
Bunny hands-free and having it yield — is NOT_SUPPORTED**, because there is no
always-open microphone and no echo cancellation
(`companion/speech/coordination.py` keeps Bunny's own voice out of its own
microphone by refusing simultaneous capture, not by AEC). This is documented,
not pretended away.

## 7. Offline

Every provider in the ladder is local; the neural worker sets
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and the synthesis child gets
`BUNNY_VOICE_NETWORK=disabled`. Vosk is in-process with local models. The
offline matrix (§10 of the Stage 2 report) is proven by runs with every
non-loopback link down, not inferred from this paragraph.

## 8. Failure recovery

Every failure ends in a state a person can act from — never a permanent
LISTENING / THINKING / SPEAKING:

* Microphone unavailable / lost mid-capture → the interaction ends with the
  device-loss reason, the indicator clears, a retry is offered
  (`speech_input_retry`), and the next interaction works.
* STT unavailable (model missing/corrupt/runtime missing) → readiness state
  names the reason; the microphone control is disabled with the reason; text
  interaction is unaffected.
* TTS unavailable → the text answer remains; ERROR is presentational only.
* Network unavailable → nothing in the voice path needs it (see §7).

## 9. Companion integration

One semantic state drives all three renderers (`RenderMode`:
`prerendered / 2d / 3d`) through the same `CharacterPresenter` →
`display_state()` path; listening/transcribing/speaking are honoured in each
mode's own vocabulary (pre-rendered safety-holds, procedural postures, 3D
animation candidates + listening overlay). Quiescence never freezes a
voice-active character: `NEVER_QUIESCENT` contains LISTENING, TRANSCRIBING,
SPEAKING, WAITING_FOR_APPROVAL, and any state change wakes the clock. These
are verified per-mode on the artifact, not assumed from the table.

## 10. The release gate

Stage 2 is complete only when, **on the built artifact** (no overlays, no
injected transcripts, from a real pointer press on the visible microphone
button):

1. speak → understand → act → respond → idle passes end-to-end;
2. every truthfulness promise in §2 holds against runtime evidence;
3. STT and TTS behave per §3/§5 across the matrix's phrase and failure sets;
4. permissions cannot be bypassed by voice (allow and deny both driven);
5. every §8 failure path recovers;
6. offline behaviour is classified per-component with run evidence;
7. performance is measured (or a number is honestly withheld, with the
   reason, as the worker-RSS number was in the E2E report);
8. the full test suites pass with baseline/current/delta reported;
9. all evidence carries provenance: candidate commit, image digest, host,
   date, and the exact command that produced it.

`NOT_RUN` stays `NOT_RUN` without new evidence. `NOT_SUPPORTED` is written
where the product genuinely does not support a thing, with the design reason.
