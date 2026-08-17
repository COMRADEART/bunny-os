# Production signing — conformance against §19, and what actually enforces it

**No production key exists. None was created in Phase 5, and creating one would
have been wrong.**

§19 asks for a signing workflow with six properties. Five of them are already
specified in this repository, in detail, and were before Phase 5. The sixth is
not an engineering task. What Phase 5 adds is **a check that the refusals
refuse** — because a signing policy nobody has tried to violate is a policy
nobody has tested.

---

## 1. Conformance

| §19 requirement | State | Where |
| --- | --- | --- |
| Production signing key | **Absent** — `productionKeyCeremonyHeld: false` | `operations/data/signing-keys.json` |
| Controlled access | **Specified** — production keys must be a hardware token, offline HSM, or protected signing service; a directory is refused | `release/signing.py`, `parse_key_record` |
| Second signer / approval | **Specified and blocked** — four of seven roles require two-person approval; there is one potential signer | `docs/PRODUCTION_SIGNING_CEREMONY.md`, entry condition 1 |
| Artifact digest verification | **Present** | `build/scripts/verify-stable-rc.py`, `verify-bunny-artifact.py` |
| Signed artifact verification | **Present, development-only** | `build/scripts/sign-stable-rc.py` / `verify-stable-rc.py`; drill evidence in `DEVELOPMENT_SIGNING_DRILL_REPORT.md` |
| Documented key ownership | **Specified** — seven authorities, disjoint namespaces, role separation | `docs/SIGNING_ROLE_SEPARATION.md`, `docs/KEY_RECOVERY.md` |

**The single blocker is a person.** The ceremony's first entry condition reads:

> **Two people.** Four of the seven roles require two-person approval. There is
> currently one potential signer, so the ceremony cannot legitimately produce
> an `osRelease`, `updateMetadata`, `recoveryImage` or `oemProfile` key.

Phase 5 does not attempt to route around that. A ceremony held by one person
would produce a key that the project's own gate would then have to be weakened
to accept, and §23's rule — never change "required" because it is inconvenient
— applies to this at least as much as to a matrix row.

**No private key material was created, handled, or written anywhere by Phase 5,
and no secret appears in Phase 5 evidence.** §19's two prohibitions, stated as
having been observed rather than intended.

---

## 2. What Phase 5 measured

Run against `operations/data/signing-keys.json` as committed. Every key in the
register was put through the admission path a release would use —
`parse_key_record` for register admission, then
`require_production_key(parse_key_id(...))` for the production gate.

    productionKeyCeremonyHeld: False
    keys in register: 5

    refused for production: 5
      dev-bunny-os-release-drill1    role=osRelease
      dev-bunny-os-release-drill2    role=osRelease
      dev-recovery-drill1            role=recoveryImage
      dev-update-drill1              role=updateMetadata
      dev-catalogue-drill1           role=applicationCatalogue

    accepted for production: 0

**Nothing that exists can sign a release.** That is the claim Phase 4 made in
words — "the artifact is development-signed" — measured rather than asserted.

### The negative controls

A refusal that has never rejected anything is not evidence. Four records were
constructed and pushed through the same path:

| Record | Result |
| --- | --- |
| Production key id, development directory, two-person approval claimed | **refused** — "production key storage must be a hardware token, offline HSM, or protected signing service; got 'development-directory'" |
| Production key id, hardware token, **no** two-person approval | **refused** — "the `osRelease` authority requires two-person approval" |
| The real development `osRelease` key, unmodified | **refused** — "is a development key and can never satisfy a production release gate" |
| Production key id, hardware token, two-person approval claimed | **accepted** |

Three independent refusals, each firing on its own condition. The fourth row is
the one worth reading carefully.

---

## 3. The thing this does not enforce, said plainly

**The register asserts custody. It does not prove it.**

The fourth control was *accepted*, and correctly: a record that declares a
hardware token and two-person approval satisfies every check, because the
checks read a JSON file. Nothing in this path verifies that a hardware token
exists, that two people were present, or that the public key at
`publicKeyReference` corresponds to a private key anyone controls.

That is not a defect at this stage — the register is committed, reviewed, and
currently contains only development keys, so the declaration and the reality
are both trivially checkable. It becomes one the moment a production key
exists, because from then on the gap between "the file says two people
approved" and "two people approved" is the whole of the control.

**Recorded here so that it is a known property rather than a discovery.** When
the ceremony is held, the register entry should be accompanied by evidence a
verifier can check independently of the register: the token's attestation, both
signers' own signatures over the key record, and a public key published
somewhere reachable without the artifact being verified — which is entry
condition 5 of the ceremony, already written down.

---

## 4. What signing blocks, and what it does not

| Gate | Effect |
| --- | --- |
| `Second production signer available` | **BLOCKED** — not NOT_RUN. It waits on a person, not on work. |
| Any release-qualified label | Impossible. `require_production_key` refuses every existing key. |
| The Alpha Release Candidate | **Unaffected.** An alpha candidate is not a release; Phase 4 said so and the gate agrees. |
| Update manifests | **Not blocked for qualification.** The update path can be exercised with `dev-update-drill1`, whose signature the agent's own validator accepts, and the resulting evidence carries `keyClass: development` so it can never be mistaken for a release. |

That last row matters for §20. Update and rollback can be qualified as
*mechanisms* with development keys without touching production signing at all,
provided every record says which class of key it used — which the existing
evidence already does.
