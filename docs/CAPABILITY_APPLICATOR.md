# The Bunny OS plan applicator

`capability/` decides what should run. `capability/apply/` decides what to *do*
about the difference between that and what is running, and it is the only code
in Bunny OS permitted to change a machine.

This document describes that layer: how it compares desired state against actual
state, how it converts the difference into a safe, ordered set of operations,
and — more importantly — every case in which it declines to.

## The decision boundary

The capability engine is the only authority on what should run. The applicator
has no way to disagree with it, and that is enforced structurally rather than by
convention.

**The applicator may say no. It may never say yes.**

| Legitimate applicator decisions | Illegitimate, and impossible here |
|---|---|
| Reject a stale or superseded plan | Increase a memory grant beyond the plan's figure |
| Delay a start because resources changed | Enable remote execution the policy disabled |
| Roll back after a failed start | Start an undeclared dependency |
| Refuse an unauthorised unit | Silently select a different provider |
| Refuse an allocation that breaches the reserve | Treat a powerful machine as licence to bypass privacy |
| Keep a service alive to protect user work | Decide an ineligible service is eligible after all |
| Enter a degraded state after repeated failure | |

Three mechanisms hold the boundary:

1. **Desired state is a projection, never an inference.** `desired_from_plan()`
   reads the plan; nothing derives desired state from what happens to be
   running. A service that started by accident does not thereby become a service
   that is supposed to be running.
2. **Every grant is a ceiling.** `ServiceLimits.from_desired()` copies the
   plan's figures. `InMemoryLedger.commit()` raises if a commit exceeds its
   reservation. There is no code path that widens a limit.
3. **Refusals are typed.** Reconciliation returns either a `Transition` (an
   operation the plan implies) or a `Blocked` (a refusal with a reason). There
   is no third kind of output.

## The pipeline

```text
Capability discovery
        ↓
Inventory and scores
        ↓
Budget calculation
        ↓
Policy evaluation
        ↓
Desired execution plan          ← capability/engine.py
        ↓
Plan validation                 ← apply/identity.py, apply/revalidate.py
        ↓
State reconciliation            ← apply/reconcile.py
        ↓
Operating-system backend        ← apply/backends.py, apply/systemd.py, apply/cgroup.py
        ↓
Observed actual state           ← apply/state.py
        ↓
Runtime monitoring              ← apply/monitor.py
        ↓
Reevaluation request            → back into capability/engine.py
```

## Plan identity

Execution plans are now schema version **2**. The added `identity` block answers
every question the applicator asks before acting.

| Field | Question it answers |
|---|---|
| `planId` | Which plan is this? Content-derived, comparable without a registry |
| `revision` | Which generation? Monotonic; a lower revision arriving later is a replay |
| `contentDigest` | Is this the same *desired state* as the last one? |
| `fingerprints.inventory` | What was the machine when this was decided? |
| `fingerprints.budget` | What could be spent? |
| `fingerprints.policy` | What was permitted? |
| `fingerprints.registry` | What did the services declare? |
| `createdAtMonotonic` | How old is it, on a clock that does not step |
| `maximumAgeSeconds` | When does it expire (default 300s) |
| `previousPlanId`, `reevaluationReason` | Where did it come from, and why |

**Identity is content-derived, so it is deterministic.** Everything is
canonicalised — sorted keys, fixed separators, ASCII — before hashing. Two hosts
that reached the same decision from the same inputs agree on its identity, which
is what lets the tests assert on plan ids.

**Fingerprints exclude volatile and identifying data.** `detectedAt` and probe
durations are dropped: a plan is not a different plan for having been decided a
second later, and a per-run timestamp inside a fingerprint would make every
comparison useless. Probe *outcomes* are kept, because a probe that failed this
time genuinely is a different machine as far as a decision is concerned. The
inventory model collects no serial numbers, MAC addresses or hostnames in the
first place.

`planId` folds in the revision and the previous plan id as well as the content,
so a chain of reevaluations that keeps reaching the same answer still produces
distinguishable plans. `contentDigest` is what says two of them describe the
same desired state.

### Supersession

A plan supersedes another only at a strictly higher revision. Equal revisions do
not supersede, so a replayed plan cannot displace the one in force even if its
content differs. When a plan is superseded, every approval granted against the
old one is expired: consent to an act under one set of numbers is not consent to
the same act under different ones.

