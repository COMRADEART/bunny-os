<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny Model Studio — foundation milestone

The first foundation for an optional, developer-side model-training subsystem.
It is not part of Bunny OS, does not ship in any image, and cannot become part of
the Companion's privileged execution path without a reviewed edit to the file
whose whole purpose is that nobody makes one by accident.

This report is at the repository root rather than under `docs/` because `docs/`
is a build `COPY` root: a file there is installed to `/usr/share/doc/bunny-os`
and changes the image. The same reasoning put the subsystem's own documentation
at `model_studio/README.md`.

---

## 1. Architecture

### 1.1 The architectural rule, and where it is enforced

```text
BUNNY DEVELOPMENT / MODEL STUDIO         model_studio/  (no install route)
            |
            v
     Training backend                    backend/transformers_lora.py
    LoRA / QLoRA / SFT
            |
            v
        Adapter                          adapter_config.json
   adapter_model.safetensors              + provenance.json + MANIFEST.json
            |
  ==========|=============================  the only interface: a directory
            |
            v
       BUNNY OS RUNTIME
            |
            v
      Local inference                    companion/agents/adapters/*  (untouched)
   llama.cpp / Ollama / future
            |
            v
      Bunny Companion                    companion/  (untouched)
            |
            v
 Actions -> Approvals -> Capsules        trust/, capsules/  (untouched)
```

The finding that shaped everything else: **the isolation boundary in this
repository is not a directory convention, it is
`build/scripts/install_routes.py`** — the single declaration of what reaches the
image, read by both the installer and the build-closure analyser. Every runtime
package has a route there. `model_studio` has none, so:

* it cannot be installed, and the repository's own analyser says so rather than
  this report asserting it;
* `tests/model_studio/test_isolation.py` asserts it in both directions, against
  `install_routes.py` itself rather than against a list maintained in the test.

Measured, on this change set:

```console
$ python build/scripts/build-input-closure.py --paths $(git status --porcelain | awk '{print $2}')

  examined 10 path(s): 0 installed, 1 context-only, 9 unreachable
  BUILD-AFFECTING: no installed path found

  In the build context, not installed by a declared route:
    scripts/task.py
  Unreachable from the build:
    .gitattributes  Makefile  release/validation.py  MODEL_STUDIO_REPORT.md
    model_studio/   tests/model_studio/

  Every commit changes the OCI configuration digest through the revision label
  and /usr/lib/bunny-os/release.json. An unchanged layer digest is not an
  unchanged image.
```

So: **no installed path's content changes.** The image is not byte-identical to
its parent's — no commit's is, because the revision label and `release.json`
embed the commit — and that last line is the analyser's own caveat, kept here
rather than paraphrased away.

Three further placement decisions follow from the same fact:

| Decision | Reason |
| --- | --- |
| Schema in `model_studio/schemas/`, not `schemas/` | `schemas/` is an install route; a training schema there would ship to every Bunny machine. `release/validation.py` was extended to walk the new directory so the schema is still validated by `make validate`. |
| CLI at `model_studio/bin/bunny-model`, not `bunny-os model` | `tools/bunny-os/bunny_os` installs to `/usr/lib/bunny-os/python`. A subcommand there would either ship training code or ship a command that raises `ImportError` on every installed system. `oem/bin/bunny-oem` is the existing precedent for a repo-side developer tool. |
| Documentation in `model_studio/README.md` | `docs/` is a build `COPY` root. |

### 1.2 New components and responsibilities

