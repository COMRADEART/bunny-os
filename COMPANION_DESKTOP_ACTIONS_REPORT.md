# Bunny Companion Desktop Action Broker

The first phase in which the companion causes something to happen on a person's
desk. Everything before it produced information — text, speech, a transcript, a
drawn character, a provider's proposal. This produces **effects**, and an effect
on somebody's desktop cannot be taken back by deleting a record.

This report states what was built, what was measured, and what was not. Where
something was not run it is listed as NOT_RUN with the reason, not omitted.

---

## 1. Starting and final SHAs

| | |
|---|---|
| Base branch | `feature/companion-agent-providers` |
| Starting commit | `ef0c9572262acd8bd48b74ff7234573ac0b78d55` (verified head of the base branch) |
| Working branch | `feature/companion-desktop-actions` |
| Gate commit | `d0442fb2d4ca4ae7ec306c5bf22dda3abaff113c` (all 170 gate iterations record it) |
| Evidence commit | *(filled by the evidence commit)* |
| Final SHA | *(filled at closure)* |

Preflight, before the branch was created:

1. the full SHA of `ef0c957` was resolved and matched the branch head;
2. the working tree was clean;
3. the agent-provider post-gate range `3f07a6e..ef0c957` was analysed and
   reports **0 installed, 1 context-only, 12 unreachable** — the collector
   script, and the report with its eleven evidence files;
4. the corrected build-input-closure analyzer was run, and its installer audit
   reports that `install-root.py` installs only what
   `build/scripts/install_routes.py` models;
5. no prior evidence tree was touched. `qualification/companion-linux/`,
   `companion-voice/`, `companion-voice-closure/`, `companion-speech-input/` and
   `companion-agent-providers/` are untouched by every commit on this branch;
6. no completed source branch was modified.

**Discarded gate runs are named in §22**, because a reader counting gate
invocations should arrive at the same number this report does.

---

## 2. Branch lineage

```
feature/companion-runtime-core
  → feature/companion-runtime-integration
  → feature/companion-character-renderer
  → feature/companion-linux-validation
  → fix/companion-pause-approval-consistency
  → feature/companion-voice-runtime
  → fix/companion-voice-closure
  → feature/companion-speech-input
  → feature/companion-agent-providers        ef0c957
  → feature/companion-desktop-actions        (this phase)
```

---

## 3. Build-input impact

**This branch is build-affecting**, and says so before anything else because the
previous phase's report records what happens when that question is answered by
inspection rather than by the analyser.

`companion/` is installed wholesale by the `companion-package` route
(`copy_python_package`, `*.py` only, excluding `tests`/`testing`/`__pycache__`),
so every module added here lands under
`/usr/lib/bunny-os/python/companion/desktop/`.

The analyser over `ef0c957..24ce040` — the whole branch up to the gate commit:

```
examined 64 path(s): 41 installed, 13 context-only, 10 unreachable
BUILD-AFFECTING: YES
profiles affected: beta, desktop, developer, live, minimal, recovery, shell, shell-test
```

By route:

| route | paths |
|---|---|
| `companion-package` | 36 |
| `bunny-os-python` | 2 |
| `capability-package` | 1 |
| `companion-service-executable` | 1 |
| `schemas` | 1 |

Thirteen context-only: the four `scripts/ops/` collectors written for this phase
and nine development scripts whose `sys.path` idiom was corrected (§*What
validation found*). None is installed by any route; the Containerfile deletes
`/tmp/bunny-os` before committing, so they are *probably* absent from the
artifact — and "probably" is not the standard, which is why they are reported
as context-only rather than as unreachable.

Ten unreachable: this report, the preserved-evidence record and the eight test
files.

The non-obvious entries:

* `capability/apply/approval.py` — six approval classes added to
  `SENSITIVE_ACTIONS`. Installed by the `capability-package` route. It is the
  designed extension point: membership of that set is what makes an unanswered
  question mean *denial*, and a desktop effect is exactly the kind of act that
  must not happen because nobody was at the machine to object;
* `schemas/companion-protocol.schema.json` — six operation names, installed by
  the `schemas` tree route;
* `companion/tools.py`, `companion/approvals.py`, `companion/runtime.py`,
  `companion/service.py`, `companion/cancellation.py`, `companion/protocol.py` —
  the integration points, all installed;
* eleven scripts and tools carrying the corrected `sys.path` idiom. Three of
  them are installed — `services/bunny-companion/bunny_companion_service.py` by
  `companion-service-executable`, and the two `bunny_os` CLI modules by
  `bunny-os-python` — and the eight measurement scripts are not.

No non-`.py` asset is added to `companion/`, so no new `tree` route is needed,
no route table entry changed, and no generated file was introduced. The
*shape* of the install set is unchanged; what changed is its contents.

**This branch is build-affecting and this report does not attempt to argue
otherwise.** The analyser is run and quoted rather than the question being
settled by inspection, which is the discipline
`build/scripts/build-input-closure.py`'s own docstring exists to enforce.

---

## 4. Broker architecture

```text
provider tool proposal
  → canonical PlannedOperation            companion.executor
  → ToolBroker allowlist + declaration     companion.tools
  → approval derivation and binding        companion.approvals + companion.desktop.binding
  → user approval                          canonical ApprovalGate, unchanged
  → DesktopActionRequest                   companion.desktop.request
  → DesktopActionBroker                    companion.desktop.broker
  → one typed adapter                      companion.desktop.adapters.*
  → DesktopActionResult                    companion.desktop.result
  → canonical task event                   companion.runtime
```

**The package holds no task authority.** Nothing under `companion/desktop/`
imports the runtime, the store, the task model, the approval gate, the executors
or the tool broker. Every authority fact arrives as a *value* on a request that
has already been validated. The one seam is `companion/desktop_bridge.py`, which
lives outside the package for the same reason `companion/capability_bridge.py`
and `companion/agent_bridge.py` do: "this subsystem holds no task authority"
stays checkable by reading one directory.
`tests/companion/test_desktop_authority.py::ImportGraph` asserts it from the
import graph.

**Exactly one invocation owns an attempt.** `DesktopActionBroker._inflight` is
keyed by idempotency key and claimed before anything else happens, so two threads
proposing the same act produce one attempt and one refusal. That is stronger
than the ledger alone: the ledger is durable and therefore slow, and two threads
can both read "not started" from it.

**The broker cannot resolve an approval.** It has no approval store, no consent
source and no way to grant anything. It is handed the act that *was* approved
and compares the act about to happen against it.

Module map:

| module | what it is |
|---|---|
| `catalogue.py` | the nine actions, §6's descriptors, the seven-word standing ladder |
| `parameters.py` | the closed parameter schemas and the one normalisation |
| `uris.py` | the scheme allowlist and URI normalisation |
| `paths.py` | path references, approved roots, symlink resolution |
| `entries.py` | desktop-entry resolution and field-code validation |
| `request.py` | §3's versioned request |
| `binding.py` | §8's fourteen fields and the comparison |
| `idempotency.py` | §9's derived key, states and per-action retry semantics |
| `result.py` | §12's seven states and the observation that justifies each |
| `environment.py` | §16's probes and the four postures |
| `ledger.py` | §20's durable operation ledger |
| `undo.py` | §11's classification and what would reverse an entry |
| `broker.py` | the one place an attempt is owned |
| `service.py` | §21's six protocol operations |
| `adapters/` | one typed adapter per declared operation |
| `vertical_slice.py` | §22's thirty steps |

---

## 5. Action schemas

`DesktopActionRequest` carries every field §3 names: request, session, task,
lifecycle epoch, plan, operation, idempotency key, action type, structured
parameters, expected effect, target, privacy classification, approval class,
approval reference, creation timestamp, expiration, deadline, cancellation
token, reversibility, undo action, presentation summary, audit reference.