## Desired, actual and transition state

Three types, and the distinction between them is the design.

**Desired** — what the plan requires, projected into `DesiredService`. Never
inferred from the machine.

**Actual** — what can presently be *observed*, as `ServiceObservation`.
Emphatically not what the applicator last did: an operation that reported
success is evidence, not proof. Every observation carries `observed_by`, and
`ServiceObservation.observed` is false for anything the applicator merely
believes. Nothing is stopped on the strength of an inference.

The state vocabulary is wider than running/stopped, because most of the
interesting states in an adaptive system are the waiting ones:

```
running        stopped        starting       stopping       suspended
failed         unknown        degraded       externally_managed
waiting_for_approval   waiting_for_dependency   waiting_for_resources
waiting_for_network    remote_execution_pending remote_execution_active
```

`externally_managed` is what keeps the applicator honest on a developer's
machine: a unit that is running but was not started by Bunny OS is not ours to
stop, and recording it as `running` would let a reconciliation decide it may be
shut down.

**Transition** — one attempt to move one service, as a record rather than a
command. It exists before the operation starts, is updated as it proceeds, and
survives its own failure. `transition_id` is derived from
`(planId, serviceId, operation, attempt)` rather than generated, so an audit
record is reproducible and a test can assert on it.

## The reconciliation algorithm

`reconcile(desired, actual, settings, now)` is a pure function returning an
ordered `ReconciliationPlan`. It starts nothing.

```
1. Refuse the whole plan if it is internally inconsistent
   (two mutually exclusive services both wanted running).

2. Phase one — release, in reverse dependency order:
     for each service, dependents before dependencies:
       skip if not active
       refuse if externally managed, unobserved, or unauthorised
       choose the gentlest operation the plan permits (suspend > stop)
       refuse if essential and no explicit allowance
       refuse if the adaptation would interrupt user work without approval
       emit stop | suspend

3. Project available memory forward:
     available += memory that phase one will release
     (a suspend releases nothing — a frozen service keeps every page)

4. Phase two — acquire, in dependency order:
     for each service, dependencies before dependents:
       skip if the plan does not want it running
       refuse if externally managed, unauthorised, or awaiting approval
       refuse if a dependency is neither running nor starting in this pass
       refuse if a conflicting service is still up
       refuse if the circuit is open or the retry backoff has not elapsed
       resume if suspended with the right implementation
       apply_limits if running with the wrong enforced limit
       refuse if the grant exceeds projected availability
       emit start
       available -= the grant
```

### Why stops come before starts

Everything that yields resources happens before anything that consumes them. A
reconciliation that interleaved them would have to reason about whether the
memory freed in step 4 is the memory spent in step 2, and it would sometimes get
that wrong on exactly the machine where it matters.

### Why one topological sort produces both orders

Dependencies start before dependents; dependents stop before the dependencies
they need. Those are the same edge read in two directions, so `stop_order()` is
literally `reversed(start_order())`. Written as a reversal rather than a second
walk so the two cannot disagree.

### Determinism

Every sort has an explicit tie-break down to the service id, and `start_order()`
is seeded in the same `(essential, -priority, id)` order the budget engine hands
out memory in. Keeping them identical means a service cannot be funded ahead of
another and then started behind it. Declaration order, dictionary order and
filesystem order affect nothing.

### Idempotency

Applying reconciliation to a converged system produces no transitions, however
many times it is called. Two things make this true: `_limits_match()` compares
the *enforced* limit rather than the requested one, so a service whose limit was
never applied is correctly reported as not converged; and the engine's plan
reaches a fixed content digest after one hysteresis-aware evaluation, so
repeated reevaluation of an unchanged machine converges rather than oscillating.

### Partial convergence

Transitions are independent. A blocked or failed optional service produces one
`Blocked` or one failed `Transition`; unrelated services still converge in the
same pass. Only the *dependents* of a failed service are skipped, and they are
recorded as `postponed` rather than failed.

## Apply-time revalidation

A plan is a statement about a machine at an instant. Between that instant and
the moment a service starts, a user can open forty tabs, unplug a laptop,
withdraw a permission, or install a new manifest.

