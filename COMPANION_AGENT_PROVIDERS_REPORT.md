# Bunny Companion Agent Provider Runtime — Phase Report

This report closes the first Bunny Companion agent-provider phase: a canonical
provider descriptor and registry, genuine local text-generation adapters,
remote adapters that stay dark unless explicitly configured, deterministic and
fully explained selection, bounded streaming, locally validated structured
output, tool proposals mediated by the existing ToolBroker, approval-bound
remote transfer, cost and usage accounting, circuit-broken health, cancellation
that releases what it touched, recovery that repeats nothing, eight protocol
operations, and the `100/50/20` stress gates on one exact commit.

Every claim below is bounded to what was executed on the named machines. Where
something was not run, it is listed as NOT_RUN with the reason, not omitted.

---

## 1. Starting and final SHAs

| | |
|---|---|
| Base branch | `feature/companion-speech-input` |
| Starting commit | `65472aa2f43c78e3db16cb4b9f7ff5d244b52e10` (verified head of the base branch) |
| Working branch | `feature/companion-agent-providers` |
| Gate commit | `0a48579e9fc5eb28e6c9a1f95c73d484ed2bffa0` (every gate iteration records it) |
| Evidence commit | *(filled by the evidence commit)* |
| Final SHA | *(filled at closure)* |

Preflight, before the branch was created: the full SHA of `65472aa` was
resolved and matched the branch head; the working tree was clean; the
speech-input evidence commit (`0a78806`) and report-closure commit (`65472aa`)
were shown to touch only `COMPANION_SPEECH_INPUT_REPORT.md` and
`qualification/companion-speech-input/evidence/**`, so neither introduced a
post-gate installed-code change; and the corrected build-input analyzer
classified `db9e0b1..65472aa` as non-build-affecting — **0 installed, 0
context-only, 11 unreachable**. The completed speech-input branch was not
modified. All prior runtime, renderer, voice and speech-input evidence trees
(`qualification/companion-linux/`, `companion-voice/`, `companion-voice-closure/`,
`companion-speech-input/`) are untouched by every commit on this branch.

Two gate runs were started. The first, on `9a57a69`, reached 100/100 on gate 1
and two iterations into gate 2 before it was stopped deliberately: the harness
was not recording which backend each iteration exercised, and "a genuine local
provider produced this result" is a claim the evidence has to carry rather than
the prose. The harness change and the restart from one are commit `0a48579`;
the discarded partial run is named here because a reader counting gate
invocations should find the same number this report does.

---

## 2. Branch lineage

```text
main
 └── … (companion runtime core, integration, character renderer,
          pause/approval consistency, Linux validation, voice runtime)
      └── fix/companion-voice-closure         50b1d4d
           └── feature/companion-speech-input  db9e0b1 (speech gates)
                                               0a78806 (speech evidence)
                                               65472aa (speech closure) ← base
                └── feature/companion-agent-providers
                     e896de3  the subsystem, the bridge, the slice, the tests
                     9a57a69  the router is told what only the companion knows
                     0a48579  each iteration records which backend it exercised  ← gate commit
```

No commit on this branch touches any file under `qualification/` belonging to
an earlier phase.

---

## 3. Build-input impact

Measured with `build/scripts/build-input-closure.py`, which classifies against
the single install declaration in `build/scripts/install_routes.py`.
`--audit` passes: *install-root.py installs only what install_routes.py
models*.

Over `65472aa..0a48579`: **BUILD-AFFECTING: YES** — 35 installed, 5
context-only, 13 unreachable, across all eight profiles. The installed paths
are the new `companion/agents/` package (24 modules), `companion/agent_bridge.py`,
and the modified `companion/{service,protocol,runtime,cli,gtk_shell,capability_bridge}.py`.
They join the artifact through the existing `companion-package` route with no
new install route, because that route is `kind="package"` over the whole
`companion/` tree — a new module under it is installed by declaration already
made.

Not installed, and correctly classified: `scripts/companion_stress.py`,
`scripts/agent_measure.py` and `scripts/ops/agents-*` are development tools
outside the `script_names` tuple; `tests/companion/**` is excluded by the
package route's `PACKAGE_EXCLUDED`.

