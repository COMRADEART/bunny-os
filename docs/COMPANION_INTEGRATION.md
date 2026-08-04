# The integrated Bunny Companion

This describes the companion after the headless runtime core and the GTK UX
prototype were reconciled into one thing. It is the document to read before
changing anything in `companion/`, because most of what follows is about which
component is *allowed* to make a given decision, and that is not visible from
any one file.

The short version:

```text
GTK window  →  local socket  →  CompanionRuntime  →  event stream  →  store
   (view)      (13 operations)    (every decision)     (the truth)   (durable)
```

Everything else here is the consequence of taking that arrow direction
seriously.

---

## 1. Canonical authorities

There is exactly one implementation of each of these, and
`tests/companion/test_integration_authority.py` reads the package with an AST
parser on every run to check that a second one has not appeared.

| Concern | Authority | Module |
| --- | --- | --- |
| Session identity and lifecycle | `CompanionSession` | `companion/session.py` |
| Task identity and lifecycle | `CompanionTask`, `TRANSITIONS` | `companion/task.py`, `companion/states.py` |
| Event identity, ordering, integrity, replay | `TaskEvent` | `companion/events.py` |
| Persistent history | `CompanionStore` | `companion/store.py` |
| Approval binding and validation | `ApprovalGate` over `CompanionApprovalStore` | `companion/approvals.py` |
| Executor ownership | `ExecutorLeases` | `companion/coordination.py` |
| Reviewer restriction | `ReviewContext`, `ToolBroker` | `companion/reviewer.py`, `companion/tools.py` |
| Cancellation | `cancel_task` | `companion/cancellation.py` |
| Recovery | `recover` | `companion/recovery.py` |
| Privacy classification | `DATA_CLASSES`, `AUDIENCE_CEILING` | `companion/privacy.py` |
| Cost limits | `CostPolicy`, `CoordinationPolicy` | `companion/session.py`, `companion/coordination.py` |
| Capability routing | `evaluate_task` over `capability.router` | `companion/capability_bridge.py` |
| CLI | `bunny-os companion` | `companion/cli.py` |
| **Presentation state** | `PresentationProjector` | `companion/presentation.py` |
| **Local IPC** | `CompanionProtocol` | `companion/protocol.py` |
| **Service lifetime** | `CompanionService` | `companion/service.py` |

The first thirteen came from `feature/companion-runtime-core` unchanged in
substance. The last three are new and are the integration itself.

## 2. What the donor branch contributed, and what it did not

`codex/companion-runtime-ux-shell` contained a second, complete companion
runtime: its own `runtime.py`, `events.py`, `store.py` (SQLite), `state.py`,
`model.py`, `approval.py` and `coordination.py`. **None of it was merged.** The
reconciliation is recorded file by file in
[`COMPANION_OVERLAP_MATRIX.md`](COMPANION_OVERLAP_MATRIX.md); the summary is
that every overlapping module was resolved in favour of runtime-core, and the
donor's contribution is the *shape* of the UX layer rather than any of its code
paths that own state.

What was carried across, rewritten against canonical contracts:

- the idea of a presentation state machine (rebuilt as a fold over canonical
  events, with §12's priority order);
- the local JSON-lines socket (rebuilt with a closed operation table, strict
  parameter validation and peer checks);
- the GTK 4 window (rebuilt against the projection; its logic separated into a
  GTK-free view model so it can be tested);
- the systemd user unit, the desktop entry and the launcher;
- the local system-voice adapter and the microphone activation rule;
- the static character, and the accessible description that replaces it.

## 3. The event → presentation projection

`companion/presentation.py` folds canonical events into a `PresentationState`.
It is a pure function: it reads events and returns a value. It cannot write, and
it imports no module that can — a test asserts that from the import graph.

**The §12 mapping.** Each event type maps to a phase (`EVENT_PHASES`), and the
generic `task_state_changed` maps through the canonical task state
(`TASK_STATE_PHASES`). Every event type and every task state is covered; a test
compares the tables against `companion.events.EVENT_TYPES` and
`companion.states.STATES`, so an event added to the runtime and not to the
projection fails the build rather than silently drawing nothing.

Two entries are decided by the payload, because one event type is emitted for
opposite outcomes: `capability_checked` (`eligible`) and `approval_resolved`
(`decision`). One entry is deliberately *not* what it looks like:
`operation_failed` maps to `working`, not `error`. A failed step is not a failed
task, and mapping it to `error` would pin the surface at the top of the priority
order while the executor carried on replanning around it.

**The §12 priority.** When several phases are true at once, `resolve_phase`
picks by `PHASE_PRIORITY`:

```text
error > blocked > waiting_for_approval > cancelling > cancelled > listening
      > speaking > working > reviewing > presenting_result > planning
      > understanding > recovering > paused > starting > success > idle
```

§12's nine-phase order appears in that as an unbroken subsequence, and a test
asserts it — so a phase added later cannot quietly reorder the part that was
specified. Priority resolves *concurrency*, not recency: an `operation_progress`
arriving after an `approval_requested` does not mean the question was answered.

**What the projection may contain** is the property list in §5, and the schema
`schemas/companion-presentation-state.schema.json` is the enforceable version of
it. What it may *not* contain is the interesting half: there is no field for
hidden reasoning, a credential, a provider token, a raw tool result, a screen
capture, a microphone sample or an arbitrary object. Adding one requires editing
that file, which is the point.

Every payload read goes through `TaskEvent.view("ui")`, whose ceiling is
`sensitive`. A `secret` task's contents arrive as a withheld marker and
`contentWithheld` is set, so a surface showing a redacted view says so rather
than looking complete.

## 4. The local protocol

A Unix domain socket at `$XDG_RUNTIME_DIR/bunny-companion/runtime.sock`, mode
0600, in a directory mode 0700, with the peer's user id checked through
`SO_PEERCRED`. One newline-terminated JSON object each way: at most 64 KiB in,
4 MiB out.

Thirteen operations, and no fourteenth:

```text
health              create_session   list_sessions   get_session
submit_task         list_tasks       get_task        get_events
get_presentation_state              resolve_approval
cancel_task         pause_task       resume_task
```

The handler is looked up in a table keyed by a name from that list — never by an
attribute name off the wire. Parameters are declared per operation and validated
strictly: **an undeclared parameter is refused, not ignored**, because an ignored
parameter is one the caller believes took effect. There is no pickle, no `eval`,
no import by name and no path that reaches a shell; a test walks the whole
package's syntax tree to check.

The audience is fixed at `ui` and is not a parameter. A protocol that let the
caller name its own audience would let a client ask for the `executor` ceiling —
privilege escalation by keyword argument.

**A developer fallback** exists for platforms with no `AF_UNIX`: loopback TCP on
an ephemeral port with a per-run token, compared in constant time.
`CompanionServer.describe()` names the transport in use, `BUNNY_COMPANION_REQUIRE_UNIX=1`
refuses it outright, and no measurement taken over it is reported as though it
were the shipped transport.

## 5. The service, the worker and consent

`CompanionService` owns one runtime and serves the socket. Requests are served
one per connection, so **closing the window cancels nothing** — there was never
anything attached to the socket to cancel.

Tasks run on a single worker thread. That is a deliberate limit, not an
oversight: two threads driving one `CompanionRuntime` would share its in-memory
session cache and its executor leases, and "probably fine under the GIL" is not
a property worth resting the record on. The consequence — a task parked on an
approval holds the worker — is listed under known limitations, and both
answering and cancelling free it without going through the worker.

`InteractiveConsent` is the seam through which a person's answer reaches the
runtime, and it is a narrow one. It returns `"granted"`, `"denied"` or `None`,
and that is the entire vocabulary; every exit other than an explicit grant means
*no*. There is no timeout branch that grants and no configuration that creates
one.

## 6. Approvals

The Approval Centre cannot bypass runtime validation because there are two
independent checks and it is on the wrong side of both.

**The gateway check** compares the client's claim — the binding it says it
displayed — against the `ApprovalRequest` the runtime recorded: task, plan,
transition, action, destination, provider, data classification, cost. Any
difference is `approval_mismatch`. Expiry is *bound* and is checked against the
runtime's own record rather than the client's copy, because a client-supplied
expiry is the one field an attacker would want to restate.

**The gate check** then compares the recorded `ApprovalReference` against the
plan that is actually about to run: transition, plan id, plan revision and
destination fingerprint, plus a per-run consumed set that catches a replay.

Both are needed. The first catches a client that altered what it showed; the
second catches a plan that changed after the person answered.

`ApprovalPresentation.binding()` returns exactly the fields an answer repeats.
The specific destination a person reads — a provider id, a hostname — is
`destinationDetail`, outside the binding, because it is a rendering and binding
a rendering would mean a change of wording could invalidate consent while a
change of provider might not.

## 7. Reviewers

Unchanged from runtime-core and enforced the same way: a reviewer is handed a
`ReviewContext` holding no store, no broker and no runtime, and `ToolBroker`
refuses any caller of kind `reviewer` outright. The window adds nothing: a
reviewer's card in the Approval Centre carries the line *"Reviewers observe
only: no tools, no approvals, no changes"* and has no buttons. Material
disagreement is a distinct field in the projection so a client does not have to
re-derive the threshold, and it stays visible after the executor revises around
it.

## 8. Persistence

The runtime-core append-only event store remains canonical. §8's evaluation:

| Dimension | Event store | Donor SQLite |
| --- | --- | --- |
| Integrity checking | per-event hash chain, verified on every full read | none; rows are trusted |
| Crash recovery | truncated final record dropped and reported; nothing invented | WAL rollback, but no way to detect a partial *logical* write |
| Event replay | the stream is the source; projections rebuild from it | possible, but the ordering has no integrity |
| Concurrent access | one advisory lock per session; appends durable before acknowledged | one connection with a process lock |
| Cross-session querying | linear scan (the honest weakness) | indexed |
| Constrained memory | a file handle | a database engine in a 64 MB budget |
| Migration complexity | forward-migrates every version it has written | would need a chain minted for records that never had one |
| Existing test coverage | extensive, in `tests/companion/test_events_store.py` | none carried across |
| Operational dependencies | none | `sqlite3`, present but not free |

The decision is to keep the event store. Cross-session querying is the real
weakness and is not currently needed; when it is, the answer is a derived index
beside the stream, not a different authority. A test asserts that no module in
`companion/` except `migration.py` imports a database driver, because that is
how the decision would actually be reversed — by an import, not by a discussion.

## 9. Migration

Development machines may hold a donor `companion.sqlite3`. It is **not**
imported into the canonical store, and cannot be truthfully: the donor stream
has no hash chain, so importing would mean minting hashes; its event vocabulary
has no canonical equivalent, so importing would mean choosing one; and a donor
row saying `terminal=1` would arrive as a completed task with no events proving
it, which is exactly the invented completion §20 forbids.

Instead `bunny-os companion migrate-ux-store` **archives** it: the database is
copied, the copy verified by digest, every row transcribed to JSON, and a
manifest written saying what was found and what could not be established.
Nothing enters `sessions/`. Rolling back is deleting one directory, and the
rollback refuses a directory it did not write. A dry run is the default.

Tasks the donor record cannot settle are marked `uncertain` and stay that way.
Approvals are transcribed only when every binding field is present; the rest are
listed with the field that was missing, and even a complete one is annotated
*"authorises nothing in the canonical runtime"*.

## 10. Presentation, honestly

`select_presentation` produces two answers and keeps them apart:

- `eligible` — what the machine and the capability policy would permit, read
  from the `capability_checked` event's own signals rather than re-measured;
- `implementation` — what this build will actually draw, filtered through
  `IMPLEMENTED_PRESENTATIONS = {static-image, audio-only, text-only}`.

On a capable machine `eligible` is `full-3d`, `implementation` is
`static-image`, and `limitedByImplementation` is true with a reason saying so.
**No animated 2D or 3D renderer exists in this build and none is claimed.**
Captions are produced in every presentation including audio-only: they are the
authoritative rendering of what the companion said, and audio is the optional
one.

## 11. The window

`companion/gtk_shell.py` is in two halves. `CompanionViewModel` is the whole of
the behaviour and imports no GTK, so it is tested on machines with no display —
which is the only way that logic is tested at all.
`BunnyCompanionApplication` is the widgets and contains no decision the view
model does not make.

Supported: centre, docked and compact presentation; task panel; Approval Centre;
speech bubble; caption view; text-only view; hide; restore; minimise; keyboard
navigation (`Ctrl+W`, `Enter` to submit); screen-reader labels on every control;
reduced motion and no-animation (there are no animations or transitions declared
anywhere in the stylesheet, so the preference is honoured by construction);
high-contrast compatibility through named system palette colours.

**A refresh never touches focus.** The poll updates labels and rebuilds panels;
it does not present, raise or grab. The single exception is an approval, and
that is decided by `window_directive` from the *phase* — so the window coming
forward always corresponds to "there is a question" and never to "an event
arrived".

**Wayland placement is not claimed.** `WindowDirective.absolute_placement_available`
is `False` and no code sets it otherwise. GTK 4 on Wayland gives placement to
the compositor; the directive drives size and shape only.

## 12. Voice and the microphone

Speaking is implemented where a local synthesiser exists (Speech Dispatcher,
eSpeak NG, the platform voice). Arguments are always an array — never a command
string, never a shell — with `--` before the text so a caption beginning with a
hyphen is spoken rather than parsed. The text is bounded at the process
boundary, and oversized text is refused rather than shortened, because a caption
cut in half and spoken says something different from what is on the screen
beside it. Every failure returns an outcome; nothing a caller must catch.

Listening is **not** implemented. `MicrophoneBoundary` is the activation rule —
explicit interaction (a required argument with no default), a visible indicator
raised *before* the provider can reach the device and cleared in `finally`,
separate consent for an always-listening mode, and approval for any recogniser
that would send audio off the device. Nothing activates at service start.
`AbsentSpeechRecognition` raises rather than returning an empty transcript,
because an empty transcript is indistinguishable from a recogniser that heard
nothing.

## 13. The static character

One asset: `shell/assets/companion/default-bunny.svg`, drawn for Bunny OS, GPL,
transparent, with no external reference, no embedded font and no script. Loaded
from a closed path list that no environment variable can extend. Symbolic links
are refused rather than followed; the file must be SVG or PNG, size-bounded, and
not marked executable; and an SVG carrying `<script>`, `javascript:`,
`<foreignObject>`, an event handler or an entity declaration is refused rather
than rendered.

`describe_phase` gives the state in words for every phase, written as a
description of the *companion* rather than of the drawing, so the text-only
surface is the same surface without the picture rather than a lesser one. A
missing asset is not an error: text-only is a supported presentation.

The character-package importer — manifests, archives, animation maps — is
**not** here. It belongs to the character-renderer branch, where a loader for
third-party content can be reviewed as the thing it is.

## 14. Schemas

| Schema | Authority |
| --- | --- |
| `companion-core-session.schema.json` | canonical |
| `companion-core-task.schema.json` | canonical |
| `companion-core-event.schema.json` | canonical |
| `companion-core-reviewer-observation.schema.json` | canonical |
| `companion-presentation-state.schema.json` | presentation only; no authority |
| `companion-protocol.schema.json` | transport envelope; no authority |

The donor's `companion-state`, `companion-task`, `companion-event`,
`companion-approval`, `companion-provider` and `companion-character-package`
schemas are **not** carried over. The first three duplicated canonical
authority; `companion-approval` is subsumed by the binding in the presentation
schema plus `capability.apply.approval`; `companion-provider` describes provider
adapters that do not exist in this build and would be a shape for one to be
poured into without review; `companion-character-package` belongs with the
importer, on the character-renderer branch. There are therefore no compatibility
aliases and no deprecated schemas shipped — nothing ever shipped them.

Every schema here carries `$id`, a version, strict `required`, bounded strings
and arrays, and `additionalProperties: false`.

## 15. Systemd

`systemd/user/bunny-companion.service` starts `/usr/libexec/bunny-companion-service`
in the graphical session. `RuntimeDirectory=` gives it the 0700 socket
directory, `StateDirectory=` the 0700 store, `UMask=0077`,
`RestrictAddressFamilies=AF_UNIX` (the companion makes no outbound connection,
so a provider adapter added later has to change this file, in a review, rather
than simply starting to work), plus `NoNewPrivileges`, `ProtectSystem=strict`,
`MemoryDenyWriteExecute`, a `@system-service` syscall filter and bounded
restart.

There is exactly one service. The desktop entry launches `/usr/bin/bunny-companion`,
which is a *client*: if no runtime is listening it says how to start one and
exits, rather than quietly becoming a second runtime.

`ConditionPathExists=/usr/lib/bunny-os/python/capability` names the dependency
the companion needs for every routing decision, so an image without the
capability runtime logs a skipped unit rather than an ImportError on each
restart attempt.

## 16. Security boundaries, in one list

- The socket is the only interface. It is 0600 in a 0700 directory with a peer
  uid check, and there is no network listener.
- The operation table is closed. No filesystem, command, provider or attribute
  operation exists.
- Parameters are declared and strictly validated; identifiers are pattern-bound,
  so a path traversal is refused before it reaches a filename.
- Clients cannot execute tools: there is no operation, and `ToolBroker` refuses
  every caller kind that is not `runtime`, `executor` or `recovery`.
- Reviewers cannot execute tools, resolve approvals or write files.
- Clients cannot write to the store; every mutating operation goes through the
  runtime, and none of them names a path.
- Credentials never reach the wire: `sanitize` removes them before an event is
  built, and the projection re-bounds every string.
- A disconnecting client cancels nothing.
- A second runtime on one endpoint is refused; a symlinked or non-endpoint path
  is refused rather than replaced.
- Voice takes argument arrays and never a shell string.
- The microphone cannot activate silently, and cannot activate at start-up.

## 17. Known limitations

1. **One worker thread.** A task parked on an approval holds it; other tasks
   queue behind it. Answering or cancelling frees it, and neither goes through
   the worker. Concurrency across tasks is future work and would need the
   runtime's in-memory session cache made explicitly thread-safe first.
2. **The GTK widget layer is not covered by any automated test.** It needs a
   compositor. Everything below it is covered, through `CompanionViewModel`.
3. **The loopback-TCP fallback is a developer transport.** It exists so this can
   be developed on a platform without `AF_UNIX`. It is not what ships and no
   security property is claimed for it beyond the token and the loopback bind.
4. **No speech recognition.** The boundary is built and tested; there is nothing
   behind it.
5. **No animated 2D or 3D renderer**, and no provider adapter of any kind.
6. **Cross-session querying is a linear scan.** Fine at present scale; the fix
   when it is not is a derived index, not a database.
7. **Pause is best-effort in timing.** It takes effect at the next phase
   boundary, and a pause issued the instant a question appears may record the
   phase before the question rather than the question itself. Both are resumable
   states and no work is lost either way.

## 18. Build and qualification impact

**This branch is build-affecting and is not covered by any existing
qualification evidence.** It installs the `companion` and `capability` packages,
a libexec entry point, a user unit, a desktop entry, a launcher and an asset
into the image. It is not covered by candidate `79bb99d`, by Commit C′, by the
capability H1/H2 hosted evidence, or by any previous visual prototype
measurement, and no reproducibility candidate has been created for it.

It requires its own qualification cycle before any such claim is made.
