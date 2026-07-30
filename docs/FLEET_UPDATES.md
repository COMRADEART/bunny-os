# Fleet updates

Implementation: `enterprise/fleet.py`. Tests: `tests/fleet`.

## Rings sit above channels

The update manifest keeps its closed three-value `channel` enum and its mandatory Ed25519 verification, exactly as `docs/UPDATES.md` describes. A ring only decides *when* a device is offered an already-signed manifest and to what fraction of a group. An organisation gains scheduling control and no influence over trust.

`signatureVerificationRequired` is not a setting. Supplying `false` is a rejection, so there is no representable ring configuration that turns verification off.

## Rings

`internal-test`, `early-validation`, `general-deployment`, `deferred`, `emergency`.

Promotion runs in order through the first three; skipping `early-validation` is refused. `emergency` may be entered directly.

## Controls

Percentage rollout, hardware exclusions, deadline, pause, withdrawal, maintenance window, AC-power requirement, and reboot reminder. A withdrawn update must have rollout 0. A paused or withdrawn ring offers zero devices.

Forced restart requires `forcedRestartPolicyReference` naming the explicit organisation policy that permits it, and a `deferred` ring cannot force a restart at all.

## Reportable states

`not-offered`, `offered`, `downloading`, `staged`, `restart-required`, `healthy`, `failed`, `rolled-back`, `deferred`.

A `failed` or `rolled-back` report must set `rollbackAvailable: true` and name the `previousVersion` that remains selectable. A failed fleet update that did not preserve rollback is a rejected report, which is how the rollback guarantee is enforced rather than assumed.

## Never recorded

What the user was doing when an update ran. `PROHIBITED_UPDATE_CONTEXT` refuses active application, foreground window, open files, current task, window title, terminal command, and the rest, with a privacy-specific message rather than a generic unknown-field error.

## Groups

Organisation, site, department, device purpose, hardware family, update ring, risk group, support group. Group attributes may not describe personal behaviour; productivity, activity, usage hours, keystroke counts, attendance, and application usage are refused by name.

## Simulation is not evidence

`make fleet-simulation` computes rollout arithmetic over synthetic counts and writes `build/out/phase7/fleet-simulation.json`. It performs no device, image, signature, or network operation. No fleet update has ever been delivered to a real device.