The subsystem adds **no non-`.py` asset**, so no new `tree` route is needed. A
provider configuration file is user state under the runtime root, not a shipped
artifact: absent, `companion/agents/config.py` supplies local-only defaults.

Every commit changes the OCI configuration digest through the revision label
and `/usr/lib/bunny-os/release.json`; an unchanged layer digest is not an
unchanged image.

---

## 4. Provider architecture

The §2 pipeline, and where each stage lives:

```text
canonical task (companion/runtime.py — unchanged authority)
    ↓  companion/agent_bridge.py  ProviderBackedExecutor.plan/result
context builder            companion/agents/context.py
    ↓
privacy and locality filter companion/agents/context.py + descriptor ceiling
    ↓
provider eligibility        companion/agents/registry.py  _reasons()
    ↓
provider selection          companion/agents/registry.py  select()
    ↓
generation request          companion/agents/request.py
    ↓
provider adapter            companion/agents/adapters/*
    ↓
text / structured / proposal
    ↓
schema validation           companion/agents/structured.py
    ↓
ToolBroker or result        companion/tools.py (unchanged) via PlannedOperation
    ↓
canonical task events       companion/runtime.py._emit (unchanged)
```

**The subsystem is runtime-free, structurally.** Nothing under
`companion/agents/` imports `companion.runtime`, `store`, `task`, `session`,
`approvals`, `executor`, `reviewer`, `tools`, `cancellation`, `recovery`,
`events`, `coordination` or `migration`. `tests/companion/test_agents_authority.py`
parses every module in the package and fails on any of them, the same
proof-by-import-graph the voice and speech runtimes carry. The one seam is
`companion/agent_bridge.py`, which lives *outside* the package for exactly that
reason — the arrangement `companion/capability_bridge.py` already uses.

**A tool proposal is a plan entry.** `ProviderBackedExecutor.plan` turns
validated structured output into ordinary `PlannedOperation` tuples, so a
model's proposal meets the same broker, the same approval derivation, the same
lifecycle re-checks and the same operation-key idempotency as the deterministic
executor's entries. There is no second execution path, which is why "providers
cannot execute tools" needs no enforcement of its own: providers have nothing
to execute with.

**Exactly one executor owns a task at a time.** Unchanged: `ExecutorLeases`
holds the lease. Re-selection prefers the provider already recorded for the
task (`_sticky_provider`), so a re-plan does not silently migrate a task
between models mid-flight.

---

## 5. Descriptor schema

`companion/agents/descriptor.py`, `ProviderDescriptor`, schema version 1,
frozen dataclass validated in `__post_init__`. Every §3 field is present:
provider id, adapter id, provider type, local flag, model id, model revision,
endpoint identity, supported task classes, input and output modalities, context
limit, maximum output, streaming, structured-output, tool-proposal, image-input,
audio-input and cancellation support, available authentication *kinds*, standing,
cost class, privacy ceiling, resource estimate, supported languages, licence
reference, availability explanation.

**There is no credential field.** Not optional, not redacted, not "a reference
that is usually safe". `tests/companion/test_agents_authority.py` asserts the
absence by field name. Authentication appears only as a *kind*
(`none`, `secret-service`, `credential-file`, `environment`, `hardware-backed`)
and presence, never a value, a path beyond the approved-location label, or a
header it would appear in.

Refusals at construction: unknown provider type, cost class, privacy class,
task class, modality or authentication kind; a remote provider declaring a
privacy ceiling above `internal`; `supports_image_input` disagreeing with
`input_modalities`; a negative or non-integer limit; a wrong schema version; an
endpoint locator carrying userinfo, a query, a fragment or a scheme.

The six-word ladder is `ProviderStanding` plus the selection explanation:

| rung | meaning | where |
|---|---|---|
| `configured` | in the configuration, enabled, adapter present in this build | `ProviderStanding.configured` |
| `authenticated` | declared credential requirement met — *presence*, never value | `ProviderStanding.authenticated` |
| `available` | last probe reached the endpoint and the model was offered | `ProviderStanding.available` |
| `healthy` | available and the circuit breaker is closed | `ProviderStanding.healthy` |
| `eligible` | permitted for one **specific** request | `SelectionExplanation.eligible` |
| `selected` | eligible and first in the deterministic order | `SelectionExplanation.selected` |

`ProviderStanding.__post_init__` refuses an incoherent ladder — authenticated
without configured, available without authenticated, healthy without available.
`eligible` and `selected` are deliberately *not* on the descriptor: they exist
only against a concrete request, and a status display showing "eligible" with no
request in hand would be inventing the request.

---

## 6. Local provider adapters

Three, all genuine, none a placeholder.

**`ollama`** (`adapters/ollama.py`) — loopback NDJSON. `GET /api/version` and
`GET /api/tags` to probe, `POST /api/chat` with `"stream": true` to generate,
one JSON object per line. Structured output uses Ollama's `format` parameter,
which constrains decoding to a JSON schema server-side — always one of ours.
`"think": false` is sent explicitly: §6 forbids hidden reasoning in the record,
and the honest way to exclude it is not to produce it. Usage from
`prompt_eval_count`/`eval_count`, basis `reported`.

**`llamacpp`** (`adapters/llamacpp.py`) — loopback SSE against `llama-server`'s
OpenAI-compatible surface. `GET /health`, `GET /v1/models` and a best-effort
`GET /props` to probe; `POST /v1/chat/completions` to generate. The chat
endpoint rather than the native `/completion` deliberately: the server applies
the chat template recorded in the GGUF's own metadata, so this adapter never
hard-codes a template that silently mismatches somebody's model. Structured
output via `response_format` `json_schema`, compiled to a grammar server-side.

**`llamacli`** (`adapters/llamacli.py`) — an allowlisted subprocess. Program
resolved from `("/usr/bin", "/bin")` only, never `PATH`, never a configured
path; a group- or world-writable binary is refused. The model is a *file name*
resolved against a fixed pair of trusted directories, refused when loose-moded
— the arrangement the speech runtime uses for recogniser models. argv is an
array built in the adapter; nothing from a provider, a model or a request is
ever a program name or a flag. The environment is a fixed allowlist.
Termination escalates terminate → kill on a watchdog that polls in 0.1 s steps
so it never outlives a fast generation, and the exit status is reaped on every
path including a raise out of `emit`. It declares **no** structured-output
support, which is what routes structured work to the server adapters instead of
failing at the subprocess.

Absence is a structured result, never an exception and never a silent skip: an
uninstalled runtime probes to `available: false` with the reason, so "not
installed" is distinguishable from "does not support this request" — the first
is fixed with `dnf install`, the second with a policy change.

---

## 7. Remote provider adapters

Three, implemented, and dark by default: `openai-compat`, `anthropic`,
`gemini`. Each refuses a configuration that is not both `remote: true` and
`enabled: true` before any socket, and refuses a generation with no resolved
credential as `authentication`.

**Remote adapters never probe the network.** A model-list request carrying the
key is still a transfer of the key, and §8 puts approval before any remote
transfer. So their availability rung is *configured + credential present*,
verified by the registry through `credential_status`, and their first network
contact is an approved generation. The model listing they return is empty and
says why.

Per-adapter notes recorded in their own docstrings: Anthropic's Messages API has
no seed parameter, so determinism is not claimed for it, and no
`response_format`, so structured requests there rest on instruction-following
plus the local validation that always runs; Gemini's `responseSchema` is a
weaker OpenAPI-style subset, converted by dropping `additionalProperties`, with
local validation as the real check, and its model id is validated against
`^[A-Za-z0-9._-]+$` before becoming part of a request path — "a request-line
injection wearing a configuration field".

**No remote provider was dispatched to in any run reported here.** §23 step 19
is NOT_RUN; see §24.

---

## 8. Credential design