**It carries none of §3's forbidden fields, and cannot.** There is no field for a
shell command, an executable path, an argument vector, an environment variable,
a D-Bus destination, a raw provider string, a credential, a screen capture or an
unbounded path.
`test_desktop_authority.py::RequestSurface::test_the_request_has_nowhere_to_put_an_execution`
asserts that over the dataclass rather than over this paragraph.

Every per-action parameter schema sets `additionalProperties: false`, checked at
import by `companion/desktop/parameters.py::_check_tables` and again by
`test_desktop_schema.py::Schemas`. An undeclared parameter is **refused**, never
ignored: an ignored parameter is one a caller believes took effect, and the first
time one of them means "…and skip the confirmation" the silence becomes the
vulnerability.

Three time fields, and they are not redundant: `created_at` is wall time for a
person reading a history; `expires_at_monotonic` is when consent stops being
consent, on the monotonic clock because a wall-clock expiry can be extended by
changing a timezone; `deadline_monotonic` is when the attempt must have finished,
and is clamped below the expiry so an act cannot complete after the consent for
it ran out.

`to_record_json()` is what reaches the durable ledger: the parameters are
replaced by the binding digest, because a clipboard write's parameters *are* the
text and a URI's are the address with its query.

---

## 6. Action catalogue

Nine actions. The shortness is the design: every one can be shown to a person in
a sentence and refused without understanding the implementation.

| action | approval class | privacy ceiling | reversibility | verifiable |
|---|---|---|---|---|
| `desktop.notification.show` | `interrupt_user_work` | personal | irreversible | no |
| `desktop.application.launch` | `launch_application` | personal | irreversible | no |
| `desktop.application.present` | `interrupt_user_work` | internal | irreversible | no |
| `desktop.settings.open` | `open_settings_surface` | internal | irreversible | no |
| `desktop.audio.set-volume` | `change_device_state` | internal | **reversible** | **yes** |
| `desktop.notifications.set-do-not-disturb` | `change_device_state` | internal | **reversible** | **yes** |
| `desktop.clipboard.copy-text` | `write_clipboard` | sensitive | **compensatable** | **yes** |
| `desktop.uri.open` | `open_external_uri` | personal | irreversible | no |
| `desktop.file.reveal` | `reveal_file` | personal | irreversible | no |

`carries_task_data` is a separate field from the ceiling and the distinction was
forced by a failure. Four of these — a settings page, a window activation, a
volume, a do-not-disturb value — carry *nothing* of the task's, and gating them
on the task's classification meant a task marked `personal` could not open the
sound settings. The ceiling still applies, against the class of what the action
actually carries.

**§5's deferred list is present as data**, twenty-two entries in
`DEFERRED_ACTIONS`, each mapping to the sentence a caller gets. Asking for one
produces a typed refusal saying *this is deliberately not implemented* — a
different sentence from "unknown action", leading to a different place. Naming
them is what stops a later phase adding "type into the focused window" as an
obvious extension of a catalogue that never said it was closed.

§6's seven-word ladder — `declared`, `available`, `eligible`, `approved`,
`executing`, `completed`, `undone` — is `ACTION_STANDING`, and each rung is
answered by a different component. A declared action is not an available one.

---

## 7. Backend adapters

There are exactly **two transports** and both are closed.

**D-Bus.** `companion/desktop/adapters/dbus.py` holds a *table* of nine complete
calls in which the bus name, object path, interface, method and argument
signature are all fixed per entry. `SessionBus.call` takes a call *identifier*;
there is no parameter through which a caller could name a bus. One entry —
`portal.close_request` — takes an object path, because a portal request handle is
minted by the portal, and it is validated against the portal's request prefix
before use. The system bus is never opened; `BusType.SYSTEM` appears nowhere.

**Commands.** `companion/desktop/adapters/command.py` holds an eight-entry
executable allowlist on top of the runner `companion/voice/execution.py` already
provides — trusted directories rather than `PATH`, refusal of group- or
world-writable binaries, refusal of a substituted symlink, a built environment,
process groups, bounded stderr, always reaped. Copying that runner would have
produced a second implementation of the same rules, which is the failure
`build/scripts/install_routes.py` exists to prevent one layer up. What is *not*
shared is the allowlist. There is no shell on it, no `xdg-open`, no `env`, and —
the interesting absences — no `dbus-send`, `gdbus`, `busctl` or `qdbus`, any one
of which would undo the D-Bus table entirely.

The adapters:

| adapter | operation | mechanism |
|---|---|---|
| `NotificationAdapter` | show one notification | D-Bus `Notify`, or `notify-send` (recorded) |
| `ApplicationLaunchAdapter` | start one installed application | `Gio.DesktopAppInfo` |
| `ApplicationPresentAdapter` | raise a window, or say it cannot | `org.freedesktop.Application` activation |
| `SettingsAdapter` | open one allowlisted page; read/set do-not-disturb | `gnome-control-center` / `systemsettings`, `gsettings` |
| `AudioControlAdapter` | read and set volume and mute | `pactl` |
| `ClipboardAdapter` | take and release the selection | `wl-copy --foreground` / `xclip` |
| `UriOpenAdapter` | open one parsed URI | xdg-desktop-portal `OpenURI` |
| `FileRevealAdapter` | reveal one resolved path | `org.freedesktop.FileManager1` |
| `PortalAdapter` | the portal client the two openers use | xdg-desktop-portal |

`test_desktop_authority.py::AdapterSurface` asserts each adapter's public
surface against a written list, so a generic method added later fails a test
rather than passing review.

Three type-level defences do more work than any check:

* `UriOpenAdapter.open` takes a `ParsedUri`, which can only be produced by
  `parse_uri` — so there is no way to *construct the argument* for a
  `javascript:` URI;
* `FileRevealAdapter.reveal` takes a `ResolvedPath`, produced only after symlink
  resolution inside an approved root;
* `ApplicationLaunchAdapter.launch` takes a `DesktopEntry`, produced only by
  reading an installed file that passed every check in §19.

---

## 8. Approval binding

`ApprovalBinding` holds §8's fourteen fields. It is compared **field by field**
rather than by digest alone, at a deliberate cost: a digest answers "is this the
same act?" and nothing else, and when the answer is no a user is owed "the
address changed" rather than "the approval no longer matches".

**The binding rides on the machinery that already exists.** A desktop
requirement's `destination_declaration` *is* the binding material, so
`ApprovalGate.resolve` — unchanged — refuses a changed target, address, path,
clipboard digest, volume, parameter, classification, plan or epoch without
knowing what a desktop action is. There is no second approval system.

The twelve §8 conditions and where each is enforced:

| condition | where |
|---|---|
| target application changes | `ApprovalBinding.differences` |
| URI changes | binding, **and** re-parsed at execution against `request.target` |
| file path changes | binding, **and** re-resolved at execution against `request.target` |
| clipboard text digest changes | binding (the digest *is* the target) |
| volume value changes | binding (parameter comparison) |
| action type changes | binding |
| new parameter appears | binding |
| privacy classification increases | binding, one-directional |
| plan superseded | binding, plus the gate's own plan check |
| lifecycle epoch changes | binding |
| approval replayed | `DesktopActionBroker.consumed`, plus the gate's own |
| action already completed | the ledger |

The URI and path are checked **twice**, and the second check is the one that
matters: the two are separated by however long a person takes to answer, and a
symlink can be re-pointed inside that window.
`test_desktop_security.py::test_a_path_repointed_after_approval_is_refused_at_execution`
drives exactly that.

The privacy rule is one-directional: an approval survives the classification
going *down* and never up. A user who agreed to disclose personal text has, in
substance, agreed to the lesser disclosure; the reverse is a consent bypass.

`off_device` was added to `ApprovalRequirement` during Linux validation, because
the coarse locality a surface renders was being *inferred* and the inference was
wrong for every action here. See *What validation found*, item 6.

---

## 9. Idempotency model

`action_key` digests §9's six facts — task, lifecycle epoch, plan, operation,
action type, normalised parameters — as canonical JSON of the whole tuple. Not
joined with a separator: `companion/ids.py` records what went wrong with the
separator form, where shifting the delimiter across a field boundary produced
identical material for two different acts.