| Component | Responsibility |
| --- | --- |
| `backend/base.py` | The `TrainingBackend` protocol — `detect`, `preflight`, `prepare`, `train`, `cancel`, `evaluate` — plus `BackendStatus`, `PreflightReport`, `TrainingPlan`, `TrainingResult`, `EvaluationResult`, `ProgressEvent`, `CancellationSignal`. Nothing above this layer imports torch. |
| `backend/transformers_lora.py` | The one working backend. Transformers + PEFT, LoRA and QLoRA, with an explicit training loop rather than `Trainer`. |
| `backend/__init__.py` | The registry: identifier → factory. Adding a backend is one entry plus one module. |
| `config.py` + `schemas/` | The declarative run. Closed sections, contradiction checks, two digests (document and resolved run), and a strict YAML subset parser for hosts without PyYAML. |
| `datasets/chat.py` | JSONL chat corpus, validated as a file rather than line by line, with a deterministic seeded split. |
| `datasets/policy.py` | The permission-model lint. |
| `hardware/probe.py` | CPU, RAM, disk, accelerator, VRAM, compute capability, bf16/fp16 as a tri-state, plus a second independent view of GPUs seen without torch. |
| `hardware/precision.py` | The single canonical precision decision. |
| `memory.py` | Derived memory requirements with named components, the formula, and stated exclusions — or `None`. |
| `models.py` | Base-model resolution (local / cached / absent) and the analytic parameter count the estimate rests on. |
| `network.py` | `NetworkPolicy`, the offline environment, and `refuse_upload`. |
| `jobs/state.py` | The ten-state machine. |
| `jobs/store.py` | Persisted records, atomic writes, and crash recovery from pid and boot identity. |
| `provenance.py` | Base + dataset + recipe + software versions per run. |
| `artifacts.py` | The run directory, its files and its `MANIFEST.json`. |
| `studio.py` | The facade. Owns every state transition; decides what "finished" means. |
| `view.py` | The data a future Model Studio window renders. |
| `cli.py`, `bin/bunny-model` | The developer surface. |

### 1.3 Interfaces

```python
class TrainingBackend(Protocol):
    backend_id: str
    def detect(self) -> BackendStatus: ...
    def preflight(self, config: TrainingConfig) -> PreflightReport: ...
    def prepare(self, config: TrainingConfig) -> TrainingPlan: ...
    def train(self, job, *, progress=None, cancellation=None) -> TrainingResult: ...
    def cancel(self, job_id: str) -> None: ...
    def evaluate(self, result: TrainingResult) -> EvaluationResult: ...
```

The contract borrows its central rule from `companion/agents/adapter.py`:
**absence is a result, never an exception.** `detect()` on a machine with no PEFT
returns a status saying so and naming what is missing; `preflight()` on a card
too small returns `BLOCKED` with the arithmetic. Neither raises.

Three verdicts, and the third is the point: `READY` (every requirement checked
and met), `BLOCKED` (a requirement checked and not met), `UNKNOWN` (a requirement
could *not* be checked — which is not a pass).

### 1.4 Dependencies

Nothing in this subsystem is a dependency of Bunny OS, and no Bunny image
installs any of it.

| Dependency | Needed for | Status here |
| --- | --- | --- |
| `torch` | everything | already vendored in Bunny for the Pocket TTS runtime (CPU 2.9.1); a CUDA build was installed separately for the GPU evidence |
| `transformers`, `peft`, `safetensors` | LoRA | installed in the evidence environments only |
| `bitsandbytes` + a CUDA device | QLoRA | installed in the CUDA evidence environment only |
| `huggingface_hub` | approved base-model download | arrives with `transformers` |
| PyYAML | YAML configuration | **optional** — a strict subset parser is used when it is absent, and the two are checked against each other |
| `jsonschema` | schema self-test | optional; the test skips |

---

## 2. Changed files

### Modified (4)

| File | Change |
| --- | --- |
| `scripts/task.py` | added the `test-model-studio` command |
| `Makefile` | added `test-model-studio`, `model-studio-slice`, `model-studio-hardware`, `model-studio-demo` |
| `release/validation.py` | schema validator now also walks `model_studio/schemas` |
| `.gitattributes` | `model_studio/bin/** -text`, so the shebang cannot acquire a carriage return on a Windows checkout |

### Added — package (29 files, 6,551 lines of Python plus data)

```
model_studio/__init__.py                 errors.py             config.py
model_studio/memory.py                   models.py             network.py
model_studio/provenance.py               artifacts.py          studio.py
model_studio/view.py                     cli.py                README.md
model_studio/bin/bunny-model
model_studio/backend/{__init__,base,transformers_lora}.py
model_studio/datasets/{__init__,chat,policy}.py
model_studio/hardware/{__init__,probe,precision}.py
model_studio/jobs/{__init__,state,store,job}.py
model_studio/schemas/bunny-training-config.schema.json
model_studio/examples/{bunny-demo.yaml,bunny-companion-demo.jsonl}
```

