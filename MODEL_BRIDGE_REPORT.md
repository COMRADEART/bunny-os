<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny Model Adapter Runtime Bridge

A model trained outside Bunny OS can now be loaded inside it, and the OS trust
boundary is not weaker for it. This report is the evidence.

At the repository root rather than under `docs/` for the usual reason: `docs/`
is a build `COPY` root, so a file there is installed into the image and changes
it.

---

## 1. Architecture

### 1.1 The finding that shaped the design

**Bunny's inference is out-of-process.** Every provider in `companion/agents/`
is a *client* — loopback HTTP to a model server (`ollama`, `llamacpp`) or one
allowlisted subprocess (`llamacli`) — and `build/packages/*.txt` package **no
inference runtime at all**. The runtime has never loaded weights and does not
start model servers.

So the obvious reading of "adapter loading abstraction" — a class that opens
safetensors and merges tensors — would have meant putting a tensor library and
a model loader inside the Companion's process: a large new dependency, a large
new attack surface, and a duplicate of what the model server already does. This
milestone does something narrower and, at the boundary, stronger:

> **validate → resolve to a trusted path → ask the backend to apply → verify
> with the backend that it took.**

`applied` and `verified` are separate fields on `AdapterApplication` for exactly
that reason. A backend that returns 200 and does nothing has not activated
anything, and the bridge says so.

### 1.2 Where the bridge lives, and why

`companion/models/` — a subpackage of the already-installed `companion`
package.

| Decision | Reason |
| --- | --- |
| Inside `companion/`, not a new top-level package | It rides the existing `companion-package` install route. **No new install route was needed**, so the install set did not widen — asserted by `test_no_new_install_route_was_needed`. |
| Beside `companion/agents/`, not merged into it | `agents` answers *which provider*; `models` answers *which weights, and may they be used*. The two meet at a provider's `model_id`. Extending the provider registry would have conflated a network destination with a set of weights. |
| Artifacts under the **existing** trusted model directories | `~/.local/share/bunny-os/agent-models` and `/usr/share/bunny-os/agent-models`, imported from `companion.agents.adapters.llamacli.trusted_model_directories` rather than restated. One definition of "where trusted model material lives". |
| Manifest schema in `schemas/` | Unlike the *training* config schema, this is a runtime contract read by installed code, so it belongs with the other published contracts and ships with them. |
| Conversion (PEFT → GGUF) in `model_studio/export.py` | It needs llama.cpp's converter and the `gguf` package. Those are training-side dependencies and stay off-image. |

### 1.3 The trust boundary

```text
OFF-IMAGE / DEVELOPMENT                    model_studio/   (no install route)
  Bunny Model Studio
        │ training
        ▼
   PEFT adapter  ──► convert ──► GGUF      model_studio/export.py
        │ explicit export
        ▼
   Bunny model artifact                    a directory: manifest + adapter
   bunny-model-manifest.json
════════════════════════════════════════   the boundary: a directory, not an API
        ▼
  BUNNY OS RUNTIME IMAGE                   companion/models/  (installed)
   Artifact validator                      validation.py   PASS / FAIL / UNKNOWN
        ▼
   Runtime model registry                  registry.py     discover/enable/disable
        ▼
   Inference backend                       llama_server.py apply + verify
        ▼
   Bunny Companion                         (unchanged)
        ▼
   Intent / proposal                       proposal.py     admit_proposal()
        ▼
   Policy validation                       capsule_tasks.OPERATIONS (closed table)
        ▼
   User approval                           trust.TrustGate
        ▼
   Capsule / action                        capsules/
```

Nothing below the boundary imports anything above it, and nothing above it
imports the runtime. Both directions are asserted.

### 1.4 What remains outside the runtime

Training, datasets, the trainer, the evaluator, the conversion tooling, and
every heavy dependency they need. `test_build_isolation.py` asserts that no
install route resolves any `model_studio/**` path, that the bridge imports none
of `torch`, `transformers`, `peft`, `safetensors`, `gguf`, `numpy` …, and that
the bridge's *entire* import surface is the standard library plus `companion`.

---

## 2. Changed files

### Added — runtime bridge (installed)