The plan **revision** is deliberately absent, for the reason
`companion.ids.operation_key` records: with it, every replan produces fresh keys
and the skip branch is unreachable. The lifecycle **epoch** is deliberately
present: a task paused and resumed is being attempted again by a person who
watched the first attempt not finish.

Seven states: `not-started`, `started`, `completed`, `failed`, `cancelled`,
`unknown`, `undone`. `undone` is separate from `completed` because an undone
action *did* happen.

Per-action retry semantics, as §9 asks, are `RETRY_POLICIES` — data, not prose:

| action | duplicate safe | reconcilable |
|---|---|---|
| notification | yes | no |
| application launch | no | yes (activation state) |
| application present | yes | yes |
| settings open | yes | yes |
| volume | no | yes (read-back) |
| do-not-disturb | no | yes (read-back) |
| clipboard | no | yes (ownership) |
| **URI open** | **no** | **no** |
| file reveal | yes | yes |

None of these is a licence to retry automatically. The policy shapes the
*question* a user is asked; §20 requires a new decision, and the broker never
acts on one by itself.

---

## 10. Cancellation behaviour

`cancelled` is a **callable** the broker re-reads at each checkpoint, not a flag
captured at entry: a stop can arrive from another process — `bunny-os companion
task cancel` — while a backend call is in flight.

| §10's point | behaviour |
|---|---|
| before approval | refused, no ledger entry, effect prevented |
| after approval, before execution | refused before dispatch, effect prevented |
| during backend connection | `GioCancellable` aborts the call |
| during a portal request | `Request.Close`; the portal's answer is reported, not assumed |
| during application launch | checkpoint after entry resolution |
| during notification dispatch | cancellable passed to `call_sync` |
| during URI opening | portal handle held so it can be closed |
| during volume update | checkpoint before `pactl` |
| during clipboard ownership | the child is killed, ownership released, **effect prevented verified** |
| immediately after backend success | clipboard released and verified; others record the effect honestly |
| while result persistence fails | the ledger write precedes the effect, so a failure prevents it |

**A cancellation that could not prevent the effect records `unknown`, not
`cancelled`.** That is the load-bearing line: a stop that arrived after the
backend had accepted leaves the same uncertainty a crash does, and §10 forbids
claiming a rollback nobody verified.
`test_desktop_broker.py::test_a_cancellation_that_could_not_prevent_the_effect_records_unknown`
drives it.

A task cancellation stops every attempt of that task and drops this broker's
spent-approval entries for it, ordered *before* the canonical withdrawal in
`companion/cancellation.py` — withdrawing an approval while a call is still
running would leave the act to finish under consent that had just been taken
back.

---

## 11. Undo framework

Four classifications, and the middle one is not a softer first:
`reversible`, `compensatable`, `irreversible`, `unknown`.

* **volume** — reversible. The previous value was read before the change and is
  in the ledger; the undo is a new action of the same type with its own
  approval, its own key and its own entry;
* **do-not-disturb** — reversible, same shape;
* **clipboard** — *compensatable only*. Releasing ownership stops the text being
  pastable; it does not restore what was there, because nobody read it. The
  descriptor's limitations say so in a sentence a user can read;
* **notification, launch, URI, settings page, present, reveal** — irreversible.
  §11's explicit warning is honoured: *do not silently kill an application as
  "undo launch"*. `undo_plan_for` returns "an application that was started stays
  started. Closing it is not an undo — it is a separate act that could discard
  work you have done since."

**An undo is offered only when the previous state was actually read.** An action
*declared* reversible whose previous value could not be read has no undo in
practice, and offering one would produce a button that fails when pressed.
`_undo_availability` computes it rather than copying the descriptor.

**An uncertain action is never undone.** Undoing an act that may not have
happened is itself an act: setting a volume "back" to a value it may never have
left is a change the user did not ask for.

The one undo that needs no new approval is the clipboard compensation, because
it *withdraws* a disclosure the user already approved. Asking permission to stop
disclosing would leave a cancelled task holding somebody's clipboard until they
clicked something.

---

## 12. Observation confidence

Seven result states. The rule is enforced at construction:
`DesktopActionResult` **refuses to be built as `confirmed` without an
observation that verified something**, so no code path can report an
acknowledgement as a confirmation.

| state | means |
|---|---|
| `confirmed` | something was read back and matched |
| `accepted-not-confirmed` | the backend took the request; the *normal* outcome for six of the nine |
| `refused` | the broker declined, always a policy decision |
| `failed` | the backend was reached and did not do it |
| `cancelled` | a stop arrived; carries whether the effect was prevented |
| `unknown` | begun, nothing settled it; never repeated automatically |
| `unsupported` | this environment cannot do it |

Five observation kinds — `acknowledgement`, `read-back`, `ownership`, `error`,
`none` — and only `read-back` and `ownership` can justify a confident result.
`matched` is tri-state through `None`, because an acknowledgement compares
nothing and recording it as `False` would read as a mismatch: "we did not check"
and "we checked and it was wrong" are different facts.

Three actions can reach `confirmed`, and each was exercised on a real desk:

* **volume** — `pactl get-sink-volume` after the change, compared at
  whole-percent resolution (the descriptor says so, because `pactl` itself
  rounds);
* **do-not-disturb** — `gsettings get` after the change;
* **clipboard** — the child holding the selection is alive after the compositor
  has had a moment to take the offer. **Nothing is read**: not the contents, not
  the previous contents, not the offered MIME types. The check is on a process we
  started, using a handle we hold.

A notification daemon returning an id is `accepted-not-confirmed` and always
will be. So is a portal accepting a URI, a file manager accepting a reveal, and
Gio launching an entry.

---

## 13. Privacy boundaries

Enforced by absence wherever absence was possible.

| §13 requirement | how |
|---|---|
| no screen capture | no code can produce one; `desktop.screen.capture` is a named deferral |
| no application-content inspection | no adapter reads a window |
| no clipboard reading | the clipboard adapter has no read path; a test greps for one |
| no browser-history reading | nothing touches a browser profile; `.mozilla` is a forbidden path component |
| no accessibility-tree scraping | no AT-SPI client exists |
| no microphone or camera | not in this package |
| no credential retrieval | `.ssh`, `.gnupg`, `.pki`, `.password-store`, `.aws`, `.config` and eleven more are refused path components |
| no cross-session disclosure | the binding carries the session and the task |
| no unrelated process inspection | the only `/proc` read is of *our own* children, by name, for the leak counters |

Clipboard text goes down **stdin**, never into an argv: an argv is readable in
`/proc` by every process the user runs, and this is the one adapter whose
argument would be the user's own material.

A diagnostic record holds the action id, digests, bounded target metadata, the
result and the timing — §13's permitted list and nothing outside it.
`ParsedUri.display` strips the query, because a query can carry a token and a log
line outlives one. `path_digest` exists so a record can compare paths without
holding one: `/home/x/divorce/draft.odt` discloses something whether or not
anybody opens it. A refusal about a changed clipboard digest names neither the
old text nor the new.

---

## 14. Provider isolation

`tests/companion/test_desktop_authority.py::ImportGraph::test_no_agent_module_can_reach_the_desktop`
walks the AST of every module under `companion/agents/` and asserts that none
imports `companion.desktop`, `companion.desktop_bridge`, `companion.tools`,
`gi.repository`, `dbus`, `pydbus`, `gtk` or `Xlib`.

A provider cannot:

* **call a desktop adapter** — it cannot import one;
* **select an executable** — `PlannedOperation` names a tool from an allowlist,
  and no desktop schema has a field for a program;
* **set a URI outside the schema** — `parse_uri` refuses every scheme but four,
  and the adapter takes a `ParsedUri`;
* **bypass approval** — a desktop tool declares `requires_context=True` and
  `ToolBroker.invoke` refuses it without the authority facts, which only the
  runtime supplies;
* **change an approved parameter** — the executed act is the *same object* the
  question was built from, cached under the plan fingerprint;
