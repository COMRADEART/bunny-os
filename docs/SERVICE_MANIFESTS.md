# Service capability manifests

Schema: `schemas/service-capability-manifest.schema.json` (version 1).
Parser: `capability/manifest.py`. Registry: `capability/registry.py`.
Shipped manifests: `capability/services/*.json`.

A service declares what it needs. The engine decides whether it gets it. Nothing
in a manifest makes a decision, and there is no field in which a mode, a tier or
a hardware class could be written.

## Format

JSON, not the YAML the brief sketches. This repository validates JSON in
`release/validation.py`, ships JSON Schemas in `schemas/`, and cannot rely on
PyYAML — its own workflow validator degrades to SKIP when PyYAML is missing. A
manifest format that cannot be validated on every host is one that is not
validated, and a manifest is a safety input.

```json
{
  "schemaVersion": 1,
  "id": "bunny.companion",
  "title": "Bunny companion",
  "description": "The companion presence. One user-facing feature with five implementations.",
  "essential": false,
  "priority": "standard",
  "budgetCategory": "companion_rendering",
  "handlesSensitiveData": false,
  "requirements": { },
  "dependencies": { "requires": [], "conflictsWith": [] },
  "execution": { "suspendable": true, "restartPolicy": "on-failure" },
  "startup": { "estimatedMilliseconds": 1200, "estimatedPeakMemoryBytes": 2147483648 },
  "implementations": [ ... ]
}
```

## Fields

### `id`

Dotted, lowercase, stable: `^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9-]*)+$`. It appears
in policy files users write by hand and in explanations users read, so the
character set is deliberately narrow.

### `essential`

An essential service is part of the control plane. Three consequences, all
enforced:

- it is funded off the top, before the discretionary pool exists;
- it **must** have a local implementation — a control plane that only runs
  remotely cannot bring up the machine it runs on;
- it may only depend on other essential services — a control plane whose
  dependency can be switched off by a resource decision is not a control plane.

Essential services are also exempt from the hysteresis start margin. See
`docs/CAPABILITY_POLICY.md`.

### `priority`

A band name or an integer `0..100`. Higher wins under contention.

```text
critical 90    important 70    standard 50    deferred 30    background 10
```

The vocabulary deliberately avoids "low" and "high". Those would be correct
English for a priority band, but this is the one codebase where they are
reserved words: the project rule is that Bunny OS has no low/balanced/high/ultra
anything, and a grep for "high" in this tree should find nothing rather than find
a priority and require the reader to decide whether it is a performance mode.
`tests/capability/test_manifest.py::test_no_manifest_contains_a_mode_word_anywhere`
enforces it as a property of the shipped bytes.

Priority is a ranking among services **within one Bunny OS**, not a product
tier: every service exists on every machine.

### `budgetCategory`

Must be `essential_services` if and only if `essential` is true, and one of the
ten discretionary categories otherwise. The registry refuses a mismatch: an
essential service drawing from a discretionary pool could be outbid by an
optional one, and an optional service in the essential category would take
memory off the top it has no claim to.

### `handlesSensitiveData`

When true, **no remote implementation may be selected unless
`remoteExecution.allowSensitiveData` is explicitly true** — independently of
whether remote execution is enabled at all. Turning remote execution on does not
turn sensitive-data egress on with it.

### `requirements`

Declared at the service level (applies to every implementation) and again per
implementation (applies to that one). Both are evaluated; both must pass.

```json
{
  "memory":  { "minimumBytes": 268435456, "recommendedBytes": 402653184 },
  "cpu":     { "minimumScore": 35.0, "minimumCores": 0.5 },
  "gpu":     { "required": true, "runtime": "vulkan", "minimumVramBytes": 6442450944 },
  "storage": { "minimumFreeBytes": 2147483648, "writable": true },
  "network": { "required": false },
  "display": { "required": true, "minimumResolution": "1280x720" },
  "audio":   { "outputRequired": true, "inputRequired": false },
  "scores":  { "graphics": 60.0, "storage_performance": 30.0 }
}
```

