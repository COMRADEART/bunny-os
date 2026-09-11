# Capsule network allowlist — deny-by-default boundary

**Status of this document:** design plus the fail-closed implementation
shipped with it. Not a guest measurement. Not an image or boot claim.

**Baseline:** `main` at `23ecc964`, after the host security inventory in
PR #44. That inventory restated a fact already measured in a guest and
already disclosed: only `network=none` used `--unshare-net`;
`loopback`, `local-network` and `allowlisted` mapped onto full internet
access.

**Historical guest (do not restate as current evidence):** a capsule
granted `example.com` connected to `example.org`. Re-verification on a
bootable Bunny image is **NOT_RUN** in this change.

---

## 1. What a real allowlist boundary would have to do

Deny-by-default means:

1. A capsule with no network grant has no network namespace
   (`--unshare-net`). Already true.
2. A capsule granted `internet` has a network namespace. Already true.
3. A capsule granted named destinations may reach **those destinations
   and nothing else** — not “those destinations, and also the rest of
   the internet because we asked nicely.” That third clause is what
   this build did not have.

A user-facing string that names a domain (`Network: example.com only`,
`wants to connect to api.example.com`) is a claim about (3). Companion
UX must not make that claim until kernel- or mediator-enforced
filtering exists and has been measured.

Until then, **only Off / `none` may read as an absolute restriction.**
On / `internet` may read as open. Everything between is either a real
filter or a refusal.

---

## 2. Options

### A. nftables (or iptables) inside a dedicated netns

**Shape.** Do not attach the capsule to the host network namespace.
Create a netns with a veth pair, run a host-side forwarder, and install
a deny-by-default `nft` table that allows established/related plus an
explicit destination set.

**What it could enforce.** IP and port, if the set is populated with
resolved addresses. Loopback vs not-loopback. Possibly “local subnet”
if the host routes are known.

**What it cannot enforce by itself.** A domain name. DNS is a TOCTOU:
resolve `example.com` now, connect to that A record, later the name
points elsewhere — or connect to an allowed IP and send `Host:
example.org` / a different TLS SNI. Pinning IPs without pinning name
and SNI is a partial boundary and must not be labelled “example.com
only”.

**Cost / fit.** Needs a netns + veth + nft helper beside `bwrap`,
privilege to configure that helper, and a resolver policy. Does not
fit the current isolation planner, which only decides whether `net` is
in `unshare`. Not straightforward.

### B. Landlock net (Linux 6.7+ TCP bind/connect)

**Shape.** Landlock network rules on `connect(2)` / `bind(2)` for
specific ports or, in later ABI revisions, more of the socket path.

**What it could enforce.** A port-level connect/bind restriction in
the same process that `bwrap` already sandboxes.

**What it cannot enforce.** Destination hostname. Current Landlock net
is not “these DNS names”. Host support is also not guaranteed on every
kernel Bunny images target.

**Cost / fit.** Attractive later if the ABI grows destination matching
and the image kernel floor includes it. Not available as a domain
allowlist today. Not straightforward.

### C. Userspace proxy / SOCKS / HTTP CONNECT mediator

**Shape.** Capsule netns has no default route except to a host
mediator. The mediator is the only thing that performs DNS and
outbound connect. The allowlist is applied there (name, maybe SNI).

**What it could enforce.** Named destinations, if the capsule cannot
bypass the proxy (no other route, no raw sockets, DNS only via the
mediator).

**What it cannot enforce without help.** An application that talks raw
TCP to an IP it already knows, unless the netns routing and seccomp
make that impossible. Also a new host daemon, a new failure mode
(mediator down ⇒ no network), and a new audit surface.

**Cost / fit.** Real filter, real complexity, new process in the
trusted computing base. Not straightforward and not a small PR.

### D. Fail-closed: only `none` and `internet` until a filter exists

**Shape.** Keep the two classes this build can actually hold:

| Class | Mechanism | User-facing |
| --- | --- | --- |
| `none` | `--unshare-net` | **Off** — absolute |
| `internet` | no net unshare | **On** — the whole network |

