# Provisioning a local AI model

This directory is installed read-only to `/usr/share/bunny-os/agent-models`
and is one of the two trusted model directories the `local.llamacli` adapter
reads (the other is `~/.local/share/bunny-os/agent-models`, for a user-owned
model). The adapter discovers any `*.gguf` file here, refuses any file that is
group- or world-writable, and resolves `llama-cli` from `/usr/bin` or `/bin`
only — never from `PATH`, never from a configured path.

No model is vendored in this repository and none is downloaded at boot. The
intended Alpha path is for the operator to place a small (1B–3B) GGUF here
before a rebuild, or for a user to drop one into the per-user trusted
directory at runtime. A directory with no `.gguf` is not an error: the adapter
probes to "unavailable" with the reason, and selection falls back to the next
eligible provider or blocks with the explanation — graceful unavailability,
not a silent skip.

## Adding a model to the image

1. Obtain a GGUF whose licence permits redistribution (e.g. a Llama, Qwen or
   Phi small model). Record its origin and licence in a provenance file next
   to it.
2. Place the `.gguf` in this directory (`assets/ai/models/`).
3. Rebuild. The `agent-models` install route copies every file here to
   `/usr/share/bunny-os/agent-models/` read-only (mode 0444).
4. On boot, `local.llamacli` auto-discovers the model and becomes eligible;
   the resource-aware selection (see `companion/agents/resources.py`) binds
   the largest model whose resident footprint fits the machine's current
   memory budget — a small machine gets a smaller model, with no tier named.

## What is deliberately not here

- No auto-download. The image is offline by construction.
- No world-writable model. The adapter refuses one; the install route sets
  mode 0444.
- No fabricated or placeholder model bytes. A model that has not been
  exercised on real hardware is marked `NOT_RUN`, not declared working.