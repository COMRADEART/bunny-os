# Production signing — the measured position

**Status: NOT_DONE.** No production key exists, no second signer exists, and —
measured here for the first time — **the subject artifact carries no signature
of any kind.**

---

## 1. What was measured

§12 requires that the signing process sign *the artifact being released*, and
warns: *"Do not sign a tree and assume the resulting build is equivalent."*

Before asking whether the process is sound, ask what it produced. On the
reference builder, across the entire build output tree and the whole archive:

```
find /root/bunny-os/build/out /root/bunny-build-archive -name '*.sig'
(no results)
```

**Zero signature files.** Not for the subject artifact, not for its ISO, not for
any of the ten retained builds.

The subject artifact's directory holds `BUNNY-MANIFEST.json` and `SHA256SUMS`
and no `BUNNY-MANIFEST.json.sig`. The live/ISO output directory is the same.

This is consistent with the build scripts. `build-beta-image.sh` and
`build-live-image.sh` sign the media manifest **only when
`BUNNY_MEDIA_SIGNING_KEY` is set**; it was not set for these builds. Nothing
failed, and nothing warned.

**Correction to a framing that has been carried forward.** Phase 4 described the
artifact as "development-signed", and Phase 5 measured that no key in the
register can sign for *production*. Neither established whether the artifact
carries *any* signature. It does not. "Development-signed" describes the drill
that was run against constructed inputs, not this artifact.

---

## 2. The two signing paths, and which has ever been used

| Path | Signs | Used on the subject artifact? |
| --- | --- | --- |
| `build/scripts/sign-stable-rc.py` | every artifact **individually** plus `STABLE-CANDIDATE.json`, after re-hashing each artifact against the manifest and refusing on mismatch | **No.** No `STABLE-CANDIDATE.json` exists anywhere on the builder. |
| `build-beta-image.sh` / `build-live-image.sh` | `BUNNY-MANIFEST.json` only, one detached signature over the manifest | **No.** `BUNNY_MEDIA_SIGNING_KEY` was unset; no `.sig` was written. |

**On §12's actual requirement, the stable path is correct.** It reads the
manifest, recomputes the sha256 of each named artifact, **refuses if any
mismatches**, and only then signs. `verify-stable-rc.py` re-checks every hash
and verifies a detached signature per artifact as well as over the manifest. It
signs artifacts, not a tree.

But it has never been pointed at a real build. The subject artifact uses the
other manifest format entirely, so **the release signing path and the artifact
Phase 6 is releasing have never met**.

---

## 3. Conformance against §12's requirements

| §12 requirement | State | Evidence |
| --- | --- | --- |
| Signing authority | **Absent** — `productionKeyCeremonyHeld: false` | `operations/data/signing-keys.json` |
| Controlled private-key access | **Specified** — hardware token, offline HSM or protected signing service; a plain directory is refused | `release/signing.py` `parse_key_record` |
| No private key in repository | **Observed** | no key material created or written by Phase 6 |
| No private key in qualification evidence | **Observed** | the Phase 6 refusal probe generates a control key *inside a throwaway container* and it dies with the container; no key material is in the evidence |
| Artifact digest verification before signing | **Present** | `sign-stable-rc.py` re-hashes and refuses on mismatch |
| Signature verification after signing | **Present, never exercised on a real artifact** | `verify-stable-rc.py` |
| Second-party approval | **Blocked** — four of seven roles need two people; there is one | `docs/PRODUCTION_SIGNING_CEREMONY.md` |
| Documented key ownership and rotation | **Specified** | `docs/SIGNING_ROLE_SEPARATION.md`, `docs/KEY_RECOVERY.md` |

Phase 5 measured the admission path directly: **5 keys in the register, 5
refused for production, 0 accepted**, with four constructed negative controls.
Phase 6 does not repeat that; it stands.

---

## 4. §13 — second signer

**NOT_DONE.** No approval record exists, and one cannot: the record must name a
first signer and a second reviewer who are different people.

§13's rule is observed rather than merely quoted: *"Do not infer approval from a
successful test run."* Phase 6 has produced several green runs and none of them
is an approval.

---

## 5. What would close this

1. A production key ceremony with **two people**, producing a key under
   controlled access.
2. A `STABLE-CANDIDATE.json` structure built for the artifact being released —
   or the beta/live manifest path extended to the per-artifact signing the
   stable path already implements.
3. `sign-stable-rc.py` run against that structure, then `verify-stable-rc.py`
   against the released bytes.
4. An approval record naming artifact digest, version, first signer, second
   reviewer, date and decision.

Steps 2 and 3 are engineering and could be done now. **Steps 1 and 4 need a
second person**, and step 3 is worthless without step 1 — signing with a
development key produces an artifact the project's own gate must then be
weakened to accept.

---

## 6. Recommendation, not a change

`build-beta-image.sh` and `build-live-image.sh` sign **only if**
`BUNNY_MEDIA_SIGNING_KEY` is set, and are silent when it is not. That is how an
artifact came to be described as signed while carrying no signature.

Recommended: make the build **state** whether it signed, in `provenance.json`
and in the build log, so the answer is recorded at build time rather than
discovered by a `find` two phases later.

**No change is made here.** Editing the build scripts changes a `COPY` root and
therefore the next image, during a release phase, on the strength of one
observation. That is the edit that should be proposed and reviewed rather than
slipped in — the same restraint Phase 5 applied to the scanner invocation.