`revalidate_plan()` runs once per pass, cheapest and most decisive first:

1. Does the plan carry an identity, and is its schema version supported?
2. Has a newer plan superseded it? (two integers)
3. Has it expired?
4. Do the inventory, budget, policy and registry fingerprints still match?

`revalidate_transition()` runs immediately before **every resource-increasing
action**, against figures obtained after the plan was:

1. Does the grant still fit the ledger's remaining capacity?
2. Would the grant leave free memory below the protected reserve?
3. Are the dependencies still active?
4. Is the required approval still valid?
5. Is remote execution still permitted, for a remote implementation?

The reserve is checked separately from the budget even though the budget already
excludes it. Two independent statements of one invariant: if a future change to
the budget engine ever let the reserve into an allocatable figure, this check
catches it at the moment of allocation rather than after the OOM killer did.

**A failed check never adjusts the plan.** The module returns a verdict whose
only remedies are "do not apply" and "ask the engine again". There is no code
path from here that writes a smaller number into a decision and proceeds.

Revalidation deliberately does **not** run before releases. Stopping a service,
lowering a limit and suspending something all make the machine safer, and
refusing them because a fingerprint moved would leave a machine under pressure
holding exactly the work it needs to shed.

## Resource reservation

The ledger holds one invariant:

```
committed + reserved  ≤  capacity − protected reserve
```

checked after every mutation, not before every read.

Reservations are **two-phase**. `reserve()` takes memory out of the pool without
claiming the service is running; `commit()` records that it actually started;
`release()` gives it back. A start that fails halfway returns exactly what it
took, and a crash between the phases leaves a visibly uncommitted reservation
rather than a leak that looks like a running service.

| Property | How |
|---|---|
| Atomic | The availability check and the take happen under one lock |
| Idempotent release | Releasing twice, or releasing nothing, never raises |
| Expiry | Uncommitted past its deadline (default 120s) is reclaimed |
| Orphan detection | Committed reservations for services the backend says are stopped |
| Restart recovery | `JsonFileLedger` restores from one atomically-written file |
| Never over-grants | `commit()` raises if the committed amount exceeds the reserved one |

The persisted file is a **cache of promises, not a source of truth about the
machine**. On load, every committed reservation is provisional until
`reconcile_with_actual()` has compared it against what the backend can see. A
ledger that trusted its own file would, after an unclean shutdown, believe a
machine full of services that are not running.

A corrupt or invariant-violating file is discarded with a warning rather than
repaired by guessing. Refusing to run because a bookkeeping file is unreadable
would be worse than reconciling against the machine.

No database. §18 requires this to work on a node where a resident database would
cost more memory than the services it accounts for.

## The transaction model

A start is seven steps, and each can fail:

```
validate → reserve → apply limits → start → confirm state → health check → commit
```

On failure the record is walked backwards:

```
record failure → stop the partial service → restore the previous implementation
if safe → release the reservation → record the rollback → schedule or refuse a retry
```

Three rules:

**Limits go on before the process exists.** A service started first and limited
second has already had a window in which it could allocate past its grant, and
on a constrained machine that window is exactly when the machine is least able
to survive it.

**A rollback may not make things worse.** Restoring a previous implementation is
attempted only when it can be reserved *and* started. If it cannot, the service
is left stopped and that is reported, because a rollback that overcommits the
machine has traded a failed service for a failing machine.

**Cleanup does not fail.** Every release is idempotent; every stop of a partial
service tolerates its absence. A cleanup path that can itself raise is a cleanup
path that leaks.

A service whose limits could not be enforced is **rolled back rather than left
running unconstrained**. The budget engine's arithmetic assumed a ceiling; every
later admission decision would otherwise rest on a fiction.

## Failure classification and retry

Nineteen classes, each stating whether it is retryable and whether it means the
*plan* is wrong rather than the act.

| Not retryable | Retryable |
|---|---|
| `invalid_plan`, `stale_plan`, `superseded_plan` | `dependency_unavailable` |
| `insufficient_resources`, `protected_reserve_violation` | `backend_unavailable` |
| `permission_denied`, `unit_not_authorized` | `startup_timeout`, `shutdown_timeout` |
| `configuration_error`, `permanent_incompatibility` | `health_check_failure` |
| `approval_missing`, `cgroup_unavailable` | `network_unavailable`, `remote_provider_failure` |
| | `unexpected_internal_error` (once) |