### Added — tests (17 files, 3,028 lines)

```
tests/model_studio/{__init__,support}.py
tests/model_studio/test_{config,datasets,encoding,memory,precision}.py
tests/model_studio/test_{jobs,artifacts,provenance,network}.py
tests/model_studio/test_{backend,studio,view,cli,isolation}.py
tests/model_studio/test_{adapter_delta,training_slice}.py
```

---

## 3. Test results

### 3.1 The subsystem's own suite

Runs anywhere. No torch, no GPU, no network, no model download.

```console
$ python scripts/task.py test-model-studio          # Windows 11, Python 3.14.6
Ran 219 tests in 2.9s
OK (skipped=5)

$ python scripts/task.py test-model-studio          # Fedora WSL, Python 3.14.3, torch present
Ran 219 tests in 38.7s
OK (skipped=7)
```

The five skips on both hosts are `test_training_slice.py`, which needs
`BUNNY_MODEL_STUDIO_HEAVY=1` — so `make test` never downloads a model or takes a
GPU. The two extra skips on the Linux host are the schema self-checks, guarded
on `jsonschema`, which is not in the training virtualenvs.

The 38.7 s there is almost entirely one `git status --porcelain` hitting its
30-second ceiling: that host runs the checkout over a 9p mount from Windows, and
the provenance test asks for the tree state once. On a native checkout the same
suite is the 2.9 s above. It is one call rather than twenty because the result
is cached per process — see `provenance._commit_of`, which exists for exactly
this reason.

| Suite | Tests | What it establishes |
| --- | --- | --- |
| `test_config` | 27 | every refusal: unknown keys, contradictions, remote code, URL datasets; the YAML subset parser agreeing with PyYAML |
| `test_datasets` | 24 | corpus rules; the lint catching bypasses **and** accepting refusals worded the same way |
| `test_precision` | 17 | Ampere+/Turing/Pascal/CPU/no-CUDA-runtime/Metal, and `UNKNOWN` never resolving upward |
| `test_memory` | 18 | parameter count against a published figure; estimate composition; batch resolution |
| `test_jobs` | 20 | the machine, and that an interrupted run never reads as completed |
| `test_studio` | 13 | every run outcome: completed, blocked, failed, cancelled, and learned-nothing |
| `test_encoding` | 7 | which tokens the loss is taken over, and the whole-corpus fallback |
| `test_adapter_delta` | 8 | the evidence-gate comparison, with a fake tensor that refuses `bool()` like torch |
| `test_isolation` | 10 | no install route, no runtime coupling, no upload path, licence headers |
| `test_backend` | 18 | preflight verdicts: ready, blocked, and the unknowns that are not a pass |
| `test_cli` | 17 | exit codes 0/1/2, JSON payloads, and the absence of a publish command |
| `test_network` | 13 | the offline default, the environment it sets, and model resolution |
| `test_artifacts` | 8 | the manifest, overwrite refusal, and digest verification |
| `test_provenance` | 8 | every required field, and what the record must not carry |
| `test_view` | 6 | the GUI contract, including a screen built from a blocked report |
| `test_training_slice` | 5 | the real run — skipped unless `BUNNY_MODEL_STUDIO_HEAVY=1` |

### 3.2 Repository gates

```console
$ python scripts/task.py validate
repository validation: PASS
  ok    JSON parsing                     321 documents parsed
  ok    Schema validation                54 schemas      # 53 before; the new one is covered
  ok    Python compilation               994 files compiled in memory
  ok    Licence headers                  885 declarations, all within GPL-3.0-or-later/Apache-2.0
  ...
```

### 3.3 The full repository suite

```console
$ python -m unittest discover -s tests -t .           # Windows, ~5,400 tests
FAILED (failures=14, skipped=103)
```

Those 14 failures are **not** from this change set, and that was measured rather
than assumed. Running the five failing modules with the work stashed and again
with it restored gives the same result both times:

```console
$ git stash push -u && python -m unittest <the five failing modules>
FAILED (failures=14, skipped=1)
$ git stash pop   && python -m unittest <the five failing modules>
FAILED (failures=14, skipped=1)
```