* **retry an uncertain action itself** — an executor's plan reaches the ledger,
  which refuses a key in `unknown`.

The last one is worth stating precisely. An executor *can* propose the same
operation again; what it cannot do is have it performed. The refusal is recorded
and handed back as a fact it may plan around.

---

## 15. ToolBroker integration

§15's ten steps, and where each happens:

1. **validate action availability** — at execution, from the environment report;
2. **validate task permission** — the classification ceiling, in `normalise`;
3. **validate structured parameters** — the closed schema, same place;
4. **recheck lifecycle epoch** — on the request, compared in the binding;
5. **derive approval requirements** — `DesktopSupport.requirement_for`;
6. **bind exact target and data disclosure** — the requirement's
   `destination_declaration` is the binding material;
7. **obtain or validate approval** — the canonical gate, unchanged;
8. **invoke the desktop broker** — with the very `PreparedAction` the question
   was built from;
9. **record the result** — the runtime's own `operation_completed`/`operation_failed`;
10. **return a sanitized result** — `DesktopActionResult.to_tool_json()`.

`ToolDeclaration` gained `requires_context`. A tool that declares it and is
called without the authority facts is **refused**, so a caller that forgot
produces a refusal rather than an unauthorised act.

`to_tool_json()` is six fields: action id, state, confidence, succeeded,
explanation, undo available. No backend object, file descriptor, socket or portal
handle — because `AdapterOutcome` and `DesktopActionResult` have nowhere to put
one, which `test_desktop_authority.py` asserts over the dataclass fields.

`requirements_for` gained a `refine` hook. It **replaces** the generic
requirements for an operation with a stricter one and can never produce zero: a
refiner that returns `None` or raises changes nothing, and the generic path is
what a failure falls back to.

---

## 16. Capability integration

`probe_environment` asks the *service*, never the filesystem:

* the notification daemon is asked whether it **owns its bus name**, not whether
  `notify-send` exists;
* the portal is asked for the **version of its OpenURI interface**;
* the mixer is asked for `pactl info`, which fails when no sound server is
  running however installed `pactl` is;
* the clipboard is decided from which **compositor socket** is in the
  environment and then from whether the matching helper exists — in that order,
  because a Wayland session with only `xclip` has no clipboard this build can
  take;
* the file manager is asked for ownership *and* for activatability, because a
  file manager that will start on demand is available.

The four postures:

| posture | meaning |
|---|---|
| `desktop-actions-available` | a graphical session and every service |
| `limited-desktop-actions` | a graphical session and some; the report says which are missing and why, per action |
| `notification-only` | no graphical session and a working notification path |
| `headless-no-desktop-actions` | nothing |

**Reduced interruption is a preference, not a capability**, and is kept separate.
A user who asked for fewer interruptions has not made notifications impossible;
they have made an unrequested one a bad idea. The report carries the preference
and it applies to the *approval*.

`env.json` in the evidence records what was installed and what was answering as
two different maps, so a later reader cannot draw the inference §16 forbids.

---

## 17. Headless behaviour

| §17 requirement | behaviour |
|---|---|
| notifications may degrade to canonical text events | the action reports `unsupported` with the environment's sentence, and the typed result reaches the task's event stream |
| application launch unavailable | yes, by name |
| settings-page opening unavailable | yes, by name |
| clipboard unavailable | yes, by name |
| URI opening needs an explicit headless policy, disabled by default | `BrokerOptions.headless_uri_policy`, off; `ServiceOptions.desktop_headless_uri_policy`, off |
| audio may remain available with a valid user audio session | yes — audio is one of two actions not gated on a display, and is available exactly when `pactl info` answers |

**Availability is enforced at execution, not at preparation**, and that ordering
was corrected during this phase. Refusing at preparation turned a headless
machine into a *planning* failure: the run had no request to bind, no prompt to
render and no typed result to record, so the honest sentence §17 asks for never
reached the task's history.

The whole Windows development machine is a headless run, and the vertical slice
passes there with 18 of 30 steps NOT_RUN and every authority step green.

---

## 18. UX integration

The approval prompt is built from the same `PreparedAction` the act is executed
from. `to_prompt_json()` carries: the action, the sentence, the exact target, the
target kind, what is disclosed, the expected visible effect, the classification,
the reversibility, whether an undo will be available and what it would do, the
approval class, the **exact normalized parameters**, the resource impact and the
known limitations.

§18's examples, produced verbatim by `normalise`:

```text
Open Firefox                                          → "Open GNOME Settings"
Copy 84 characters of internal text to the clipboard  → produced exactly
Set speaker volume from 35% to 50%                    → "Set RDPSink volume from 100% to 50%"
Open https://example.com/docs                         → produced exactly
Reveal ~/Documents/report.pdf                         → produced exactly
```

`test_desktop_schema.py::Presentation::test_no_presentation_is_a_vague_label`
asserts no presentation contains "task action" and none is shorter than ten
characters.

Two corrections came out of running this against a real desk, both in §20.

---

## 19. Protocol operations

Six, and what is absent is the point:

| operation | mutating | what it does |
|---|---|---|
| `desktop_actions_list` | no | every declared action, its descriptor, its standing, plus §5's deferred list |
| `desktop_actions_status` | no | posture, counters, ledger summary, and what still needs a decision |
| `desktop_action_explain` | no | one descriptor, its availability reason, its retry policy, its schema |
| `desktop_action_cancel` | yes | stop an attempt in flight and say what that prevented |
| `desktop_action_undo` | yes | the undo *plan*; performs only the compensation |
| `desktop_action_history` | no | the ledger, bounded |

There is **no operation that performs an action**. Causing a desktop effect needs
a task, a plan and an approval. An operation taking an action id and a parameter
object would be a generic tool invocation with a narrow name, walking past §2's
whole pipeline.

No parameter names an application, a path, a URI, a command, a bus destination or
a backend; `test_desktop_authority.py::ProtocolSurface` asserts that over the
parameter names. Undeclared parameters are refused by
`Operation.validate`. `DesktopActionService.boundaries()` states ten things this
surface cannot do and a test asserts every one is false.

`desktop_action_undo` returns a *plan* for a reversal rather than performing it:
§11 requires an undo to be a new typed action with its own lifecycle, and a
service that just did it would take that away.

---

## 20. Security results

§19's list, with the class that drives each. All in
`tests/companion/test_desktop_security.py` unless another file is named.

| §19 item | result | driven by |
|---|---|---|
| provider attempts arbitrary shell command | refused at the allowlist; no desktop module entered, ledger empty | `ProviderAttemptsExecution` |
| provider attempts arbitrary executable path | refused; six shapes including `/usr/bin/sh`, `../../usr/bin/sh`, `thing;rm` | `ProviderAttemptsExecution` |
| malicious desktop entry | refused: `sh -c`, five metacharacter forms, `Type=Link`, `Hidden`, `NoDisplay`, outside the roots, symlinked out | `MaliciousDesktopEntry` |
| desktop-entry field-code injection | `%z` and deprecated `%n` refused; **no expansion exists**, asserted over the source | `MaliciousDesktopEntry` |
| URI scheme injection | thirteen schemes refused, including four spellings of `javascript` | `UriInjection` |
| redirect destination change | binding refuses a changed address; opening is never `confirmed`, and the descriptor says why | `UriInjection` |
| file traversal | `..` inside a reference refused; a sibling with a shared prefix is not inside | `PathTraversal` |
| symlink path substitution | refused before the containment check, **and again at execution** | `PathTraversal` |
| clipboard credential copy | four credential shapes refused outright, not scrubbed | `ClipboardHandling` |
| clipboard oversized text | refused, not truncated | `ClipboardHandling` |
| markup injection | escaped unconditionally in title and body | `InjectionThroughText` |
| terminal escape injection | ESC refused by name; C0 and C1 refused | `InjectionThroughText` |
| arbitrary D-Bus destination | the table is closed; an undeclared call and an arbitrary object path both refused; no system bus | `DbusSurface` (authority) |
| changed action after approval | refused, naming the action | `ApprovalBindingChanges` |
| changed URI after approval | refused, naming the address | `UriInjection` |
| changed path after approval | refused at execution; nothing revealed | `PathTraversal` |
| changed clipboard digest after approval | refused; **neither text appears in the refusal** | `ClipboardHandling` |
| approval replay | refused; the adapter ran once | `ApprovalBindingChanges` |
| lifecycle-epoch mismatch | refused, naming the pause and resume | `ApprovalBindingChanges` |
| idempotency collision | two epochs give two keys; a separator cannot be shifted across a field | `IdempotencyAndDuplication` |
| duplicate action request | the recorded result is returned; the adapter ran once | `IdempotencyAndDuplication` |
| cancellation race | pre-dispatch prevents; post-ownership releases and verifies | `CancellationRaces` |
| portal callback after cancellation | the handle is closed and the portal's answer reported, not assumed | `CancellationRaces`, `test_desktop_broker.py::Cancellation` |
| result persistence failure | the ledger write precedes the adapter, so a failure prevents the effect | `ResultPersistence` |
| unknown effect recovery | reloads as `unknown`, not repeatable, warning surfaced | `ResultPersistence`, `test_desktop_broker.py::Recovery` |
| cross-session action | an approval for one task does not authorise another | `CrossSessionAndHeadless` |
| headless execution attempt | every visual action refused by name; the adapter never called | `CrossSessionAndHeadless` |