The retry policy reads the **class**, never the message. A policy that parsed
error text would silently start retrying permanent failures the day somebody
reworded a diagnostic.

**Backoff is deterministic.** Exponential with jitter, but the jitter is a hash
of the transition identity rather than a random draw. Two services failing in
the same second still get different delays — the only property jitter provides —
while a test can assert the exact sequence and a restart recomputes the same
schedule.

**Retries are scheduled, not slept through.** A failure writes a deadline into
`RetryJournal` and returns. The next reconciliation picks it up. Nothing in the
applicator sleeps, so nothing can hold a reconciliation open, and the journal is
persisted so that restarting the applicator does not restart the retries —
without which a supervisor and a retry counter combine into a restart loop
assembled from two components that each believed they were bounded.

**Circuit breaking** opens after three consecutive failures and lets one probe
through after a recovery window. **Essential services are never broken**: opening
a breaker on the control plane would remove the thing that would have reported
the fault.

## Backends

Provider-neutral, eight verbs, three contractual properties: every operation is
**bounded** by a deadline, every failure is **classified**, and every backend is
**honest about enforcement** — it reports what it managed to apply, not what it
was asked to apply.

| Backend | What it is for |
|---|---|
| `DryRunBackend` | **The default.** Records intentions, changes nothing. Reads through an optional observer so a rehearsal compares against real actual state |
| `InMemoryBackend` | A deterministic model of a service manager, for tests. Holds real state, enforces real ordering rules, injects real failure modes |
| `SystemdBackend` | The only code that can change a live host |

### The systemd backend

- **No shell, ever.** Every invocation is an argument array with `shell=False`.
  There is no string interpolation into a command line anywhere in the module.
- **Unit names are derived, not declared.** `unit_name_for()` maps a service id
  to `bunny-<slug>.service` by a fixed rule. A manifest cannot name a unit, so a
  manifest cannot name somebody else's unit.
- **An allowlist, not a denylist.** `authorized_units_for(registry)` builds the
  permitted set from the shipped manifests. Nothing that is not a Bunny OS
  service can be reached, whatever it is called. No configuration file exists
  whose editing would widen it.
- **Opt-in twice.** Constructing the backend requires
  `allow_host_modification=True`; without it every mutating method refuses
  before doing anything and only the read paths work.
- **Bounded.** Every subprocess has a timeout enforced by killing the child.
- **Never root by ambition.** No `sudo`, no escalation, no privilege check. It
  runs what it is given and reports `permission_denied` when the system says no.
- **A minimal child environment.** Only `PATH`, `LC_ALL` and `SYSTEMD_COLORS`,
  so nothing in the parent process can change what the child does.
- **`systemctl start` returning zero is not success.** The unit state is read
  back; a unit that is not active is a failed start however the command exited.
  `activating` maps to `starting`, not `running`.
- Diagnostics pass through a redactor before they reach a record.

Detection is `/run/systemd/system` — the marker systemd's own tooling uses.
Checking for the `systemctl` binary is not enough: a container image can ship it
while running something else as PID 1.

### The cgroup backend

cgroup v2, in a Bunny OS-owned subtree (`bunny-os.slice`), with every write read
back.

- Detects version, delegation, controller availability and container
  restrictions — four different conditions with four different remedies, never
  collapsed into "cgroups unavailable".
- Every path is built by joining a validated service id onto the configured
  root, then verified after resolution to still be inside it, so a symlink
  cannot move it out. A traversal attempt **raises** rather than being
  sanitised: quietly rewriting `../../system.slice` would mean an attempted
  traversal produced a working cgroup and no alarm.
- `EnforcedLimits` carries `requested` and `effective` separately, and they are
  allowed to differ. Enforcement is judged by what came back out of the kernel,
  never by whether the writes returned without error — a kernel that accepts a
  write and clamps the value has enforced something other than what was asked.
- A stricter effective limit still counts as enforced; a looser one does not.
- When cgroups cannot be used at all, `NullCgroupController` answers truthfully
  so the caller has no branch in which a missing controller is mistaken for a
  working one.

**Bunny OS never claims a service is constrained when the write failed.**

## The runtime monitor

