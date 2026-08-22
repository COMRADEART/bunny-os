<!-- SPDX-FileCopyrightText: 2026 ComradeArt -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Bunny voice image packaging

This is the installed-system contract for Bunny's push-to-talk stack. Audio
capture and speech inference remain in `bunny-companion.service`; GNOME Shell
only invokes the versioned companion protocol and renders microphone, transcript
and lifecycle events. No voice code opens an audio device or loads a model in
the compositor process.

## Runtime dependency matrix

| Component | Fedora package or image payload | Required | Declared in image | Packaging result |
|---|---|---:|---:|---|
| PipeWire capture (`pw-record`, `pw-dump`) | `pipewire-utils` | Preferred | Yes | Named directly in `build/packages/desktop.txt` |
| PulseAudio-compatible capture (`parec`, `pactl`) | `pulseaudio-utils`, `pipewire-pulseaudio` | Fallback | Yes | Named directly; no transitive-package assumption |
| ALSA capture (`arecord`) | `alsa-utils` | Last fallback | Yes | Named directly |
| Vosk native STT runtime (`libvosk.so`) | `vosk-api-devel` | Yes | Yes | Fedora 44's only Vosk API binary subpackage; called through the public C API |
| Python STT dependencies | Python standard library `ctypes` | Yes | Yes | No PyPI wheel, downloader, HTTP client, subtitle or WebSocket dependency |
| English STT model | `assets/voice/models/vosk-model-small-en-us-0.15` | Yes | Yes | Installed read-only at `/usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15` |
| Default neural TTS | bundled Pocket TTS 2.1.0 source, English model and prepared CC0 voice | Yes | Yes | Default local CPU provider; no voice-cloning surface or network path |
| Pocket CPU runtime | official PyTorch 2.9.1+cpu `cp314` wheel | Yes | Yes | Outer SHA-256 and every wheel `RECORD` entry are verified and expanded only at image build |
| Pocket Python dependencies | Fedora Python packages named in `build/packages/desktop.txt` | Yes | Source declared | Package lock/snapshot refresh is still required before the exact candidate can build |
| Low-resource neural TTS | Kitten TTS Nano INT8 model plus `python3-onnxruntime` | Optional provider, installed in Alpha source definition | Source declared | Fixed local ONNX CPU adapter and packaged eSpeak phonemizer |
| Direct system TTS | `espeak-ng` | Required fallback | Yes | Third provider in the fixed local fallback order |
| Speech Dispatcher TTS | `speech-dispatcher`, `speech-dispatcher-espeak-ng`, `speech-dispatcher-utils` | Optional fallback | Yes | `spd-say` and bounded logging configuration ship |
| Neural inference entry point | `bunny-voice-neural-worker` | Yes | Yes | Persistent bounded JSON child of `bunny-companion.service`; Python isolated mode, AF_UNIX-only cgroup |
| Bunny voice runtime | `companion/speech`, `companion/voice` | Yes | Yes | Installed under `/usr/lib/bunny-os/python/companion`; inference is outside GNOME Shell |
| Session lifecycle | `bunny-companion.service` | Yes | Yes | Installed in `/usr/lib/systemd/user`, globally enabled for `graphical-session.target` |
| IPC | private companion AF_UNIX socket | Yes | Yes | Socket lives in `%t/bunny-companion` with mode `0700`; no network address family is allowed |

The resolution half of that obligation is closed: `build/inputs/package-lock.json`
was re-resolved against the retained base with `resolve-package-lock.py` (101
named packages, 642-package transaction, every signature verified), so it now
covers the voice command-package declarations and the Pocket/Kitten
Python/ONNX dependencies.
`tests/supplychain/test_input_locks.py::PackageLockConsistencyTests` binds the
lock to the declared sets, so the two cannot drift apart silently again.

The retained **snapshot** itself — the signed, materialised repository the
hermetic build installs from — still predates those declarations and must be
re-materialised and re-signed before a future hermetic release build. The
Public Alpha build is explicitly non-hermetic and resolves the named Fedora 44
packages while recording the installed RPM inventory in its artifact.

## TTS distribution and size accounting

Pocket is installed as immutable image data under
`/usr/share/bunny-os/voice/pocket/english`; Kitten Nano INT8 is under
`/usr/share/bunny-os/voice/kitten/nano-int8`. The pure-Python Pocket package and
expanded CPU-only PyTorch wheel live under
`/usr/lib/bunny-os/voice-runtime/site-packages`. Neither login nor first use
downloads a model.

