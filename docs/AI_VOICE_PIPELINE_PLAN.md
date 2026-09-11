# P1 Voice pipeline plan (host-honest)

**Audience:** LEAD, Bunny AI, Platform.
**Date:** 2026-09-11.
**Repository:** `COMRADEART/bunny-os`
**Base:** `main` after merge of [PR #50](https://github.com/COMRADEART/bunny-os/pull/50) (`b4b4a1397215af8df90694079d9b7e9d6d93de56`).
**This document is:** planning + host-honest harness. It is **not** a spoken PASS.
**LEAD instruction honoured:** start voice planning; start verify/harden only when Platform can give Fedora image evidence; do **not** mark spoken e2e PASS from host unit tests.

---

## AI STATUS: PARTIAL (runtime BLOCKED)

| Verdict | Meaning here |
|---|---|
| **PARTIAL** | The spoken path **exists in source** and is wired: push-to-talk, Vosk STT, confirmation → `submit_task`, local intent / model executors, caption-first TTS (Pocket → Kitten → eSpeak NG / Speech Dispatcher), typed fallback. Independent failure isolation is **designed and unit-tested with fixtures**. |
| **BLOCKED** | Live STT, live microphone, live local-LLM generation from a transcript, and live TTS playback. This host has no Fedora image, no guest mic, and (typically) no `libvosk.so` / Vosk model / GGUF / neural TTS weights. |
| **PASS** | Not claimed. Spoken e2e on hardware would require IMAGE/BOOT evidence. Host tests must not mint that. |

`conversation-summary`, `authorize_cloud_context` vs `remote_dispatch` tightening, and OS-keystore DEK wrap are **out of scope** (Security / Memory follow-ups). No IMAGE/BOOT/USER FLOW PASS is claimed.

---

## Required pipeline (what “voice” actually is)

```text
explicit push-to-talk
        → capture (pw-record / parec / arecord)
        → STT (Vosk ctypes → libvosk.so + trusted model dir)
        → user confirmation (default)
        → CompanionGateway.submit_task   ← same door as typed/keyboard input
        → intent / local model (llama-cli + GGUF) / tool broker
        → presentation caption (authoritative)
        → TTS (Pocket → Kitten → eSpeak NG → Speech Dispatcher)
```

Wake-word is **disabled**: `WakeWordService.enable()` raises. There is no always-on mic.

---

## Per-stage evidence: CODE vs NOT_RUN vs IMAGE/BOOT

Legend:

| Label | Means |
|---|---|
| **CODE** | Source exists; host unit tests may PASS the *contract*. |
| **NOT_RUN** | This host did not execute the live step. Missing assets/mic are NOT_RUN, never FAIL-for-absence, never fixture-PASS. |
| **IMAGE/BOOT** | Needs a booted Fedora image (and usually a guest microphone / speakers). Unverified here. |

| Stage | CODE | This host | IMAGE/BOOT |
|---|---|---|---|
| 1. Push-to-talk | `companion/speech/request.py` closed `activationSource`; GTK `CompanionViewModel.press_to_talk`; protocol `speech_input_start` | CODE PASS (contract) | Live button in a session: **NOT_RUN** |
| 2. Microphone capture | `companion/speech/capture.py` PipeWire / Pulse / ALSA; indicator before open | Capture helper presence probed; live capture **NOT_RUN** | Guest mic **NOT_RUN** |
| 3. STT runtime | `companion/speech/vosk_runtime.py` loads only `/usr/lib64/libvosk.so` or `/usr/lib/libvosk.so` | **NOT_RUN** if library missing (typical cloud host) | Packaged `vosk-api-devel` on Fedora image |
| 4. STT model | Trusted dirs only: `/usr/share/bunny-os/speech-models`, `/var/lib/bunny-os/voice/models`, `~/.local/share/bunny-os/speech-models` | **NOT_RUN** — repo does not vendor bytes | Image install of `vosk-model-small-en-us-0.15` |
| 5. STT live | Vosk streaming session | **NOT_RUN** — fixture transcript is labelled, not a recording | Real speech in a real room |
| 6. Silence | Energy gate + `no-speech` disposition | CODE PASS (`test_speech_worker.Endings`) | Room silence on hardware **NOT_RUN** |
| 7. Malformed transcript | `bounded_transcript_text` refuses controls/oversize; partials cannot become tasks | CODE PASS | — |
| 8. Intent | `companion/intents.py` `recognise()` closed grammar | CODE PASS on **fixture** text | Spoken intent **NOT_RUN** |
| 9. Model | `llama-cli` at `/usr/bin` or `/bin`; GGUF in trusted dirs; 120s generation deadline | Binary/weights typically **NOT_RUN** | Fedora image + GGUF |
| 10. Model timeout/crash | `llamacli` watchdog returns `GenerationOutcome(ok=False)` | CODE path exists; live timeout **NOT_RUN** | IMAGE/BOOT |
| 11. Tool/task | Same `submit_task` as typing; `ToolBroker` allow-list | Fixture local intent CODE PASS | Live desktop tool **NOT_RUN** |
| 12. Tool failure | `ToolBroker.invoke` catches `Exception` | CODE PASS | IMAGE/BOOT |
| 13. Response / captions | Presentation projector; caption is the output | CODE PASS | Spoken caption **NOT_RUN** |
| 14. TTS | Pocket (neural worker, no in-process PyTorch) → Kitten → eSpeak NG → `spd-say` | Binary/weights probed; **live playback NOT_RUN** | Speakers on image |
| 15. Typed/keyboard fallback | `CompanionViewModel.submit()`; speech unavailable → `typedInputPreserved: true` | CODE PASS | — |
| 16. Companion states | See below | CODE PASS (mapping) | Live pose on image **NOT_RUN** |
| **Spoken e2e** | — | **NOT_RUN** | **NOT_RUN** until Platform Fedora evidence |

Host inventory command (re-probes; does not freeze this table):

```bash
python3 tools/bunny-os/bin/bunny-os companion voice-pipeline-inventory
# or
python3 -c "from companion.voice_pipeline import run_voice_pipeline_inventory; import json; print(json.dumps(run_voice_pipeline_inventory().to_json(), indent=2))"
```

---

## Companion AI states (real pipeline, not fake thinking)

Required product states: **listening, understanding, executing, failed**.

| Product state | Actual `CompanionPhase` | Visual Key | Honest? |
|---|---|---|---|
| listening | `listening` (then `transcribing`) | `listening` | Yes. Indicator raised before the mic opens. |
| understanding | `understanding` | `thinking` (**projection** of `understanding` / `planning` / `starting` / `recovering`) | The pose name is “thinking”; it is **not** chain-of-thought and **must not** be shown while STT is missing or stalled. |
| executing | `working` (task `executing`) | `working` or an activity key (`searching`, …) | Yes. There is no separate “waiting for tool” phase. |
| failed | `error` (task `failed`) | `error` | Yes. |

Do **not** fake thinking: a missing Vosk runtime, silence, or a refused transcript must degrade to a typed-input message / `error` / idle — not a spinner that looks like the model is reasoning.

Character listening postures come from real speech events (`companion/character/listening_link.py`). Renderer failure is swallowed so a draw cannot stop capture.

---

## Failure-isolation matrix

Each stage must fail **independently**. The companion and the typed path stay up. Source status vs live proof:

| Failure | What the code does | Host tests | Live IMAGE/BOOT |
|---|---|---|---|
| Mic unavailable | Health `AUDIO_UNAVAILABLE`; start refused; `typedInputPreserved` | CODE (scripted backends + health) | **NOT_RUN** |
| STT / `libvosk` missing | `STT_RUNTIME_MISSING`; constructor does not map the .so at import; `_build_speech` swallows | CODE + this PR construction probe | **NOT_RUN** |
| STT model missing/corrupt | `STT_MODEL_MISSING` / `STT_MODEL_CORRUPT` | CODE (`test_speech_recognizers`) | **NOT_RUN** |
| STT engine crash mid-capture | Session settles `failed` / `recognition_failed`; worker `finally` releases mic + indicator | CODE (scripted) | Native crash **NOT_RUN** |
| Silence | Disposition `no-speech`; **no** empty transcript submitted | CODE | **NOT_RUN** |
| Malformed transcript | `TranscriptError`; confirm refused; GTK falls back to typing | CODE | **NOT_RUN** |
| Model timeout | 120s `deadline_seconds` watchdog; `GenerationOutcome(ok=False)` | CODE path | Live hang **NOT_RUN** |
| Model crash / missing binary | `model-unavailable` / `connection`; task blocks or fails with explanation | CODE | **NOT_RUN** |
| Tool failure | Broker records failed outcome; reviewer still runs | CODE | Live desktop tool **NOT_RUN** |
| TTS unavailable | Caption remains; `voiceFailureFailsTask: false`; Pocket/Kitten/eSpeak each report unavailable rather than empty success | CODE | Playback **NOT_RUN** |
| TTS child crash | Voice worker catches per utterance; `_build_voice` swallows at service start | CODE | **NOT_RUN** |

`CompanionService._build_speech` and `_build_voice` already catch all construction exceptions so a missing library cannot prevent the service from starting. This PR adds a host probe that **constructs** both runtimes and asserts they do not raise, plus CLI health commands that return `available: false` instead of crashing if construction ever does raise.

---

## Exact Platform dependencies (do not download, do not vendor)

| Dependency | Where the code looks | Package / payload | This PR |
|---|---|---|---|
| Fedora image | bootc Fedora 44 guest | Platform | **BLOCKED** — start verify/harden only with image evidence |
| `libvosk.so` | `/usr/lib64/libvosk.so`, `/usr/lib/libvosk.so` only | `vosk-api-devel` | No download |
| Vosk model dir | `MODEL_DIRECTORIES` (see above); name `vosk-model-…` | `assets/voice/models/` install route → `/usr/share/bunny-os/speech-models/` | No vendor bytes |
| Capture in guest | `pw-record` / `parec` / `arecord` | `pipewire-utils`, `pulseaudio-utils`, `alsa-utils` | Host helper probe only |
| Guest microphone | PipeWire / ALSA source that is not a monitor | Hardware / QEMU audio | **NOT_RUN** |
| `llama-cli` | `/usr/bin/llama-cli`, `/bin/llama-cli` | image `llama-cpp` | No PATH search |
| GGUF | `/usr/share/bunny-os/agent-models`, `~/.local/share/bunny-os/agent-models` | `assets/ai/models/` | No download |
| Pocket TTS weights | `/usr/share/bunny-os/voice/pocket/english` | image LFS / install route | No download |
| Kitten TTS | `/usr/share/bunny-os/voice/kitten/nano-int8` | optional image payload | No download |
| eSpeak NG / Speech Dispatcher | `espeak-ng`, `espeak`, `spd-say` | `espeak-ng`, `speech-dispatcher` | Binary probe only |
| Neural worker | `/usr/bin/bunny-voice-neural-worker` | companion package | No in-process PyTorch |
| GPU / NPU | not a voice scheduling input | — | **Not claimed** |

Packaging contract (already documented, not re-proven here): `docs/VOICE_IMAGE_PACKAGING.md`, `assets/voice/models/PROVISIONING.md`.

---

## Test commands that already exist vs gaps

### Already exist (host; fixtures/scripted audio — not live speech)

```bash
python3 -m unittest \
  tests.companion.test_speech_worker \
  tests.companion.test_speech_capture \
  tests.companion.test_speech_recognizers \
  tests.companion.test_speech_service_protocol \
  tests.companion.test_speech_races \
  tests.companion.test_speech_security \
  tests.companion.test_speech_confirmation \
  tests.companion.test_speech_schema \
  tests.companion.test_speech_authority \
  tests.companion.test_vosk_runtime \
  tests.companion.test_voice_worker \
  tests.companion.test_voice_providers \
  tests.companion.test_voice_audio \
  tests.companion.test_voice_authority \
  tests.companion.test_product_vision.VoiceStoryTests \
  -q
```

These suites **PASS the contracts** (silence, malformed frames, missing Vosk library as `STT_RUNTIME_MISSING`, TTS unavailable, captions authoritative). They inject scripted recognisers / PCM. That is **CODE**, not spoken e2e.

Vertical slices (still not a guest mic):

```bash
python3 tools/bunny-os/bin/bunny-os companion speech-input-health
python3 tools/bunny-os/bin/bunny-os companion voice-health
python3 tools/bunny-os/bin/bunny-os companion run-speech-slice   # scripted / installed slice; not physical speech
python3 tools/bunny-os/bin/bunny-os companion run-voice-slice    # may be NOT_RUN without a synthesiser
```

Product-vision demo (honest NOT_RUN for STT/mic/TTS):

```bash
python3 demos/10-product-vision/run.py
```

### Added by this PR

```bash
python3 -m unittest tests.companion.test_voice_pipeline_plan -v
python3 tools/bunny-os/bin/bunny-os companion voice-pipeline-inventory
```

Asserts: `spokenE2e == NOT_RUN`; STT live / mic live / TTS playback never PASS; fixture transcript labelled; SpeechInputService / VoiceService construct without raising when assets are missing; typed `submit` still exists.

### Gaps (do not close from this host)

| Gap | Why it stays open |
|---|---|
| Live Vosk on real speech | Needs `libvosk.so` + model + mic in guest |
| Guest push-to-talk in GNOME | Needs Fedora image + session |
| Spoken intent → llama-cli plan | Needs GGUF + `llama-cli` on image |
| Live tool after a spoken request | Needs desktop in guest |
| Live TTS through a DAC | Needs speakers / QEMU audio + weights or espeak |
| Independent native crash of `libvosk` / neural worker | Needs IMAGE/BOOT |
| STT accuracy in a real room | Hardware; `docs/phase-1` already forbids wav-file PASS |
| GPU/NPU voice or GGUF offload | Out of scope; not claimed |

`scripts/voice_measure.py` and qualification `qualification/companion-voice/` evidence folders are **historical packaging/slice records**, not this host’s spoken e2e.

---

## What this PR changes (code)

1. `docs/AI_VOICE_PIPELINE_PLAN.md` — this plan.
2. `companion/voice_pipeline.py` — host inventory; `spokenE2e` hard-wired `NOT_RUN`.
3. `companion/voice_story.py` — probe production `MODEL_DIRECTORIES`; never treat unattended TTS playback or a capture-helper node as live speech PASS.
4. CLI `voice-pipeline-inventory`; `speech-input-health` / `voice-health` return `available: false` instead of crashing if construction raises.
5. Host tests in `tests/companion/test_voice_pipeline_plan.py`.

No model downloads. No vendored model bytes. No GPU/NPU claims. No spoken PASS.

---

## Next recommendation

**BLOCKED on Fedora image evidence.** When Platform can provide a bootable image with:

1. `libvosk.so` + `vosk-model-small-en-us-0.15` under `/usr/share/bunny-os/speech-models/`
2. a guest microphone (not a monitor source)
3. `llama-cli` + one trusted GGUF (optional for the speech-only slice; required for spoken→model)
4. eSpeak NG and/or packaged Pocket/Kitten weights
5. speakers or QEMU audio that actually plays

…then start P1 **verify/harden** on that image. Until then, keep every live STT/mic/TTS row `NOT_RUN`. Do not promote host unit tests to spoken e2e.

Optional later (still not this PR): bind Visual Key `thinking` more tightly to `understanding`/`planning` only, so a missing STT path cannot present as thought.
