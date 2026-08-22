# Provisioning an offline speech-recognition model

This directory is installed read-only to `/usr/share/bunny-os/speech-models`
and is one of the two model directories the Vosk recognizer reads (the other
is `~/.local/share/bunny-os/speech-models`, for a user-owned model). The
recognizer scans for directories named `vosk-model-...` and infers the
language from the name; `vosk-model-small-en-us-0.15` is the small English
model the runtime expects by default.

No model is vendored in this repository and none is downloaded at boot. The
operator places a Vosk model directory here before a rebuild, or a user drops
one into the per-user trusted directory at runtime. A directory with no model
is not an error: the recognizer reports "no model found" and the push-to-talk
path declines to listen, rather than fetching one — offline by construction.

## Adding a model to the image

1. Obtain a Vosk model (e.g. `vosk-model-small-en-us-0.15` from
   https://alphacephei.com/vosk/models). Record its origin and licence
   (Apache-2.0 for the small models) in a provenance file next to it.
2. Place the unpacked model directory in this directory
   (`assets/voice/models/`).
3. Rebuild. The `speech-models` install route copies the tree to
   `/usr/share/bunny-os/speech-models/` read-only (mode 0444).
4. On boot, the recognizer discovers the model and the speech-input path
   becomes available.

## What is deliberately not here

- No auto-download. The image is offline by construction.
- No fabricated or placeholder model. A speech path that has not been
  exercised with a real microphone on real hardware is marked `NOT_RUN`, not
  declared working.