Additionally, and not on §19's list:

* a desktop tool called **without** the authority facts is refused, and with a
  foreign context is refused;
* a **reviewer** reaching a desktop tool raises `ReviewerViolation`;
* an **expired** approval is refused and the adapter is never called;
* an **unapproved** request does nothing — "no response means no action";
* a URI carrying **credentials in its authority** is refused rather than
  stripped, because stripping would open a different URI from the one proposed;
* a `mailto:` carrying an **`attach` parameter** is refused: opening a composer
  is approved here and disclosing a file is not;
* the clipboard adapter is greped for every read primitive and has none.

**151 tests** across the four desktop files. All pass on Windows and on Linux.

---

## 21. Recovery behaviour

The ledger entry reaches disk in state `started` **before** the adapter is
called. A process that dies in between leaves a `started` entry from a run that
is over, and `OperationLedger.load` turns exactly those into `unknown` — never
into `failed`, never into "retry me".

A **run identifier** is what makes "from a previous run" answerable. An entry in
`started` bearing *this* run's id is genuinely in flight; one bearing another
run's id is the wreckage of a crash. Without it the two are indistinguishable and
a concurrent attempt would be reclassified while it was still running.

| §20 requirement | behaviour |
|---|---|
| do not repeat incomplete actions | `unknown` is refused by `_authorise`; the caller gets a typed result |
| load the operation ledger | at broker construction |
| classify only when observation supports it | `unknown` stays `unknown` across a second restart |
| do not reuse prior approvals | the ledger holds no approval; `CompanionApprovalStore.load` expires everything from a previous run |
| do not automatically issue undo | `undo_plan_for` returns `none` for `unknown` |
| clear stale portal handles | a handle belongs to a connection that did not survive; the in-process half is `release_all` |
| release temporary clipboard ownership | a selection belongs to a process; the in-process half is `release_all` |
| preserve completed results | `completed` and `undone` are left exactly as they were |
| require a new decision for uncertain actions | `status()["pendingDecisions"]` names each with its retry policy's sentence |

---

## 22. Stress gates

All three on one commit, `d0442fb2d4ca4ae7ec306c5bf22dda3abaff113c`, recorded by
every iteration and asserted before gate 2 ran: the runner reads the commit out
of gate 1's and gate 3's own reports and refuses if either differs from the tree
it is about to clone.

**The collector was corrected after the gates ran, and the correction re-derives
the verdicts from the raw reports — which are unchanged.** Summing only the
positive per-iteration deltas failed a clean suite gate on a fixture thread that
was merely *exiting* when a snapshot happened to be taken: +1 in one iteration,
−1 in the next, and a positives-only sum calls that growth. The verdict is now
taken on the net, both halves are reported, and a four-iteration measurement
confirms the thread is flat from iteration 2 onward. The JSON the harness wrote
is the evidence; `gate-verdicts.json` summarises it.

**The desk is asserted before the gates run.** The runner refuses unless the
posture is `desktop-actions-available` with all nine actions, because a gate
that measured the refusal path while the report claimed a desk would be worse
than one that did not run: the numbers would look like evidence.

| gate | runs | result | longest consecutive |
|---|---|---|---|
| desktop-broker lifecycles | 100 | **100/100** | 100 |
| complete companion suites | 50 | *(filled)* | *(filled)* |
| installed desktop-action slices | 20 | **20/20** | 20 |

Recorded per iteration, §23's list. "net" means summed across iterations 2..N,
positives and negatives together.

| column | gate 1 | gate 3 |
|---|---|---|
| thread delta | net 0 | net 0 |
| file-descriptor delta | +4 on iteration 1; net 0 after (3 gained, 3 released) | +7 on iteration 1; net 0 after |
| portal-handle delta | net 0 | net 0 |
| D-Bus connection delta | net 0 | net 0 |
| clipboard-owner delta | net 0 | net 0 |
| child processes | +1 on iteration 1; net 0 after (3 gained, 3 released) | net 0 |
| zombies | net 0 (3 gained, 3 released) | net 0 |
| pending-action count | 0 every iteration | 0 every iteration |
| prepared-action count | 0 every iteration | 0 every iteration |
| approval count | reported, never failed on | reported, never failed on |
| operation-ledger consistency | **true every iteration** | **true every iteration** |
| temporary-file delta | net 0 | net 0 |
| duration (min / median / p95 / max) | 0.219 / 0.222 / 0.224 / 0.531 s | 1.000 / 1.061 / 1.100 / 1.257 s |
| exit status | 0 | 0 |

The three gained-and-released triples in gate 1 are the same event seen three
times: a settings program that had exited but not yet been reaped when a
snapshot was taken, collected by the next iteration's spawn. It is the window
`DetachedChildren.reap` closes, it is bounded by one iteration, and it is the
reason the verdict is taken on the net — the positives-only sum would have
called it a leak of three descriptors, three children and three zombies.

**Iteration 1 is measured and does not fail a gate.** A broker's first run opens
a session-bus connection and maps the GObject typelib; the second reuses both.
Summing all hundred would count a one-off cost a hundred times and fail a clean
gate; subtracting it silently would hide a real leak of the same size. So it is
reported under `firstIterationWarmUp` and the growth that fails is summed from
iteration 2 — where a genuine leak of one descriptor per run still totals
ninety-nine.

RSS since baseline is flat: 26.8 MB after a hundred lifecycles, 62.9 MB after
twenty slices, both reached in the first iteration.

**Which user each gate ran as, and why.** Gates 1 and 3 ran as root, because
that is the user WSLg gives the session to — the compositor socket, the session
bus, the notification daemon, the portal and the mixer all belong to it. Gate 2
ran as `bunny`, because root ignores the permission bits a read-only directory
carries and
`test_store_durability.PermanentFailureTests.test_a_read_only_directory_fails_before_any_replacement`
asserts an `OSError` that cannot occur as root. Excluding it would have meant
the gate was not running the *complete* suite, which is what §23 asks for. The
suite needs no desk, so nothing is lost. The same test passes as `bunny` and the
whole companion suite passes there.

**Discarded runs, named so the count matches.** Five gate runs were started
before the one reported here. Every one of them was stopped for a reason that
would have made its numbers describe something other than this build.

