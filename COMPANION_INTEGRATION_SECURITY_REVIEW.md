# Security review: the integrated Bunny Companion

Scope: everything the integration added — the local socket, the service, the
presentation projection, the GTK client, the voice adapter, the microphone
boundary, the static character loader and the donor-store migration. The runtime
core's own review is `COMPANION_RUNTIME_CORE_SECURITY_REVIEW.md` and is not
repeated here; what *is* here is the effect of putting a socket and a window in
front of it.

Every item in §21's list appears below with the test that covers it. Findings
made during this work are in §4, including two that were mine and were fixed.

---

## 1. Threat model

The attacker is a **process running as another local user**, or a **process
running as the same user that is not the companion client** — a browser tab's
helper, a language server, anything the user installed. There is no network
listener, so there is no remote attacker in scope for this component.

What such a process wants: another user's task history (which contains whatever
they asked the companion to do), the ability to authorise an approval on their
behalf, or the ability to make the companion perform an operation.

A second attacker is a **defective or hostile client** — the GTK window itself,
compromised or merely wrong. It has legitimate access to the socket and the
question is what that access is worth.

Explicitly out of scope: an attacker who is already root, or who can rewrite the
store. The event chain is unkeyed and detects damage, not a determined rewrite;
that is the signing layer's problem and remains out of scope.

## 2. §21's list

| Test | Result | Covered by |
| --- | --- | --- |
| Unauthorized local socket client | Refused. Socket 0600 in a 0700 directory; on the loopback fallback a per-run token compared with `hmac.compare_digest`. | `test_a_peer_without_the_transport_token_is_refused` |
| Wrong peer user | Refused via `SO_PEERCRED`. A peer whose credentials cannot be read is refused, not admitted. | `test_a_peer_whose_credentials_cannot_be_read_is_refused` |
| Oversized request | Refused at 64 KiB, and the excess is never read. | `test_an_oversized_request_is_refused_and_never_read` |
| Malformed JSON | `invalid_request`, no traceback on the wire. | `test_malformed_json_is_refused_without_a_trace` |
| Unknown operation | `unknown_operation`. The table is closed. | `test_an_unknown_operation_is_refused_by_name` |
| Protocol downgrade | `unsupported_version` for every version but the current one. No negotiation. | `test_a_protocol_downgrade_is_refused_rather_than_negotiated` |
| Replayed request | A `requestId` mismatch is discarded by the client; a replayed *approval* is `approval_replayed`. | `test_an_approval_answered_twice_is_a_replay` |
| Approval replay | Refused by the gateway (already-resolved) and again by the gate (consumed set). | as above |
| Changed approval destination | `approval_mismatch`; also provider, cost, classification, task, plan, step and action. | `ApprovalRefusalTests` (4 tests) |
| Event payload injection | A malformed event document cannot move the phase; an unknown state name is ignored; progress is clamped. | `InvalidInputTests` (5 tests) |
| GTK markup injection | Neutralised at the point the string is produced, not where it is displayed. | `MarkupTests` |
| Status-text escaping | Escaped exactly once — the double-escape was a real finding, §4.1. | `test_markup_in_a_status_line_is_neutralised` |
| Path traversal | Identifiers are pattern-bound; `../../etc/passwd`, `a/b`, a UNC path and a NUL are all refused before reaching a filename. | `test_an_identifier_carrying_a_path_traversal_is_refused` |
| Symlink state-file attack | A symlinked endpoint is refused, not bound through. A symlinked character asset is refused, not followed. The store already uses `O_NOFOLLOW`. | `test_a_symlinked_endpoint_is_refused`, `test_a_symlinked_asset_is_refused_rather_than_followed` |
| Client cannot execute tools | No operation exists; `ToolBroker` refuses every caller kind that is not `runtime`, `executor` or `recovery`. | `test_a_client_cannot_execute_a_tool` |
| Reviewer cannot execute tools | Refused and recorded against the reviewer's identity, even holding a broker it was never given. | `test_a_reviewer_cannot_execute_a_tool_even_holding_a_broker` |
| UI cannot mutate persistence | No operation names a path; a read-only sweep leaves the store byte-identical. | `test_a_client_cannot_write_to_the_store`, `test_the_client_never_writes_to_the_store` |
| Voice input cannot inject shell arguments | argv arrays only. A caption of `; rm -rf ~ && curl … \| sh` arrives as exactly one argument. No `shell=`, checked by AST. | `VoiceArgumentTests` (4 tests) |
| Microphone cannot activate silently | Indicator raised before the provider is reached and cleared in `finally`; explicit activation is a required argument; nothing activates at start-up. | `MicrophoneBoundaryTests` (10 tests) |
| Runtime does not expose credentials | A credential-shaped request is redacted before it becomes an event and is absent from health, task, events and presentation. | `test_the_runtime_never_puts_a_credential_on_the_wire` |
| Client disconnect does not cancel tasks | The task keeps running and is still in `runningTasks`. | `test_a_client_disconnecting_does_not_cancel_a_task` |
| Duplicate runtime instance is rejected | `DuplicateRuntime`. A live endpoint is never displaced; a stale one is removed. | `test_a_second_runtime_on_the_same_endpoint_is_refused` |

