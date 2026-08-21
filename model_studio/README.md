<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny Model Studio

An optional, developer-side subsystem for creating small personal adapters for
Bunny OS. It is **not part of Bunny OS**. It has no install route, ships in no
image, and runs on no Bunny machine.

This document is here rather than in `docs/` on purpose: `docs/` is a build
`COPY` root, so a file there is installed to `/usr/share/doc/bunny-os` and
changes the image. A document about a subsystem that deliberately does not ship
should not itself ship.

## The two paths

```text
BUNNY DEVELOPMENT / MODEL STUDIO          <- this package
            |
            v
     Training backend
    LoRA / QLoRA / SFT
            |
            v
        Adapter
   adapter_config.json
   adapter_model.safetensors
   provenance.json
            |
  ==========|===============================  the only interface: a directory
            |
            v
       BUNNY OS RUNTIME
            |
            v
      Local inference                     <- companion/agents/adapters/*
   llama.cpp / Ollama / future
            |
            v
      Bunny Companion
            |
            v
 Actions -> Approvals -> Capsules
```

The separation is a **build property**, not a coding convention.
`build/scripts/install_routes.py` is the single declaration of what reaches the
image; `companion`, `capsules`, `trust`, `catalog` and `capability` each have a
route there, and this package has none. `tests/model_studio/test_isolation.py`
asserts it in both directions — no route resolves a path here, and nothing here
imports the runtime — so training code cannot join the privileged execution path
without a reviewed edit to the file whose whole purpose is that nobody adds one
by accident.

## Layout

| Path | What it is |
| --- | --- |
| `backend/base.py` | The `TrainingBackend` protocol. Everything above it talks to this and never to torch. |
| `backend/transformers_lora.py` | The one working backend: Transformers + PEFT, LoRA and QLoRA. |
| `config.py` | The declarative run, validated. Strict: unknown keys and contradictions are refusals. |
| `schemas/` | The JSON Schema for that document. Not in `schemas/`, which is an install route. |
| `datasets/chat.py` | The JSONL chat corpus and its validation. |
| `datasets/policy.py` | The lint that refuses a corpus teaching Bunny to bypass its own permissions. |
| `hardware/probe.py` | What this machine is, with `UNKNOWN` as a first-class answer. |
| `hardware/precision.py` | The single canonical precision decision. |
| `memory.py` | Derived memory requirements, or `None`. No lookup tables, no fudge factors. |
| `models.py` | Base-model resolution and the parameter count the estimate rests on. |
| `network.py` | Offline by default. One approved operation. No upload path at all. |
| `jobs/` | The state machine, and a store that survives a crash without lying. |
| `provenance.py` | Base + dataset + recipe + software versions, per run. |
| `artifacts.py` | The output directory and its manifest. |
| `evaluation` (in the backend) | Reload, tensor delta, held-out loss, side-by-side samples. |
| `view.py` | The data a future Model Studio window renders. No widgets. |
| `cli.py`, `bin/bunny-model` | The developer surface. |

## Using it

```bash
python model_studio/bin/bunny-model hardware
python model_studio/bin/bunny-model backends
python model_studio/bin/bunny-model validate  model_studio/examples/bunny-demo.yaml
python model_studio/bin/bunny-model preflight model_studio/examples/bunny-demo.yaml
python model_studio/bin/bunny-model train     model_studio/examples/bunny-demo.yaml
python model_studio/bin/bunny-model jobs
python model_studio/bin/bunny-model inspect <job-id>
python model_studio/bin/bunny-model verify  <output-directory>
```

Exit codes: `0` succeeded or READY, `1` the input was wrong, `2` the machine
cannot do it. They are distinct because "fix the file" and "fix the machine" are
different actions.

Requirements: `torch`, `transformers`, `peft`, `safetensors` for LoRA; also
`bitsandbytes` and a CUDA device for QLoRA. `bunny-model hardware` reports which
of those this machine has and what follows from it. None of them is a
dependency of Bunny OS, and none is installed by any Bunny image.

## The rules the shape enforces

**Nothing is downloaded implicitly.** The default policy is offline and sets
`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` and the telemetry variables around
everything the backend does. A base model that is not on the machine blocks
preflight with an instruction; `--allow-model-download` approves the fetch for
one invocation. The telemetry variables are never lifted.

**There is no upload.** Not a disabled one — there is no code in this package
that publishes a model, and a test walks the syntax tree of every module to keep
it that way. Publishing an adapter trained on a personal corpus is a separate,
deliberate act with a separate tool.

**A corpus may not teach permission bypass.** `datasets/policy.py` rejects a
dataset whose assistant turns propose unrestricted operating-system commands
without asking, or frame the permission system as an obstacle. It judges each
match inside its own sentence, so an assistant *refusing* to bypass — the
behaviour the corpus exists to teach — passes. It is a lint over surface text,
not a proof: the strong guarantee stays in `trust/` and `capsules/`, which do
not consult the model about whether a permission is required.

**Nothing claims a number it did not obtain.** Hardware capability is
tri-state; a machine that will not report its VRAM yields `UNKNOWN`, and
`UNKNOWN` blocks a run rather than passing it. Memory requirements are derived
from the model's own `config.json` by arithmetic that is checked against a
published parameter count, and every estimate carries its formula and its
exclusions.

**A run that stopped is not a run that finished.** `completed` has exactly one
predecessor in the state machine, `evaluating`, and evaluation reloads the
adapter from disk and compares its tensors against a snapshot taken before the
first optimizer step. An adapter that did not move ends the job in `failed`.
A record found in an active state whose process or boot is gone is recovered to
`failed` on the next read.

## Adding a backend

Implement `backend/base.py`'s protocol and add one entry to `REGISTRY` in
`backend/__init__.py`. Nothing above the backend package names a backend except
by identifier, so `SoupBackend`, `UnslothBackend`, `MLXBackend` or a remote one
is an addition, not a redesign. `detect()` must report absence as data — a
backend that raises because its runtime is missing breaks the one property the
CLI and the future window both depend on.

## Tests

```bash
python scripts/task.py test-model-studio      # no torch, no GPU, no network
make model-studio-slice                       # the real training run, opt-in
```

The slice needs `BUNNY_MODEL_STUDIO_HEAVY=1` and either a local base model in
`BUNNY_MODEL_STUDIO_BASE` or `BUNNY_MODEL_STUDIO_ALLOW_DOWNLOAD=1`. Nothing
downloads a model without one of those, on any target.