| # | commit | what it reached | why it was discarded |
|---|---|---|---|
| A | `256a1da` | gate 1 reported **0/100** | the stress harness was importing `/usr/lib/bunny-os/python` — an installed build from an earlier phase — rather than the checkout |
| B | `0095bd2` | gates 1 and 3 passed 100/100 and 20/20; gate 2 failed at iteration 1 | the unit had no compositor or audio variables, so gate 3 measured `limited-desktop-actions` and the volume steps — the reversible action the completion standard requires be *verified and undone* — recorded NOT_RUN. Gate 2 failed on a root-only assertion. **The desk assertion in this runner exists because of this run** |
| C | `0095bd2` | gate 2 alone, as `bunny`, 2/50 | stopped once the root-only failure was understood and the whole set could be re-run together |
| D | `cda73ea` | gates 1 and 3 passed 100/100 and 20/20; gate 2 reached 9/50 | a review of the source found `clearAfterSeconds` accepted by the schema, carried through normalisation, digested into the binding, shown in the approval prompt — and releasing nothing. Gates 1 and 3 were re-run rather than carried forward: §23 asks for one commit, and a parameter that had been a promise in a prompt is not a fix a gate can be excused from |
| E | `24ce040` | gates 1 and 3 passed 100/100 and 20/20 | the unprivileged clone the suite gate runs from was silently at the *wrong commit*. See *What validation found*, item 9 |
| F | `24ce040` | gates 1 and 3 passed 100/100 and 20/20; gate 2 reached 2/50 | a review of the settings adapter found it opening a GUI program under a two-second timeout on a runner that *terminates* a child which outlives one. The page would open and the user would see it flash. Item 10 |

A reader counting invocations should find **six runs of gate 1, six of gate 3,
and six starts of gate 2** before this one — and none of the six reached a
verdict.

Three of those six were stopped by *reading the source* rather than by a failure
(D, F, and the preservation test that ended C). A gate that runs a suite missing
one of its tests, or a broker missing one of its behaviours, has measured
something other than the thing — and each of the three found something a passing
gate had been hiding.

---

## 23. Installed vertical-slice result

Thirty steps against a real `CompanionService` over its socket, on a real
Wayland desk, twenty consecutive times under gate 3.

**29 PASS, 1 NOT_RUN, 0 FAIL** on every one of the twenty iterations, with
posture `desktop-actions-available` throughout.

Genuine effects, on a real desktop:

* a **notification** dispatched through `org.freedesktop.Notifications` and
  reported `accepted-not-confirmed` — the daemon returned an id, which proves
  acceptance and not display;
* **GNOME Settings launched** through `Gio.DesktopAppInfo`, the exact
  application id displayed in the approval, and the coarse locality shown as
  `local`;
* the **output volume changed from 100% to 50% and verified by read-back**,
  reported `confirmed`;
* the **volume undone** — a *new* action with its own approval, its own key and
  its own ledger entry — back to 100%, verified, reported `confirmed`, and the
  original entry moved to `undone`;
* the **clipboard taken** by a `wl-copy --foreground` child this build owns and
  can release, reported `confirmed` on ownership, with nothing read;
* a **second clipboard request cancelled** before it was answered, and no second
  selection taken;
* an **arbitrary-command proposal refused at the allowlist** before any desktop
  module was entered;
* the **broker restarted** and five completed actions found still completed, with
  none repeatable.

The one NOT_RUN is step 3: no local agent provider is installed on this host. The
proposals come from a canonical local executor instead, which exercises the
identical pipeline. §22's requirement is that no paid provider or network
connection is needed, and none is.

Every task in the slice reaches `completed`. That is asserted per step, and it
had to be: an earlier run had every desktop task reaching `blocked` after doing
exactly what it was asked to do, and reading only the operation value made it
look like a pass. See *What validation found*, below.

---

## 24. Measurements

### Memory

Each figure taken in a **fresh interpreter**, median of three, because a
measurement made after something else has imported is a measurement of the
import order.

| | RSS | PSS |
|---|---|---|
| interpreter baseline | 11.09 MB | 6.26 MB |
| **desktop broker, idle, nine adapters probed** | **40.86 MB** | **26.11 MB** |
| the broker's own cost over baseline | 29.77 MB | 19.85 MB |
| companion stack **with** the desktop broker | 49.81 MB | 34.40 MB |
| companion stack **without** it | 35.59 MB | 26.12 MB |
| **the desktop broker's share of the stack** | **14.22 MB** | **8.28 MB** |

The broker's cost measured alone (29.77 MB) is larger than its share of the
stack (14.22 MB) because the stack has already paid for most of what it imports.
Both are reported; neither on its own is the answer.

Per adapter, constructed and probed alone, median of two:

| adapter | RSS | PSS |
|---|---|---|
| `NotificationAdapter` | 39.25 MB | 24.60 MB |
| `FileRevealAdapter` | 34.68 MB | 20.51 MB |
| `UriOpenAdapter` | 32.13 MB | 19.23 MB |
| `PortalAdapter` | 32.00 MB | 19.19 MB |
| `ApplicationLaunchAdapter` | 31.85 MB | 19.45 MB |
| `ApplicationPresentAdapter` | 31.79 MB | 19.46 MB |
| `AudioControlAdapter` | 25.37 MB | 16.79 MB |
| `ClipboardAdapter` | 25.09 MB | 16.70 MB |
| `SettingsAdapter` | 25.08 MB | 16.69 MB |

**These are not additive.** The six above 30 MB are the ones that touch
PyGObject; the three below it do not. The sum of the nine is far larger than the
set of nine, because they share a session-bus connection and the GObject typelib.

**A launched application's memory is not counted anywhere here.** GNOME Settings
is a separate process this build started and does not own; counting it against
the broker would make the broker look like it costs what GNOME Settings costs.

### Latency

From the twenty gate-3 slice iterations, in seconds:

| measurement | min | median | p95 | max | n |
|---|---|---|---|---|---|
| approval-to-dispatch | 0.0006 | 0.0009 | 0.0014 | 0.0022 | 20 |
| volume read-back | 0.0043 | 0.0055 | 0.0059 | 0.0082 | 20 |
| application launch | 0.0251 | 0.0475 | 0.0497 | 0.0498 | 20 |
| undo (volume, end to end) | 0.1481 | 0.1542 | 0.1585 | 0.1601 | 20 |
| broker restart (ledger reopened) | 0.0001 | 0.0001 | 0.0003 | 0.0003 | 20 |
| whole slice | 0.9904 | 1.0375 | 1.0773 | 1.1685 | 20 |

Per task, submission to a terminal state, in seconds:

| task | min | median | p95 | max |
|---|---|---|---|---|
| notification | 0.0474 | 0.0708 | 0.0749 | 0.0925 |
| application launch | 0.0504 | 0.0727 | 0.0769 | 0.0770 |
| volume change | 0.0955 | 0.1213 | 0.1273 | 0.1278 |
| volume undo | 0.1381 | 0.1422 | 0.1459 | 0.1461 |
| clipboard copy | 0.2220 | 0.2272 | 0.2314 | 0.2360 |
| clipboard, cancelled | 0.0362 | 0.0480 | 0.0611 | 0.0618 |
| arbitrary-command proposal, refused | 0.0614 | 0.0685 | 0.0967 | 0.0974 |

The clipboard is the slowest and it is supposed to be: 150 ms of it is the
settle window `BackgroundChild` waits before deciding the compositor has taken
the offer. Shortening it would trade a real observation for a faster number.

*(Per-action dispatch latencies from `desktop-latency.py` are filled at closure.)*

---

## 25. Complete test results

All at the gate commit `d0442fb` unless noted.

| run | result |
|---|---|
| whole repository, Linux, as `bunny` | **4037 tests, OK**, 8 skipped |
| whole repository, Linux, as root | 4037 tests, **1 failure**, 5 skipped |
| whole repository, Windows (at the branch head) | 4020 tests, **2 failures**, 77 skipped |
| companion suite, Linux, as `bunny` | **1507 tests, OK** |
| companion suite, Windows | **1507 tests, OK**, 41 skipped |
| desktop files alone, Windows | **158 tests, OK**, 4 skipped |

The three failures outside the clean run are all environmental and all verified
as such:

* **as root**,
  `test_store_durability.PermanentFailureTests.test_a_read_only_directory_fails_before_any_replacement`
  asserts an `OSError` from writing into a read-only directory. Root ignores the
  permission bits, so the error cannot occur. It passes as `bunny` on the same
  host, same commit;
* **on Windows**, `test_evidence_gate` needs symlink privileges and
  `test_repository_validation` needs a shell validator. Both fail identically at
  the base commit `ef0c957`, verified against a worktree at that commit. Both
  pass on Linux.

New in this phase, 156 tests in five files:

| file | tests | what it asserts |
|---|---|---|
| `test_desktop_authority.py` | 25 | §1 and §14's boundaries, from the import graph and the dataclass fields |
| `test_desktop_schema.py` | 36 | §3, §4, §5, §6, §9 and §12 — the tables, and that they agree |
| `test_desktop_security.py` | 57 | §19's list, one class per group |
| `test_desktop_broker.py` | 33 | §10, §11, §12, §16, §17, §20 and §15, including six through a real runtime |
| `test_desktop_preservation.py` | 5 | the five prior phases' evidence, byte for byte |

Existing suites touched:

* `test_protocol_ipc.py` — the operation enumeration and the schema file gained
  six names. The test that enumerates operations is written as a *literal* so
  that adding one is a deliberate edit, and it was;
* `test_recovery_cancellation.py` — two stand-ins for `ToolBroker.invoke` now
  take `**extra`, because the runtime passes the desktop invocation context. A
  fixed signature there would have been testing the signature rather than the
  cancellation.

**A defect the tests found and the source had to answer**, rather than the other
way round: `Path.parts` versus `PurePosixPath(str(path)).parts` in the
forbidden-directory check. The latter splits on `/` only, so on a backslash
platform the whole path is one part and the check silently matched nothing —
while its test went on passing, because the test ran on Linux.

---

## What validation found

Ten defects. Seven were found by running the thing; three were found by reading
the source *because* a run had made the reader suspicious. Listed because the
list is the argument for having done both — and because three of them were
sitting under a gate that was passing.

**1. A gate that measured the wrong tree.** `companion_stress.py` inserted each
of its two candidate paths at the front of `sys.path` only if it was not already
there. With `PYTHONPATH` pointing at the checkout, the checkout was skipped as
already-present and the installed tree went in ahead of it. A hundred iterations
reported `ModuleNotFoundError` — which is the *lucky* outcome. Had the installed
tree contained the module, the gate would have reported a hundred clean passes
for code nobody had changed.

**2. The same idiom in eleven more files.** Two measurement scripts, four GTK
probes, the companion service, and the two CLI modules all carry it, and any of
them being imported by a test process rearranged that process's import path.
The full Linux suite reported thirty-one loader errors for modules the installed
tree — a build from an earlier phase — has never heard of. The block now runs
only when the package it exists to make importable is not importable yet, so a
standalone invocation is unchanged and a process that already works is left
alone.

**3. A whole run of tasks that blocked after succeeding.** Every desktop task in
the slice reached `blocked`, and the recorded reason named the approval: *has
already authorised this step of this plan*. The replay guard was right. The
executor was not — the reviewer asked for a revision and the slice executor
re-proposed the operation it had just performed, producing identical operations,
an identical fingerprint and therefore the same approval transition. `TaskContext`
hands an executor `completed_operation_keys`, `unknown_operation_keys` and the
previous round's `operation_results` precisely so that cannot happen, and the
first version of that executor read none of them. **Nothing in the runtime
changed.**

**4. Steps that asserted an action worked without asserting its task finished.**
Which is how (3) went unnoticed for a whole run. Four steps now check both.

**5. A sixty-second stall in every slice iteration.** The run that proposes
`shell.run` waited the full approval timeout for a question the allowlist had
already made impossible. The wait now ends when the task settles, which is what
an approval centre does with a finished task. An iteration went from 61 seconds
to under one.

**6. A settings page presented as somewhere else.** `ApprovalGate.build`
inferred the coarse locality a surface renders from whether the requirement's
destination was the literal word `local`. That is right for a provider, whose
destination string *is* a provider id, and wrong for every desktop action:
opening the sound settings was shown to the user as **remote**. The requirement
now states it.

**7. A message that misattributed a cause.** The settings probe told a GNOME
session with no `gnome-control-center` that this build has no mapping for GNOME.
It has one; the program was missing. Two absences with two remedies had one
sentence, and the sentence sent a reader to the wrong file.

**8. A check that silently stopped checking on one platform.** The
forbidden-directory test used `PurePosixPath(str(path)).parts`, which splits on
`/` only — so on a backslash platform the whole path was one component and
`.ssh` matched nothing. Its test went on passing, because the test ran on Linux.

**9. The unprivileged gate ran a tree from another phase.** Gate 2 runs from a
clone owned by `bunny`, made with `git clone` followed by
`checkout --detach <sha>`. The commit lives on a *remote-tracking* ref in the
source repository, and `git clone` copies `refs/heads/*` only — so the clone
never had the object, the checkout printed an error that `--quiet` swallowed,
and the clone stayed at whatever HEAD the source repository happened to be on.
A fifty-run suite gate was measuring a commit from an earlier phase. It is now a
named branch, a single-branch clone of it, and the clone's HEAD **asserted**
against the gate commit rather than reported.

Found by reading the log line `clone at:` and noticing it was empty — the same
line that was meant to be the reassurance.

**10. A settings window opened and then killed two seconds later.**
`SettingsAdapter.open_page` ran `gnome-control-center` through the command
runner with a two-second timeout — and that runner *terminates* a child which
outlives its timeout. Right for `pactl`; wrong for anything with a window. The
page would open and the user would see it flash.

The gate had been passing throughout, which is why this needed reading rather
than running: `gnome-control-center` is single-instance, so every invocation
after the first exits immediately and never reaches the timeout. The *first*
one would have been killed.

Settings programs are started detached now and never signalled. What is still
owed to them is reaping — a child that exits and is never waited for is a zombie
for as long as this process lives, and §23 counts zombies. A window still open
when the broker stops stays open, because it is the user's window and closing it
would be a second act nobody approved.

**And one that was not a defect in the code at all.** Two `companion_stress.py`
processes from stopped gate runs were still alive, competing for CPU with the
run being measured. `su` starts a new session, so a child of it escapes the
unit's cgroup when the unit is stopped. Every timing figure taken while they ran
is discarded; the ones in §22 and §24 are from a run started after the machine
was confirmed idle.

Two more were design decisions the run forced rather than defects:
availability moved from preparation to execution (§17), and `carries_task_data`
was separated from the privacy ceiling (§6).

---

## 26. Known limitations

Ordered by how likely each is to matter.

1. **Six of nine actions can never be `confirmed`.** A notification daemon
   returning an id, a portal accepting a URI, a file manager accepting a reveal
   and Gio launching an entry are all acknowledgements. This is a property of
   the desktop, not of this build, and the honest word is in the result rather
   than in a footnote.
2. **A redirect is outside the approval.** The binding holds the normalised
   address that was handed over. A handler that follows a redirect has gone
   somewhere nobody approved, and this build has no way to know. Stated in the
   descriptor's limitations; the reason URI opening is never `confirmed`.
3. **`desktop.application.present` is unsupported for most applications.** Only
   entries declaring `DBusActivatable` can be raised, and even then the
   compositor may decline. See §29.
4. **Settings pages and file reveals are per-desktop.** The catalogue knows
   GNOME and KDE. An unrecognised desktop gets `UNSUPPORTED` by name.
5. **Clipboard verification is ownership, not content.** §13 forbids reading the
   clipboard, so "the text you asked for is what a paste will produce" is not
   something this build checks. What it checks is that a process it started
   holds the selection.
6. **Do-not-disturb is GNOME-only.** It is read and written through GSettings;
   KDE keeps it somewhere this build does not read, and says so.