The checked-in byte counts are exact:

| Payload | Bytes | What the number includes |
|---|---:|---|
| Pocket English model/default prepared voice | 224,351,600 | config, integrity manifest, weights, tokenizer, prepared voice state |
| Pocket 2.1.0 Python runtime and metadata | 172,490 | vendored package and minimal distribution metadata |
| PyTorch CPU wheel staging input | 184,378,975 | pinned wheel plus retained Bunny wheel manifest |
| PyTorch CPU wheel after expansion | 682,347,734 | all four wheel roots; compressed wheel is removed from the image |
| Pocket installed lower bound | 906,871,824 | Pocket model/runtime plus expanded PyTorch, before shared Fedora packages and notices |
| Kitten Nano INT8 model payload | 27,652,174 | config, ONNX weights, voices, manifest/model card |
| All selected checked-in TTS runtime/model/notices | 436,603,918 | repository input size before wheel expansion |
| Installed selected-asset lower bound | 934,573,334 | checked-in selection with the PyTorch wheel replaced by its expanded bytes |

The final compressed artifact delta, Fedora dependency installed sizes, eSpeak
RPM installed size and measured filesystem block usage remain unknown until the
exact Fedora candidate builds. Those values must come from that artifact rather
than from package names or compression guesses.

The Fedora `python3-torch` RPM is intentionally excluded: the Fedora 44 build
pulls a hard ROCm/GPU dependency closure. Bunny instead pins the official
manylinux CPU wheel compatible with the image's CPython 3.14 ABI. The build
verifies the wheel's outer digest, member bounds, safe paths and every hashed
`RECORD` member before installation.

## Model distribution and integrity

Alpha bundles exactly one English model. It is never downloaded at boot or at
login. `assets/voice/PROVENANCE.json` records the upstream archive URL, archive
size, SHA-256, licence, extraction size and file count. The model's
`.bunny-model.json` records the size and SHA-256 of every upstream file.

Discovery order is fixed and cannot be redirected by an assistant request:

1. `/usr/share/bunny-os/speech-models` — immutable, image-reviewed models;
2. `/var/lib/bunny-os/voice/models` — administrator-managed models;
3. `~/.local/share/bunny-os/speech-models` — models installed knowingly by the user.

Settings select only a bounded model directory name, never a path. Discovery
rejects symlinks, special files, foreign ownership, group/world-writable model
content, missing required Vosk files, an incomplete graph or i-vector tree, and
any hash/size mismatch in a Bunny integrity manifest. A structurally valid
third-party user model without a Bunny manifest remains selectable, but does not
gain a claim of byte-level Bunny attestation.

## Readiness and failure behavior

`speech_input_health` exposes both human detail and a stable readiness state:

- `STT_READY`
- `STT_MODEL_MISSING`
- `STT_MODEL_CORRUPT`
- `STT_RUNTIME_MISSING`
- `STT_PROVIDER_FAILED`
- `AUDIO_UNAVAILABLE`
- `VOICE_INPUT_DISABLED`
- `VOICE_RESOURCE_UNAVAILABLE`

The shell maps missing runtime/model states to “Voice recognition isn't
installed yet,” corrupt content to a repair message, and audio absence to “No
microphone is available.” Typed input and text responses remain available in
every state. Missing TTS never prevents a text response.

TTS provider health separately exposes `INITIALIZING`, `MODEL_VERIFIED`, `READY`,
`RUNTIME_MISSING`, `MODEL_MISSING`, `MODEL_CORRUPT` and `WORKER_FAILED` for
Pocket and Kitten. `READY` is emitted only after the isolated worker has loaded
the pinned model and an installed voice. The ordinary startup observation
integrity-checks assets asynchronously and stops at `MODEL_VERIFIED`; it does
not load both inference stacks at login. The first selected utterance loads only
its provider on the dedicated voice worker, never the GNOME Shell thread.

The service starts at graphical login, opens no microphone at startup, loads no
STT model until an explicit capture, and has no visible companion window by
default. Shell extension reloads reconnect to the same long-lived service.

## Diagnostic record

Capture journal events record the selected backend and device, raw PCM format
(`S16LE`, 16 kHz mono), capture duration, byte count, dropped-byte count and
recorder exit status. Raw audio is never exposed through IPC and batch audio is
deleted when recognition finishes or fails.
