# Capability runtime: trust boundaries and security properties

Companion to `docs/THREAT_MODEL.md` and `docs/PRIVACY_MODEL.md`, scoped to
`capability/`.

## Trust boundaries

```text
+----------------------------------------------------------------+
|  the machine: sysfs, procfs, vendor tools, block devices        |  UNTRUSTED INPUT
+----------------------------------------------------------------+
                        |  capability/discovery/sources.py
                        v  allowlist, timeouts, size caps, sanitisation
+----------------------------------------------------------------+
|  inventory: strings, ints, bools, all with provenance           |  TRUSTED DATA
+----------------------------------------------------------------+
                        |  pure functions only
                        v
+----------------------------------------------------------------+
|  scores -> budgets -> plan                                       |  NO I/O AT ALL
+----------------------------------------------------------------+

+----------------------------------------------------------------+
|  /etc/bunny-os/capability-policy.json    (system, root-owned)   |  CONFIGURATION
|  $XDG_CONFIG_HOME/bunny-os/capability.json (user, narrowing)    |
|  capability/services/*.json              (image-owned)          |
+----------------------------------------------------------------+
```

The capability runtime **holds no privilege**. It reads, computes and reports.
It does not start processes, write to `/etc`, call the broker, or mutate any
system state — producing an execution plan is a read-only operation. Whatever
applies a plan is a separate component with its own authority, and it is not in
this package.

## Probe execution

`capability/discovery/sources.py` is the only module that executes anything.

**No shell, ever.** `run()` takes an argv list whose first element must be an
absolute path on `ALLOWED_COMMANDS`. There is no `shell=True`, no string
command, and no `PATH` lookup. A bare command name is refused — it would resolve
through `PATH`, and a writable directory on it would become code execution.

```python
ALLOWED_COMMANDS = {
    "/usr/bin/nvidia-smi", "/usr/bin/rocm-smi", "/usr/bin/vulkaninfo",
    "/usr/bin/clinfo", "/usr/bin/lspci", "/usr/bin/systemd-detect-virt",
    "/usr/bin/nmcli",
}
```

Every entry is invoked with a **fixed argument list**. No user input, no policy
value and no parsed output ever becomes an argument. `reachabilityEndpoints`
hosts reach `socket.create_connection` and nothing else.

**Bounded time.** One `Deadline` covers a whole discovery pass and every probe
draws its slice from it. A probe cannot exceed what remains, and one that would
start after exhaustion is skipped and recorded. Per-probe timeouts would not
bound boot: twelve probes at three seconds each is a thirty-six second stall.

**Bounded size.** Subprocess output is truncated at `MAX_OUTPUT_BYTES`
(256 KiB); file reads take an explicit limit. Several `/proc` and `/sys` nodes
are effectively unbounded streams, and a probe must not be able to allocate
arbitrarily by opening the wrong one.

**Fixed environment and working directory.** `PATH=/usr/bin:/usr/sbin`,
`LC_ALL=C`, `cwd=/`, `stdin=DEVNULL`, `stderr=DEVNULL`.

**Nothing parsed is executed.** Probe output becomes strings, ints and bools.
It never becomes a path that is opened, an argument passed back to a subprocess,
or anything `eval`-shaped. `sanitize()` drops everything outside a narrow
character allowlist — dropped rather than escaped, because a capability
inventory has no legitimate use for control characters.

**No privilege is required or requested.** Every probe reads what an
unprivileged process can read. `/proc/iomem` is zeroed for unprivileged readers,
and that zeroing is *detected* and reported `unknown` rather than being read as
"nothing is reserved".

**A failing probe is not an error.** It yields `unknown` observations and a
recorded outcome. An inventory with holes is useful; an exception at boot is not.

## Network behaviour

**Nothing is contacted during a default discovery pass.** Reachability probing
requires both an explicit caller opt-in and configured endpoints; with neither,
no socket is opened. Asserted by
`test_no_network_probe_runs_unless_reachability_was_requested`.

When enabled, each endpoint gets one bounded TCP connect. **Nothing is sent on
the socket.** There is no bandwidth probe at all — an honest one means moving
real traffic on a user's connection, which this subsystem will not do.

Remote execution is off by default, requires an allowlisted named provider, and
refuses providers that have not declared retention, training use and locality.
See `docs/CAPABILITY_REMOTE_EXECUTION.md`.

## Privacy

The inventory contains **no serial numbers, MAC addresses, hostnames or machine
UUIDs**. Not redacted — never collected. `bootIdPresent` is a boolean because
the boot id itself is a machine identifier.

`privacy.identifiersCollected` and `privacy.transmitted` are `const: false` in
the schema, so a document claiming otherwise fails validation.
`test_no_identifying_information_is_collected` asserts it over every simulated
machine.

`instructionSets` records only the flags a decision actually reads. Recording
all 200-odd x86 flags would make the inventory a fingerprint.

**Nothing is uploaded.** No code in `capability/` transmits an inventory, a
score set, a budget or a plan. The documents are safe to attach to a diagnostic
because there is nothing in them to redact.

## Configuration files

| File | Owner | Trust |
|---|---|---|
| `/etc/bunny-os/capability-policy.json` | root | system policy; may permit remote execution |
| `$XDG_CONFIG_HOME/bunny-os/capability.json` | user | may only narrow the above |
| `capability/services/*.json` | the image | validated at build and at load |