7. **The clipboard selection dies with the process.** A selection belongs to a
   living process, so a companion restart drops it. That is correct — nothing
   claims otherwise — but a user who copied something through the companion and
   then restarted it has lost the clipboard.
8. **`windowIdentity` is accepted and unused.** No mechanism this build has can
   address a specific window. Recorded on the result rather than silently
   dropped.
9. **An executor that does not respond to review reaches a replay refusal.**
   The replay guard is right and the executor is wrong, but the recorded reason
   names the approval — "has already authorised this step of this plan" — rather
   than the executor. Found by this phase's own slice (§20 of the deliverables
   list); fixed in the slice, not in the runtime, because the runtime's
   behaviour is correct. A future phase could make the refusal name the cause.
10. **`notify-send` cannot be withdrawn.** It returns no id, so a cancellation
    after a notification sent that way cannot close it. The result says so.
11. **Per-adapter memory figures are not additive.** The adapters share a
    session-bus connection and the GObject typelib.
12. **The measurements are from one host.** A WSLg session on Fedora 44 is a
    real Wayland compositor with a real notification daemon, a real portal, a
    real file manager and a real mixer — and it is one machine. The latency
    figures are what this desk does.

---

## 27. NOT_RUN items

| item | why |
|---|---|
| a genuine local **agent provider** driving the slice's proposals | no local model runtime is installed on this host. The slice's proposals come from a canonical local executor, which exercises the identical pipeline — every refusal, binding check and ledger entry is the one an ordinary task produces. §22's requirement is that no paid provider or network connection is needed, and none is. Step 3 records the absence rather than omitting it |
| **reproducibility candidate** | deferred by §25 of the brief until functionality, Linux validation, gates and measurements are complete. See §30 |
| **release qualification** | not claimed and not attempted |
| **KDE** settings pages and do-not-disturb | no KDE session on this host; the mapping exists and is unexercised |
| **X11** clipboard path (`xclip`) | this host's session is Wayland, so `wl-copy` is the path taken. `xclip` is installed and the branch is unexercised |
| `desktop.application.present` **succeeding** | exercised only in its `UNSUPPORTED` direction against a non-activatable entry, and through activation of an activatable one. Whether a compositor *raised* a window is not observable from here in either case |
| **PSS** figures where `/proc/self/smaps_rollup` is unavailable | recorded as `NOT_RUN` per figure rather than substituted with RSS |
| the two repository-wide tests that need **symlink privileges** and a **shell validator** | fail on the Windows development machine at the base commit `ef0c957` as well; verified against a worktree at that commit. They pass on Linux |

---

## 28. Remaining browser-automation work

Nothing in this phase automates a browser and nothing here is a step towards it.
What exists is `desktop.uri.open`, which hands an address to whatever the user's
own configuration has registered for its scheme, through the portal, with the
handler chooser asked rather than silently defaulted.

What a later phase would have to build, and what each would cost:

* **navigation beyond opening a URI** needs a channel into a running browser —
  a WebDriver endpoint, a browser extension, or a CDP socket. Each is a
  general-purpose remote-control surface, and the whole difficulty is that none
  of them is bounded the way this catalogue is: a WebDriver session can do
  anything a user can. A bounded subset would have to be designed first, and
  "navigate to an approved URL in an approved tab" is the only member of it that
  is obviously safe;
* **form filling** needs page content, which needs reading the page, which §13
  forbids for good reason;
* **download acceptance** needs the browser's own download surface;
* **credential access** is excluded permanently rather than deferred.

The result state that would matter most is the one this phase already has:
opening a URI is never `confirmed`, because a redirect the handler follows has
gone somewhere nobody approved. Any browser work inherits that problem and makes
it larger.

---

## 29. Remaining compositor-integration work

`desktop.application.present` is the honest edge of what a compositor will do
today.

* **`org.freedesktop.Application.Activate`** works, and only for entries
  declaring `DBusActivatable`. An entry that does not gets `UNSUPPORTED` and no
  synthetic input, because there is no standard way to raise the window of an
  application that does not declare it;
* **XDG activation tokens** are the mechanism that would make this reliable: a
  compositor honours an activation carrying a token that proves a user asked.
  Obtaining one requires being the application the user interacted with, which
  the companion is not when a task raises somebody else's window. A future phase
  could obtain a token from the companion's own GTK surface and pass it, which
  would turn "the compositor may decline" into "the compositor will honour it";
* **window identity** is accepted by the schema and unused, because none of the
  mechanisms this build has can address a window. A compositor-specific protocol
  — `wlr-foreign-toplevel-management` or a GNOME Shell extension — could, and
  each is a per-compositor dependency this catalogue has so far avoided;
* **focus-stealing prevention is respected and never worked around.** That is a
  permanent decision, not a limitation.

`desktop.file.reveal` and `desktop.settings.open` both depend on a per-desktop
mapping; the catalogue knows GNOME and KDE and says so by name when it does not
know a desktop.

---

## 30. Reproducibility implications

**No reproducibility candidate was created and none is claimed.**

This branch is build-affecting: thirty-seven installed paths, all under
`companion/`, `capability/apply/approval.py` and `schemas/`. Every one is a
`.py` or a `.json` copied by an existing route, so the *shape* of the install set
is unchanged — no new route, no new destination, no generated file, no non-`.py`
asset. `install-root.py` continues to install only what
`build/scripts/install_routes.py` models, which the analyser's audit confirms.

What that means for the three-builder reproducibility result recorded at Commit C
`225a5e1` / Commit D `f65b65c`:

* the result **does not carry forward**, and this report does not claim it does.
  A byte-identical build is a statement about one commit;
* the *mechanism* is undisturbed. The reproducibility work turned on layer
  digests being stable given the same inputs, and adding source files to a
  package route that already exists changes the inputs without changing how they
  are copied;
* two facts recorded in earlier phases still apply and would have to be handled
  again by whoever runs the next candidate: `fedora-bootc:44` is rebuilt daily
  and old digests vanish, so a pinned base digest is not durable; and a hosted
  runner is not a fixed environment, since `ubuntu-24.04` changed podman
  4.9.3 → 5.8.4 between two runs an hour apart and changed a result;
* the evidence trees of every prior phase are untouched by this branch, so
  nothing recorded there has been invalidated by anything here.

A candidate for this phase would need the full three-builder run at a single
commit, and §25 of the brief explicitly defers it until functionality, Linux
validation, stress gates and measurements are complete — which is what this
report is.

---

## Completion standard

The brief's fifteen, and what each rests on.

| | criterion | evidence |
|---|---|---|
| 1 | providers can only propose typed operations | §14; `test_desktop_authority.py::ImportGraph` |
| 2 | ToolBroker remains the sole execution gateway | §15; slice steps 26–27, twenty times |
| 3 | desktop adapters expose no generic execution surface | §7; `AdapterSurface`, `DbusSurface`, `CommandSurface` |
| 4 | exact targets and data disclosure are approval-bound | §8; the requirement's declaration *is* the binding material |
| 5 | changed actions are rejected after approval | §8, §20; ten conditions, two of them checked twice |
| 6 | no arbitrary shell, D-Bus, keyboard or mouse control exists | §7, §13; asserted as an absence of code, not of permission |
| 7 | at least three genuine desktop actions execute successfully | §23; **four action types, five executions** — notification, application launch, volume (set and again to undo), clipboard |
| 8 | at least one reversible action is verified and undone | §23; volume 100% → 50% → 100%, both `confirmed` by read-back |
| 9 | cancellation prevents or accurately records side effects | §10; and a cancellation that could not prevent records `unknown` |
| 10 | incomplete actions are not repeated automatically | §21; `unknown` is refused, and a new decision is required |
| 11 | headless systems fail safely | §17; the whole Windows slice run is one |
| 12 | the 100/50/20 gates pass on one commit | §22 |
| 13 | Linux memory and latency are measured | §24 |
| 14 | the installed provider-driven slice passes | §23; 29/30 with one honest NOT_RUN |
| 15 | no release or reproducibility qualification is claimed | §30; stated, not implied |

---