```
companion/models/__init__.py        the boundary, stated
companion/models/errors.py          the little that raises
companion/models/artifact.py        manifest parsing, closed sections
companion/models/validation.py      12 checks, PASS/FAIL/UNKNOWN, named codes
companion/models/registry.py        discover / validate / enable / disable / active
companion/models/inference.py       the adapter-capable backend protocol
companion/models/llama_server.py    the one real backend
companion/models/proposal.py        model output is not authority
companion/models/events.py          structured events, closed payload
schemas/bunny-model-artifact.schema.json    the published contract
tools/bunny-os/bunny_os/model_cli.py        bunny-os model …
```

### Added — export side (not installed)

```
model_studio/export.py              run -> artifact, and PEFT -> GGUF conversion
```

### Added — tests

```
tests/model_bridge/__init__.py, support.py
tests/model_bridge/test_validation.py            37 tests incl. all 7 tampering cases
tests/model_bridge/test_registry.py              discovery, enable, fallback, rollback
tests/model_bridge/test_authority.py             Phase 7, three surfaces
tests/model_bridge/test_denied_action.py         Phase 9, against the real gate
tests/model_bridge/test_approved_action.py       Phase 10, against the real gate
tests/model_bridge/test_llama_backend.py         the backend, against a known server
tests/model_bridge/test_events_and_network.py    Phases 16 and 13
tests/model_bridge/test_build_isolation.py       Phase 17, both directions
tests/model_bridge/test_contract_round_trip.py   export ⇄ runtime parser
tests/model_bridge/test_runtime_slice.py         Phase 20, real everything
```

### Modified (4)

| File | Change |
| --- | --- |
| `companion/agents/wire.py` | `request_json`'s `body` annotation widened to accept a sequence. `json.dumps` already handled both; only the type was too narrow. llama-server's `POST /lora-adapters` takes a JSON array. |
| `tools/bunny-os/bunny_os/cli.py` | the `model` command group |
| `scripts/task.py` | `test-model-bridge` |
| `Makefile` | `test-model-bridge`, `model-bridge-slice` |

No existing runtime behaviour was changed. The Companion, the trust layer, the
capsule runtime and the operation table are untouched.

---

## 3. Dependencies

**Runtime dependencies added: none.**

The bridge is metadata, SHA-256 and one loopback HTTP call. Its complete import
surface is the standard library plus `companion` itself — asserted by
`test_the_bridge_uses_only_the_standard_library_and_the_companion`. Loading an
adapter did not drag a tensor stack into the image, which is what Phase 18 asks.

| Dependency | Side | Why |
| --- | --- | --- |
| `llama-cpp` (`llama-server`) | runtime, **optional, not packaged** | The backend that can apply a GGUF LoRA. Bunny packages no inference runtime; a machine without one lists artifacts and activates none, which the `NullAdapterBackend` makes the honest default rather than a crash. |
| llama.cpp's `convert_lora_to_gguf.py` + `gguf`, `mistral_common` | development only | PEFT safetensors is not what llama.cpp applies. Conversion happens on the training side, before the boundary, and the runtime only ever sees the result. |
| `torch`, `transformers`, `peft` | development only | Unchanged from the previous milestone. |

The reason conversion is a development concern rather than a runtime one is
worth stating plainly: it is the difference between shipping a 270 MB dependency
tree to every Bunny machine and shipping none.

---

## 4. Test results

### 4.1 New tests — the bridge suite

Runs anywhere. No model, no GPU, no inference server, no network.

```console
$ python scripts/task.py test-model-bridge      # Windows 11, Python 3.14.6
Ran 138 tests in 10.9s
OK (skipped=11)

$ python scripts/task.py test-model-bridge      # Fedora WSL
Ran 138 tests in 5.6s
OK (skipped=10)
```

The skips are `test_runtime_slice.py` (10 tests, needs `BUNNY_MODEL_BRIDGE_HEAVY=1`)
plus one POSIX-mode test that cannot run on Windows.