| Requirement | Checked against |
|---|---|
| `memory.minimumBytes` | the **allocatable budget**, not free physical memory |
| `memory.recommendedBytes` | granted instead of the minimum when the budget can afford it |
| `cpu.minimumScore` | the `cpu_compute` dimension |
| `cpu.minimumCores` | `effective_cores`, which includes any cgroup quota |
| `gpu.required` + `runtime` | a usable GPU with that runtime *verified*; `"any"` means a bound driver and a render node |
| `gpu.minimumVramBytes` | the **largest single device**, never the sum |
| `storage.writable` | the root mount's `ro` flag |
| `display.minimumResolution` | the widest published connected mode |
| `scores.<dimension>` | any scored dimension, so a service can gate on `storage_performance` without a bespoke field being invented |

Memory is checked against the budget rather than against free memory so that the
protected reserve cannot be consumed by an optional service merely because the
kernel happens to have the pages free.

### `dependencies`

`requires` defers a dependent until its dependency is running.
`conflictsWith` **must be declared symmetrically** by both services, or the
engine's verdict would depend on evaluation order. Cycles are refused.

### `execution`

`suspendable` decides whether a running service that no longer fits is
`suspend`ed or `stop`ped. `restartPolicy` is `never`, `on-failure` or `always`.

## Implementations are the degradation ladder

The brief lists degradation steps separately from implementation selection. They
are the same mechanism seen twice, and modelling them once means the two cannot
disagree.

```json
"implementations": [
  { "id": "animated-3d",   "rank": 1, "locality": "local",
    "requirements": { "memory": {"minimumBytes": 2147483648},
                      "gpu": {"required": true, "runtime": "vulkan"},
                      "display": {"required": true, "minimumResolution": "1280x720"},
                      "scores": {"graphics": 60.0} } },
  { "id": "animated-2d",   "rank": 2, "locality": "local", "...": "..." },
  { "id": "static-avatar", "rank": 3, "locality": "local", "...": "..." },
  { "id": "audio-only",    "rank": 4, "locality": "local", "...": "..." },
  { "id": "text-only",     "rank": 5, "locality": "local",
    "requirements": { "memory": {"minimumBytes": 25165824} } }
]
```

Rank 1 is the richest. The engine walks upward and takes the first whose
requirements are met. Ties are broken by id so the walk is stable — an unstable
order would make selection non-reproducible for the same inventory.

**Design the floor of the ladder to need nothing.** `text-only` requires 24 MiB
and no hardware at all, which is why the companion is present as a feature on
every machine that can afford 24 MiB, in the same vocabulary, with the same
controls. That is what "one Bunny OS" means in a manifest.

### Remote implementations

```json
{ "id": "remote-node", "rank": 4, "locality": "remote",
  "provider": "bunny-node", "costsMoney": false,
  "requirements": { "memory": {"minimumBytes": 50331648},
                    "network": {"required": true} } }
```

- `provider` is required in practice: an unnamed destination cannot be
  allowlisted, so it could never be authorised.
- `sendsUserDataRemotely` defaults to true for remote implementations and **may
  not be set false** — that cannot be true of remote execution.
- A remote implementation still declares a memory requirement: its client-side
  footprint. A remote path is not free by assumption.

## Registry validation

`build_registry()` refuses a set that disagrees with itself:

- duplicate service ids
- a dependency no manifest declares
- an essential service depending on an optional one
- an asymmetric conflict
- a dependency cycle
- an unknown budget category, or one that disagrees with `essential`

`release/validation.py` runs this as the **Capability manifests** validator in
`python scripts/task.py validate`, so a bad manifest fails the source gate
rather than failing at boot on the machine it was meant to describe.

## Start order

`Registry.start_order()` is essential first, then descending priority, then id,
rearranged so dependencies precede dependents. It is total and stable: ties are
broken by id rather than by directory listing order, which differs between
filesystems and would make a plan depend on which machine produced it.

## Adding a service

1. Write `capability/services/<id-with-dashes>.json`.
2. Choose the floor of the ladder so the feature degrades rather than
   disappears, unless it genuinely cannot.
3. Set `handlesSensitiveData` if it touches user content.
4. `python scripts/task.py validate` — the manifest validator must pass.
5. `python scripts/task.py test-capability` — the shipped-manifest tests assert
   the essential floor still fits a 64 MB machine.
6. `bunny-os capability plan --simulate embedded-64mb` and
   `--simulate multi-gpu-ai-server`, and read both explanations.
