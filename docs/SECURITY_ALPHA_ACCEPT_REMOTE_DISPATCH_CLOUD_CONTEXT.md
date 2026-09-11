# Alpha CODE accept — `remote_dispatch` vs `PrivacySettings.cloud_context=none`

**STATUS:** ACCEPTED for Alpha at CODE  
**Owner:** Bunny OS Security Engineer  
**Date:** 2026-09-11  
**Base:** `main` after Memory Core PR #50 (`b4b4a139`). Extra forbidden markers from that PR (`memory_body`, `memory_hits`, `recall`) remain complementary tightenings; this accept does not reopen them.

Allowlist P0 is a separate, primary fence. This memo does not change destinations, CVE disposition, or network filtering.

---

## Decision (authoritative)

These are **two consents**. Conflating them is the defect this accept closes.

| Consent | What it gates | Alpha default |
|---|---|---|
| `PrivacySettings.cloud_context` | **Memory / cloud-context egress** — durable records, session memory, conversation-summary / `summary_text` | `none` (off) |
| `remote_dispatch` | **This-interaction online generate** of current-request allow-listed fields only (`REMOTE_GENERATE_ALLOWED_FIELDS`) | denied until granted for this plan |

Therefore:

1. `cloud_context=none` **MUST NOT** silently block an already-granted `remote_dispatch` current-request hop.
2. `authorize_remote_generate` **MUST** keep refusing `summary_text`, conversation-summary, durable, and `memory_records` as a **whole payload** (no strip-into-leak).
3. Conversation-summary stays **unwired**. Filling that slot is a new Security review, not a silent follow-on.

`authorize_cloud_context` remains the memory/cloud-context gate. On `cloud_context=none` it still refuses. `authorize_remote_generate` is the hop gate. After a granted `remote_dispatch` it may release only the current-request allow-list, using an effective policy that keeps session/durable off. The person's `cloud_context=none` is recorded at the SECURITY CO-SIGN HOOK and is not a veto of that hop.

Do not reverse the hook's `pass` into a refuse without a new Security decision.

---

## What is accepted

- Source behavior in `companion/memory_boundary.py` `authorize_remote_generate` on this base.
- CODE tests in `tests/companion/test_remote_dispatch_cloud_context.py`:
  - `cloud_context=none` + `remote_dispatch_granted=True` + current-request-only payload → **allowed**
  - the same plus `summary_text` or `memory_records` (also conversation-summary / durable) → **refused, `released is None`**
  - the same current-request payload through `authorize_cloud_context` with `cloud_context=none` → **refused** (proves the gates are not the same function)
- Existing `#48` `CloudContextWire` tests remain in force.
- Companion `RemoteProviderExecutor.result` already calls `authorize_remote_generate` only after a granted `remote_dispatch` for that plan, with a current-request-only payload. Conversation-summary items in the built context are refused separately.

## What is not accepted

- Live online generate, guest boot, image build, or network allowlist completeness.
- Memory Core OS-keystore wrap, live retrieval quality, or any claim that durable memory is “safe to dump” because this hop is allowed.
- Expanding `REMOTE_GENERATE_ALLOWED_FIELDS`.
- Wiring conversation-summary into local or remote generate.
- Changing TrustPrompt chrome in this PR (see disclosure below).

---

## Residual risks

- A future change that feeds `policy` into `authorize_cloud_context` **instead of** the effective current-request policy would silently turn `cloud_context=none` into a hop veto and break this accept.
- A future change that **strips** forbidden keys instead of refusing the whole payload would leak a current-request remainder beside a summary the person never approved.
- `RemoteProviderExecutor` does not yet pass the person's `MemoryPolicy` into `authorize_remote_generate`. Behavior is unchanged (the hop already uses the effective current-request policy). The hook is exercised by CODE tests that pass `policy=MemoryPolicy(cloud_context="none")`.
- `remote_dispatch` copy today names the destination, not the two-consent split. A person with cloud memory off may think they are turning cloud memory on. Mitigation is the disclosure sentence below, not a silent hop block.
- Allowlist / destination filtering remains a separate P0. This accept does not claim the hop can only reach an intended host.
- `#50` added complementary forbidden markers (`memory_body`, `memory_hits`, `recall`). This accept already locks `summary_text` / conversation-summary / durable / `memory_records`. Additional markers are tightenings, not a reopening of the two-consent decision.

---

## When to revisit

Re-open this accept **before**:

1. Wiring conversation-summary (or any recall/summary slot) into generate — local or remote.
2. Expanding the online path: new allow-listed fields, session/durable riding along, tool proposals from remote, or passing the person's `cloud_context` as the hop policy.
3. Changing TrustPrompt / approval chrome so that `remote_dispatch` and cloud-memory share one control.
4. Public beta, if Alpha field evidence shows people grant `remote_dispatch` believing it enables saved cloud memory.

Until then, CODE on this hop is **ACCEPTED for Alpha**.

---

## Suggested TrustPrompt disclosure

No existing TrustPrompt string hook covers this split. Companion `remote_dispatch` uses `ApprovalRequirement.reason` (`companion/approvals.py`), not `trust.explain.TrustPrompt`. **Docs-only until TrustPrompt hooks it**; this accept does not invent UX chrome.

When Companion offers `remote_dispatch` and the person's `cloud_context` is `none`, say:

> Cloud memory stays off. Allowing this sends only what you asked this time to that online service — not your saved memory, session memory, or a conversation summary.

Pair that sentence with **Allow once** / **Don't allow** (Deny focused). Do not add Always allow, a second prompt, or a new toggle in the same change.

Advanced / diagnostics copy may still say “allowed fields” (`REMOTE_GENERATE_ALLOWED_FIELDS`). Person-facing TrustPrompt copy must not.

This sentence does **not** imply network allowlist enforcement. Destination filtering remains a separate P0. Granting `remote_dispatch` is consent for this-interaction current-request generate, not a claim that the hop can only reach an intended host.

---

## CODE evidence

Host unit tests only. No GPU, no GGUF, no guest, no image, no boot.