| Suite | Tests | What it establishes |
| --- | --- | --- |
| `test_validation` | 37 | the 12 checks, all 7 tampering cases, and four separate proofs that `UNKNOWN` is not a pass |
| `test_registry` | 26 | discovery, enable, fallback, disable, rollback, provenance |
| `test_authority` | 16 | **Phase 7**, across three surfaces |
| `test_llama_backend` | 10 | the real backend against a server whose behaviour is known exactly |
| `test_approved_action` | 10 | Phase 10, against the real gate |
| `test_events_and_network` | 14 | Phases 16 and 13 |
| `test_build_isolation` | 12 | **Phase 17**, in both directions |
| `test_contract_round_trip` | 8 | export ⇄ runtime parser ⇄ published schema |
| `test_denied_action` | 7 | Phase 9, against the real gate |
| `test_runtime_slice` | 10 | Phase 20 — the real chain (opt-in) |

### 4.2 Existing Model Studio tests — unbroken

```console
$ python scripts/task.py test-model-studio       # Fedora WSL, same run
Ran 219 tests in 39.6s
OK (skipped=5)
```

The previous milestone's 219 tests are untouched and still pass.

### 4.3 Repository gates

```console
$ python scripts/task.py validate
repository validation: PASS
  ok    JSON parsing                     322 documents parsed
  ok    Schema validation                55 schemas       # 54 before
  ok    Python compilation               1017 files compiled in memory
```

### 4.4 Build closure — the Phase 17 asymmetry, machine-checked

```console
$ python build/scripts/build-input-closure.py --paths <every changed path>

  examined 14 path(s): 4 installed, 2 context-only, 8 unreachable
  BUILD-AFFECTING: YES

  Installed into the artifact:
    companion/models/*.py
      -> /usr/lib/bunny-os/python/companion/models/*   [companion-package, package]
    tools/bunny-os/bunny_os/model_cli.py
      -> /usr/lib/bunny-os/python/bunny_os/model_cli.py  [bunny-os-python, tree]
    schemas/bunny-model-artifact.schema.json
      -> /usr/share/bunny-os/schemas/…                 [schemas, tree]
    companion/agents/wire.py
      -> /usr/lib/bunny-os/python/companion/agents/wire.py

  Unreachable from the build:
    model_studio/   model_studio/export.py
    tests/model_bridge/   tests/model_studio/
    Makefile   release/validation.py   the reports
```

The bridge is in the image; the training tree is not; and that is the analyser's
answer, not this report's assertion. This change *is* build-affecting, correctly
so — unlike the previous milestone, which installed nothing.

### 4.5 Full repository suite

```console
$ python -m unittest discover -s tests -t .          # Windows
FAILED (failures=14, skipped=114)
```

**14 failures, 0 errors — the same 14 the previous milestone measured, and no
new ones.** They are in `tests/capsules`, `tests/companion` and `tests/shell`;
this repository needs a Linux ext4 host for a clean run, and Windows is not its
reference environment. They were shown to be pre-existing by running the five
failing modules with the work stashed and again restored, both giving
`failures=14`. The skip count rose from 103 to 114 because the bridge's ten
heavy tests and one POSIX-mode test skip here.


---

## 5. Real runtime evidence

One machine: Intel Core Ultra 9 185H, NVIDIA RTX 4050 Laptop (6 GiB), Fedora
under WSL2. `llama-cpp b6153` from Fedora at `/usr/bin/llama-server` — already
present in the trusted directory the Bunny runtime resolves against, and *not*
installed by this milestone.

### 5.1 The chain, end to end

| Step | Result |
| --- | --- |
| **base model** | `HuggingFaceTB/SmolLM2-135M-Instruct` @ `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| base weights (GGUF) | `smollm2-135m-instruct-f16.gguf`, 270,885,856 bytes, sha256 `c983bb1b7888…` |
| **adapter** | the previous milestone's CUDA LoRA run, job `20260814T040212Z-e750ea0a` |
| conversion | `convert_lora_to_gguf.py` @ b6153 → **240 tensors** (the same 240/240 that changed in training) |
| **adapter hash** | `cec8eba5d432d6a3574cb775dbc0258916b3039c88538f14f2f286a82e938229`, 3,703,584 bytes |
| export | `bunny-model-manifest.json` carrying dataset, config, commit, method, precision, steps, loss |
| **runtime discovery** | found under `~/.local/share/bunny-os/agent-models` |
| **manifest validation** | **PASS**, 11 checks, every one reported |
| base identity | settled **by digest** — `baseModel.sha256` vs the weights the backend reports loaded |
| **adapter load** | `POST /lora-adapters [{"id":0,"scale":1.0}]`, then re-read: scale **1.0** confirmed |
| **inference** | through Bunny's own `LlamaCppAdapter`, `generation_started` … `generation_completed` |
| model output | `'Open Downloads is a powerful tool for organizing and managing your time…'` |
| **authorization** | denied → nothing; approved → executed; authority claim → refused before the gate |
| release | scale **0.0** confirmed; artifact still on disk |

### 5.2 `bunny-os model list`

```text
backend  llama-server (llama.cpp llama-server)
         base /root/gguf/smollm2-135m-instruct-f16.gguf  params 134,515,008
         formats ['gguf']