Two further checks not on §21's list but implied by it:

| Test | Result | Covered by |
| --- | --- | --- |
| An endpoint path holding something else | Refused, and the file is left exactly as it was. | `test_an_endpoint_path_holding_something_else_is_not_replaced` |
| An undeclared protocol parameter | Refused, not ignored. | `test_an_undeclared_parameter_is_refused_rather_than_ignored` |
| A character asset carrying active content | Refused: `<script>`, `javascript:`, an event handler, an entity declaration and `<foreignObject>`. | `test_an_svg_carrying_a_script_is_refused` |

## 3. What a compromised client can and cannot do

**Can:** create sessions, submit tasks, read everything at the `ui` ceiling,
cancel, pause, resume, and answer an approval *correctly*. That is the whole
list, and it is deliberately the list of things a user could do anyway.

**Cannot:** name a tool, name a file, name a provider, choose an executor,
evaluate capability, decide a task succeeded, write an event, alter a stored
approval, read above `sensitive`, or reach anything at the `executor` ceiling.
The audience is fixed in `companion/service.py` and is not a protocol parameter,
which was a deliberate choice: the donor's design had no audience concept, and
adding one as a parameter would have been the natural mistake.

**Cannot, specifically, forge consent.** The three-layer check is: the gateway
compares the claim against the recorded request; `InteractiveConsent` carries
only `granted`/`denied`/`None`; the gate compares the recorded reference against
the plan about to run. Slice step 12 exercises the first by altering the
destination and requiring a refusal *before* the honest answer is sent — so the
refusing direction is tested on every run rather than assumed.

## 4. Findings

### 4.1 Status text was escaped twice — fixed

`_text()` escaped markup and the assembled status line escaped it again, so a
task summary containing `<span>` reached the surface as `&amp;lt;span` — the user
shown the escaping rather than the text. Not exploitable, but it is the failure
mode that makes people turn escaping off. Fixed by separating `_text` (escapes
once, per payload value) from `_bound` (bounds an already-escaped line). Found by
`MarkupTests`, which is why the assertion checks for `&lt;span` specifically
rather than merely for the absence of `<span`.

### 4.2 A task's own classification was withheld from its privacy indicator — fixed

`task_created` was classified wholesale at the task's level, so for a `secret`
task the payload's `classification` field — the field whose entire purpose is to
say the task is secret — arrived at the `ui` audience as `[withheld: secret]`.
The surface could not display a privacy indicator for exactly the tasks that
most need one. Fixed by declaring `classification`, `dataLocality`,
`requiresOffline`, `costLimitUnits` and `executionDeadlineSeconds` as
`internalFields`, which is the same fix `session_created` had already received
for its policy blocks. The user's words stay at the task's class.

### 4.3 A pause was silently erased by the runner — fixed