Four mechanisms, routinely confused, each doing a different job:

| Mechanism | About | Effect |
|---|---|---|
| **Hysteresis** | the value | Enter at one threshold, leave at another; a signal on the boundary does not toggle |
| **Debounce** | how long it held | A crossing must persist before it counts |
| **Cooldown** | how often we act | The same event cannot repeat for a period |
| **Coalescing** | the batch | Several events become one reevaluation |

Together: a laptop whose free memory oscillates around a threshold produces one
event, not forty; and the service suspended under pressure is not restored the
instant memory blips upward, but only once the recovery has held.

Events (a strict subset of the plan's `reevaluationReason` vocabulary, so no
translation is needed): `memory_pressure_entered` / `_recovered`,
`thermal_limit_entered` / `_recovered`, `battery_critical` / `battery_recovered`,
`network_lost` / `_restored`, `display_attached` / `_removed`,
`audio_device_changed`, `cpu_saturation_entered` / `_recovered`,
`gpu_memory_pressure_entered` / `_recovered`, `service_failed`,
`remote_provider_unavailable`, `user_policy_changed`,
`manifest_registry_changed`.

Emergencies (`memory_pressure_entered`, `thermal_limit_entered`,
`battery_critical`) bypass the cooldown and outrank everything else when
coalescing. A cooldown that suppressed "memory is critically short" would be a
stability mechanism that let the machine run out of memory quietly; a plan
generated in response to a display being attached is not the plan a machine
short of memory needs.

**Sampling is not free and is not assumed.** Every signal is individually
switchable. `CONSTRAINED_SIGNALS` watches memory only, with a 30s debounce and a
300s cooldown. An unmeasured signal raises nothing and does not resolve a breach
— a reading that was never taken is not a reading of zero, and reading an
unmeasured battery as 0% would fire `battery_critical` on every desktop.

**The monitor decides nothing.** It emits typed reasons and has no ability to
start, stop or reprioritise anything.

## Adaptation safety

| Class | Examples | Requires |
|---|---|---|
| **Non-disruptive** | lowering a background CPU weight, shrinking a cache, pausing an optional indexer, starting a service | proceeds automatically |
| **Gracefully disruptive** | switching an inference backend, restarting a nonessential service with a smaller grant | graceful handoff; never against declared unsaved work |
| **User-visible / destructive** | terminating a foreground task, discarding unsaved state, sending data remotely, spending money, overriding a pin | explicit approval |

The default when a class cannot be determined is the most expensive one.

User-work policies: `graceful_completion`, `user_notification`,
`approval_required`, `deadline_shutdown`, `emergency_only`.

**The one documented emergency.** `EMERGENCY_POLICY` — available memory below
the protected reserve and still falling — permits terminating a nonessential
service that holds unsaved work, with a notification. It never permits sending
data to a remote provider, spending money, or stopping an essential service.
Naming it as a constant with a stated threshold means an emergency is a
measurement rather than an adjective anybody can apply to a transition they are
impatient about.

## Approvals

The Approval Centre UI is deliberately not built. The interface is.

An `ApprovalRequest` carries the request and plan ids, the action, why it is
needed, the data affected, the destination, the provider, the estimated cost,
the resource impact, an expiry, the available alternatives, and the safe
default.

**The default for an unanswered sensitive request is denial.** Not deferral, not
"assumed fine because the machine is under pressure". A timeout is an answer,
and the answer is no. This is enforced in `__post_init__`: constructing a
sensitive request with `safe_default="granted"`, or with no stated alternative,
raises.

Sensitive actions: `remote_dispatch`, `paid_provider`, `interrupt_user_work`,
`discard_unsaved_state`, `stop_essential_service`,
`override_pinned_implementation`, `send_sensitive_data`.

`DenyingApprovalStore` is the default. It records every request so a UI can
later show what was asked, and grants nothing. A machine with no way to ask a
person must not act as though they said yes.

## Remote execution

Provider-neutral state model, implemented and tested, integrating with nothing.

```
not_permitted → (terminal on most machines)
awaiting_approval → awaiting_provider → queued → dispatching → active
                                                → completing → completed
                                      ↘ failed | cancelled | lost
lost | cancelled → reconciliation_required → completed | failed | cancelled
```