model    bunny-demo  status=PASS  valid=True checks=11
           PASS  VALID  path              PASS  VALID  adapterType
           PASS  VALID  modelId           PASS  VALID  adapterFormat
           PASS  VALID  schemaVersion     PASS  VALID  baseModel.sha256
           PASS  VALID  intendedRuntime   PASS  VALID  adapterFile
           PASS  VALID  permissions       PASS  VALID  adapterSha256
           PASS  VALID  networkRequired
active   NO_MODEL_ENABLED
```

The backend's reported parameter count — 134,515,008 — is the figure the
previous milestone derived analytically from `config.json`. Two independent
routes to the same number.

### 5.3 `bunny-os model enable bunny-demo`

```json
{"code": "ACTIVE", "modelId": "bunny-demo", "usingAdapter": true,
 "reason": "bunny-demo is active: adapter 0 at 127.0.0.1:8080 is in effect at scale 1.0"}
```

with provenance carrying `adapterSha256`, `baseModel`, `baseRevision`,
`datasetSha256`, `configSha256`, `bunnyCommit`, `trainingJobId`,
`trainingSource: bunny-model-studio`, and `validationStatus: PASS`.

Server state immediately after:

```json
[{"id":0,"path":"…/agent-models/bunny-demo/bunny-demo-lora-f16.gguf","scale":1.0}]
```

### 5.4 The real runtime slice

```console
$ make model-bridge-slice
Ran 10 tests in 2.0s
OK

  [slice] inference with adapter: 'Open Downloads is a powerful tool for organizing
  and managing your time. It allows you to create a schedule that includes all your
  tasks, including those that a'