`load_policy()` reports a system policy file that is **group- or world-writable**.
A capability policy decides whether remote execution is permitted and which
providers may receive data; a writable one is a privilege escalation waiting to
be used. The check is a no-op on Windows, where POSIX mode bits do not carry the
same meaning, rather than a false alarm on every development checkout.

Policy parsing **refuses rather than repairs**. A malformed value raises; it is
never silently replaced with a default, which would leave an operator believing
a limit was in force when it was not. Deprecated mode-based keys
(`performanceMode`, `hardwareTier`, ...) are refused with their replacement
named.

## Manifest validation

Manifests are safety inputs: a manifest is what tells the engine how much memory
a service needs *before* that service is started.

- Per-manifest validation raises on anything it cannot trust.
- Registry validation refuses a set that disagrees with itself.
- `release/validation.py` runs both as the **Capability manifests** validator, so
  a bad manifest fails the source gate rather than failing at boot.
- The JSON Schema is `additionalProperties: false` throughout, so an unknown
  field is a validation failure rather than a silently ignored one.

## Denial of service

| Vector | Mitigation |
|---|---|
| a wedged device blocking discovery | one shared deadline; probes skipped and recorded |
| an unbounded `/proc` or `/sys` node | explicit read limits |
| a vendor tool that never exits | per-call timeout, capped by the remaining deadline |
| a huge `/sys/class/*` directory | `iter_directory` entry cap |
| a pathological policy file | length-bounded hosts, capped endpoint count, numeric ranges |
| a manifest with thousands of implementations | schema `maxItems` |
| the engine over-granting memory | asserted invariant before a plan is returned |

## What this subsystem does not defend against

- **A compromised kernel.** Every measurement comes from the kernel. If sysfs
  lies, the inventory is wrong, and nothing here detects that.
- **A malicious vendor tool.** `nvidia-smi` on the allowlist is trusted to be
  the real one. Its *output* is sanitised and bounded; its *presence* at an
  absolute path is the trust decision, and it is the same decision the rest of
  the OS already makes about `/usr/bin`.
- **A hostile service manifest inside the image.** Manifests are image content,
  covered by image signing and the build gate. A manifest that passes validation
  but declares dishonest memory figures would produce over-committed plans.
  Manifest figures are declarations, not measurements — recorded in
  `KNOWN_LIMITATIONS.md`.
- **Applying a plan.** This package produces one. Enforcing it — cgroups,
  systemd properties, actual start and stop — happens in `capability/apply/`,
  which carries higher privilege requirements and its own threat model. Those
  are documented in `docs/CAPABILITY_APPLICATOR.md` and summarised below.

## The applicator's boundaries

`capability/apply/` is the only code in Bunny OS that can change a running
machine, so its trust boundaries are stated separately from the engine's.

| Boundary | Rule |
|---|---|
| Who may submit a plan | Only a plan carrying an identity that revalidates against live inventory, budget, policy and manifest fingerprints |
| Who may approve an action | An `ApprovalStore`. The shipped default grants nothing, and an unanswered sensitive request defaults to denial |
| Who may operate the service manager | Only a `SystemdBackend` built with `allow_host_modification=True`; without it every mutating method refuses before acting |
| Which units may be controlled | Only unit names derived from shipped manifests by a fixed rule. A manifest cannot name a unit, so it cannot name somebody else's |
| Which cgroup subtree may be written | `<detected root>/bunny-os.slice` only, verified to contain the target after path resolution so a symlink cannot escape it |
| How replayed plans are rejected | A plan must carry a strictly higher revision than the one in force |
| How stale approvals are rejected | By expiry, and by invalidation whenever the plan they were granted against is superseded |
| Privilege separation | The applicator escalates nothing, calls no `sudo`, and does not check whether it is privileged. It runs with what it was given and reports `permission_denied` when refused |

Command construction is the sharpest edge, and it is closed by construction:
**no string is ever interpolated into a command line.** Every systemd invocation
is an argument array run with `shell=False`, unit names are validated against a
regular expression narrower than systemd's own — no templates, no path units, no
slices — and then checked against an allowlist derived from the registry.

Two further properties are worth stating because their absence is the usual
failure mode:

- **Enforcement is never claimed on faith.** Every cgroup write is read back,
  and `EnforcedLimits` carries the requested and effective figures separately.
  A service whose limits could not be applied is rolled back rather than left
  running unconstrained, because the budget engine's arithmetic assumed a
  ceiling that would not exist.
- **Credentials have nowhere to live.** `RemoteTask` and `ProviderIdentity`
  have no field for one. Audit records are redacted on the way in, not on the
  way out, because a redactor at the read end protects nothing once the bytes
  are on disk.

What the applicator does **not** defend against:

- **A compromised service manager.** If systemd itself is hostile, an allowlist
  of unit names is not a boundary. The applicator's guarantee is that it asks
  for nothing outside that list.
- **A privileged process racing it.** The reservation ledger is
  concurrency-safe within one applicator process. Two applicators against one
  machine, or an administrator running `systemctl` alongside it, are outside
  the model — which is why an externally started unit is reported
  `externally_managed` and never touched.
- **Its own untested backends.** The systemd and cgroup backends have never run
  against real systemd or a real cgroup hierarchy. Their security properties are
  arguments about the code, not observations of behaviour. Recorded in
  `KNOWN_LIMITATIONS.md`.