`companion/agents/credentials.py`. A resolved credential is a `Secret`: `repr`
and `str` are `<secret>`, `to_json` raises, it is unhashable so it cannot be a
dictionary key, equality returns `NotImplemented` so no code can branch on the
value, and the only read is `reveal()` — named so a grep finds every use. It is
resolved at the moment of dispatch, used for one adapter call, and dropped;
`AgentWorker._run` clears its reference in a `finally`.

Sources: an explicitly named environment variable (named, never enumerated —
there is no environment dump anywhere in this package); a private file; and the
desktop Secret Service through `secretstorage` where installed, which reports
unavailable rather than succeeding when it is not.

A credential file is refused when it is a **symlink** ("the link's author, not
the file's, would choose the secret"), **group- or world-accessible**,
**owned by someone else**, **outside the approved directories**, relative,
empty, oversized, or not a regular file. `lstat` comes first so a symlink is
refused before anything follows it.

Reported presence, never value: `CredentialStatus` has no value field.
`tests/companion/test_agents_security.py` plants a sentinel in the environment
and asserts it appears nowhere in `providers_list`, `providers_status`,
`provider_health`, `providers_explain` or `task_provider_status`, and that no
refusal message quotes file contents.

Configuration refuses credential-shaped content in any string field, using the
same `companion.privacy.scrub_text` the runtime uses — a key pasted where a
reference belongs is a key on disk in the wrong mode.

---

## 9. Context builder

`companion/agents/context.py`, one builder, used by every path.
`CONTEXT_SOURCES` is a closed eight-value set: user request, task history,
current plan, capabilities, reviewer observations, tool results, conversation
summary, system policy. §7's exclusion list is enforced by there being **no
value** for a credential, raw audio, a screen capture, a file, another session,
hidden reasoning or an approval record — an item claiming to be one is refused
at construction rather than filtered by a reviewer who has to remember the list.

Every item records source, classification, audience, size, redactions and
digest (`ContextItem.manifest`). The assembled messages' digest is carried on
the request and re-verified there, so a request whose messages were altered
after building is not representable.

Data is framed as data: history, plan, tool results and observations are wrapped
in `[data:<source>]` fences, and the system policy is the only text claiming
instruction status. That does not make prompt injection impossible; it makes the
runtime's authority not rest on the model obeying, which is what makes the §20
injection tests meaningful.

**Oversized context is refused, not trimmed.** Per-item and total bounds, plus
an estimated-token check against the provider's window, each raising
`ContextOverflow` with the measured size. The refusal is the feature: the items
a "drop the oldest" rule sheds first are the policy and the privacy preamble.

---

## 10. Provider selection

`companion/agents/registry.py`. A derivation, not a ranking: no score, no
weights, no tie-break a reader cannot reproduce from the configuration file.

1. **Local before remote**, categorically — a different act, not a better one.
2. **User preference** within a category: the request's explicit preference,
   then the `userPreferred` configuration flag.
3. **Configuration file order** as the final tie-break.

Eligibility gathers **all** reasons, never the first: task class, structured
output, tool proposals, streaming, image and audio input, privacy ceiling,
locality, offline requirement, context capacity, output bound, cost class
against the ceiling, language, and each rung of the standing ladder with its
detail. `SelectionExplanation` keeps the ineligible list **even on success**, so
"why that one" is always answerable, and names the decisive factors, the
fallback order, and the approvals the choice would require.

The §10 ladder falls out of the same order: preferred eligible local →
alternative eligible local → approved remote → blocked with the explanation.
`ProviderBackedExecutor._generate` walks the ladder and filters the fallback to
**local providers only**; when every one fails it raises `CapabilityRefused`
carrying each provider's failure. There is no path from "local failed" to a
remote dispatch, and a failure after approval does not authorise a different
destination — `RemoteProviderExecutor.result` fails the task rather than
falling back anywhere.

**The gap this phase found and closed.** The capability router settles
permission for remote only after finding local impossible, and it decides that
from *hardware*. A machine with ample memory and no model installed answered
"local execution satisfies every requirement" — so every configured remote
provider was unreachable, with "the router did not permit remote execution" as
the recorded reason: true of the code, false of the policy. Three changes close
it, none of which grants anything (`companion/capability_bridge.py`,
`companion/agents/capability.py`):

* the companion re-asks the router when no local executor can serve the task,
  supplying the one fact the probes cannot see, so the router settles remote
  permission properly instead of never being asked;
* a route refused **only** because it needs consent is read as a destination on
  the table rather than one denied — which is what `requires_user_approval` and
  its `disclosure` exist for, and what puts the question in front of the gate
  §8 says owns it;
* configured remote providers become router declarations, so the router has a
  destination to name. Retention and training use are configuration facts;
  undeclared stays undeclared and the router fails it closed.

The blocked-reason order changed with it, and had to: leading with the router
pushed "the synthesiser is not installed" past the three reasons the error
summary keeps, replacing the actionable sentence with one that is true and
useless.

---

## 11. Remote approval binding

Remote execution reaches `_settle_approvals` unchanged, which derives
`remote_dispatch` (+ `send_sensitive_data` at ≥ personal, + `paid_provider` for
a paid class) from *declarations*, never from the executor's own say-so.

`RemoteProviderExecutor.destination_declaration(task)` supplies the §8 binding
material — provider, adapter, model, endpoint identity, data classes,
approximate context bucket, cost ceiling, tool names (empty: no remote tool
proposals in this build), policy reference — and the runtime now feeds a
non-local executor's declaration into `destination_fingerprint` when the
executor can produce one (duck-typed, like the consent extras; an executor
without the method falls back to the route's coarse identity). Any change to
any of those fields changes the fingerprint, and `ApprovalGate.resolve` refuses
the stale approval as `ApprovalMismatch`.

Rejected by the existing gate, now with the finer fingerprint behind it:
changed provider, model, endpoint, enlarged context bucket, new data
classification, increased cost ceiling, added tool, superseded plan, replayed
approval.

**Planning transmits nothing.** A remote executor's plan is produced
deterministically on-device with zero operations; the approval binds to *that*
plan; the first byte leaves the machine in `result()`, after the grant. The
worker re-checks at the last layer: a remote provider with no
`remote_approval_reference` on the request is refused there even if every layer
above misbehaved, and `test_agents_security.py` asserts the adapter was never
reached.

A second attempt carries its revision into the plan summary and therefore into
the fingerprint — a second dispatch to somebody else's computer is a second act
and gets its own approval, rather than being refused as a replay of the first.

---

## 12. Streaming

`companion/agents/stream.py`. Eight event kinds — `generation_started`,
`output_delta`, `structured_delta`, `tool_proposal`, `usage_update`,
`generation_completed`, `generation_cancelled`, `generation_failed` — each
carrying the provider's identity and a strictly incrementing sequence.

`StreamAssembler` enforces the whole contract in one place so an adapter cannot
honour half of it: monotonic sequence with no duplicate, gap or regression; a
`generation_started` first and once; no event after a terminal; bounded delta
size; bounded total output; bounded event count; a rolling one-second rate
bound; and a refusal of unpaired surrogates — the shape a byte-sliced decode
produces when somebody skips the incremental decoder. Adapters draw events from
a `StreamEventFactory` bound to their request, so they never mint sequences or
read a clock; backpressure is structural, because adapters emit on the worker
thread through the assembler.

UTF-8 correctness is established in `wire.py`, which decodes network chunks with
an incremental decoder so a code point split across chunks reassembles.

Provisional versus final is a type distinction: `provisional_text()` for
display, `finalize()` — which requires a terminal event and re-digests
everything received — for the only value the runtime may treat as a result.
Malformed partial structured output can therefore be displayed and can never be
presented as final, because the final path runs through validation first.

---

## 13. Structured output

`companion/agents/structured.py`. Two decisions carry it.

**Schemas are named, never transported.** A request carries a *reference* into
a table of schemas this build owns; there is no path by which a provider — or
anything downstream of one — supplies a schema object. `schema_for` on an
unknown reference raises. This is §20's "untrusted model descriptor" closed at
the type.

**Validation never coerces.** A string where an integer belongs is a refusal;
an unknown field is a refusal (every schema closes with
`additionalProperties: false`); a string carrying ESC or C0 control bytes is a
refusal, because the next reader may be a terminal. Bounds on depth, item
count, string length and total size. The validator is a deliberate JSON Schema
subset with a private `identifier` keyword, and it compiles no pattern from a
schema.

Repair is bounded to one round, asks the *model* again with the failure named,
and never edits output into validity. The original invalid output survives as a
digest; two failures raise `MalformedOutput` naming both digests. The repair
generation carries `purpose="repair"`, so the record shows it happened.

---

## 14. Tool mediation

Providers propose; the runtime decides. A proposal validated against the plan
schema becomes a `PlannedOperation`, and from there the path is the pre-existing
one: `requirements_for` derives approvals from tool *declarations*;
`_execute_plan` re-reads the persisted task, skips completed operation keys,
refuses unknown ones, checks tool-call, event, deadline and cost ceilings, and
calls `ToolBroker.invoke(..., caller="runtime")`, which validates the allowlist
and the classification ceiling and returns a sanitized `ToolOutcome`.

A proposal naming a tool outside the request's permitted set is **refused, not
filtered** — `MalformedOutput`, because a provider proposing an unpermitted tool
is a fact about that generation the record should carry. Providers never receive
a filesystem, subprocess, browser or desktop handle: the `TaskContext` they see
has nowhere to put one.

§14's loop limits: the coordination policy's existing maximum tool calls, review
rounds, events, elapsed time and cost, plus a new refusal in the bridge — an
operation name that has already failed twice for this task may not be proposed
again (`CoordinationLimitExceeded`, limit `repeated-failed-proposal`). Context
growth is bounded by the context builder's refusal; output by the assembler's;
cost by the ledger's pre-flight check.

---

## 15. Executor and reviewer rules

**Executor** (`ProviderBackedExecutor`): may plan, may generate results, may
propose tools, may respond to reviewer observations, and owns no direct tool
authority — it holds no broker, no store and no task.

**Reviewer** (`ProviderBackedReviewer`): observation-only, local-only, fed the
reviewer-projected context the coordination layer already builds (ceiling
`internal`, content above it arriving as a withheld marker). Its output passes
through `observation_from_json`, which refuses attribution to another reviewer.
It cannot propose executable tools — its schema has no operations — cannot
resolve approvals, cannot replace the executor, and cannot reach another
reviewer. A reviewer that cannot review returns nothing; it is never fatal.
`ToolBroker.invoke` still raises `ReviewerViolation` for a `reviewer:` caller,
which remains the enforcing wall.

A reviewer whose only eligible provider is remote reviews with nobody rather
than transmitting to review.

Material disagreement is recorded by the existing mechanism:
`ReviewObservation.material` (severity high or blocking) becomes a
`reviewer_disagreement` event.

---

## 16. Cost accounting

`companion/agents/usage.py`. Every figure carries its `basis` — `measured`,
`reported` or `estimated` — and the three never merge. `spent_units` is the
conservative reading, `max(reported, estimated)`, so a ceiling check errs toward
protecting the wallet. Tracked: input and output units with the provider's own
unit name, cached units, tool rounds, generation duration, provider-reported
cost, locally estimated cost, currency and reported currency amount kept
separately from cost units, and a pricing-reference timestamp field.

Ceilings are enforced **before** a generation starts (`UsageLedger.check_budget`,
raising `GenerationBudgetExceeded`, converted by the bridge to
`CoordinationLimitExceeded`), because a ceiling noticed afterwards has already
been spent through. Zero means nothing may be spent — the `CostPolicy` meaning —
so a metered provider against a zero ceiling is refused by the router before the
companion is even consulted.

---

## 17. Health and circuit breaking

`companion/agents/health.py`. Nine named failure kinds — connection,
authentication, rate limit, timeout, invalid response, malformed output,
cancellation failure, context limit, model unavailable — because a failure that
cannot be named cannot be counted, and one that is not counted keeps a paid
provider being retried.

Three states with two deliberate asymmetries:

* **Authentication failures do not close on a timer.** A wrong key at 09:00 is a
  wrong key at 09:05, and a breaker half-opening every thirty seconds turns one
  misconfiguration into a login-attempt pattern the provider's own abuse systems
  will notice. The circuit opens for fifteen minutes and is marked
  `requiresIntervention`; the status surface says the credential is the fix.
* **Rate limiting opens on the first failure**, honouring a retry hint bounded
  at five minutes. One 429 is the provider saying stop; counting to a threshold
  first would be continuing after being told to stop.

Half-open admits exactly one probe: its success closes, its failure re-opens the
full window. Everything is driven by the caller's monotonic clock; the module
never reads time.

---

## 18. Cancellation

A latch the worker owns and the adapter watches, plus closing the transport
under the reader — for HTTP adapters the wire session closes the connection, for
the subprocess adapter the watchdog escalates terminate → kill and reaps.

| case | behaviour |
|---|---|
| before the request starts | refused at dispatch; the adapter is never called |
| while queued | the queued job settles cancelled; no adapter call |
| during connection | the wire error is read as cancellation when the signal is set, not as a connection failure |
| during streaming | the stream closes, deltas so far are provisional history only |
| during structured output | same, and nothing malformed reaches validation |
| after a tool proposal | proposals stop; the runtime's lifecycle re-check refuses the operation |
| while approval is pending | the existing gate withdraws with `cancelled-with-task` |
| provider ignores cancellation | the outcome still settles and the worker survives — asserted in `test_agents_security.py` |
| runtime restarts mid-generation | §19 |
| client disconnects | the task worker owns the generation, not the client |

Cancellation releases the executor lease (existing `finally` in `run_task`),
records the outcome, and reaps child processes where local providers use them.

---

## 19. Recovery

`companion/agents/journal.py`. A start is recorded before any dispatch; a
settlement after every outcome. `reconcile()` runs at service construction,
**before the worker thread exists**, and turns every unsettled start into an
explicit `interrupted-not-repeated` record. Nothing is re-enqueued: an
interrupted paid generation quietly retried is money spent without a decision.

After a restart: an interrupted generation is not assumed complete and not
repeated; no old remote approval is replayed (the approval store expires
everything from a previous run, because expiry is measured on a monotonic clock
that did not survive); no pending tool proposal executes automatically;
confirmed tool results are preserved by the existing operation ledger; a new
lifecycle decision is required, which the canonical runtime's own recovery
makes; local-provider children are reconciled by the adapter's `close()`; and
abandoned streams are closed with their connections.

The journal holds request ids, provider ids, purposes and dispositions — never
message content — so even its loss costs accounting, never privacy. Mode 0600.

---

## 20. Protocol operations

Eight, added to the one `OPERATIONS` table and derived into
`PROVIDER_OPERATIONS`, so the schema a client is checked against and the schema
the service serves are one table read twice:

`providers_list`, `providers_status`, `providers_explain`, `provider_models`,
`provider_health`, `provider_test_local`, `task_provider_status`,
`task_provider_cancel`.

None mutates provider configuration; none takes an endpoint; none returns a
credential in any form. `test_agents_authority.py` asserts no parameter name
contains a credential, key, secret, token, endpoint or URL term.
`provider_test_local` is the strongest operation on the surface and refuses a
remote provider by construction — a "test" that transmitted context to a paid
endpoint would be a remote dispatch wearing a diagnostic's name.

Provider configuration is a file the user edits (`<root>/agents/providers.json`),
read at service start, validated strictly, never written by any operation.
A file that exists but cannot be accepted is an error, not a silent fallback to
defaults.

The gateway answers with the subsystem-absent shape when no agent runtime was
built, exactly as voice and speech do:
`{available: false, operation, reason, taskAffected: false}`.

---

## 21. UX integration

`companion/gtk_shell.py`. The view model reads two protocol documents —
`providers_status` and `task_provider_status` — and builds one line from them:
selected provider, local or remote, streaming state, cost, and degradation
(any provider whose circuit is not closed). The label uses `set_text`
throughout; `_draw_provider` contains no `set_markup`, asserted from source in
the security suite, so a model that emits markup emits words.

The remote indicator has two strengths, and the stronger one is driven by
`remoteActive`, which the service derives from the worker's live state rather
than the window's guess. The weaker one — "Remote provider X selected — nothing
is sent before your approval" — appears when a remote provider is selected,
which is **before dispatch** by construction: the worker refuses a remote
request with no approval reference, so the indicator cannot lag the transfer.

Approval requirement, tool proposal and result all surface through the existing
presentation projection, unchanged.

---

## 22. Security results

`tests/companion/test_agents_security.py` — 44 tests, one per §20 attack family,
each asserting the refusal at the layer that owns it.

| attack | refused by | how |
|---|---|---|
| prompt injection overriding policy | context fencing + bridge | policy is the only instruction text; a non-permitted tool proposal is `MalformedOutput` |
| unauthorized tool | bridge, then broker | refused at the proposal; broker refuses again and records it |
| changed tool arguments | operation key | different arguments are a different key, and therefore a different act with its own approval path |
| arbitrary command | `llamacli` resolution | program allowlist + trusted directories; model ids may not carry separators |
| markup injection | GTK layer | `set_text`, never `set_markup` |
| terminal escape sequences | structured validator + bridge | refused in structured output; stripped from plain text before it becomes an output |
| credential leakage | `Secret` + descriptor shape | sentinel absent from all five protocol responses; `to_json` raises |
| cross-session context leakage | closed source set | no context source names another session; the digest binds the messages |
| secret data sent remotely | executor + worker | no granted approval → `ApprovalInvalidated`; no approval reference → `authentication`, adapter never reached |
| changed remote endpoint | destination fingerprint | endpoint change changes the fingerprint; the gate refuses |
| approval replay | `ApprovalGate.consumed` | `ApprovalReplayed`, fingerprinted declaration included |
| cost-ceiling bypass | ledger, pre-flight | `GenerationBudgetExceeded` before any adapter request |
| oversized context | context builder | `ContextOverflow`, refused not trimmed |
| oversized output | assembler, through the worker | `malformed-output` |
| malformed stream | assembler | `malformed-output`, adapter cancelled |
| duplicate stream sequence | assembler | `StreamViolation` |
| invalid structured output | validator | one bounded repair, then `MalformedOutput` naming both digests |
| tool-loop exhaustion | bridge | `CoordinationLimitExceeded`, `repeated-failed-proposal` |
| provider cancellation refusal | worker | outcome settles, worker survives, next generation served |
| local endpoint SSRF | `HttpTarget` + wire | plain http is loopback-only; a 302 is refused and the Location never fetched |
| untrusted model descriptor | `schema_for` + adapters | unknown reference raises; configured model beats a hostile discovered id |
| symlink credential file | credential resolver | refused through the registry, `CredentialRefused` |

Two findings the suite raised were fixed rather than documented: terminal escape
bytes survived the plain-text result path (`display_summary` scrubs credential
shapes, not control bytes) and are now stripped in `agent_bridge._printable`;
and `supports_structured_output` was inferred from a hard-coded list of adapter
ids, so adapters now declare it.

Two were recorded and left, with reasons: the absolute `MAX_CONTEXT_BYTES` check
is unreachable through `ContextBuilder.build` because eight items at the
per-item bound cannot exceed it — redundancy, failing closed, not a hole; and a
discovered model id is bounded in length but free in content, with the
downstream walls (GTK `set_text`, Gemini's regex, llama-cli's separator refusal)
holding and a configured id always winning.

---

## 23. Stress-gate results

*(filled from `qualification/companion-agent-providers/evidence/gate-verdicts.json`)*

---

## 24. Installed vertical-slice result

*(filled from `qualification/companion-agent-providers/evidence/slice.json`)*

---

## 25. Measurements

*(filled from `qualification/companion-agent-providers/evidence/agent-measurements.json`)*

---

## 26. Complete test results

*(filled)*

---

## 27. Known limitations

*(filled)*

---

## 28. NOT_RUN items

*(filled)*

---

## 29. Remaining desktop-action work

*(filled)*

---

## 30. Reproducibility implications

*(filled)*