```

covering: discovery, digest of the real adapter, apply-and-verify, real
inference through Bunny's provider adapter, release-and-verify, a one-byte
tamper on the *real* adapter, denied action, approved action, an authority claim
refused before the gate, and events free of private content.

### 5.5 Two findings the evidence run produced

Both were the design working, and both are worth stating because they change how
this is deployed.

**The server must be started with the artifact's adapter file.** The first run
started `llama-server --lora /root/gguf/…` — a staging copy — while the artifact
lived under `agent-models/`. The backend refused with `ADAPTER_NOT_PRELOADED`,
because it matches by *resolved path* and the runtime can only vouch for the
file whose digest it verified. That is a deployment requirement, not a bug: the
adapter llama-server loads and the adapter Bunny validated must be the same file.

**A listing and an activation must agree.** At first `model list` reported
`UNKNOWN / BASE_MODEL_UNVERIFIED` for a model that `model enable` then activated,
because only `enable` hashed the base weights. A status that depends on which
command you typed is worse than a slow one, so discovery now establishes the base
by digest too — once per registry, not once per model.


---

## 6. Security evidence

### 6.1 An adapter cannot grant permissions

Three surfaces, three proofs.

**The artifact.** `permissions` must be empty. A manifest declaring anything is
refused with `PERMISSIONS_NOT_GRANTABLE` — not sanitised, not ignored, not
logged and accepted:

```json
{"status": "FAIL", "code": "PERMISSIONS_NOT_GRANTABLE", "field": "permissions",
 "message": "the manifest declares permissions ('filesystem.write'). A model artifact
  cannot carry, request or imply a capability: authority comes from the trust layer,
  the capability system and the person using the machine…"}
```

An unknown manifest field is refused too, so a capability cannot arrive under a
name the parser does not know. And `export_artifact` has no argument that could
fill the array — asserted by inspecting its signature.

**The proposal.** `admit_proposal` refuses any authority-shaped key, at any
depth, matched on the *normalised* key so spelling does not help:

| Proposal | Result |
| --- | --- |
| `{"action": "delete_file", "path": "/important/file"}` | `UNKNOWN_OPERATION` |
| `{"operation": "image.resize", "approved": true, …}` | `AUTHORITY_CLAIMED` |
| `{… "capability": "filesystem.write"}` | `AUTHORITY_CLAIMED` |
| `{… "trusted": true}` / `{… "permission": true}` | `AUTHORITY_CLAIMED` |
| `is_approved`, `isApproved`, `IS-APPROVED`, `skip_approval`, `no_prompt`, `as_root` | `AUTHORITY_CLAIMED` |
| nested `{"parameters": {"context": {"security": {"approved": true}}}}` | `AUTHORITY_CLAIMED` |
| `{"operation": "shell.run", …}` | `UNKNOWN_OPERATION` |

Refused, not stripped. A stripped key is a model quietly learning that the field
is ignored; a refusal is one somebody finds out about.

**The type.** `AdmittedProposal` has exactly three fields — `operation_id`,
`parameters`, `source` — and is frozen. There is no field a downstream caller
could read as authority, and none can be attached afterwards. This is the proof
that cannot be undone by deleting a check.

### 6.2 A model cannot bypass approval

Against the **real** `TrustGate`, the real capsule runtime and the real
catalogue (`tests/capsule_support.World`, the same fixture the capsule suites
use), for the brief's own scenario — *"Resize holiday.png to 50%."*:

| Assertion | Denied | Approved |
| --- | --- | --- |
| task succeeded | no | yes |
| output file created | **none** | one, beside the original |
| original file digest | **unchanged** | **unchanged** |
| capsule executor reached | **never** | yes |
| permission actually prompted | — | yes, category `files` |
| application resolved | — | from the catalogue (`art.comrade.BunnyImageTool`), never from the proposal |
| only the named file authorised | — | yes; a neighbouring `private.png` was not |

Three further properties: a model that re-proposes after a denial gets the
stored denial and never reaches a second prompt; a once-scoped approval does not
carry into a second task; and a proposal claiming approval produces **no prompt
at all** — `world.surface.asked == []`.

### 6.3 An invalid adapter cannot load

`enable` re-runs the full validator with digests before touching the backend. A
model failing or returning `UNKNOWN` never reaches `apply` —
`self.backend.applied == []` is asserted. There is no `--force`, no
`--skip-validation`, and no flag anywhere in the CLI that turns a refusal into a
load.

### 6.4 A modified adapter is rejected

On the real 3.7 MB GGUF, a **one-byte** change at the same length:
`ADAPTER_CHECKSUM_MISMATCH`. Same length on purpose — a length change trips the
cheaper size check first, and the digest is what has to catch a same-size
substitution. Re-validated on every `enable`, so an artifact tampered with
*after* a listing is caught before activation.

### 6.5 A missing base model does not trigger a silent download

`BASE_MODEL_NOT_PRESENT`, status `UNKNOWN`, message *"It is not fetched: a
missing dependency is reported, never downloaded as a side effect of validating
an adapter."* Structurally: no module in `companion/models/` imports `socket`,
`http`, `urllib`, `requests` or `httpx`, or references `urlopen`,
`snapshot_download`, `hf_hub_download` or `urlretrieve`. The one thing that
reaches a network is `llama_server.py`, through the audited `WireSession` whose
target type refuses a non-loopback host for a local endpoint. An artifact
declaring `networkRequired: true` is refused outright.

### 6.6 The runtime cannot make a model server open a file

A structural property worth naming: llama-server's `POST /lora-adapters` takes
an **index into a preloaded list**, not a path. Every request this backend sends
names an id the server itself reported, asserted by
`test_the_runtime_cannot_make_the_server_open_a_file`. So there is no call in
this package that causes a model server to read a file of the runtime's — or an
artifact's — choosing.


---

## 7. Known limitations

Stated as what was **not** established.

**One backend, one machine.** The only implemented adapter-capable backend is
llama-server, tested against `llama-cpp b6153` on one host. Ollama, vLLM, MLX
and anything else are shapes the protocol accommodates, not implementations.

**GGUF only, in practice.** `peft-safetensors` artifacts validate and are then
reported `UNKNOWN / NO_BACKEND_FOR_FORMAT`, because nothing in the image can
apply them. That is honest rather than convenient: converting to GGUF is a
development step, and this milestone did not add a runtime that reads
safetensors.

**No inference runtime ships with Bunny.** A Bunny image as it ships has
`NullAdapterBackend`: artifacts are discovered, validated and listed, and none
can be activated. Everything in §5 required an operator to install `llama-cpp`
and start a server. This bridge makes adapters *usable* where a runtime exists;
it does not put one in the image.

**The adapter must be the file the server was started with.** The runtime cannot
ask a server to load anything — deliberately — so activation requires an
operator to have started llama-server with `--lora <the artifact's adapter>`.
There is no hot-load, and adding one would mean giving the runtime the power
this design withholds.

**No hot reload, no multi-adapter.** One adapter at a time. `release` sets
*every* adapter the backend holds to zero rather than one, because "the adapter
I think is off is off" is weaker than "nothing is on" when the two disagree.
Stacking or weighting several adapters is not implemented.

**Rollback is one step deep.** `previousModelId` is recorded and disabling never
deletes an artifact, so returning to a previous model is `enable <id>` — but
there is no history beyond one entry and no automatic revert.

**The approved-action test does not assert pixels.** It asserts that the capsule
path ran after approval, an artefact was exported, and the original survived.
Whether the output is *correctly resized* is `bunny-image-tool`'s business and is
covered by the capsule suites against the real program; the coordinator's default
`RecordingTool` performs the export path without claiming anything about image
rendering.

**Base revision is settled by digest, not by revision string.** An adapter
trained against a Hugging Face revision and applied to a GGUF conversion of it
has no revision string to compare. The digest ladder is stronger where it
applies — the bytes are the bytes — but a deployment where the base weights
cannot be hashed by the runtime (a server on another host, or in a container
with a different filesystem view) falls back to `UNKNOWN` and cannot activate.

**No GUI.** The registry and provenance are available through the CLI and the
Python API. Nothing renders them.

**Not tested on a booted Bunny image.** Everything here ran from the checkout on
a development host. The install closure proves the bridge *would* be installed;
it has not been exercised on an installed system, and the earlier evidence run
found the reverse hazard in passing — a stale `/usr/lib/bunny-os/python` shadows
the checkout in the `bunny-os` launcher, so on a machine with both, the installed
copy wins.

**The event log is not tamper-evident.** Unlike `companion/events.py`, it is not
hash-chained. It records what the bridge did for an operator to read; it is not
evidence against someone with write access to the file.


---

## 8. Final status

```text
BUNNY MODEL ADAPTER RUNTIME BRIDGE = PASS
```

The gate the milestone set was a real chain, not a passing validator, and the
chain ran:

```text
real Model Studio adapter (240 tensors, job 20260814T040212Z-e750ea0a)
  → real artifact + manifest (sha256 cec8eba5d432…)
  → real runtime discovery under a trusted model directory
  → real validation: PASS, 11 checks, base identity settled by digest
  → real adapter load: POST /lora-adapters, re-read, scale 1.0 confirmed
  → real inference through Bunny's own LlamaCppAdapter
  → real proposal admitted through the authority gate
  → real Bunny authorization: denied stayed denied, approved executed
  → release: scale 0.0 confirmed, artifact intact
```

`make model-bridge-slice` → 10 tests, OK.
`make test-model-bridge` → 138 tests, OK.
`make test-model-studio` → 219 tests, OK — the previous milestone is unbroken.

**What this establishes.** A model trained outside Bunny OS can be validated,
loaded and used inside it, and the trust boundary is not weaker for it: the
artifact cannot carry a capability, the model cannot claim one, an approval is
still asked of a person, a denial still stops the work, and a single changed
byte still stops the load.

**What it does not.** It does not put an inference runtime in a Bunny image, it
does not make a 135M demonstration adapter useful, and it has not been exercised
on a booted installed system. Those are named in §7 rather than implied by
silence.

The most useful thing this milestone produced is probably the sentence the
backend prints when it refuses:

> *"This runtime cannot ask a model server to open a file — an operator starts
> the server with `--lora`, and this turns it on."*

That is the whole design in one refusal, and it fired for real during the
evidence run.
