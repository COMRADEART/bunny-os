# Qualifying the update refusal

**§10 option B is a claim about behaviour, and behaviour has to be measured.**

Declaring updates unsupported is cheap. What makes it a release position rather
than a sentence is evidence that the system *refuses*, closed, on every route,
and that the refusal was observed rather than inferred from reading the code.

This is that evidence.

| | |
| --- | --- |
| Instrument | `refusal_probe.py` |
| Instrument's own tests | `tests/update/test_phase6_refusal_probe.py` — 12 tests |
| Subject | `localhost/bunny-os-beta:e906a48793d7` (`sha256:c87a6616…`) |
| Method | container from the artifact's own image, `--network=none` |
| Checks | **18 of 18 AS_INTENDED** |
| Negative control | **UNEXPECTED — 7 of 18 checks flipped** |
| Run record | `evidence/refusal-qualification.json` |
| Control record | `evidence/negative-control/refusal-qualification.json` |

---

## 1. Why the negative control is the important half

Seventeen refusals prove nothing on their own. "The agent refused" is equally
consistent with:

* the trust store being empty — the claim being made;
* `openssl` being absent from the image;
* `KEY_DIR` pointing somewhere that does not exist;
* the probe calling a function that always raises.

**B3 separates them.** It generates an Ed25519 key pair, installs the public
half into the image's own trust store, signs a canonical manifest payload with
the private half, and hands the result to the shipped verifier. It **verifies**.

So when B1 refuses an unknown key and B4 refuses a manifest whose payload was
altered by one field, those refusals are about the trust store's contents, not
about a verifier that cannot say yes.

The second control is at the level of the instrument. The whole probe was re-run
against the same image with a signing key planted and `enabled: true` written
into the configuration. **Seven checks flipped to UNEXPECTED** — A1, A2, A4, A5,
A6, A7 and C1 — and the run result became `UNEXPECTED`. The probe can fail. It
was not failing here because there was nothing to fail on.

Equally important: **B3, B4 and D1–D3 did not flip**, because none of them
depends on the store being empty. A control that flipped everything would be
evidence of a broken run rather than a working instrument. Both directions are
asserted in the tests.

---

## 2. The eighteen checks

### A — the image exactly as it ships

| | Question | Observed |
| --- | --- | --- |
| **A0** | On an untouched system, does `status` overstate? | `state: idle`, **`configured: true`** |
| **A1** | Any trusted signing key? | **0 `.pem` files**; the directory holds only `revoked-keys.json` |
| **A2** | What does the configuration say? | `enabled: false`, `manifestUrl` → `updates.invalid.bunny-os.example` |
| **A3** | What is revoked? | a valid, **empty** list |
| **A4** | Does `check` refuse? | exit 2, `not_configured` |
| **A5** | Does `stage` refuse? | exit 2, `not_configured` |
| **A6** | Does `install` refuse? | exit 2, `not_configured` |
| **A7** | After a refusal, what does `status` say? | `state: failed`, `not_configured` |
| **A8** | Is the timer enabled? | **no enablement symlink** under any `.wants/` |

### B — the trust store, against the shipped code

| | Question | Observed |
| --- | --- | --- |
| **B1** | Untrusted key? | refused, `unknown_key` |
| **B2** | Revoked key? | refused, `revoked_key` — **before** the key lookup |
| **B3** | **Negative control:** correctly signed manifest? | **accepted** |
| **B4** | Signed manifest, payload altered? | refused, `bad_signature` |

### C — are the two controls independent?

| | Question | Observed |
| --- | --- | --- |
| **C1** | Valid key installed, config still disabled? | still refused, `not_configured` |
| **C2** | Updates enabled, no reachable source? | refused, `download_failed` — fails closed |

C1 matters because "it refuses" could have had a single cause. It has two, and
either alone is sufficient: an empty trust store, and a configuration that
disables the feature before the store is ever consulted.

### D — downgrade protection

| | Question | Observed |
| --- | --- | --- |
| **D1** | Sequence below the accepted high-water mark? | refused, `rollback_attack` |
| **D2** | Replay of the accepted sequence when staging? | refused, `rollback_attack` |
| **D3** | Higher sequence — how far does it get? | reaches the signature check, refused `bad_signature` |

---

## 3. Two things this found that were not in the record

### `status` answers two different questions depending on when you ask

`perform("status")` returns the **stored status file** when one exists, and only
computes a fresh `idle` when none does. So on a clean system it reports
`configured: true`, and after any failed action it reports that failure instead.

Both are called "status". Only the first is a statement about configuration.

This was found by the probe getting it wrong. The first version asked `status`
*after* `check`, `stage` and `install`, so it read the leftover failure record —
and **passed anyway**, because it asserted only the exit code. The check named
`configured: true` and never looked at it. The probe now asks first (A0) and
asserts the value, and asks again afterwards (A7) asserting the other one; the
ordering requirement is itself a test.

That is the fourth instance in this project of a check passing while measuring
something other than what it named, and it was caught by looking at the observed
column rather than the verdict column.

### Authentication happens last

`_verify_signature` is the **final** call in `_validate_manifest`. Schema,
sequence, channel, architecture, contract version, OS and image versions,
optional fields, release-notes URL, image digest, image reference, publication
and expiry times, sizes and the anti-rollback comparison are all evaluated
**before** the manifest is known to be authentic. D3 is what locates it: a
manifest with a valid-looking higher sequence gets all the way through those
checks and is stopped only at the signature.

The exposure is bounded — the fetch is capped at 256 KiB and the parsing is pure
Python — and for this release class it is unreachable, because `enabled: false`
stops the request two gates earlier and no key could validate the result anyway.

It is recorded because §5 says the reviewer must be able to verify the reasoning
independently, and a reviewer should be handed this rather than left to find it.

---

## 4. What this evidence does not establish

* **A container is not a booted system.** These checks exercise the shipped
  agent, configuration and trust store from the artifact's own filesystem. They
  do not exercise systemd activation, timer scheduling, or behaviour under a
  real network stack. A8 reads enablement symlinks statically instead of asking
  systemd.
* **It says nothing about whether the update design is sound.** It establishes
  that the mechanism is unreachable and that its refusals are real. Whether the
  design would be safe if a key existed is a question for the independent
  security review, and §10's rotation answer already names a gap it would find.
* **It closes no matrix row.** All thirteen update scenarios remain `NOT_RUN`.
  Nothing was executed, and the matrix records what was executed.