They are in `tests/capsules`, `tests/companion` and `tests/shell`, and this
repository is known to need a Linux ext4 host for a clean run — Windows is not
its reference environment.

An earlier full run also reported 7 *errors*, all in `tests/capsules/
test_launcher_section.py`, which shells out to `bash` to prove a quoting claim
against a real shell. They did not reproduce on the run above, and that module
passes on its own; they were transient, and coincided with the machine being
fully occupied by a training run in WSL. Recorded here rather than dropped,
because "it went away" is a weaker statement than "it was measured twice", and
this is the weaker one.

### 3.4 The heavy slice

```console
$ BUNNY_MODEL_STUDIO_HEAVY=1 python -m unittest discover -s tests/model_studio \
      -t . -p test_training_slice.py            # Fedora WSL, RTX 4050
Ran 5 tests in 89.0s
OK
```

Real model, real optimizer, real weights: the whole path end to end, the PEFT
artifact shape, the manifest and provenance, the estimate against the measured
peak, and a cancelled run leaving no adapter.

---

## 4. Training evidence

Five things were run end to end on one machine — an Intel Core Ultra 9 185H and
an NVIDIA GeForce RTX 4050 Laptop GPU (Ada, compute 8.9, 6 GiB), Fedora under
WSL2 on Windows 11. Two of them are refusals, because a subsystem whose first
promise is "nothing happens implicitly" has to be shown refusing.

### 4.1 The two refusals

| Run | Command | Result |
| --- | --- | --- |
| A | `bunny-model train <config>` with an empty model cache | `BLOCKED`, **exit 2** — *"the base model is not on this machine … Approve a download with `--allow-model-download`, or point model.base at a local directory."* Nothing was fetched and no artifact directory was created. |
| B | `bunny-model validate <config>` on a two-line corpus teaching `rm -rf ~/Downloads/*` and "I'll bypass the approval prompt" | `INVALID`, **exit 1** — both examples named, with the rule and the matched text |

### 4.2 The three training runs

Same corpus, same seed, same 12 optimizer steps; the differences are the device
and the numeric type.

| | C — CPU LoRA | D — CUDA LoRA | E — CUDA QLoRA |
| --- | --- | --- | --- |
| base model | SmolLM2-135M-Instruct | ← | ← |
| base revision (resolved) | `12fd25f77366fa6b3b4b768ec3050bf629380bac` | ← | ← |
| dataset | 35 conversations, 28 train / 7 held out | ← | ← |
| method | LoRA | LoRA | **QLoRA, nf4** |
| device | cpu | cuda | cuda |
| precision | **fp32** | **bf16** | **bf16** (nf4 weights) |
| batch size | 8 (auto) | 8 (auto) | 8 (auto) |
| steps | 12 over 3 epochs | ← | ← |
| initial → final loss | 4.1726 → 3.4592 | 4.1764 → 3.4655 | 4.2654 → 3.6003 |
| duration | **504.0 s** | **5.2 s** | **5.8 s** |
| estimated memory | 1.458 GiB | 1.108 GiB | 0.927 GiB |
| **measured peak VRAM** | n/a (CPU) | **0.706 GiB** | **0.692 GiB** |
| measured peak host RSS | 1.838 GiB | 1.768 GiB | 1.798 GiB |
| trainable / total params | 921,600 / 135,436,608 | ← | 921,600 / 82,352,448 † |
| adapter size | 3,717,656 bytes | ← | ← |
| **adapter tensors changed** | **240 / 240** | **240 / 240** | **240 / 240** |
| max abs delta | 3.530e-03 | 3.532e-03 | 3.531e-03 |
| adapter reload | **True** | **True** | **True** |
| held-out loss, base → adapter | 2.9752 → **2.7642** | 2.9802 → **2.7686** | 3.1589 → **2.8713** |
| job state | `completed` | `completed` | `completed` |
| exit code | 0 | 0 | 0 |
| `bunny_commit` | `dbe5f371…-unverified` | ← | ← |
| `gpu` recorded | *RTX 4050 (present, unusable by this torch)* | RTX 4050 | RTX 4050 |
| `allowModelDownload` | **true** (approved) | false | false |
| `allowUpload` | **false** | **false** | **false** |

