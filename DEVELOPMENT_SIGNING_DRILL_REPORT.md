# Development signing drill report

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Key class: **development**  
Result: **9 of 9 checks PASS**

**This is not release signing evidence.** Every key used carries the reserved
`dev-` prefix and is refused by `release.signing.require_production_key`. No
production key exists, no key ceremony has been held, and
`docs/PRODUCTION_SIGNING_CEREMONY.md` records the procedure that has not been
run. The `Signing` evidence row records `FAIL`.

What the drill establishes is that the signing *path* works, including its
refusals — which is the part that is easy to get wrong and impossible to notice.

## Setup

Keys generated with `openssl genpkey -algorithm ed25519`, **outside the
repository**, at `~/.bunny-dev-keys/drill/`. `scripts/signing_drill.py` refuses a
key directory inside the working tree, matching the control
`build/scripts/sign-stable-rc.py` already enforces.

Before anything else, the drill asserts that every key it just minted is refused
by `require_production_key`. If that assertion failed the drill would abort,
because nothing else about it would be safe.

| Key | Role |
|---|---|
| `dev-bunny-os-release-drill1` | osRelease |
| `dev-bunny-os-release-drill2` | osRelease (rotation replacement) |
| `dev-recovery-drill1` | recoveryImage |
| `dev-update-drill1` | updateMetadata |
| `dev-catalogue-drill1` | applicationCatalogue |

## Results

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | release-image-signing | **PASS** | signed the real beta OCI archive, 1,852,119,040 bytes |
| 2 | recovery-image-signing | **PASS** | signed the real recovery OCI archive, 1,330,872,320 bytes |
| 3 | update-manifest-signing | **PASS** | signed a channel/architecture/digest manifest |
| 4 | catalogue-signing | **PASS** | signed an organisation catalogue |
| 5 | verification | **PASS** | all four verified against their published public keys |
| 6 | key-rotation | **PASS** | 92-day overlap accepted; a rotation with a gap refused |
| 7 | revoked-key-rejection | **PASS** | usable before revocation, refused after |
| 8 | wrong-role-rejection | **PASS** | recovery key refused for osRelease; release key refused for fleetPolicy |
| 9 | corrupted-artifact-rejection | **PASS** | signature does not verify against a truncated copy |

Four of the nine are **rejections**. A signing system that cannot refuse is not
a signing system, so a rejection check that did not reject fails the drill:
`evaluate_drill` treats any non-`PASS` outcome as failing, including on the
rejection checks.

## The two that are worth reading the detail of

**Rotation without overlap is refused, with the reason:**

```text
no overlapping trust period: the replacement is published at or after the
predecessor expires, so a device that updates late would trust neither key
```

That is the failure mode that strands deployed devices, and it is the reason the
overlap requirement is enforced in code rather than described in a runbook.

**A key from one authority is refused for another:**

```text
key 'recovery-001' belongs to the recoveryImage authority but was presented for
osRelease; signing roles are not interchangeable
```

Seven authorities, disjoint namespaces, checked at parse time. See
`docs/SIGNING_ROLE_SEPARATION.md`.

## Scale of the artifacts

The signing checks ran against the real built images, not synthetic files. That
matters for check 9 in particular: truncating 64 bytes from a 1.85 GB artifact
and confirming the signature no longer verifies exercises the streaming path
that a release would actually use.

## What this does not establish

- **Nothing about release signing.** Development keys cannot satisfy a
  production gate, by construction.
- **Nothing about key custody.** These keys live in a directory. A production
  key must declare `hardware-token`, `offline-hsm` or
  `protected-signing-service`, and `parse_key_record` refuses a production key
  that does not.
- **Nothing about two-person approval.** Four of the seven roles require it.
  There is one potential signer, so those roles cannot currently be provisioned
  at all.
- **Nothing about the twelve-artifact candidate.** A stable candidate needs an
  ISO, a raw image, a QCOW2 and a recovery ISO among others. Two of the four
  bootable artifacts do not exist.

## Reproducing

```text
make development-signing-drill

python scripts/signing_drill.py \
  --release-artifact build/out/beta/bunny-os.oci.tar \
  --recovery-artifact build/out/recovery/bunny-os.oci.tar
python scripts/release.py development-signing-drill
```

The drill is safe to run in pull-request CI and is: it mints its own keys and
cannot produce a releasable artifact. The CI job additionally asserts that
`signing-roles` reports no production key, so a change that introduced one would
fail the build.

Recorded results: `operations/data/signing-drill.json`.