`pause_task` wrote `paused` and the running task's next `_save_running_task`
wrote `executing` straight back over it. The pause appeared to work and then
undid itself. Fixed by giving pause the same protection cancellation has:
`_stopped` and `_save_running_task` both treat a persisted `paused` as
authoritative, `_plan_and_execute` checks after `_settle_approvals`, and
`_execute_plan` breaks between operations. `resume_task` writes authoritatively,
because it is the authority for un-pausing and the protective write would
otherwise refuse its own transition (found immediately after the first fix, by
the same test).

### 4.4 Withdrawal only looked at the task document — fixed

`ApprovalGate.invalidate_for_task` iterated `task.approvals`. A question becomes
durable when it is raised; the reference reaches the task *document* a few lines
later. Cancel or pause inside that window — which is precisely the window in
which the user is looking at the question and most likely to press stop — and
nothing was withdrawn: the question stayed pending and the surface went on
showing an Approve button for a task that had been stopped. Fixed by also asking
the store, which records the owning task in `service_id` at the same instant as
the request. This affected cancellation as well as pause.

### 4.5 The Approval Centre sent display fields as binding fields — fixed

`approval_cards()` returned `to_json()`, which includes `reason`,
`destinationDetail`, `alternatives` and `safeDefault`. The protocol's strict
parameter validation refused it as `invalid_request` — correct, but the *reason*
was wrong, and a laxer protocol would have accepted a rendering as a binding.
Fixed by `binding()` returning exactly the recorded fields, with the specific
destination kept outside it as display-only.

### 4.6 A read could meet a projection mid-replacement — fixed

Serving concurrent readers while the worker writes surfaced a Windows-only
window in which `os.replace` refuses a reader with `EACCES`. Reported as "the
task document is not readable", which is the wrong diagnosis to hand somebody.
Fixed with a bounded retry in the store's read path, documented as the platform
accommodation it is. No security impact; recorded because a misleading integrity
error is a security problem of a different kind.

### 4.7 Accepted risk: the loopback developer transport

On a platform with no `AF_UNIX` the endpoint is loopback TCP with a per-run
token. Any local process that can read the 0600 endpoint file can use the
socket, and on such a platform the file mode may not be enforced at all. This is
not what ships, `BUNNY_COMPANION_REQUIRE_UNIX=1` refuses it, and
`describe()` names it so no measurement or claim can be mistaken for the real
transport. Accepted because the alternative is not developing the component.

### 4.8 Accepted risk: the projection is not authenticated on the wire

A client receives `TaskEvent.view("ui")` documents, whose payloads have been
projected and therefore no longer match their own hashes. A client cannot verify
what it is shown. This is inherent: verifying would require the unredacted
record, which is the thing the audience ceiling exists to withhold. The
integrity of the *stream* is checked where the stream lives, on every full read.
The client is a view and is treated as one.

### 4.9 Noted, not fixed: one worker thread

A task parked on an approval holds the worker, so a hostile *user* can stall
their own companion by submitting a task and never answering. This is a
self-denial of service with no cross-user effect, bounded by the consent timeout
and cleared by answering or cancelling. Fixing it properly means making the
runtime's in-memory state thread-safe, which is a larger change than this
integration should carry.

## 5. What was deliberately not built

- **No provider adapter, and no provider descriptor.** The donor had
  `AgentProviderDescriptor` with an `authentication_state` field. A descriptor is
  a shape for a real integration to be poured into without anybody reviewing the
  decision to have one, and an `authentication_state` field is where a
  credential eventually appears.
- **No speech recognition.** The boundary is real and tested; there is nothing
  behind it, and `AbsentSpeechRecognition` raises rather than returning silence.
- **No character-package importer.** A loader for third-party desktop content is
  one of the most dangerous components a desktop can have and deserves its own
  review, on the branch that owns it.
- **No animated or 3D renderer.** `IMPLEMENTED_PRESENTATIONS` is enforced in
  code and in the schema's enum, so the presentation state cannot claim one.
- **No generic protocol operation.** No filesystem, command, provider or
  attribute operation, and the handler is never looked up by a name from the
  wire.