† Under 4-bit quantization `total_parameters` counts packed storage elements,
not logical parameters. Reported as measured rather than corrected, because the
number is what `named_parameters()` says and inventing 135M there would be the
kind of quiet fix this subsystem is built to avoid.

Output path (each run): `<output.directory>/` containing `adapter/`
(`adapter_config.json`, `adapter_model.safetensors`, tokenizer),
`config.snapshot.json`, `preflight.json`, `training-metadata.json`,
`training-log.jsonl`, `evaluation.json`, `provenance.json`, `MANIFEST.json`.

### 4.3 What the numbers say

**The parameter arithmetic is exact, not approximate.** The estimator derives
SmolLM2-135M's size from its own `config.json` and a LoRA plan's size from the
rank and the layer shapes, with no lookup table anywhere:

```text
derived   base 134,515,008  +  LoRA r=8 over q,k,v,o  921,600  =  135,436,608
measured  torch reported "921600 trainable of 135436608 parameters"
```

Both halves match to the unit. That matters because every memory figure is built
on the parameter count: an estimator wrong by a factor there would be wrong by a
factor everywhere, and would agree with every test written from the same
arithmetic. This is the check against something that was not.

**The estimate is in the right postcode.** Derived 1.108 GiB, measured 0.706 GiB
on the CUDA LoRA run — the estimate is 1.6× the measurement, on the safe side,
which is what an estimate that excludes fragmentation and the CUDA context
should be. It is a planning tool with one calibration point, not a guarantee.

**Quantization does what it claims, measured.** Base weights fall from 0.501 GiB
(fp32) to 0.251 (bf16) to 0.063 (nf4), and the nf4 run additionally carries
0.008 GiB of quantization constants — counted separately rather than folded into
a bytes-per-parameter figure, so it can be checked.

**CPU and GPU agree, and reruns agree — but not bit-for-bit.** 4.1726 → 3.4592
on the CPU against 4.1764 → 3.4655 on the GPU, from the same seed: the same run
in a different numeric type, not two different runs. Re-running the whole round
reproduced the CPU loss trajectory to four decimal places at every step.

The adapter *weights* were not identical between those two rounds, though —
`adapter_sha256` differs. That is expected and is stated rather than glossed:
torch's CPU and CUDA reductions are not bit-deterministic across runs without
explicitly requesting deterministic algorithms, which this build does not. So
the honest claim is **reproducible training dynamics, not reproducible
weights**. Bit-identical adapters would need a determinism mode and a fixed
thread count, and are not something this milestone measured or claims.

**The adapter changes behaviour.** On a held-out prompt the base model and the
adapter produce different text, and the held-out loss differs. Neither output is
good — 28 conversations and 12 steps cannot make a useful assistant, and this
report does not claim one:

```text
prompt : "Open Downloads"          (held out; the model never saw it in training)
base   : "I'm ready to assist you with your requests. Please feel free to ask me
          anything related to your computer or internet use."
adapter: "I'm sorry for the inconvenience, but as a chatbot, I don't have the
          ability to open downloads. …"
```

**The GUI contract renders.** `bunny-model view` builds the whole screen from a
preflight report, with no widget code anywhere. On the GPU host, against the
same configuration run D used:

```text
Bunny Model Studio

Base Model
  HuggingFaceTB/SmolLM2-135M-Instruct
  already in the local hub cache at /root/hf-cache/hub
Dataset
  bunny-companion-demo.jsonl
  35 conversations
Training
  * LoRA
  o QLoRA
CUDA
  NVIDIA GeForce RTX 4050 Laptop GPU
  ##........  1.1 GB / 6.0 GB estimated

  [ Start Training ]  enabled
```

The same call on the Windows development host, which has no torch and no cached
model, produces the same screen with QLoRA and LoRA both marked unavailable with
the reason, the memory bar as `??????????  UNKNOWN / 31.6 GB estimated`, and the
button disabled with both blocking reasons listed. A blocked screen is a
complete screen; that is the whole point of the contract.

And the job list:

```text
JOB                       STATE         UPDATED               RUN
20260814T034726Z-b5ee7629 blocked       2026-08-14T03:47:31Z  cpu-lora
20260814T034732Z-e3ce8283 completed     2026-08-14T04:02:03Z  cpu-lora
20260814T040212Z-e750ea0a completed     2026-08-14T04:03:00Z  cuda-lora
20260814T040302Z-f0c4d930 completed     2026-08-14T04:03:53Z  cuda-qlora
```

**The network gate held.** Run C carried `--allow-model-download` and its
provenance records `allowModelDownload: true`. Runs D and E were given no such
approval, found the model in the cache, and recorded `allowModelDownload:
false`. Every record says `allowUpload: false`, because there is no code that
could set it otherwise.

---

## 5. What the evidence gate asked for

The milestone's gate is a path, not a green tick. Each step below is the
artifact or measurement that establishes it, and the last two are the ones a
zero exit status cannot supply.

| Step | Established by |
| --- | --- |
| dataset | `bunny-companion-demo.jsonl`, 35 conversations, loaded and linted; a deliberately bad corpus is refused with exit 1 |
| validated config | `bunny-model validate`, strict sections, two digests |
| hardware preflight | `preflight.json` in every run directory, with the machine as measured |
| training plan | `training-metadata.json`, every decision named before the first forward pass |
| LoRA training | real optimizer steps with a recorded loss history |
| adapter saved | `adapter_config.json` + `adapter_model.safetensors`, genuine PEFT format |
| adapter reload | `evaluation.json`: `reloadOk`, from a fresh base model on disk |
| **tensor delta** | `adapterTensorsChanged` against a snapshot taken **before** the first step |
| inference comparison | held-out loss with and without the adapter, plus side-by-side generations on held-out prompts |
| provenance record | `provenance.json`, binding base + dataset + recipe + versions |
| completed job | `completed`, reachable only from `evaluating` |

Every row was executed three times — once per training run — and each produced
the artifact named. The middle two rows are the ones a zero exit status cannot
supply, and they are the reason the subsystem exists in this shape: the tensor
comparison is made against a snapshot taken **before** the first optimizer step,
so "changed from initialization" is a measurement and not an inference from a
value that happens to be non-zero.

That check earned its place during this milestone. Three complete end-to-end
runs trained correctly, saved a correct PEFT adapter, and then crashed *in the
evaluation* — `dict.get(a) or dict.get(b)` asks a tensor whether it is truthy,
and torch refuses to answer for more than one element. Without an evaluation
step those three runs would have exited zero with a good adapter and an
unverified claim; with it they failed loudly, at the point of the defect. The
fix carries a regression test whose fake tensor raises from `__bool__` exactly
as torch does, and the negative control was run: reintroducing the defect makes
that test fail with 2 errors, restoring the fix makes it pass.

---

## 6. Known limitations

Stated as what was **not** established, rather than as what might go wrong.

**Hardware.** Every measured figure in this report comes from one machine: an
NVIDIA GeForce RTX 4050 Laptop GPU (Ada, compute 8.9, 6 GiB) and an Intel Core
Ultra 9 185H, under WSL2 on Windows 11. No claim is made about any other GPU,
any other driver, or bare-metal Linux. QLoRA in particular was measured with
bitsandbytes 0.50.1 on that one card.

**The precision rule for Turing, Pascal and Apple Metal is tested against mocks,
not silicon.** `tests/model_studio/test_precision.py` describes those machines
precisely and asserts what the rule does with them; it does not establish that
the rule is right about hardware nobody here owns. Only the Ampere-and-later
path (`bf16`) and the CPU path (`fp32`) were exercised on real devices.

**The memory estimate is a planning tool that has been checked once.** Its
arithmetic is derived and its formula is recorded, but it is calibrated against
a single model at a single sequence length, and it explicitly excludes allocator
fragmentation, the CUDA context and the framework's own footprint. The measured
peak is reported beside it in every run so the two can be compared; do not treat
the estimate as a guarantee on a machine near its limit.

**Nothing here says anything about larger models.** A 135M-parameter model was
used throughout. VRAM behaviour at 7B is a different regime, and this milestone
measured none of it.

**The permission lint is a lint.** `datasets/policy.py` matches surface text. It
cannot read intent, does not understand paraphrase, and an author who wants to
write a harmful example past it can. Its job is the accident and the
copy-paste. The real guarantee is unchanged and lives where it always did — in
`trust/` and `capsules/`, which do not ask the model whether a permission is
required.