**The boundary between `queued` and `dispatching` is the privacy boundary.**
Everything up to `queued` is local bookkeeping that can be undone silently.
`dispatching` is the first state in which a user's data has left, so it is the
only transition requiring every precondition simultaneously: policy, approval,
authenticated provider, declared retention and training use, capability match,
privacy-class compatibility, network, an idempotency token, and an unexhausted
attempt budget. `RemoteDispatchGuard.refusals()` checks them together rather
than leaving a caller to assemble a sequence and omit one.

`lost` is distinct from `failed` because the responses differ: a failed task may
be retried; a lost one must first be reconciled, or the same work runs twice on
somebody's bill. `data_has_left` is answered from the history, so a user asking
"did my document leave this machine" is not told no because the request errored
afterwards.

Idempotency tokens are **derived** from `(planId, transitionId, taskId)`. If the
applicator crashes between dispatching and recording it, recovery recomputes the
same token and the provider can recognise the retry. A random token would make
recovery indistinguishable from a second request.

**No credential appears anywhere.** `RemoteTask` and `ProviderIdentity` have no
field for one, which is the only reliable way to guarantee one is never logged.
A machine with remote execution off produces tasks in `not_permitted`, which has
no outgoing transitions — a stronger guarantee than a check somebody has to
remember to run.

## Audit records

Twenty-one stable event identifiers (`plan.generated`, `transition.rolled_back`,
`reservation.reclaimed`, `circuit.changed`, …). Consumers match on these, never
on a message.

**Observed fact and inferred explanation are separate fields.** Every record
carries `observed` and `inferred` blocks. Mixing them produces a log in which
"the service was stopped because memory was low" cannot be checked, because
nobody can tell which half was read off a meter.

Redaction happens on the way *in*, not on the way out — a redactor at the read
end protects nothing once the bytes are on disk. Credentials, bearer tokens, IP
and MAC addresses and home directory paths are stripped recursively, so a nested
diagnostic cannot smuggle one past a check that only looked at the top level.
Free text is bounded at 1 KiB per field.

Retention is bounded by count. `JsonLinesAuditSink` counts existing lines at
construction so a process restart does not reset the window, and writes only
when something happened — a monitor that recorded "no change" 1,700 times a day
is a hardware failure being scheduled on a node with an SD card.

## Developer workflow

**Real host operation is never the accidental default.** Three modes, labelled
in the output rather than inferred:

```bash
# Simulation: synthetic inventory, modelled backend. Touches nothing.
bunny-os capability apply --simulate laptop
bunny-os capability reconcile --simulate embedded-64mb

# Dry run: this machine is observed, never modified.
bunny-os capability apply

# Real host operation: requires --host, requires systemd, refused with --simulate.
bunny-os capability apply --host
```

| Command | What it does |
|---|---|
| `capability plan` | the execution plan, with its identity |
| `capability plan --validate` | may this plan still be applied, and every check |
| `capability plan --diff <path>` | compare against a captured plan |
| `capability reconcile` | the difference between plan and machine, ordered |
| `capability apply` | apply it (dry run unless `--host`) |
| `capability transitions` | the transitions of the last pass |
| `capability transitions --explain <id>` | one transition in full |
| `capability reservations` | the ledger, and the reserve it protects |
| `capability monitor` | signals, thresholds, bands and current readings |

`--host` is refused alongside `--simulate` or `--inventory`: a rehearsal against
synthetic hardware must not be able to act on real services.

### Example explanation

```text
Transition was postponed.

Service:
  bunny.inference.local

Requested action:
  Start the service
  stopped -> running

Reason:
    ok   budget.available: required 312 MiB, measured 174 MiB
    FAIL budget.protectedReserve: required 128 MiB, measured 46 MiB
         memory that would remain free after this grant, against the reserve
         that nothing may take
  - starting bunny.inference.local would leave 48234496 bytes free against a
    134217728 byte protected reserve
  - classified as: protected_reserve_violation

Action taken:
  - no process was started
  - no reservation was held
  - capability reevaluation was requested

User impact:
  - the service is not running, and nothing it would have provided is available
  - no other service was affected
  - nothing was sent anywhere and no data was discarded
```

## Security and privilege separation

