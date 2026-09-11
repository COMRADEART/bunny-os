# Bunny OS intelligence-stack gap audit

**Audience:** LEAD, Bunny AI & Memory Engineer.
**Date:** 2026-09-11.
**Repository:** `COMRADEART/bunny-os`
**Audited ref:** `origin/main` @ `23ecc9641b54b324cf66fc7dc1e4eac95c65ed4b` (merge of PR #42).
**Scope:** Intelligence layer only (Companion AI state, routing, memory, models, planner/tools/verifier, response path, voice, eval hooks). Platform boot/image and Companion UX chrome are noted only as integration points.
**Method:** Inventory of current `main` source, ADRs 0008 / 0011 / 0012, capability manifests, host unit tests, and honest runtime probes on this cloud host. Functional Alpha source packaging is **not** treated as a working runtime.
**This document changes:** documentation only. No intelligence features were implemented.

---

## AI STATUS: PARTIAL

The Companion intelligence **runtime exists in source** and is substantially wired for deterministic local work (task state machine, local intents, tool broker, reviewer, local-before-remote provider selection, push-to-talk STT/TTS code, privacy policy objects). It is **not** an implemented Memory Service, **not** an ADR-0012-complete model router, and **not** a verified spoken or local-LLM journey.

| Verdict | Meaning here |
|---|---|
| **PASS** | Would require the seven architecture layers present, wired, tested, **and** runtime-evidenced. That bar is not met. |
| **PARTIAL** | This audit. Source-complete slices sit next to missing Memory Core, ADR drift, and `NOT_RUN` runtime journeys. |
| **FAIL** | Would mean the stack is absent or actively dishonest. It is neither: failures degrade, auto-download is refused, `NOT_RUN` is labelled. |
| **BLOCKED** | Applies to **runtime** journeys on this host (no `llama-cli`, no `libvosk.so`, no TTS binary, no microphone, no GPU/NPU). Not a source-tree blocker. |

**Do not read Functional Alpha “PASS — source level” as a working Bunny.** `FUNCTIONAL_ALPHA_REPORT.md` still heads itself as branch `functional-alpha/dev` and marks steps 12–19 **NOT_RUN / BLOCKED**. Those source changes are on `main`; the runtime evidence is not.

---

## Required report sections (summary)

| Section | Finding |
|---|---|
| **AI STATUS** | **PARTIAL** |
| **MODELS USED** | Adapters and trusted GGUF dirs exist. **No GGUF and no llama.cpp on this host. Generation NOT_RUN.** |
| **MODEL ROUTING** | Local-before-remote **EXISTS** (host tests). GPU/VRAM/NPU and measured throughput **not** in agent selection. ADR 0012 escalation observables **MISSING**. |
| **LOCAL/ONLINE EXECUTION** | Local preferred; remote gated on policy + approval. Remote path is text-only. Persistent memory cannot be dumped today because **it does not exist**. `authorize_cloud_context` is **not** called on the generation wire. |
| **MEMORY CHANGES** | **None** (audit-only). |
| **MEMORY RETRIEVAL TEST** | **NOT VERIFIED** — no Memory Service, no retrieval implementation, no recall tests. Policy unit tests only. |
| **TOOLS TESTED** | Host: structured plans, broker allowlist, local intents (`system.get_metric`, desktop ids). **No live desktop/tool execution on an image.** |
| **VOICE PIPELINE** | Source **EXISTS**. This host: STT/mic/TTS **NOT_RUN**; intent→plan **PASS** on a labelled fixture transcript. |
| **LATENCY / RAM / VRAM / NPU/GPU STATUS** | Selection/context microseconds measured; TTFT/tok/s **NOT_RUN**. Host RAM ~16 GiB / ~11 GiB available. GPU/VRAM/NPU **absent / unprobed as usable**. Companion idle RSS ~31 MiB (harness). |
| **PRIVACY CHECK** | Design is local-first. Online dispatch requires approval and declared providers. Durable memory off by default. **Gap:** cloud-context allow-list is not invoked on remote generate. **Vacuously true today:** there is no durable store to leak. |
| **TEST RESULTS** | See [Test results](#test-results). 432 intelligence-adjacent tests OK; one adjacent voice/trust string test FAIL (out of scope). |
| **REGRESSIONS** | `test_shell_renders_and_resolves_action_approval_without_weakening_policy` expects `"'Deny'"`; shell prompt uses `"Don't allow"` (PR #42 polish). Not an intelligence-layer defect. |
| **UNVERIFIED CLAIMS** | Any Functional Alpha / packaging claim that the spoken journey or local LLM works on a booted image. |
| **KNOWN RISKS** | See [Known risks](#known-risks). |
| **NEXT RECOMMENDATION** | Keep LEAD order: **(a) model router hardening → (b) Bunny Memory Core → (c) voice verify/harden.** No hard blocker to flip. |
| **ADR 0012 DRIFT** | See [ADR 0012 drift](#adr-0012-drift). |
| **ADR 0008 DRIFT** | See [ADR 0008 drift](#adr-0008-drift). |

---

## Inventory (concrete paths on `main`)

| Area | Paths |
|---|---|
| Capability services | `capability/services/bunny-inference-local.json`, `bunny-agent-orchestrator.json`, `bunny-memory-vector.json`, `bunny-speech-recognition.json`, `bunny-speech-synthesis.json`, `bunny-companion.json` |
| Capability routing / hardware | `capability/router.py`, `capability/scores.py`, `capability/budget.py`, `capability/discovery/gpu.py`, `capability/discovery/memory.py` |
| Companion runtime | `companion/runtime.py`, `companion/states.py`, `companion/model.py`, `companion/state.py`, `companion/service.py`, `companion/store.py` |
| Intent / local action | `companion/intents.py`, `companion/local_intent.py`, `companion/outcome_router.py`, `companion/capability_bridge.py` |
| Agents / models | `companion/agents/` (registry, resources, context, adapters, worker, structured) |
| Planner / tools / reviewer | `companion/executor.py`, `companion/agent_bridge.py`, `companion/tools.py`, `companion/reviewer.py`, `companion/coordination.py` |
| Memory | `companion/memory_boundary.py` **only** (plus settings flags). No `src/memory/`, no files-SoR, no SQLite index. |
| Voice | `companion/speech/`, `companion/voice/`, `companion/voice_story.py` |
| ADRs | `docs/phase-1/adr/0008-memory-storage-model.md`, `0011-local-model-runtime.md`, `0012-model-router-strategy.md` |
| Spec | `docs/phase-1/BUNNY_OS_PHASE_1.md` §13–§14 |
| Packaging | `assets/ai/models/PROVISIONING.md`, `assets/voice/models/PROVISIONING.md`, `build/packages/companion-runtime.txt` |
| Eval harness | `scripts/agent_measure.py` |
| Functional Alpha claims | `FUNCTIONAL_ALPHA_REPORT.md` |
| Demos | `demos/10-product-vision/run.py` (voice story with honest `NOT_RUN`) |

`functional-alpha/dev` is **not** ahead of `main` for this stack in a way that changes the audit: the Alpha report’s source-level AI/voice packaging is already on `main`. What is missing is **runtime evidence**, not a forgotten branch.

---

## Architecture layers

Legend: **EXISTS** / **PARTIAL** / **MISSING** / **NOT VERIFIED**. Host tests ≠ runtime evidence.

### 1. User / Companion interface to AI state — PARTIAL (runtime NOT VERIFIED)

Required: idle, listening, understanding, planning, executing, waiting for tool, verifying, complete, failed — **real state, not faked thinking**.

| Required state | What `main` actually has |
|---|---|
| idle | Presentation `CompanionPhase.IDLE`; no active task |
| listening | `LISTENING` / `TRANSCRIBING`; speech indicator |
| understanding | Task `classifying`; presentation `UNDERSTANDING` |
| planning | Task `planning`; presentation `PLANNING` |
| executing | Task `executing`; presentation `WORKING` |
| waiting for tool | **No separate state.** Tools may start only in `executing` (`companion/states.py` `may_start_operation`). |
| verifying | Task `reviewing`; presentation `REVIEWING` |
| complete / failed | `completed` / `failed`; presentation `SUCCESS` / `ERROR` |

**Evidence**

- Task machine: `companion/states.py` — `created → classifying → waiting_for_capability → waiting_for_executor → waiting_for_approval → planning → executing → reviewing → presenting → completed`, plus `blocked` / `failed` / `cancelled` / `recovering`.
- Driver: `CompanionRuntime.run_task()` in `companion/runtime.py`.
- Presentation: `companion/model.py` `CompanionPhase` (22 values); `companion/state.py` maps events → phases.
- Visual Key `"thinking"` (`companion/visual_keys.py`) is a **projection** of `understanding` / `planning` / `starting` / `recovering`, not a simulated chain-of-thought and not a field for hidden model reasoning (`companion/model.py` docstring forbids CoT in records).

**Tests:** host presentation/state suites exist (`tests/companion/test_presentation_projection.py`, task/session tests). **Runtime:** NOT VERIFIED on a booted image.

**Companion-first note:** Character poses follow the real task/presentation machine. Collapsing “waiting for tool” into `WORKING` plus a generic `"thinking"` key is the main place intelligence can still *feel* like a chatbot spinner rather than an OS task.

---

### 2. Intent + Task Router — PARTIAL (runtime NOT VERIFIED)

| Piece | Status | Evidence |
|---|---|---|
| Closed-set local intents | **EXISTS** | `companion/intents.py` `recognise()` — constants only, no ML, no free-form app ids |
| Task type classifier | **PARTIAL** | `companion/runtime.py` `classify_request()` — keyword/regex; comments call it crude |
| Capability task router | **EXISTS** (host tests) | `capability/router.py` `route()` — permission before capability; local incapability never upgrades to remote |
| Provider registry | **EXISTS** (host tests) | `companion/agents/registry.py` — local before remote, config order, resource gate (RAM only) |
| Shell launcher “confidence” | **Out of Companion path** | `shell/services/bunny_shell/launcher.py` uses **static** floats (0.65–1.0), not model confidence |

When no provider is configured, unrecognized language does **not** guess an OS action; it declines or blocks. That is honest. It is also why the product still feels like a small command grammar until a local model is present.

**Tests:** `tests.companion.test_assistant_intents`, `tests.companion.test_ai_preference_routing`, `tests.capability.test_router` — **OK** on this host. Live intent→OS-action on a desktop: **NOT VERIFIED**.

---

### 3. Context / Memory Retrieval — MISSING (policy EXISTS; retrieval MISSING)

| Piece | Status | Evidence |
|---|---|---|
| Context builder | **PARTIAL** | `companion/agents/context.py` — closed `CONTEXT_SOURCES`; `conversation-summary` slot **never populated** by `companion/agent_bridge.py` |
| Memory policy | **EXISTS** (host tests) | `companion/memory_boundary.py` — working/session/durable/cloud, deny-by-default |
| Task event store | **EXISTS** | `companion/store.py` — append-only audit/replay, **not** RAG |
| Settings flags | **EXISTS** | `companion/settings.py` `local_session_memory` / `local_durable_memory` / `cloud_context` |
| Vector capability | **MISSING runtime** | `capability/services/bunny-memory-vector.json` — `priority: "deferred"`; `tests/capability/test_machines.py` asserts it is **not running** |
| Memory Service / plugins / files-SoR / SQLite index | **MISSING** | No implementation. ADR 0008 and Phase 1 §14 are spec only. |

`may_store` / `authorize_cloud_context` are exercised in `tests/companion/test_product_vision.py`. They are **not** called from the generation path.

**MEMORY RETRIEVAL TEST: NOT VERIFIED.** There is nothing to retrieve.

---

### 4. Model Router (locality as security boundary) — PARTIAL

Two routers, not one:

1. **`capability.router.route`** — may this *task* leave the device? Locality first. Fully declared remote providers only. Explanation record on `RouteDecision`.
2. **`AgentProviderRegistry.select`** — which *provider/model* runs generation? Local before remote; user preference; config file order; RAM budget.

**What is good**

- No model self-reported confidence in selection (`registry.py` docstring: derivation, not a score).
- `localAiConfidence` in `capability_bridge.py` is **measurement confidence** (`measured` / `partial` / `unknown` from `capability/scores.py`), not instruct-model “I’m 92% sure”.
- Remote never silently enters a local fallback chain (`registry.py`).
- `bunny-inference-local.json` ranks `local-gpu` (1) → `local-cpu-large` (2) → `local-cpu-small` (3) → paired node (4) → external provider (5).

**What is not ADR 0012**

- Agent selection does **not** read GPU/VRAM/NPU. `companion/agents/resources.py` reads `/proc/meminfo` + PSI only. `llamacli` has **no GPU offload flags**.
- Capability layer **does** probe GPUs, VRAM (`nvidia-smi` / amdgpu sysfs), and NPUs (`capability/discovery/gpu.py` `probe_accelerators` — presence only, usability unknown). `capability/budget.py` can permit local GPU inference. **That permission is not an input to GGUF pick.**
- Escalation observables from ADR 0012 (plan step count, tool-schema failure, repeated no-progress, true `n_ctx` overflow, missing capability, provider health) are **not** a failover engine. Health exists (`companion/agents/health.py`); `/props` `n_ctx` is best-effort on `llamacpp` only and is **not** an escalation trigger.
- Machines are **not** tiered by measured throughput × usable memory. Selection is **largest discovered GGUF that fits a RAM heuristic**.

**Tests:** `tests.companion.test_agent_resource_selection` (29 tests) **OK**. Live GPU/CPU model pick: **NOT VERIFIED** (no models, no GPU).

---

### 5. Planner / Worker / Tools — PARTIAL (runtime NOT VERIFIED)

| Executor | File | Behaviour |
|---|---|---|
| `LocalIntentExecutor` | `companion/local_intent.py` | Grammar → `PlannedOperation` (desktop/file/system) |
| `DeterministicLocalExecutor` | `companion/executor.py` | Vertical-slice text tools |
| `ProviderBackedExecutor` | `companion/agent_bridge.py` | LLM JSON plan (`PLAN_SCHEMA`), max 8 ops |
| `RemoteProviderExecutor` | `companion/agent_bridge.py` | **Zero ops on device**; text result only after `remote_dispatch` approval |

**Tools:** `companion/tools.py` `ToolBroker` — allowlist, reviewer refused, classification ceiling, audit lists. Desktop/system tools in `companion/desktop_bridge.py`, `companion/local_system.py`, `companion/local_files.py`. `LOCAL_TEST_TOOLS` are pure functions (intentional for tests).

**Timeouts:** reviewer 5s; task execution 300s; agent generation 120s (`agent_bridge`). **`ToolBroker.invoke` has no per-call timeout.**

**Model output is untrusted by construction:** plans go through `parse_structured`; tools run only if declared; reviewers cannot invoke tools.

**Tests:** structured/security/bridge/executor-reviewer suites **OK**. Live tool on a desktop: **NOT VERIFIED**.

---

### 6. Verifier — PARTIAL

There is **no** component named Verifier. Verification is a **reviewer round**:

- Protocol: `companion/reviewer.py` — observation only.
- `DeterministicLocalReviewer` (slice checks).
- `ProviderBackedReviewer` (LLM observations, `OBSERVATIONS_SCHEMA`).
- `run_review_round()` copies context; disagreements persist as `reviewer_disagreement`.

This is a real check, not a fake “verifying…” spinner. It is **not** Phase 1 Execution Controller verification (effect admission, result classification, reconciliation).

---

### 7. Companion Response path — PARTIAL (runtime NOT VERIFIED)

```
task events → PresentationProjector → CompanionPhase / captions
           → CompanionGateway (IPC)
           → shell / GTK / character mapper
           → VoiceService.speak(captionId) when TTS exists
```

Speech return: `SpeechInputService` → confirm transcript → `submit_task` / `run_task`.

Wired in source. Spoken round-trip on hardware: **NOT VERIFIED**.

**Companion-first vs bolted-on chatbot**

- **OS-integrated:** bounded intents → declared desktop tools; Trust/approvals; capability blocking; character driven by task events; no chat-log-as-OS.
- **Still chatbot-shaped:** LLM path emits JSON plans; remote path is a text answer with no tools; **no memory** of the person; unrecognized speech cannot act; `"thinking"` Visual Key folds several real phases into one pose.

Integration points (not this owner): image packages (`llama-cpp`, `vosk-api-devel`, `espeak-ng`), `agent-models` / `speech-models` install routes, GTK/character chrome, `bunny-settings` Voice & AI page.

---

## Local LLM integration

| Claim | On `main` |
|---|---|
| Engine | llama.cpp via `llama-cli` subprocess and optional loopback `llama-server` (`llamacpp`). Also Ollama loopback. |
| GGUF dirs | `~/.local/share/bunny-os/agent-models`, `/usr/share/bunny-os/agent-models` |
| Binary dirs | `/usr/bin`, `/bin` only — never `PATH` |
| Writable models | Refused |
| Auto-download | **None.** Documented in `assets/ai/models/PROVISIONING.md`, onboarding, adapters |
| Engine binary sha256 pin (ADR 0011) | **MISSING** |
| GPU-aware engine/asset pick (ADR 0011) | **MISSING** at the adapter; capability budget can *permit* GPU inference without selecting a CUDA build |
| In-process weight load | **None** (out-of-process by design) |

This host: `llama-cli` / `llama-server` **not installed**; no `*.gguf`; `scripts/agent_measure.py` notes *“no local model provider on this host”*.

---

## Resource-aware model selection

**EXISTS for RAM + PSI; MISSING for VRAM/NPU/GPU runtime and measured tok/s.**

- `MachineResources` / `model_memory_budget`: 50% / 30% / 15% of `MemAvailable` by pressure band; unknown host → guard **disabled** (not a refusal).
- No Low/Medium/Ultra product tiers (matches C11 / Functional Alpha STEP 5).
- NPU: enumerated, **not schedulable** (`probe_accelerators`). Correct caution; not wired into selection either way.
- Throughput: **not measured**, so it cannot be a routing input (ADR 0012 / 0011 P23).

---

## Online model path

Remote adapters: `openai_compat`, `anthropic`, `gemini` — config + credentials from approved dirs.

`RemoteProviderExecutor`:

- Plan transmits **no** user corpus (empty ops; generation after approval).
- Result context is current request (+ in-task tool results). **No** `summary_text`. **No** durable memory (none exists).
- Failed remote does not authorise a different remote (`agent_bridge.py`).

**Gap:** `authorize_cloud_context(...)` is never applied to that payload. Field allow-list + remote audience projection exist and are unhooked.

Training/export: enterprise policy can block organisational memory expose; onboarding states no export for external training. **No product path dumps the (non-existent) memory store to a provider.**

---

## Tool execution (schemas, permissions, validation, timeouts, audit)

| Concern | Status |
|---|---|
| Schemas | `PLAN_SCHEMA` / `OBSERVATIONS_SCHEMA`; desktop operation schemas |
| Permissions | Declaration flags → `approvals.requirements_for`; Trust for desktop |
| Validation | `parse_structured` + one repair round; broker allowlist |
| Timeouts | Generation 120s; review 5s; task 300s; **no tool-invoke timeout** |
| Audit | Typed task events; `ToolBroker.invocations` / `refusals`; generation `journal.jsonl` |
| Untrusted model | Structural: broker executes, model proposes |

---

## Voice pipeline

**Design:** Push-to-talk → STT → intent/model → tool/task → response → TTS. Wake word **disabled** (`companion/speech/wakeword.py` `enable()` raises).

**Isolation:** Speech, voice, and task runtimes are separate workers; missing lib/model/mic is `NOT_RUN`, not FAIL. Text path still runs (`companion/voice_story.py`).

**This host (`run_voice_story()`):**

| Step | Status |
|---|---|
| Vosk runtime | **NOT_RUN** — `libvosk.so` not found |
| Recognition model | **NOT_RUN** — no packaged model dir; repo does not vendor bytes |
| Microphone | **NOT_RUN** — no capture path |
| STT | **NOT_RUN** — labelled fixture transcript, not a recording |
| Intent | **PASS** — `system_metric` for “how much memory am i using” |
| Plan | **PASS** — `system.get_metric`, local, no approval |
| TTS | **NOT_RUN** — no espeak-ng / speech-dispatcher |
| `passed` | `True` because NOT_RUN ≠ FAIL (honest story convention) |

Spoken e2e on an image: **NOT VERIFIED**. Independent failure isolation: **designed, not runtime-proven**.

---

## Evaluation / metrics hooks — PARTIAL

| Hook | Status |
|---|---|
| `scripts/agent_measure.py` | Ran here. Selection/context/validation measured. TTFT, tok/s, generation, cancel, model startup **NOT_RUN** |
| `companion/agents/usage.py` | Token/cost ledger (needs a provider that reports) |
| `companion/agents/health.py` | Failure classification |
| Capability scores | `local_ai`, GPU memory/compute — **not** consumed by agent GGUF pick |
| Retrieval quality | **MISSING** (no retrieval) |
| Product telemetry | Explicitly refused (onboarding) |

---

## Failure handling without crashing Bunny OS — EXISTS (source); runtime NOT VERIFIED

Blocked tasks with explanations; recovery replans from `planning` not `executing`; agent worker catches per job; speech/voice journals; unknown host resources do not refuse every model; missing GGUF → ineligible, not download/crash.

Crash/failure behaviour on a booted image: **NOT_RUN** (Functional Alpha steps 18–19).

---

## Layer scoreboard

| # | Layer | Classification | Host tests | Runtime evidence |
|---|---|---|---|---|
| 1 | AI state (idle…failed) | **PARTIAL** | Yes | **NOT VERIFIED** |
| 2 | Intent + task router | **PARTIAL** | Yes | **NOT VERIFIED** |
| 3 | Context / memory retrieval | **MISSING** | Policy only | **NOT VERIFIED** |
| 4 | Model router | **PARTIAL** | Yes (RAM path) | **NOT VERIFIED** |
| 5 | Planner / worker / tools | **PARTIAL** | Yes | **NOT VERIFIED** |
| 6 | Verifier | **PARTIAL** | Yes (reviewer) | **NOT VERIFIED** |
| 7 | Companion response | **PARTIAL** | Yes | **NOT VERIFIED** |
| — | Local LLM / GGUF | **EXISTS** (source) | Probe/selection | **NOT VERIFIED** (no binary/weights) |
| — | GPU/VRAM/NPU in *agent* pick | **MISSING** | Discovery tests only | **NOT VERIFIED** |
| — | Online path + memory minimization | **PARTIAL** | Policy tests | **NOT VERIFIED** |
| — | Voice PTT → TTS | **EXISTS** (source) | Partial | **NOT_RUN** this host |
| — | Eval (TTFT / tok/s / VRAM) | **PARTIAL** | Harness | Generation **NOT_RUN** |

---

## MODELS USED

| Kind | Exists in tree | Verified this audit |
|---|---|---|
| `local.llamacli` / GGUF | Adapter + trusted dirs + packaging notes | **NOT VERIFIED** — no `llama-cli`, no GGUF |
| `llamacpp` loopback | Adapter (`/health`, `/v1/models`, best-effort `/props`) | **NOT VERIFIED** — no server |
| `ollama` loopback | Adapter | **NOT VERIFIED** |
| Remote (OpenAI-compat / Anthropic / Gemini) | Adapters + credential dirs | **NOT VERIFIED** — not invoked |
| Vosk STT | `companion/speech/vosk_runtime.py` + provisioning doc | **NOT VERIFIED** — no `libvosk.so` |
| eSpeak / speech-dispatcher TTS | `companion/voice/providers.py` | **NOT VERIFIED** |
| Neural TTS | Optional path | **NOT VERIFIED** |

No model was fabricated. No download was attempted.

---

## MODEL ROUTING

- **Implemented:** locality as a category (local ≫ remote); explanations; RAM/PSI budget; capability `route()` permission-first.
- **Not implemented:** confidence-based *task* routing (good — ADR forbids it). GPU/VRAM/NPU in GGUF selection. Measured tok/s. ADR 0012 escalation ladder. Ranking from `bunny-inference-local.json` implementations inside `AgentProviderRegistry` (manifest ranks GPU first; the adapter always runs CPU `llama-cli` as packaged).

---

## LOCAL/ONLINE EXECUTION

Local is default. Remote requires policy, network, declared retention/training, spend, and usually user approval. Sensitive/secret stay on device unless policy explicitly allows (secret never leaves).

Online models are **intended** to see only current-interaction context. Enforcement is mostly structural (what `ContextBuilder` is passed). The named cloud-context function is unused on the wire.

---

## MEMORY CHANGES

None. Audit-only. Settings still default session/durable/cloud **off**.

---

## MEMORY RETRIEVAL TEST

**NOT VERIFIED.** No store, no `recall`, no snippet/ref split, no taint envelope, no deletion cascade, no plugin pack.

Closest tests: `MemoryPolicy` deny-by-default in `tests/companion/test_product_vision.py` (**PASS**). `bunny.memory.vector` deferred and not started (`tests/capability/test_machines.py`).

---

## TOOLS TESTED

| Tool / path | This audit |
|---|---|
| `recognise()` → `system.get_metric` | **PASS** (voice story fixture) |
| Structured plan parse / broker allowlist / reviewer isolation | **PASS** (unit tests) |
| Desktop launch / files / portals | **NOT VERIFIED** (no session) |
| LLM-proposed tools | **NOT VERIFIED** (no model) |

---

## VOICE PIPELINE

See layer write-up. **Source EXISTS. Runtime NOT_RUN on this host.** Functional Alpha STEP 6 = packaged, runtime NOT_RUN — still true.

---

## LATENCY / RAM / VRAM / NPU/GPU STATUS

From `python3 scripts/agent_measure.py --generations 1 --cancellations 0` on this host (2026-09-11):

| Metric | Result |
|---|---|
| provider-selection | n=20, median ~0.0 s, max 0.0013 s |
| context-construction | n=20, median 0.0001 s |
| structured-validation | n=50, ~0 s |
| TTFT / output-rate / total-generation / cancel / model startup | **NOT_RUN** — no local model provider |
| Companion RSS (idle agent runtime) | ~31 236 096 bytes |
| Model server processes | `[]` |
| Host RAM | MemTotal 16 398 384 kB; MemAvailable 11 333 968 kB |
| GPU / VRAM | No `/dev/dri`, no `nvidia-smi` |
| NPU | `/sys/class/accel` empty |

VRAM/NPU as a **routing input**: not implemented, therefore **NOT VERIFIED**.

---

## PRIVACY CHECK

| Rule | Status |
|---|---|
| Local-first; remote last resort (`bunny-inference-local.json` ranks) | **Design EXISTS**; live rank **NOT VERIFIED** |
| Online models: current-interaction only | **PARTIAL** — remote executor is narrow; `authorize_cloud_context` unhooked |
| Persistent memory stays local | **Vacuously true** (no persistent memory). Policy would allow durable local if implemented and user-enabled |
| No export for external training | Stated; no memory export pipeline found |
| No auto-download of models | **EXISTS** |
| Credentials not in context | Context source set excludes them; scrub on credential-shaped text |

---

## TEST RESULTS

**Host:** Ubuntu cloud agent, Python 3.12.3. Commands run 2026-09-11.

### Intelligence-adjacent unit tests — PASS

```text
python3 -m unittest \
  tests.companion.test_agent_resource_selection \
  tests.capability.test_router \
  tests.companion.test_ai_preference_routing \
  tests.companion.test_assistant_intents \
  tests.companion.test_agents_schemas \
  tests.companion.test_agents_security \
  tests.companion.test_agent_bridge \
  tests.capability.test_machines \
  tests.capability.test_scores \
  tests.companion.test_product_vision \
  tests.companion.test_agents_structured \
  tests.companion.test_executors_reviewers \
  tests.companion.test_agents_authority \
  tests.capability.test_discovery \
  -q

Ran 432 tests in 8.127s
OK (skipped=3)
```

### Agent measurement harness — PARTIAL / honest NOT_RUN

```text
python3 scripts/agent_measure.py --generations 1 --cancellations 0
```

Selection/context/validation series populated. Generation/TTFT **NOT_RUN** (see JSON in previous section).

### Voice story probe — intent PASS, audio NOT_RUN

```text
python3 -c "from companion.voice_story import run_voice_story; print(run_voice_story())"
```

STT/mic/TTS **NOT_RUN**; intent `system_metric` and plan `system.get_metric` **PASS** on fixture text.

### Adjacent regression (not in the 432) — FAIL

```text
python3 -m unittest tests.companion.test_voice_interaction_milestone -q
# FAIL: test_shell_renders_and_resolves_action_approval_without_weakening_policy
# AssertionError: "'Deny'" not found in shell/services/bunny_shell/prompt.js
# (buttons now label "Don't allow" after PR #42 UI polish)
```

Not an intelligence-stack functional failure. Do not treat as voice-pipeline FAIL.

Full `python3 scripts/task.py test` (7000+ tests) was **not** re-run for this docs PR.

---

## REGRESSIONS

- Host test expecting literal `"'Deny'"` vs shipping `"Don't allow"` (Companion UX chrome / Trust prompt, PR #42). Intelligence backlog should not absorb this unless LEAD wants a one-line test fix.
- `FUNCTIONAL_ALPHA_REPORT.md` still labelled as `functional-alpha/dev` while living on `main` — historical, easy to misread as a current runtime PASS.

No intelligence behaviour was changed by this audit.

---

## UNVERIFIED CLAIMS

Treat as **unverified** until a Fedora image with provisioned GGUF + Vosk + TTS is booted and logged:

1. “Default local AI path works” (Functional Alpha STEP 4 source PASS).
2. “Resource-aware selection picks the right model under load” (STEP 5 / 18).
3. “Voice path Vosk → action → TTS works offline” (STEP 6 / 17).
4. llama.cpp GPU vs CPU engine choice (ADR 0011).
5. Online provider minimization under a real remote credential.
6. Any Memory Service / retrieval quality number.
7. Failure isolation of STT vs TTS vs model vs tools on a live session.
8. `bunny.agent.orchestrator` as a **process** — orchestration is in-process `CompanionRuntime` + `agent_bridge`; the JSON is a capability budget object.

---

## KNOWN RISKS

1. **Memory Core is a one-way door** (Phase 1 §14.3 / D10). Shipping a SQLite-authoritative or embedding-first store would freeze the wrong schema. Files must be SoR from v0 of the Python port.
2. **Hooking `conversation-summary` before a tainted/ref retrieval layer** would let a model (or a remote provider) see durable facts with no provenance envelope — the MemGhost shape Phase 1 warns about.
3. **RAM-only GGUF pick on a discrete GPU** wastes the machine and can OOM CPU RAM while VRAM sits empty (ADR 0011/0012).
4. **Unhooked `authorize_cloud_context`** becomes a real leak the day Memory Core or richer remote context lands.
5. **No per-tool timeout** — a stuck desktop/portal call can sit until the 300s task deadline.
6. **Phase 1 spec is Node/Bun** (`node:sqlite`, `src/memory/`). Bunny OS `main` is Python. A literal TS port is the wrong artifact; a Python Memory Service that preserves ADR 0008 semantics is the right one.
7. **Capability GPU permission vs companion CPU `llama-cli`** can disagree: budget says GPU inference allowed; the only local adapter is CPU subprocess.
8. **NPU presence without usability** — fine if we never schedule on it; dangerous if a future router treats sysfs presence as a runtime.

---

## ADR 0012 DRIFT

**ADR:** `docs/phase-1/adr/0012-model-router-strategy.md`  
**Spec:** Phase 1 §13.

| ADR 0012 requirement | Design | Code | Tests | Runtime |
|---|---|---|---|---|
| Locality is a security boundary; classify loopback / private-network / hosted | Yes | **Yes** (`ProviderDeclaration.locality`, registry local-before-remote) | **Yes** (`test_router`, agent security/authority) | **NOT VERIFIED** |
| Cross-boundary failover rejects loudly + consent / seven disclosures | Yes | **Partial** — refuse + approval, not the full disclosure-duty UX on every escalation | Partial | **NOT VERIFIED** |
| Escalation on deterministic observables (steps, schema fail, no-progress, `n_ctx`, missing capability, health) | Yes | **No** as a ladder. Pieces exist (`health`, `/props` n_ctx, structured repair) but are not failover inputs | No | **NOT VERIFIED** |
| **Exclude model self-reported confidence** | Yes | **Honoured** in companion selection | Host tests do not introduce confidence routing | n/a |
| Machines tiered by usable memory × **measured** throughput | Yes | **No** — RAM heuristic + largest fitting GGUF | RAM tests only | **NOT VERIFIED** |
| Every decision emits a reconstructible explanation | Yes | **Yes** (`RouteDecision`, `SelectionExplanation`) | Yes | **NOT VERIFIED** |

**Confidence-based routing:** rejected by ADR; **not used** for Companion task routing. Do not confuse `Score.confidence` (was the hardware *measured*?) or STT word confidence with model-confidence routing.

**Capability JSON vs agent code:** `bunny-inference-local.json` ranks GPU first. `LlamaCliAdapter` never asks for GPU. That is the loudest design-vs-code split in the router.

---

## ADR 0008 DRIFT

**ADR:** `docs/phase-1/adr/0008-memory-storage-model.md`  
**Spec:** Phase 1 §14 (Memory Service).

| ADR 0008 / §14 requirement | Design | Code on `main` | Tests | Runtime |
|---|---|---|---|---|
| Files = system of record (one record/file, JSON + optional `.md`) | Yes | **MISSING** | — | — |
| SQLite disposable index (FTS5, bi-temporal, lineage `ON DELETE CASCADE`, later embedding BLOBs) | Yes | **MISSING** | — | — |
| `bunny memory reindex` from files; degrade to file scan | Yes | **MISSING** | — | — |
| No ANN/HNSW ever | Yes | N/A (no vectors). Manifest `bunny.memory.vector` is deferred — keep it that way until brute-force cosine (P8) is real | Machines test: vector service **not running** | n/a |
| MemoryRecord provenance, taints, no model-forged confidence/importance | Yes | **MISSING** | Phase 2 backlog A-1c still open | — |
| Sensitive bodies: per-record DEK, crypto-shred | Yes | **MISSING** | P7 unverified in TRACEABILITY_MATRIX | — |
| Retrieval: refs + snippets, not full dump; model cannot widen scope | Yes | **MISSING**. `ContextBuilder` would happily send any `summary_text` it is given | No recall tests | — |
| Model inference ≠ user-confirmed fact; confirmation before operative routines | Yes (Phase 0/1) | **MISSING** (no write path). Reviewer ≠ memory promotion | — | — |
| Plugins: conversation / preferences / task / companion / app / routines / system / project / semantic | Product taxonomy (this brief) | **MISSING** | — | — |
| Phase 1 categories: episodic / semantic / procedural / task_state / system / performance | Spec | **MISSING**. Map plugins onto these; do not invent a third ontology | — | — |
| Node/Bun sqlite adapter | ADR text | **Wrong runtime for this repo.** Python port required | P6 was Node/Bun parity | — |

**What exists instead:** deny-by-default **policy** (`memory_boundary.py`), append-only **task events**, settings toggles that enable nothing durable.

**Vector index:** optional, storage-heavy, explicitly deferred. Building HNSW to “catch up” would **violate** ADR 0008.

TRACEABILITY_MATRIX C7/C8/D10: **Ratified. Unverified.** Still accurate.

---

## Sequencing (do not flip without a hard blocker)

LEAD asked: **(a) model router hardening → (b) Bunny Memory Core → (c) voice verify/harden.**

**Keep this order.** There is no hard blocker.

| Question | Answer |
|---|---|
| Does missing Memory Core block router work? | **No.** Router gaps (GPU/VRAM, throughput, escalation, cloud-context hook) are independent and are the privacy fence Memory Core will need. |
| Does voice being NOT_RUN block router or memory? | **No.** Voice is a packaged runtime + hardware evidence problem. Intent→plan already works in text. |
| Would shipping Memory Core first be dangerous? | **Yes, slightly.** A summary slot already exists and is unwired. Filling it before remote minimization and taint envelopes is the poisoning/leak path. Router hardening first is the safer sequence. |
| Would voice-first help Alpha demos? | Cosmetically. It would still stall on missing GGUF for “understanding”, and it would not fix locality/GPU honesty. |

---

## NEXT RECOMMENDATION — ranked fix backlog

Owner unless noted: **Bunny AI & Memory Engineer**. Platform owns image packages; Companion UX owns chrome/strings.

### P0 — (a) Model router hardening

Do this **before** Memory Core writes durable facts.

1. **Feed capability GPU/VRAM (and honest NPU-unknown) into `AgentProviderRegistry`.** Today RAM-only. A machine with CUDA+VRAM should not be scheduled as CPU-largest-GGUF-that-fits. Align with `bunny-inference-local.json` rank 1 `local-gpu`.
2. **ADR 0012 escalation ladder** (deterministic observables only): plan step count, structured-schema failure, repeated no-progress, context vs true `n_ctx` (`/props` where the server exists), missing capability, provider health. Halt + consent across locality; never silent hosted failover.
3. **Replace “largest GGUF that fits RAM” with usable memory × measured throughput** once `agent_measure.py` can see a real engine (P23). Until measured, keep estimates labelled and refuse to invent TOPS.
4. **Call `authorize_cloud_context` on every remote generate** with an explicit field allow-list (current request, not session/durable bodies). Tests that fail if `summary_text` or durable records appear on a hosted adapter.
5. **ADR 0011 local runtime:** GPU offload / engine asset selection for llama.cpp; vendor engine sha256; still **no auto-download**.
6. Host tests for (1)(2)(4) with fake inventories. Live GPU generation remains **NOT_RUN** until an image exists — keep it labelled.

### P0 — (b) Bunny Memory Core (after the router fence)

1. **Python Memory Service** implementing ADR 0008: files SoR, disposable SQLite FTS5 index, reindex, file-scan fallback. Not Node. Not SQLite-as-truth.
2. **MemoryRecord v1** with mandatory provenance, taints, bi-temporal fields, **no** model-authored confidence/importance. Inference lands `proposed`, not `active`, unless the user confirms (routines/intents).
3. **Plugin packs** (files under documented trees), mapped to §14 categories — do not fork a second ontology:

   | Plugin (this brief) | §14 category (approx.) |
   |---|---|
   | conversation | episodic |
   | preferences | procedural / performance (interface) |
   | task | task_state |
   | companion | episodic + procedural (presentation prefs) |
   | app | task_state / procedural |
   | routines | procedural (**confirmation required**) |
   | system | system (**read-only to Memory Service**) |
   | project | episodic / semantic scoped to workspace |
   | semantic | semantic |

4. **Retrieval:** `recall` → refs+snippets; `read(ref)` separately; hard caps; taint envelope; never dump the store into `ContextBuilder`. Wire `conversation-summary` **only** from this path.
5. **Tests that must exist before claiming retrieval:** export/reimport files; reindex rebuild; cascade delete; cloud generate sees zero durable bodies; model cannot mark a guess as user fact.
6. Leave `bunny.memory.vector` **deferred**. No HNSW.

### P1 — (c) Voice verify / harden

1. **Runtime evidence** on the Fedora image: provisioned Vosk model + `libvosk.so` + espeak-ng + a 1B–3B GGUF. Spoken journey with microphone. Until then, keep `NOT_RUN`.
2. Prove **independent failure isolation**: kill STT → text fallback still plans; kill TTS → captions still show; kill model → local intents still run; no Companion crash.
3. Push-to-talk only (wake word stays off).
4. Optional tiny hygiene: update `test_voice_interaction_milestone` for `"Don't allow"` (UX polish, not intelligence).

### P1 — tools / verifier (parallel, small)

1. Per-invoke timeout on `ToolBroker` (or desktop adapters), not only the 300s task deadline.
2. Distinguish presentation **waiting for tool** from generic `WORKING` if LEAD wants the required state list literally (small, UX-visible).
3. Keep reviewer observation-only; if a named Verifier is required, it should classify **tool/effect outcomes**, not re-prompt the LLM to “look confident”.

### P2

- Product metrics on-image: TTFT, tokens/s, RAM vs VRAM, retrieval-quality eval (only after Memory Core).
- Do not split `bunny.agent.orchestrator` into a second daemon until the in-process pipeline has runtime evidence.
- Phoneme visemes remain unimplemented — Companion UX, not intelligence P0.
- Re-title or footnote `FUNCTIONAL_ALPHA_REPORT.md` so `main` readers do not treat STEP 4–6 as guest-boot PASSes.

---

## Suggested implementation slices (after this audit)

These are sequencing hints, not work done in this PR.

1. Router: inventory → `MachineResources` grows optional `vram_bytes` / `gpu_runtime` / `throughput_tok_s` (unknown disables that axis, same as RAM today).
2. Router: remote generate tests that fail CI if context contains `conversation-summary` or durable-looking payloads without `authorize_cloud_context`.
3. Memory: empty plugin trees + schema + `reindex` no-op on zero files (honest empty).
4. Voice: one image-lab checklist that cannot be ticked from host unit tests.

---

## Appendix — this audit host (for reproducibility)

- OS: Linux 6.12 cloud image, Python 3.12.3
- `llama-cli` / `llama-server` / `libvosk.so` / `espeak-ng` / `nvidia-smi` / `/dev/dri` / `/sys/class/accel`: **absent**
- RAM: ~16 GiB total, ~11 GiB available
- Commit audited: `23ecc964`

If a later agent claims TTFT, VRAM routing, or memory recall without a different host and provisioned assets, that claim is false.