Refuse `loopback`, `local-network`, and `allowlisted` at policy time
with `not-enforceable`, the same reason clipboard and Bluetooth use.
Do **not** record a grant the sandbox will not honour. Do **not** map
those classes onto internet access. A stale stored allow is ignored
by both policy (new requests) and the isolation planner (launch).

**What it enforces.** Deny-by-default for every class this build
cannot filter. No silent upgrade from “example.com” to the internet.

**What it does not enforce.** Per-domain, per-subnet, or loopback-only
connectivity. Those remain catalogue *declarations* of what an
application would need, not grants.

**Cost / fit.** Fits the existing planner and TrustGate. Host-testable
without a guest. Companion cannot bypass it: the surface never sees a
prompt, and a launch plan with a stale grant still unshares net.

---

## 3. Decision

**Ship D now.** A, B and C are the right long-term filters and are
out of scope for a boundary-honesty PR: each needs new runtime
machinery and guest evidence this tree cannot produce until Platform
has a bootable image.

Align with the clipboard / Bluetooth pattern rather than the previous
“record it, map it to internet, disclose the lie” pattern. Recording
an unenforced allowlist taught people that a named domain was a
permission. Refusing does not.

**Do not raise catalogue ceilings to `internet` as part of this
change.** LibreOffice still declares `allowlisted` /
`extensions.libreoffice.org`. That application will not receive
network until a real filter exists or a separate catalogue decision
explicitly raises the ceiling. Silent widening would be the other
bypass.

---

## 4. Enforcement points (what the code does)

Order matches `trust.policy.resolve` and `capsules.isolation.plan_isolation`.

1. **Malformed / store / not-declared / beyond-ceiling** — unchanged.
   Asking for `internet` under an `allowlisted` ceiling remains
   `beyond-ceiling`, not a silent upgrade.
2. **Unenforceable category** — clipboard / Bluetooth, unchanged.
3. **Unenforceable network class** — new. If the requested class is
   not in `NETWORK_ENFORCEABLE_CLASSES` (`none`, `internet`), deny
   `not-enforceable` *before* standing grants and *before*
   catalogue-default. A stale allow does not keep allowing.
4. **Isolation planner** — defense in depth. An allow grant whose
   class is declared-only is refused at plan time, `network` stays
   `none`, `net` stays in `unshare`, resolver files are not bound.
   The launch path cannot open the internet for a grant policy would
   have refused.
5. **Companion / TrustPrompt** — no prompt for those classes, so no
   “connect to example.com” headline. Status continues to derive Off
   from the plan (`none` + `net` unshared). Resource *display* for
   `allowlisted` no longer lists domain names.

The TrustPrompt JS surface does not compose permission sentences; it
renders `trust.explain`. Copy changes belong in `trust.explain` and
the status phrases, not in a second vocabulary.

---

## 5. UX contract

| Situation | What a person may be told |
| --- | --- |
| No network grant / class `none` | Network: **Off**. Absolute. |
| Grant of `internet` | Network: **On**. The internet. |
| Request for `allowlisted` / `loopback` / `local-network` | Denied. “Bunny can't enforce that in this build, so it won't record permission for it.” No per-domain language. |
| Stale stored allowlist grant | Not applied. Plan remains Off. Refusal recorded on the plan. |

No surface may say “example.com only”, “only this computer”, or
“your local network” as a *held* restriction until a filter exists
and a guest run has shown a denied destination.

---

## 6. Follow-up (not this PR)

When Platform can boot an image:

1. Re-run the historical pair: grant `example.com`, connect to
   `example.org` — expected **denied** at policy, and if a stale
   grant is planted, **no** egress from the sandbox.
2. Re-run `none`: no external, no DNS, no loopback.
3. Re-run `internet`: egress works.

A later PR may pick A, B or C. The fail-closed gate stays until that
PR has guest evidence; it must not be relaxed to “record and
disclose” again.

---

## 7. Verification (this change)

See the STATUS block at the end of the implementing PR description.
Host unit tests cover policy, isolation (including a planted stale
grant), explain/prompt absence, and capsule status copy.

**Guest / bwrap / IMAGE / BOOT: NOT_RUN.** This environment has no
Bunny guest and no claim is made about one.
