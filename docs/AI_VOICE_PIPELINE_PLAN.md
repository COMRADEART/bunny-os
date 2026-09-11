# P1 Voice pipeline plan (host-honest NOT_RUN)

**Audience:** LEAD, Bunny AI, Platform, Security.
**Date:** 2026-09-11.
**Repository:** `COMRADEART/bunny-os`
**Base:** `main` after merge of [PR #50](https://github.com/COMRADEART/bunny-os/pull/50) (`b4b4a1397215af8df90694079d9b7e9d6d93de56`). Security co-signed #50 at **CODE**. `conversation-summary` stays **unwired**. `cloud_context=none` vs `remote_dispatch` is **not** tightened here (already Alpha-accepted on `main` as `59e247f9`).
**Platform:** confirmed **no Fedora 44 builder/image on the horizon.** Do not wait for IMAGE evidence. Package lists may name `llama-cpp`, `espeak-ng`, and `vosk-api-devel`; that is **not** a claim they land in an image.
**This document is:** host-honest `NOT_RUN` labels + a failure-isolation matrix. It is **not** a spoken PASS.

---

## AI STATUS: PARTIAL

| Verdict | Meaning here |
|---|---|
| **PARTIAL** | Spoken-path **source** exists. Every **voice stage on this host is NOT_RUN**. |
| **PASS** | Not claimed for any voice stage. Host tests must not mint spoken e2e. |
| **BLOCKED (image wait)** | **Not used.** There is no image to wait for. Voice stays `NOT_RUN`. |

Out of scope (unchanged): filling `conversation-summary`; tightening `authorize_cloud_context` / `remote_dispatch` vs `cloud_context=none`; OS-keystore DEK wrap; IMAGE/BOOT/USER FLOW PASS.

---

## Required pipeline (source shape only)

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

Wake-word is **disabled**. There is no always-on mic. Caption stays the output; TTS is optional.

---

## Voice stages — host label NOT_RUN

Every row below is **NOT_RUN** on this host. Source files are named so the matrix has somewhere to point. Finding `espeak-ng` or `libvosk.so` on a development machine would still be **NOT_RUN**: it is not an image and not spoken e2e.

| Stage | Host | Source (not evidence of a run) | Package list (not an image) |
|---|---|---|---|
| Push-to-talk | **NOT_RUN** | `companion/speech/request.py`, `CompanionViewModel.press_to_talk` | — |
| Microphone | **NOT_RUN** | `companion/speech/capture.py` | `pipewire-utils` / `alsa-utils` named in lists ≠ guest mic |
| STT (Vosk) | **NOT_RUN** | `companion/speech/vosk_runtime.py`, trusted `MODEL_DIRECTORIES` | `vosk-api-devel` named in `build/packages/` ≠ `libvosk.so` in an image |
| Intent / model | **NOT_RUN** | `companion/intents.py`, `companion/agents/adapters/llamacli.py` | `llama-cpp` named in lists ≠ `llama-cli` in an image |
| Tool / task | **NOT_RUN** | confirm → `submit_task` → `ToolBroker` | — |
| Response | **NOT_RUN** | presentation captions | — |
| TTS (Pocket / Kitten / eSpeak) | **NOT_RUN** | `companion/voice/providers.py`, `neural.py` | `espeak-ng` named in lists ≠ TTS in an image |
| **Spoken e2e** | **NOT_RUN** | — | — |

Typed/keyboard fallback is **not** a voice stage. `CompanionViewModel.submit()` remains the usable text door when speech is absent (`typedInputPreserved`).

Inventory (re-probes; every voice stage still `NOT_RUN`):

```bash
python3 tools/bunny-os/bin/bunny-os companion voice-pipeline-inventory
python3 -c "from companion.voice_pipeline import run_voice_pipeline_inventory; import json; print(json.dumps(run_voice_pipeline_inventory().to_json(), indent=2))"
```

---

## Companion AI states (do not fake thinking)

| Product state | `CompanionPhase` | Visual Key | Host |
|---|---|---|---|
| listening | `listening` / `transcribing` | `listening` | **NOT_RUN** live |
| understanding | `understanding` | `thinking` is a **projection** of understanding/planning/starting/recovering — not chain-of-thought | **NOT_RUN** live |
| executing | `working` | `working` or an activity key | **NOT_RUN** live |
| failed | `error` | `error` | **NOT_RUN** live |

A missing Vosk runtime, silence, or a refused transcript must degrade to typed input / `error` / idle — never a spinner that looks like the model is reasoning.

---

## Failure-isolation matrix

Each stage must fail **independently**. The companion and the typed path stay up. **Host live status for every row is NOT_RUN.** Contract tests (scripted PCM / injected engines) exist in source; they are not spoken e2e.

| Failure | What the code does if that stage dies | Contract tests (not live) | Host live |
|---|---|---|---|
| Mic unavailable | Health `AUDIO_UNAVAILABLE`; start refused; `typedInputPreserved` | `tests.companion.test_speech_service_protocol` | **NOT_RUN** |
| STT / `libvosk` missing | `STT_RUNTIME_MISSING`; import does not map the .so; `_build_speech` swallows | `tests.companion.test_speech_recognizers` | **NOT_RUN** |
| STT failure | `recognition_failed`; worker `finally` releases mic + indicator; retry or type | `tests.companion.test_speech_worker.Endings` | **NOT_RUN** |
| Silence | Disposition `no-speech`; **no** empty transcript submitted | `test_pure_silence_settles_as_no_speech_with_no_transcript` | **NOT_RUN** |
| Malformed transcript | `TranscriptError`; confirm refused; GTK typing remains | `tests.companion.test_speech_security.OversizedAndMalformedInput` | **NOT_RUN** |
| Model timeout | 120s `deadline_seconds` watchdog; `GenerationOutcome(ok=False)` | `companion/agents/adapters/llamacli.py` | **NOT_RUN** |
| Model crash / missing binary | `model-unavailable` / `connection`; task explains | adapter + registry | **NOT_RUN** |
| Tool failure | `ToolBroker.invoke` catches `Exception`; failed outcome recorded | `tests.companion.test_executors_reviewers` | **NOT_RUN** |
| TTS unavailable | Caption remains; `voiceFailureFailsTask: false`; `_build_voice` swallows | `tests.companion.test_voice_worker` | **NOT_RUN** |

This PR also probes that `SpeechInputService` / `VoiceService` **construct without raising** when assets are missing, and CLI `speech-input-health` / `voice-health` return `available: false` instead of crashing.

---

## Platform dependencies (lists ≠ image)

| Name in tree | Where code looks | Honest reading |
|---|---|---|
| Fedora 44 image | — | **None on the horizon.** Do not wait. |
| `vosk-api-devel` | `/usr/lib64/libvosk.so`, `/usr/lib/libvosk.so` | Listed under `build/packages/`. **Not** claimed installed in an image. |
| Vosk model | `/usr/share/bunny-os/speech-models`, `/var/lib/bunny-os/voice/models`, `~/.local/share/bunny-os/speech-models` | Repo does **not** vendor bytes. |
| `llama-cpp` | `/usr/bin/llama-cli`, `/bin/llama-cli` | Listed under `build/packages/companion-runtime.txt`. **Not** claimed in an image. |
| GGUF | trusted agent-model dirs | No download. None on this host. |
| `espeak-ng` | `espeak-ng` / `espeak` / `spd-say` | Listed under `build/packages/`. **Not** claimed in an image. |
| Pocket / Kitten weights | `/usr/share/bunny-os/voice/…` | No download. No GPU/NPU claim. |

---

## Tests that already exist vs this PR

Contract suites (scripted; **not** spoken e2e): `tests.companion.test_speech_*`, `test_vosk_runtime`, `test_voice_worker`, `test_voice_providers`, `test_product_vision.VoiceStoryTests`.

This PR:

```bash
python3 -m unittest tests.companion.test_voice_pipeline_plan -v
```

Asserts: every voice stage `NOT_RUN`; `spokenE2e == NOT_RUN`; `fedoraImageOnHorizon is False`; package-list flag set; isolation rows `hostStatus == NOT_RUN`; construction does not raise; typed `submit` still exists.

Gaps that stay open (and are **not** queued on an image): live Vosk, live mic, spoken→llama-cli, live TTS, native crash of `libvosk`, GPU/NPU.

---

## Authoring-host probe

See `tests.companion.test_voice_pipeline_plan`. Inventory JSON carries `fedoraImageOnHorizon: false` and `packageListIsNotImageEvidence: true`. Construction: no raise; speech readiness `STT_RUNTIME_MISSING`.

---

## Next recommendation

Keep every voice stage **NOT_RUN**. Do **not** start IMAGE verify/harden. Do **not** fill `conversation-summary`. Do **not** retighten `cloud_context=none` vs `remote_dispatch`. Typed input stays the usable path.