| Question | Answer |
|---|---|
| Who may submit a plan? | Only `capability.engine.evaluate()` produces one with a valid identity; anything else is refused at `revalidate_plan` |
| Who may approve? | An `ApprovalStore`. The default grants nothing |
| Who may operate the service manager? | A `SystemdBackend` constructed with `allow_host_modification=True` |
| Which units may be controlled? | Only those derived from shipped manifests, by a fixed naming rule |
| Which cgroup subtree? | `<root>/bunny-os.slice` and nothing else, verified after path resolution |
| Which files are written? | The ledger, the retry journal, the audit log — all at caller-supplied paths |
| How are providers authenticated? | Outside this layer; `ProviderIdentity.authenticated` records only that it succeeded |
| How are replayed plans rejected? | Revision must be strictly higher than the plan in force |
| How are stale approvals rejected? | Expiry, plus invalidation on plan supersession |
| How are fingerprints validated? | Recomputed from live inputs and compared, before any transition |
| How does privilege separation work? | The applicator escalates nothing. It runs with whatever it was given and reports `permission_denied` |
| How is a dry run isolated? | `DryRunBackend` has no code path calling a mutating method on its observer |

Plans, manifests and provider responses are treated as **untrusted structured
input** and validated before use.

## Constrained-node implications

The runtime cost of this architecture, stated so a decision can be made about it
later:

- **Pure Python, standard library only.** No new dependency. `hashlib`, `json`,
  `threading`, `subprocess`, `pathlib`, `re`, `dataclasses`.
- **No resident database.** One JSON file for the ledger, one for the retry
  journal, one append-only audit log.
- **No polling loop.** `RuntimeMonitor.due()` gates sampling; nothing here owns
  a thread or a timer.
- **Selectively enabled monitoring.** A constrained node enables
  `CONSTRAINED_SIGNALS` — memory only, 300s cooldown.
- **Serializable, language-neutral interfaces.** Every type has `to_json()`.
  The plan, the runtime state and the audit record all have JSON Schemas. A
  constrained agent written in another language can implement the same
  control-plane contract.

**Components that would likely need a compiled implementation on a very
constrained node:** `applicator.py`, `reconcile.py` and `ledger.py` — the parts
that must run on the node itself. `identity.py`, `revalidate.py` and `monitor.py`
are small enough to port directly. `explain.py` and the CLI need not exist on a
constrained node at all; they can run wherever the operator is.

**This is not a "Lite" edition.** A constrained node may use a different
implementation of the same control-plane contract. It is the same Bunny OS,
running fewer things, and saying which and why.

**No memory figure is claimed.** Nothing in this package has been measured for
resident size, on a 64 MB board or anywhere else. See `KNOWN_LIMITATIONS.md`.

## Known limitations

- **Nothing has run on physical hardware.** Every result comes from simulated
  inventories and modelled backends.
- **The systemd backend has never talked to systemd.** It is driven in tests
  through an injected runner returning captured `systemctl` output. No unit has
  been started, stopped or frozen by this code.
- **The cgroup backend has never written to a real cgroup hierarchy.** It is
  tested against directory trees in `tempfile`, which reproduce the file layout
  but not kernel semantics: a real `memory.max` write can be rejected, clamped
  or partially honoured in ways a plain file cannot model.
- **No remote provider exists.** `TestProvider` sends nothing anywhere.
- **The applicator is not wired into the image.** Like `capability/`, it is not
  copied by `build/scripts/install-root.py`. Nothing runs it on a booted system,
  and no unit invokes it on a timer.
- **Retry deadlines are monotonic and do not survive a reboot.** A restored
  journal has deadlines in the past, so every service is immediately due. That
  is deliberate — a reboot genuinely is a fresh chance — and the attempt count
  is what stops it looping.
- **The single-pass transition cap is 32.** A larger plan converges across
  several passes. The cap is logged when it bites.

## Reading order

1. `docs/CAPABILITY_RUNTIME.md` — the engine that decides
2. This document — the layer that acts
3. `capability/apply/identity.py` — plan identity, first because everything
   downstream validates against it
4. `capability/apply/state.py` — the three state models
5. `capability/apply/reconcile.py` — the algorithm
6. `capability/apply/applicator.py` — the transactions
7. `capability/apply/systemd.py` and `cgroup.py` — the dangerous parts
