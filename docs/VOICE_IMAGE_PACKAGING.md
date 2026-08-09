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
| Direct local TTS | `espeak-ng` | Yes | Yes | Primary lightweight offline synthesizer |
| Speech Dispatcher TTS | `speech-dispatcher`, `speech-dispatcher-espeak-ng`, `speech-dispatcher-utils` | Optional fallback | Yes | `spd-say` and bounded logging configuration ship |
| Bunny voice runtime | `companion/speech`, `companion/voice` | Yes | Yes | Installed under `/usr/lib/bunny-os/python/companion`; inference is outside GNOME Shell |
| Session lifecycle | `bunny-companion.service` | Yes | Yes | Installed in `/usr/lib/systemd/user`, globally enabled for `graphical-session.target` |
| IPC | private companion AF_UNIX socket | Yes | Yes | Socket lives in `%t/bunny-companion` with mode `0700`; no network address family is allowed |

The retained hermetic Fedora package snapshot predates the voice command-package
declarations. It must be resolved and re-signed before a future hermetic release
build. The Public Alpha build is explicitly non-hermetic and resolves the named
Fedora 44 packages while recording the installed RPM inventory in its artifact.

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

The service starts at graphical login, opens no microphone at startup, loads no
STT model until an explicit capture, and has no visible companion window by
default. Shell extension reloads reconnect to the same long-lived service.

## Diagnostic record

Capture journal events record the selected backend and device, raw PCM format
(`S16LE`, 16 kHz mono), capture duration, byte count, dropped-byte count and
recorder exit status. Raw audio is never exposed through IPC and batch audio is
deleted when recognition finishes or fails.