**A completed run means the adapter changed, not that the model improved.** The
evidence gate asserts that training moved trainable tensors, that the adapter
reloads, and that held-out loss with the adapter differs from without. It does
not assert that the difference is an improvement, and 35 synthetic conversations
cannot make one. The demonstration corpus is an engineering fixture, not a
training set.

**Cancellation does not cross process boundaries.** `ModelStudio.cancel` latches
a signal held by the process running the job and returns `False` when there is
none. Cancelling a run in another process would need a signalling channel that
does not exist yet; inventing one that wrote a file the other process might
read would be a cancellation that silently does not work.

**Crash recovery has one residual case.** A job is declared orphaned when its
boot identity differs or its pid is gone. Within a single boot, a reused pid
belonging to an unrelated process would make a dead job look alive. The reboot
case — the common one — is exact.

**There is no GUI.** `view.py` is the data contract a window would render, and
it is exercised by tests and by `bunny-model view`. No widget exists.

**There is one backend.** `SoupBackend`, `UnslothBackend`, `MLXBackend` and a
cloud backend are shapes the registry accommodates, not implementations.

**The adapter is not connected to anything yet.** By design for this milestone:
it is not merged into the base model, and no Bunny inference path loads it. The
handoff is a directory on disk, and building the runtime side of that handoff is
a separate piece of work.

**Windows is untested for training.** The package imports, the CLI runs and the
full test suite passes on the Windows development host, but torch is not
installed there and no training has been performed on it.

**CPU bfloat16 is not used** even on CPUs that have AMX or AVX512-BF16. The rule
selects `fp32` on CPU; the flags are detected and reported but not acted on.

**One network destination.** The approved download path reaches
`huggingface.co` through `huggingface_hub`. There is no mirror, proxy or
air-gapped import path yet, which matters for the environments where Bunny OS is
built.

**Provenance depends on the environment it runs in, and says so when it cannot
read one.** The first evidence round recorded `bunny_commit: "unknown"` on every
run. The cause was measured, not guessed: a systemd service gets `HOME` unset,
so git could not read its configuration, refused the `/mnt/c` checkout as
"dubious ownership", and the field honestly reported that it could not
establish the commit. The same environment lacks `/usr/lib/wsl/lib` on `PATH`,
so the GPU probe fell back to sysfs and named an "unknown display controller"
for a card it names correctly from a shell. The first was fixed by configuring
the runner rather than by having the code bypass git's ownership check; the
second by teaching the probe two fallback locations. Both are worth knowing
before anyone runs this from cron or CI.

**Sample generation is slow on CPU.** The three side-by-side comparisons cost
roughly four of the CPU run's thirteen minutes — six greedy 48-token decodes of
a 135M model, where per-token matmuls are too small to use twenty-two threads
well. It is evidence, not a benchmark, and it is not on the GPU path in any
meaningful way; but a CPU-only user will notice it.

---

## 7. Final status

```text
BUNNY MODEL STUDIO FOUNDATION = PASS
```

The whole path ran end to end, three times, on real hardware:

```text
dataset -> validated config -> hardware preflight -> training plan
        -> LoRA training -> adapter saved -> adapter reloaded
        -> tensor delta measured -> inference compared
        -> provenance recorded -> job completed
```

with **240 of 240 adapter tensors changed** from their pre-training values in
every run, the adapter reloaded from disk into a fresh base model each time, and
held-out loss measurably different with the adapter than without. The two
refusals — an unapproved download and a corpus that teaches permission bypass —
were demonstrated as refusals with distinct exit codes.

This is a foundation, not a product. What it establishes is that the machinery
is correct and honest: it refuses what it should refuse, measures what it
claims, says `UNKNOWN` where it cannot measure, and cannot make a half-finished
run look like a finished one. What it does not establish is anything about model
quality, about hardware other than the one machine listed in §6, or about the
runtime side of the handoff, which is a separate piece of work.

The single most useful thing this milestone produced is probably the evidence
gate itself. Three complete runs trained correctly and then failed *in the
evaluation* — a defect that a subsystem judging success by exit status would
have shipped as a green tick over an unverified adapter.
