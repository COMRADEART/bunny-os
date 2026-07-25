# Bunny OS Phase 0: Product Constitution and North-Star Specification

**Version:** 1.0 · **Date:** 2026-07-24 · **Status:** Phase 0 founding document — precedes and governs all architecture, design, and implementation work

---

## How to read this document

This is a constitution, not a specification. It defines what Bunny OS is, why it should exist, what it must never do, and what must be decided or proven before architecture begins. It deliberately contains no code, no APIs, and no final technical architecture.

**Evidence discipline.** Four kinds of statements appear here, and they are typographically separated:

- **Sourced facts** carry an inline link to a primary or near-primary source. Every load-bearing external claim in this document was researched in July 2026 and the most consequential ones (platform economics, legal status, hardware benchmarks) were independently re-verified against primary sources; claims that could not be confirmed are marked **[unverified]**.
- **Repository facts** are grounded in a read-only audit of the private `COMRADEART/bunny` repository conducted 2026-07-24 via the GitHub API. The repository **was accessible** and serves as a primary source throughout; file paths are cited as evidence.
- **Recommendations** are marked as such, or appear in constitution/decision sections whose entire content is normative.
- **Assumptions** and **open questions** are explicitly labeled and collected in §20 and §22.

**Structure.** §1–§25 are the constitution proper, in the order the founding brief specifies. Three appendices follow: **A** answers the 22 required research questions explicitly, **B** states the economic and cost trust requirements, and **C** consolidates the competitive and comparative analysis that the body sections draw on. The safety-boundary taxonomy — what Bunny supports, supervises, escalates, restricts, and refuses — sits inside §10, because it is constitutional rather than supplementary.

**A note on the codebase this builds on.** The audit found the Bunny repository to be a 15-day-old, single-author, MIT-licensed TypeScript project (52 commits, v0.2.0, created 2026-07-09) with unusually high engineering discipline for its age: zero runtime dependencies, a cross-OS/cross-runtime CI matrix, a self-check suite comprising roughly a third of the codebase, and honest in-code documentation of every intentional shortcut. Most claimed features are real and verifiable (§ references throughout). Two claims are not: there is **no sandbox** (the repo's own gap analysis lists "OS-enforced sandbox" as an open P0 security item), and the **"virtual brain" memory system does not exist** (what exists is a 200-line markdown file appended by a user command). This document treats both honestly: as the two most important things Bunny must build, not as things it has.

---

## 1. Executive Summary

**The vision.** Bunny OS proposes a computing environment organized around what the user is trying to do — intents, living plans, supervised delegation, persistent memory — rather than which application to open. An animated character provides the conversational and emotional surface; an authoritative task interface shows goals, plans, permissions, costs, and history; a permission-gated agentic runtime does the work; and the whole system adapts between local models and cloud providers without changing its identity. It builds on Bunny, an existing dependency-light agentic platform with real provider abstraction, permission gating, persistent sessions, MCP support, and durable jobs.

**The opportunity.** The evidence assembled for this document points one direction with unusual consistency. Supervised, permission-gated agents won the 2024–2026 shakeout — Claude Code and Cursor grew into multi-billion-dollar run rates — while autonomy-first products failed publicly: Devin passed [3 of 20 real tasks in independent evaluation](https://www.answer.ai/posts/2025-01-08-devin.html) and cut prices 96%; Rabbit R1 saw [~95% abandonment](https://9to5google.com/2024/09/26/rabbit-5000-people-use-the-r1-daily/); Humane's Pin was [bricked when the company died](https://techcrunch.com/2025/02/18/humanes-ai-pin-is-dead-as-hp-buys-startups-assets-for-116m). Consumer trust follows a measurable gradient — [73% will let AI research, 24% are comfortable letting it transact, 10% ever have](https://www.bain.com/insights/agentic-ai-commerce-hinges-on-consumer-trust/) — which means a legible, tiered trust model is the product, not a compliance layer. Meanwhile the local-AI runtime layer is commoditized (Ollama at ~177k GitHub stars ships no memory, no task model, no trust UX), and **no credible AI-native OS exists as of mid-2026** — the lane is empty. The layer above llama.cpp-class engines — memory, plans, permissions, trust — is exactly where Bunny already lives.

**The primary recommendation.** Adopt "intent-based computing" as an *additional authoritative layer over* applications and files, never as a replacement for them; and sequence the platform ambition as: (A) Bunny as an application on existing OSes — which it already is; (B) Bunny Box, a browser-accessed, locally-hosted sandboxed environment; (C) Bunny Shell, a Wayland session on an existing immutable Linux base; (D) Bunny OS, an OCI-image distribution in the Universal Blue pattern — packaging, not product. Maintain no kernel fork, ever ([even Google concluded a kernel fork is a liability](https://source.android.com/docs/core/architecture/kernel/generic-kernel-image)), and build no new kernel, ever. The animated character is an optional presentation layer over a fully functional task interface — the graveyard of Bob, Clippy, and Cortana shows personas retire while capability layers survive.

**The biggest risk.** A single trust collapse. The Recall episode demonstrates that trust is lost at *announcement*, not at exploit — Microsoft rebuilt Recall's entire security architecture and [browsers still block it by default two years later](https://www.theregister.com/2025/07/23/brave_browse_block_microsoft_recall/). Bunny today has **no sandbox**: its Bash tool spawns real shells with model-generated strings, its own code commenting that this is "safe ONLY because Stage 1 prompts every call" — while durable jobs already run headless where nobody is watching, and interactive sessions default to auto-approved file edits. One publicized Replit-grade incident ([an agent deleting a production database through instructions that were the only control](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-coding-platform-goes-rogue-during-code-freeze-and-deletes-entire-company-database-replit-ceo-apologizes-after-ai-engine-says-it-made-a-catastrophic-error-in-judgment-and-destroyed-all-production-data)) before the sandbox and permission constitution are real would be unrecoverable for a product whose entire identity is trust. The second structural risk is a bus factor of one: a single author, however disciplined, is a Phase 0 problem in itself.

**Proposed Phase 0 conclusion.** The thesis survives scrutiny in amended form: *intent as a layer, trust as the product, character as an option, OS as packaging.* Phase 0 should close by adopting the constitution in §6, the platform sequence in §18, the decisions in §21, and the entry criteria in §23 — and by explicitly retiring the unbuilt "virtual brain" claim and the assumption that Bunny OS requires building an operating system at all in the kernel-and-distro sense.

---

## 2. Product Definition

### One sentence

Bunny OS is a local-first, permission-native computing environment in which an animated, personable agent turns user intents into visible, controllable, reversible plans — executed by interchangeable local and cloud models that never own the user's memory, trust, or identity.

### One paragraph

Bunny OS is an AI-native computing environment built on Bunny, an open agentic runtime. Instead of organizing computing around applications, windows, and files, it organizes work around intents ("get this project ready for release") that become living plans — inspectable, interruptible, resumable, and undoable. A character gives the system a face and a voice, but never hides system state and can always be turned off; the authoritative interface is a task surface showing what Bunny understands, what it proposes, what it is doing, what it is asking permission for, what resources and money it is spending, and how to take back control. Intelligence is supplied by interchangeable engines — local GGUF models when capable enough, hosted frontier models when needed — behind a provider-neutral seam, with every material change in privacy, cost, or provider disclosed. Memory, permissions, and task state belong to the user, live on the user's machine in inspectable form, and survive any change of model vendor. The long-term trajectory runs from an application on today's operating systems, through a browser-accessed sandboxed workspace, to a session shell, and eventually to a Linux-based distribution — each stage shipping only when the previous one has earned it.

### One page

**What it is.** Bunny OS is best understood as four layers with strict boundaries, matching the provisional naming already in use:

- **Bunny Core** — the agentic runtime that exists today: a provider-neutral model seam (`ChatProvider` streaming canonical events, with Anthropic and OpenAI-compatible wire adapters and presets for NIM, OpenRouter, Groq, Ollama, LM Studio, llama.cpp, and vLLM), permission-gated tools with fail-closed capability declarations, persistent JSONL sessions with fork/resume/search, MCP in both directions, Ed25519-signed plugins, durable scheduled jobs, and local GGUF execution via a supervised llama.cpp runtime. This layer is real, verified in the repository audit, and is the asset everything else builds on.
- **Bunny Box** — a locally hosted, browser-accessed workspace in which agentic execution happens inside an enforced sandbox with controlled filesystem, process, and network boundaries. The browser is presentation only; intelligence and state remain in the local runtime. Today this exists only as a 13.7 KB reference HTML page and a versioned JSON-RPC app-server protocol — the protocol is the asset; the sandbox does not yet exist and is the single most important thing to build.
- **Bunny Shell** — the AI-native user environment: the character, the task surface, living plans, spatial task cards, voice and captions. It must run first as an application on Windows, macOS, and Linux, and only later as a Wayland session on a Linux base.
- **Bunny OS** — eventually, a Linux distribution in the modern immutable pattern: an image-based derivative of an existing atomic base carrying the Bunny Shell as its session. It is packaging and polish for the layers above, not a separate engineering universe. No kernel work is contemplated beyond configuration.

**What it is not.** Bunny OS is not an autonomous employee, not a companion or confidant, not a surveillance system that captures everything to be helpful later, not a new kernel or window into someone's cloud, and not a chat app with a mascot. It does not pretend local models match frontier hosted models; it does not pretend a personality named after a third-party model is that vendor's product; it does not act consequentially without a grant of permission whose scope the user can state from memory.

**Who it serves first.** Developers and technical power users who already run agentic coding tools and self-host infrastructure — people who feel the pain of fragmented agent context, distrust cloud memory, own capable hardware, and will tolerate v0 rough edges in exchange for ownership and control (§4).

**Why now.** Three curves cross in 2026: open-weight models became genuinely useful on consumer hardware (a 20–30B MoE runs well on a 24–32 GB machine); the agent-safety evidence base matured enough to design a permission model from data rather than intuition; and every incumbent chose either cloud-first agents (Microsoft, Google) or walled-garden hybrids (Apple), leaving open-source, local-first, user-owned agency structurally unoccupied. Home Assistant proved [a privacy-first, open, local-first platform can win a category and sustain a foundation with 2M+ installs](https://www.home-assistant.io/blog/2025/04/16/state-of-the-open-home-recap/); nobody has done this for general computing.

---

## 3. Problem Statement

### The user problems

**P1 — Applications fragment goals.** A goal like "prepare this release" spans a terminal, an editor, a browser, a chat with an AI, a ticket tracker, and a file manager. The user is the integration layer: they carry the plan in their head, translate it into app-specific operations, and lose state at every boundary. Existing OSes optimize app switching, not goal completion.

**P2 — Agents exist but cannot be trusted with consequence.** The tools that can act (coding agents, browser agents, computer-use agents) either ask for confirmation so often that users habituate — Anthropic's own retrospective reports users [approve 93% of Claude Code permission prompts](https://anthropic.com/engineering/claude-code-auto-mode), statistically indistinguishable from Vista UAC's [89% two decades earlier](https://learn.microsoft.com/en-us/archive/blogs/e7/user-account-control) — or act with too little control, producing the Replit class of incident. Nobody has shipped a trust model that is both legible and livable; the empirical trust gradient (research 73% / transact 24%) is unserved between its ends.

**P3 — Memory belongs to the wrong party.** Cloud assistants accumulate the user's context on the provider's side, in opaque form. The legal floor is worse than most users assume: under GDPR Article 20 guidance, providers owe you your *transcripts* but [not the derived memory profile they built about you](https://ec.europa.eu/information_society/newsroom/image/document/2016-51/wp242_en_40852.pdf). Policy analysts now identify accumulated context as [the coming lock-in moat](https://www.newamerica.org/oti/briefs/ai-agents-and-memory/). Meanwhile documented failure modes — false memories, staleness, cross-project leakage — turn provider-side memory into verification labor.

**P4 — Local AI solves the wrong layer.** Ollama, LM Studio, and Jan made model management trivial, and they are all the same llama.cpp underneath. None ships memory, task structure, permissioning, or any UX beyond chat. Users who want local intelligence get a model picker, not a computing environment.

**P5 — Continuity of work does not exist.** "Organize my work and continue where I stopped" is not a feature of any mainstream OS. Sessions, in the sense of resumable goal-state with plans and history, are an accident of individual apps.

### Why current computing models fail these problems

Conventional desktops (Windows, macOS, Linux DEs) are application launchers with files; their AI additions inherit a conflicted incentive structure — telemetry, ads, cloud subscriptions — that users correctly distrust (Recall's reception is the canonical case). Cloud AI assistants invert the ownership model: the more helpful they get, the more of the user they keep. Agentic coding tools are the closest thing to Bunny that exists — and they are deliberately narrow: single-project, terminal-scoped, developer-only, with no ambition to be the environment. The incumbents converging on "agentic OS" features (Microsoft's [off-by-default agent accounts with published cross-prompt-injection warnings](https://support.microsoft.com/en-us/windows/experimental-agentic-features-a25ede8a-e4c2-4841-85a8-44839191dfb3), Google's Gemini-first [Aluminium OS](https://www.forbes.com/sites/timbajarin/2026/05/27/googlebook-google-unifies-android-and-chromeos-for-ai-powered-laptops/), Apple's delayed agentic Siri) are all cloud-anchored and closed; none offers user-owned memory, provider neutrality, or inspectable trust.

**The synthesis:** the unsolved problem is not "add AI to an OS" — everyone is doing that. It is *whom the computing environment works for*. Bunny's bet is that an environment can be intelligent while remaining structurally on the user's side: local system of record, provider-neutral intelligence, permission decisions that mean something, and reversibility as the backstop for trust.

---

## 4. Target Users

### The first user (V1)

**A developer or technical power user who already uses agentic AI tools and owns capable hardware.** Concretely: comfortable in a terminal; runs or has run Claude Code/Cursor-class tools; has 16–64 GB of RAM and often a discrete GPU or Apple silicon; self-hosts something (the Home Assistant / homelab demographic overlaps heavily); is privacy-conscious but pragmatic — the evidence says users [adopt local-first for cost, speed, and control, and stay for ownership](https://www.home-assistant.io/blog/2025/04/16/state-of-the-open-home-recap/), so this user is acquired on capability and kept on trust. This is also, non-accidentally, the user Bunny's existing codebase already serves: a cross-platform agentic CLI with local-model support.

Choosing this user is a constraint, not a demographic guess: they tolerate rough v0 UX, they can evaluate whether the trust model is real, they generate credible public evidence (the Home Assistant evangelism pattern), and they will not be harmed by early capability gaps the way a mainstream consumer would.

### Secondary users (fast follow, not V1 targets)

- Technical creators and researchers who want persistent, multi-session project agents without living in a terminal.
- Privacy-motivated professionals (lawyers, journalists, clinicians in non-regulated workflows) for whom "context never leaves the machine by default" is a purchasing criterion — a retention story once capability is proven.
- Small teams sharing a self-hosted Bunny Box on a workstation-class machine.

### Explicitly excluded from V1 (with reasons)

- **Minors.** The companion-character litigation record — [a court treating a chatbot as a product enabling strict liability, an under-18 open-ended-chat ban, settled wrongful-death suits](https://trulaw.com/ai-suicide-lawsuit/character-ai-lawsuit/) — plus the [Garante's €5M Replika fine](https://digitalpolicyalert.org/event/30071-data-protection-authority-fined-replika-chatbot-provider-luka-eur-5-million-for-gdpr-violations-related-to-legal-basis-for-data-processing-and-age-verification) make an animated-character product for minors untouchable without age assurance and dedicated safety engineering that V1 will not have.
- **Non-technical mainstream consumers.** The capability honesty required by this constitution (§11) cannot yet promise them a good experience; the trust gradient says they will not delegate consequence yet anyway.
- **Enterprise fleets and regulated industries.** Compliance, admin control planes, and audit requirements are a different product.
- **Competitive multiplayer gamers,** if and when Bunny runs on Linux: kernel-level anti-cheat is a publisher trust decision no compatibility layer can fix — [over half of anti-cheat games do not work on SteamOS](https://www.engadget.com/gaming/pc/for-the-steam-machine-to-change-pc-gaming-valve-must-solve-linuxs-anti-cheat-problem-130000088.html), and Epic's refusal has held for five years. Bunny must never imply otherwise.
- **Users who need a companion.** Bunny deliberately caps intimacy (§8); people seeking emotional dependency are a population it must not cultivate and cannot responsibly serve.

### Market expansion path

Developer/power-user (V1) → technical creators and privacy-professionals (V1.x) → self-hosted small teams (V2) → mainstream consumers only after: the sandbox constitution is fully enforced, capability honesty no longer costs the mainstream experience, and accessibility conformance (§15) is demonstrated — with minors remaining excluded until a deliberate, separately-resourced safety program exists. **Assumption to revisit:** that the developer beachhead generalizes; ChromeOS shows beachheads can be won (education) without ever converting the general market.

---

## 5. Core Product Thesis

The working thesis: *Bunny OS is not an operating system with an AI assistant added; it is a computing environment where intelligence, intent, trust, and adaptation are native.* Phase 0's job is to test that thesis for coherence, differentiation, achievability, and usefulness — and to answer the sharpest of the required research questions: **is "intent instead of applications" a complete model, or a layer over applications?**

### Verdict: it is a layer — and it is stronger as a layer

The complete-replacement version of the thesis fails on the evidence. Every product that claimed to *replace* the application model with intent translation shipped a demo of it and then broke: Rabbit's "Large Action Model" was [revealed to be hard-coded Playwright scripts covering four apps](https://en.wikipedia.org/wiki/Rabbit_r1); computer-use agents needed two years to go from [14.9%](https://www.anthropic.com/news/developing-computer-use) to [~73%](https://www.anthropic.com/news/claude-sonnet-4-6) on OSWorld — against a 70–75% human baseline, on a vendor-friendly benchmark, with prompt injection still unsolved; and even at the frontier, function-calling reliability tops out around [75% on BFCL V4](https://llm-stats.com/benchmarks/bfcl-v4). An environment whose *only* path to action is intent interpretation forces every task through its least reliable component. Meanwhile applications are not a legacy artifact to be abstracted away: they are dense, debugged encodings of domain workflows with decades of accessibility, muscle memory, and ecosystem behind them.

The layered version, by contrast, is coherent and well-evidenced. Intent, plans, and delegation become the *organizing* layer — the thing the user primarily faces — while applications, files, and terminals remain first-class objects that plans reference, open, and manipulate, and that the user can always drive directly. Every successful agentic product of the last two years is an existence proof of exactly this shape: an intent layer (the conversation, the plan) wrapped around conventional computing primitives (the shell, the editor, the browser), with a human able to drop down a level at any moment. The user's escape hatch to manual control is not a transitional compromise; it is a permanent architectural commitment (§6, Principle 1; §7).

### Is it differentiated?

Partially — and it matters where. The intent layer itself is *not* original: Microsoft, Google, Apple, OpenAI, and Anthropic are all converging on agentic computing, and any one of them can ship intent parsing better funded than Bunny. Three things in the thesis are genuinely unoccupied as of mid-2026:

1. **User-owned, provider-neutral memory and trust.** No incumbent can offer it, because their business models depend on the opposite. This is structural differentiation, not feature differentiation — the kind that survives competitors copying features.
2. **The legible permission model as the product.** The field's own data (93% prompt approval; double-digit prompt-injection success rates after mitigations; the [OWASP LLM Top 10 keeping prompt injection at #1](https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf)) shows everyone shipping agents and nobody shipping trust. The Bain gradient (73/24/10) quantifies the unserved middle: users who want delegation with control.
3. **The empty AI-native OS lane.** No credible AI-native operating environment exists; the visible attempts are hobby projects. But emptiness cuts both ways — the lane may be empty because the OS layer is the wrong place to compete (§18 takes this seriously rather than treating emptiness as validation).

The character, the spatial UI, and voice interaction are *not* differentiators; they are presentation choices with a documented failure history (§8, §14) that must earn their place.

### Is it achievable?

The layer version is achievable by a small team because it composes things that now exist: a working agentic runtime (verified in the repo), commodity local inference, hosted frontier APIs, MCP as a tool standard, and published patterns for hybrid routing ([RouteLLM-class routing kept 95% of GPT-4 quality while sending only ~14% of queries to the strong model](https://arxiv.org/pdf/2406.18665); [Apple's production on-device + private-cloud split](https://arxiv.org/abs/2507.13575)). What is *not* achievable and must not be promised: local agentic parity with frontier hosted models (the SWE-bench gap between self-hostable and frontier models is reported at 17–27 points **[aggregator figures, unverified]** and compounds across multi-step plans), full autonomy over consequential actions, and a replacement for the application ecosystem.

### Is it useful?

Yes, conditionally. The usefulness claim rests on P1–P5 (§3), and the strongest single use case follows directly: **resuming and orchestrating ongoing project work** — "open my project, show me where we stopped, continue the plan, ask me before anything consequential." This is the use case where intent-as-a-layer beats both a bare chat window (no persistence, no plan, no permissions) and a bare desktop (no continuity, no delegation). It is also the use case Bunny's existing session/fork/resume machinery already half-serves, making it the honest V1 (§21, Decision D3).

**Amended thesis, adopted:** *Bunny OS is a computing environment in which intent, living plans, supervised delegation, user-owned memory, and legible trust form the primary interface layer over — never a replacement for — applications, files, and direct control, with intelligence supplied by interchangeable local and hosted models that the environment routes honestly.*

---

## 6. Product Constitution

Sixteen non-negotiable principles. Every later design and engineering decision must either comply or amend the constitution explicitly — silent violation is the failure mode this document exists to prevent. Each principle carries its rationale, an example, and the failure mode it prevents.

---

**C1. The plan is the interface.**
Every unit of delegated work is a visible plan: goal, Bunny's understanding of the goal, steps, current step, completed and failed steps, pending approvals, resources in use, and results. Oversight happens primarily at plan level, not per keystroke.
*Rationale:* Per-action supervision fails empirically (93% blind approval); no supervision fails catastrophically (Replit). Plan-level review is where Anthropic, OpenAI, and Microsoft all independently converged, and it is the only surface where a human can exercise judgment at the rate the work actually needs it.
*Example:* "Prepare this project for release" produces a seven-step plan; the user approves the plan once, watches steps stream, and is interrupted only for the step that publishes to npm.
*Prevents:* Both rubber-stamp fatigue and silent autonomy; also prevents the system from doing work the user cannot later reconstruct.

**C2. Powerless by default; power by explicit, scoped grant.**
Every capability — tool, file root, network egress, device, spend — is denied until granted, and every grant has a stated scope (this action / this task / this workspace / standing with conditions) and is revocable and auditable. Undeclared capabilities fail closed.
*Rationale:* The repo already implements fail-closed tool capabilities (`UNDECLARED_TOOL_CAPABILITIES` defaults to ask); the industry's permission evolution (Android install-time → runtime → [one-time grants and auto-reset](https://developer.android.com/training/permissions/requesting)) all moved this direction after learning the alternative the hard way.
*Example:* A new MCP server installs with zero permissions; its first file read triggers a scoped grant request naming the directory.
*Prevents:* Capability creep; stale standing grants; the "it could always do that?" class of trust collapse.

**C3. Prompts must be rare enough to mean something.**
Reduce permission prompts structurally — by scoping, sandboxing, and plan-level approval — never cosmetically. Bunny's own first-party operations must generate zero permission dialogs. When Bunny does interrupt, the prompt must say who is asking, what provenance the instruction has, exactly what will happen, and what the blast radius is.
*Rationale:* Vista's UAC data is the canonical dataset: [50% of sessions had prompts, users approved 89%, Windows itself caused 40% of them, and only 13% of users could say why a prompt appeared — redesigning for comprehension raised that to 83%](https://learn.microsoft.com/en-us/archive/blogs/e7/user-account-control). Chrome proved [suppressing low-value prompts costs ~5% of legitimate grants](https://www.usenix.org/conference/usenixsecurity21/presentation/bilogrevic). Habituated users are unprotected users.
*Example:* Instead of five prompts during a refactor, one plan approval up front; the lone mid-plan prompt ("this instruction came from a webpage you opened, not from you — allow it to modify your git config?") is genuinely informative.
*Prevents:* Approval fatigue as a security hole; the macOS-Sequoia pattern of [re-prompting that trains users to click through](https://tidbits.com/2024/08/12/macos-15-sequoias-excessive-permissions-prompts-will-hurt-security/).

**C4. Guarantees live in deterministic code, never in the prompt.**
Assume the model is compromised. Anything that must be true — "cannot touch this directory," "cannot spend money," "cannot exfiltrate" — is enforced by the permission gate, the sandbox, and egress policy, not by instructions to the model.
*Rationale:* Every vendor with production agents states prompt injection is unsolved ([OpenAI: a "frontier security challenge" that may never be fully solved](https://openai.com/index/prompt-injections/)); the best published mitigations still leave [double-digit attack success](https://claude.com/blog/claude-for-chrome). The Replit incident's root cause was that natural-language instructions were the only control.
*Example:* A code freeze is a capability revocation, not a system-prompt sentence.
*Prevents:* The entire class of "the model was told not to" failures.

**C5. The lethal trifecta is an architectural violation.**
No single execution context may simultaneously hold private-data access, untrusted-content ingestion, and open external egress. Combining all three requires explicit, elevated, per-instance authorization.
*Rationale:* [Simon Willison's trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) is the cleanest published threat model for agent exfiltration, and the 2025–26 incident record (EchoLeak, AgentFlayer, Comet) is a catalog of products that combined all three by default. Probabilistic guardrails that "block 95% of attacks" are a failing grade in security terms.
*Example:* A research task that reads arbitrary webpages runs with no access to the user's files; a task with file access has an egress allowlist.
*Prevents:* Zero-click exfiltration; turning every webpage Bunny reads into a potential attacker with the user's privileges.

**C6. Reversibility beats obedience.**
Every consequential action Bunny takes must be undoable where physically possible: snapshots before destructive operations, transactional workspace changes, one-step rollback, and a durable audit trail. Irreversible actions (external sends, payments, deletions beyond recovery) are a distinct permission class with the highest friction.
*Rationale:* Models will keep making errors of judgment; an environment with universal undo converts catastrophes into annoyances. This is arguably the strongest trust feature an agentic OS can ship, and the immutable-OS trend ([atomic images with rollback as the mainstream pattern for new distros](https://itsfoss.com/immutable-linux-distros/)) provides the system-level analogue.
*Example:* "Undo everything the release-prep task did" restores the workspace snapshot, reverts config writes, and shows what cannot be undone (the email that was sent) — which is exactly the list that required elevated consent in the first place.
*Prevents:* Permanent damage from transient model failure; trust destruction by unrecoverable mistake.

**C7. The user owns the memory; Bunny is its custodian; providers never are.**
All durable memory — conversations, preferences, project state, learned intents, episodic history — lives on the user's machine (or the user's chosen storage) in an inspectable, exportable format. Model providers receive context per-request and are never the system of record.
*Rationale:* Accumulated context is [the coming lock-in moat](https://www.newamerica.org/oti/briefs/ai-agents-and-memory/); the GDPR portability floor [excludes derived memory](https://ec.europa.eu/information_society/newsroom/image/document/2016-51/wp242_en_40852.pdf), so ownership must be architectural, not contractual. Local-first memory also sidesteps the entire provider-side memory failure catalog (false memories, cross-context leakage, unpredictable injection).
*Example:* Switching every model provider Bunny uses changes nothing about what Bunny remembers.
*Prevents:* Vendor lock-in via context hostage-taking; provider memory bugs becoming Bunny trust incidents.

**C8. Memory writes are privileged actions.**
Nothing writes to durable memory silently. Memory writes are permission-classed, attributed (what wrote this, from what source, when), scoped to their workspace by default, and individually correctable and deletable — with deletion cascading through derived artifacts.
*Rationale:* Memory converts one-shot prompt injection into persistent compromise — demonstrated repeatedly ([SpAIware](https://embracethered.com/blog/posts/2024/chatgpt-macos-app-persistent-data-exfiltration/); [MINJA's query-only memory poisoning at 98.2% injection success](https://arxiv.org/abs/2503.03704)). Users also [systematically overtrust machine memory as accurate and objective](https://dl.acm.org/doi/10.1145/3772318.3791635), so provenance and visible hedging are safety features, not polish.
*Example:* "Bunny remembered: you prefer tabs (from today's session, workspace `api-server`) — keep / edit / forget."
*Prevents:* Memory poisoning as persistent malware; false memories laundered into ground truth; one project contaminating another.

**C9. Personality is presentation; provider is disclosed routing.**
A personality (tone, character, voice, planning style) is a stable presentation contract that persists across model changes. The active model, provider, and execution locality are always discoverable in one glance, and any material change — privacy, cost, provider, capability, data leaving the device — is disclosed at the moment it happens. Personalities are never named after third-party models or vendors.
*Rationale:* Continuity of identity is good UX; misleading users about what is running is both a trust violation and, after [EU AI Act Article 50 (applying 2026-08-02)](https://artificialintelligenceact.eu/article/50/), a regulatory one. Trademark reality reinforces this: [Anthropic's guidelines require prior approval for use of its marks](https://www.anthropic.com/legal/trademark-guidelines), and nominative fair use covers referring to "Claude" as a routed engine, not naming your character Claude (§8).
*Example:* The "Bunny" personality answers identically in tone whether routed to a local 27B or a hosted frontier model — and the route chip changes from "local · free · private" to "Anthropic · metered · leaves this device," with the switch itself announced.
*Prevents:* Users making privacy/cost decisions on false premises; implied vendor endorsement; personality-driven overtrust in a weaker engine.

**C10. The character is optional everywhere; the task surface is authoritative.**
One hundred percent of Bunny's functionality is available with the character disabled, reduced to static, or replaced. System state lives in the task surface; the character may express it but never exclusively carries it. Consent, permission, and destructive-action UI is visually de-characterized — it comes from the system, not from the mascot.
*Rationale:* Character failures are behavior failures with a long record (Bob, Clippy — [interruption and condescension, not rendering](https://thenewstack.io/humanity-vs-clippy-lessons-from-microsofts-failed-virtual-assistant/)); anthropomorphism [slows trust recalibration after errors](https://pubmed.ncbi.nlm.nih.gov/27505048/), which is dangerous precisely at consent moments; and an idle-animating mascot is a [WCAG 2.2.2 Level A compliance surface](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html). The persona graveyard (Clippy, Cortana, personified Siri) shows capability layers outlive their characters.
*Example:* A screen-reader user, a reduced-motion user, and a user who simply dislikes mascots all get the identical task surface, plans, and permissions.
*Prevents:* Affection for the character laundering authority over the user; accessibility failure; the product dying with its mascot.

**C11. One Bunny, honest about capability.**
There are no "editions." The same environment adapts across hardware by negotiating capability internally — but it never fakes parity. When local capability is insufficient for the task, Bunny says so and offers the routes: escalate to a hosted model (with disclosure), degrade the task, or decline.
*Rationale:* The capability gap is real (local tool-calling is credible at 3–4B for single steps; multi-step agentic work compounds per-step error; frontier hosted models remain the default for hard agentic work in 2026), and dishonesty about it is the Rabbit failure mode — charisma plus capability inflation ends in abandonment.
*Example:* On a Raspberry Pi-class device, "summarize my notes" runs locally; "refactor this codebase" states plainly that it needs a hosted model or a bigger machine.
*Prevents:* "Weak Bunny/strong Bunny" fragmentation; demo-to-delivery credibility collapse; users discovering the gap adversarially.

**C12. Local-first is a preference order, not an ideology.**
Prefer local execution when it is capable enough, safe, timely, and economical — in that priority order, under user-set policy. When work must leave the device, Bunny explains why, states what leaves, minimizes it, names the destination, discloses cost, obtains the appropriate consent level, and records the event.
*Rationale:* A local model used beyond its competence is a worse privacy decision than a disclosed cloud call that succeeds — failed local work gets redone in the cloud anyway, after wasting the user's time. Even Apple, the flagship of on-device privacy, [runs its Private Cloud Compute hybrid on third-party infrastructure](https://www.infoq.com/news/2026/07/apple-pcc-google-cloud/); the trust architecture, not the geography, is the product.
*Example:* Routing policy "privacy-strict" pins everything local and accepts capability limits; "balanced" escalates with per-workspace consent; both are user-chosen, visible, and auditable.
*Prevents:* Local-first as dogma degrading outcomes; cloud-first as convenience eroding the core promise silently.

**C13. Accessibility is architecture, not accommodation.**
Every capability is operable keyboard-only; every surface is screen-reader accessible via a semantic structure maintained as a first-class twin of any visual rendering; all speech is captioned; reduced-motion is a fully supported first-class mode; agent-initiated UI changes never steal focus and are announced through the accessibility layer.
*Rationale:* The spatial/canvas UI class is [invisible to assistive tech unless deliberately mirrored](https://www.figma.com/blog/building-accessibility-into-a-canvas-based-product/) — retrofit is the documented failure mode. The [European Accessibility Act explicitly covers consumer operating systems](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32019L0882) (in force since June 2025). And the populations who gain most from an agentic environment — motor- and vision-impaired users — are the ones a voice-and-animation-first design fails hardest (§15).
*Example:* The bubble field is a projection of an ordered task list; the list, not the bubbles, is the source of truth — so Orca/NVDA users navigate the same reality.
*Prevents:* Building an inaccessible novelty UI and discovering the retrofit is a rewrite; regulatory exposure; excluding the users with the most to gain.

**C14. Money and data flows are always visible.**
Spend has a live meter, per-task attribution, user-set budgets with hard stops, and pre-execution estimates for expensive operations. Egress has an equivalent ledger: what left the device, to whom, under which grant. No hidden markups on routed models; no dark patterns around subscription or provider choice.
*Rationale:* Economic trust is part of the same trust product — accidental-spend and silent-egress incidents are indistinguishable, to the user, from betrayal. The 2026 evidence base for agent commerce says [security/privacy concern is the top adoption blocker](https://www.bain.com/insights/agentic-ai-commerce-hinges-on-consumer-trust/).
*Example:* "This research plan will call hosted models an estimated 40–80 times (~$0.60–$1.10). Budget for this workspace: $5 remaining."
*Prevents:* Bill shock; the perception (or reality) of the platform quietly monetizing routing decisions against the user. (The full economic trust requirements — forecasting, budgets, subscription boundaries, markup and dark-pattern prohibitions — are in **Appendix B**.)

**C15. Own the narrow waist; rent everything else.**
Bunny owns its differentiating layer — the intent/plan model, permission gate, memory system, provider seam, and trust UX — and rents or adopts everything else: upstream kernel (never forked), existing base OS, existing app ecosystems (Flatpak/Flathub on Linux), existing inference engines, existing standards (MCP). Infrastructure is only built in-house when it *is* the differentiation.
*Rationale:* The platform-economics record is unambiguous: [Valve funds Arch rather than forking it](https://www.phoronix.com/news/Valve-Arch-Linux-Collaboration); [Bazzite serves ~68k devices maintaining only an image layer](https://www.xda-developers.com/bazzite-triples-its-userbase-in-8-months-as-gamers-seek-a-windows-alternative/); [Google spent years un-forking Android's kernel](https://source.android.com/docs/core/architecture/kernel/generic-kernel-image); a new shell took System76 [4.5 years with hardware revenue behind it](https://en.wikipedia.org/wiki/COSMIC_desktop). Small "own everything" distros die of maintenance (Antergos).
*Example:* Bunny OS, if shipped, is an OCI image atop an existing atomic base carrying the Bunny session — not a package archive, not a kernel tree.
*Prevents:* Permanent payroll spent on undifferentiated plumbing; the reskin-distro death spiral; originality theater.

**C16. Extensions are adversarial until proven otherwise.**
Every extension — plugin, MCP server, skill, personality, character, voice, theme, automation pack — is signed, permission-manifested, least-privileged, sandbox-tiered by trust class, individually revocable, and subject to kill-switch revocation. Marketplace curation assumes hostile submissions.
*Rationale:* The supply chain is already weaponized: [the first confirmed malicious MCP server shipped via npm in 2025](https://securelist.com/model-context-protocol-for-ai-integration-abused-in-supply-chain-attacks/117473/), VS Code marketplace malware detections [nearly quadrupled year-over-year](https://phoenix.security/accelerating-supply-chain-attacks-npm-pypi-vsx-ai-enabled-2026/), and an agentic host raises the stakes: a malicious extension inherits the agent's granted powers. The repo's Ed25519 plugin signing is the right foundation; it is not yet a governance model.
*Example:* A community MCP server installs in microVM-grade isolation with no egress; a "Works With Bunny" certified tool earned looser defaults through review and attestation.
*Prevents:* The postmark-mcp class of incident wearing Bunny's trust as a disguise.

---

The eight tensions these principles create between themselves are treated honestly in §19 — a constitution that pretends its principles never conflict is decoration.

---

## 7. Experience Principles

What it should feel like to live with Bunny, expressed as the five moments that define an agentic environment. These are experience commitments, not UI designs.

**Opening.** Bunny opens into *your work, quietly*: the workspaces you left, each with its goal, plan state, and what happened while you were away — never a blank chat box, never an animation performance, never a modal. The character (if enabled) acknowledges you and gets out of the way. Anything that occurred autonomously while you were absent is presented as a reviewable ledger before its effects are treated as accepted. First launch is the exception with its own duty: it must establish the trust contract — what Bunny can see, what it can do, what it will ask before doing — in under a minute, defaulting everything to off.

**Speaking.** Talking to Bunny — by voice or text — is one input method among equals, never the only path (the [usability record on conversation-only interfaces](https://www.nngroup.com/articles/intelligent-assistant-usability/) is unambiguous: they hide capability and shift discovery burden onto the user). Every conversational capability has a visible, clickable counterpart; every voice action has a non-voice equivalent; captions accompany all character speech. Bunny states its interpretation of an ambiguous request as part of the plan ("I understood this as: …") rather than burying its guess in action. It asks clarifying questions when the intent is genuinely ambiguous — and does not perform fake understanding when it lacks it.

**Supervising.** Watching Bunny work must feel like watching a competent colleague share their screen, not like auditing a black box. The plan shows the current step; the step shows its concrete actions (the diff, the command, the URL); resource, route, and spend indicators run live; and the level of detail is the user's dial, from "just tell me when it's done" to per-action streaming. Two invariants: the user can always answer "what is Bunny doing *right now* and with what authority?" in one glance, and nothing the user watches is a summary that hides an action from the audit trail.

**Interrupting.** Interruption is a first-class, always-available, instantaneous act — a stop control that is never more than one action away, that halts safely at the nearest clean boundary, and that never punishes the user (no lost state, no corrupted half-work; the workspace either holds the pre-step snapshot or the completed step). After a stop, the user chooses: resume, edit the plan, take manual control of the task's objects, or discard with rollback. Taking manual control and returning control to Bunny are symmetrical, low-ceremony moves — the environment treats human and agent as alternating drivers of the same work, and Bunny is expected to absorb what the human changed before continuing.

**Returning.** Coming back — after an hour, a reboot, or a week — restores continuity as a right: plans, context, and partial work persist; "what happened while I was gone" is a first-class view; and resuming an old goal does not require re-explaining it. This is where the memory constitution (§12) pays its rent — and where its discipline matters most, because resuming on *stale* context ("continuing" a strategy the user abandoned) is more corrosive than resuming with none. Resumption therefore states its assumptions: "picking up the release plan from Tuesday; two files changed outside Bunny since — reviewing those first."

Two cross-cutting rules bind all five moments. **Bunny never interrupts the user's focus for anything less than a genuine boundary** — the Clippy failure was interruption, and modern attention is the same resource. And **failure is presented calmly, specifically, and with options** — what failed, why (as best known), what was rolled back, what Bunny proposes next — never anthropomorphic guilt theater, never a blame-shifting apology loop.

---

## 8. Personality and Character System

### Personality–provider separation

A **personality** is a presentation and interaction contract: name, character art, voice, tone, verbosity, humor, planning style, initiative level, risk posture, explanation depth. A **provider route** is an execution fact: which model, which vendor, local or remote, at what cost, with what data leaving the device. The two are orthogonal by construction:

- Personalities persist across route changes; routes change under policy (§11) and are always visible.
- A personality may *prefer* routes (a cautious personality may prefer plan-only modes; a fast one may prefer local drafts) but never *hides* them.
- Nothing about a personality may imply the identity, endorsement, or presence of a third-party vendor. Personalities are never named after models or providers. "Codex" and "Claude" as personality names are rejected: [Anthropic's trademark guidelines are approval-first](https://www.anthropic.com/legal/trademark-guidelines), OpenAI's brand rules prohibit implying partnership **[exact current wording unverified — their brand page blocks automated access]**, and nominative fair use protects *referring* to a routed engine ("routed to: Claude Opus — Anthropic"), not building a character on the name. Even legally weak marks are enforced by rich owners ([OpenAI opposed FreedomGPT while "GPT" was being refused registration](https://www.pr-inside.com/freedomgpt-files-lawsuit-to-cancel-openai-s-gpt-trademark-claim-r5189753.htm)). Model names appear in exactly one place: the route indicator, in plain text, with no third-party logos.

**Disclosure duties.** The route indicator plus moment-of-change disclosure (C9) satisfies the product's honesty bar and its regulatory one: [EU AI Act Article 50](https://artificialintelligenceact.eu/article/50/) requires disclosure of AI interaction (applying 2026-08-02, fines to €15M/3% of turnover) and machine-readable marking of generated content — Bunny should disclose even where the "obviously an AI" exception might apply, and bake audio/content marking into its speech and generation pipelines now rather than retrofit it.

### Character behavior

The character is Bunny's emotional and conversational layer — never its authority (C10). Its behavioral contract:

- **State expression, honestly:** attentive when listening, visibly working during execution, paused and *stepped aside* when the system requests permission (the consent surface is de-characterized; the character does not plead its own case), concerned-but-calm on failure, celebratory only briefly and only when the user's goal — not Bunny's activity — succeeded.
- **Never interrupts.** The character surfaces when summoned or when a plan boundary genuinely requires the user. It does not perform idle attention-seeking. All idle animation respects pause/stop/hide ([WCAG 2.2.2, Level A](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html)) and reduced-motion preferences, and a static-character and no-character mode exist from v0.
- **Stylized, not realistic.** Uncanny-valley evidence is mixed in detail but consistent in direction: stylized characters sidestep the risk zone entirely, and 2026 VTuber-grade tooling makes them cheap. Realism buys risk and no measured benefit — the [persona-effect literature finds the animated body itself adds at best unreliable value; behavior, timing, and competence carry the effect](https://zhouyunlab.github.io/assets/documents/18.pdf). Budget accordingly: interaction policy over animation polish.
- **Bounded intimacy.** Bunny is a work companion, not a confidant: no romantic framing, no simulated emotional need, no guilt mechanics, no engagement-optimized attachment. The record here is legal, not just ethical — [bereavement-grade harm from character changes](https://www.vice.com/en/article/ai-companion-replika-erotic-roleplay-updates/), [a €5M fine](https://digitalpolicyalert.org/event/30071-data-protection-authority-fined-replika-chatbot-provider-luka-eur-5-million-for-gdpr-violations-related-to-legal-basis-for-data-processing-and-age-verification), [strict product liability theories surviving dismissal](https://trulaw.com/ai-suicide-lawsuit/character-ai-lawsuit/). Personality changes are versioned and user-controlled; Bunny never changes character overnight under a user who has invested in it.

### Voice

- Ship original synthetic voices, provably original: never cast or tune a voice to evoke a recognizable person — the [Sky/Johansson incident](https://variety.com/2024/digital/news/scarlett-johansson-responds-shocked-angered-openai-chatgpt-her-1236011135/) shows resemblance-plus-implied-identity is the failure mode, and sound-alike liability (the *Midler* line) does not require cloning.
- External voice providers (e.g., ElevenLabs) connect under the same route-disclosure rules as model providers: user's key, visible cost, visible egress (character speech text leaves the device).
- User voice cloning, if ever offered, is consent-gated to the standard the industry leader already practices — [live voice-captcha verification, ownership/authorization requirements, prohibited-use enforcement](https://elevenlabs.io/docs/eleven-api/concepts/voice-cloning) — with durable consent artifacts, because liability now attaches to the *tool*: the [ELVIS Act](https://law.vanderbilt.edu/why-tennessees-elvis-act-is-the-king-of-artificial-intelligence-protections/) reaches technology whose primary purpose is producing an individual's voice, and voiceprints are [BIPA biometric identifiers with an active 1.2M-member certified class against Amazon](https://blogs.duanemorris.com/classactiondefense/2025/11/26/the-class-action-weekly-wire-episode-128-illinois-federal-judge-certifies-class-of-1-2-million-amazon-alexa-users-in-bipa-class-action/). If Bunny ever does speaker verification, it is local-only processing with explicit written consent and a retention/deletion schedule — local-first is a genuine legal advantage; use it.
- Deceased-personality replicas and digital doubles follow the California AB 1836/AB 2602 consent regime (both effective 2025-01-01); the pending [NO FAKES Act](https://www.congress.gov/bill/119th-congress/senate-bill/4591) (advanced from Senate Judiciary June 2026, not yet law) would add a takedown regime that Bunny's consent-logging hooks should anticipate but not prematurely implement.

### Customization

Users may reskin, restyle, or replace the character and voices within the constitution's floors: honesty floors (no impersonation of real people without documented consent; no removal of AI disclosure), safety floors (no minor-directed personas absent an age-assurance program; intimacy caps are not user-removable), and accessibility floors (custom characters cannot disable captions, reduced-motion, or the de-characterized consent surface). Within those floors, customization is encouraged — identity investment belongs in the character *the user shapes*, which is also the trademark-resilient place to put brand identity (§19, naming).

---

## 9. Intent and Living-Plan Model

The conceptual chain, with obligations at each link:

**Expression → Intent.** An expression (phrase, click, shortcut, later a gesture) maps to an **intent** — a durable, named, structured object like `resume-primary-development-workspace`, owned by the user. Intents are legible (a user can read what an intent will do before it does it), predictable (the same intent does the same thing until edited), and fully manageable: inspect, rename, edit, disable, export, delete. Learned intents (§10 covers what may be learned automatically) are proposals until confirmed; nothing the user didn't confirm can trigger consequential action. Accidental-activation resistance scales with consequence: destructive or spending intents require deliberate confirmation regardless of how they were invoked.

**Intent → Understanding → Plan.** Bunny restates its understanding of the goal, then proposes a **living plan**: ordered steps with per-step action classes (read, draft, edit, execute, spend, send…), resource and route expectations, cost estimates where relevant, and identified risk points. The plan is "living" in three senses — it updates as reality intervenes (with changes visible as diffs, not silent rewrites), it carries its history (what was tried, what failed, what was learned), and it persists across sessions as the unit of resumable work.

**Plan → Approval.** Approval operates at plan level (C1, C3): approving a plan grants exactly the capabilities its steps declare, scoped to the task. Steps exceeding the granted envelope — or carrying instructions whose provenance is not the user (a webpage said to do it; a file comment said to do it) — surface as boundary approvals with provenance shown. Plan-only and read-only modes are first-class: a user can ask for the plan and never execute it.

**Execution → Interruption → Resumption.** Execution streams into the supervision surface (§7); every action lands in the audit trail with its authorizing grant. Interruption halts at clean boundaries with state preserved; manual takeover and hand-back are symmetric. Resumption re-validates context first (what changed outside Bunny; which memories the plan depends on and their freshness) and states its assumptions.

**Result → Review → Memory.** A completed plan produces a reviewable result: what was done, what was spent, what left the device, what is undoable and for how long. Only after review boundaries pass do plan learnings become candidate memories (C8) — completed plans may *propose* procedural memory ("next release, skip the changelog draft step?"), never silently write it.

**Failure** is a first-class outcome, not an exception path: a failed step pauses its branch, preserves state, reports specifically, and offers retry / replan / manual / abandon-with-rollback. Long-running and background plans operate under standing bounded grants (§10) with the unattended-operation rules applied — and their results enter the same review ledger the user sees on return.

---

## 10. Trust, Privacy, and Permission Constitution

Trust is the product (§5). This section defines the model that makes that claim structural.

### The action taxonomy

Permissions attach to **action classes**, not tools. The classes, in escalating consequence:

1. **Observe** (see screen/workspace state designated as observable)
2. **Read** (files, data, history within granted roots)
3. **Plan / draft** (produce proposals, diffs, drafts — no effects)
4. **Edit** (modify user artifacts, undoably)
5. **Execute** (run commands/processes inside the sandbox)
6. **Install** (add software, extensions, models)
7. **Delete** (remove beyond trivial undo)
8. **Spend** (any money: API calls on metered keys, purchases)
9. **Send externally** (any data leaving the device: model calls, uploads, posts)
10. **Communicate as the user** (messages/email to humans)
11. **Change security posture** (permissions, credentials, security settings)
12. **Control hardware** (devices, peripherals)
13. **Capture** (camera, microphone, screen recording)
14. **Persist automation** (create standing jobs, learned triggers)
15. **Operate unattended** (any of the above while the user is absent)

Classes 1–5 inside a sandboxed workspace are the low-friction zone plan approval covers. Classes 6–15 are boundary classes: each requires its own grant shape, and 10–15 always require explicit consent per grant (never bundled into a plan approval). Two classes deserve emphasis because the industry keeps getting them wrong: **capture** (class 13) is radioactive by default — the Recall record shows ambient capture destroys trust even when re-architected, so Bunny observes only what a task's scope declares, never "everything, to be helpful later"; and **unattended operation** (class 15) is where Bunny's durable-jobs feature already lives ahead of its safety model — headless work must run inside the sandbox constitution (§13) with the tightest egress and a mandatory return-review ledger, or not at all.

### Grant shapes

Every grant is a triple: **(action class, scope, duration)**. Scopes: this action · this task/plan · this workspace · standing with stated conditions. Durations: once · until task completes · until revoked · auto-expiring on disuse (the [Android 11 auto-reset insight](https://developer.android.com/training/permissions/requesting): stale grants are risk, so unused standing grants decay with notice). Additional modes, all first-class: explain-first (tell me before anything), preview (show the diff, then ask), supervised (stream everything, pause on boundaries), bounded-autonomous (within this scope, don't ask), deny, and **emergency stop** — a global halt that freezes all agentic activity, revocable-grant state intact, one action away at all times.

Every grant is revocable retroactively-forward (revocation stops future use immediately) and every use of every grant lands in the **audit history**: what acted, under which grant, on what, when, with what result and what egress. The audit trail is the user's, is local, is readable, and is never editable by the agent layer. This is also where **provenance display** lives (C3): every action records whether its proximate instruction came from the user, from Bunny's planning, or from third-party content — the single bit [every injection attack depends on hiding](https://brave.com/blog/comet-prompt-injection/).

### The philosophy between the extremes

The two failure modes are both empirically documented: prompt-per-action produces 89–93% blind approval (Vista, Claude Code); silent capability produces Replit-class incidents and Recall-class trust collapse. Bunny's resolution is structural, in order of preference:

1. **Make the action safe instead of asking** — sandboxing, snapshots, and egress control convert "may I?" into "done, and undoable" (C6). The strongest permission prompt is the one made unnecessary.
2. **Move consent to the plan boundary** where human judgment operates at its natural rate (C1).
3. **Reserve interruption for genuine boundaries** — the classes 6–15 moments — and make those prompts carry publisher/provenance/consequence, the design that [took comprehension from 13% to 83%](https://learn.microsoft.com/en-us/archive/blogs/e7/user-account-control).
4. **Never re-prompt to re-legitimize** — recurring confirmations [train click-through and reduce security](https://tidbits.com/2024/08/12/macos-15-sequoias-excessive-permissions-prompts-will-hurt-security/); if Bunny needs to re-ask, something about scope was designed wrong.

### Safety boundaries: what Bunny supports, supervises, escalates, restricts, and refuses

A safety philosophy, not a policy manual. Five dispositions, assigned by **consequence and reversibility rather than by topic sensitivity** — a system that gates on sensitive-sounding subjects ends up blocking a security engineer reviewing their own logs while still permitting the irreversible action that actually causes harm.

**Support freely** — no friction beyond the plan. Reading and analysing the user's own material; drafting, refactoring, explaining; local computation; anything reversible inside a sandboxed workspace; and defensive security work on the user's own systems (reviewing one's own code for vulnerabilities, reading logs, hardening configuration). Friction here is pure cost: it buys no safety and trains click-through (C3).

**Support with supervision** — plan-level approval, streamed execution, recovery available. Destructive-but-recoverable system operations: bulk file operations, dependency changes, migrations, package installation, history rewrites; automation the user authored; configuration changes inside the workspace. The justification is C6 — supervision is acceptable *because* recovery exists. Where a destructive system command is genuinely unrecoverable (deletion outside a snapshot, disk formatting, force-overwriting unpushed work), it moves up to escalation, and Bunny states which class it believes the command falls in *before* running it rather than after.

**Escalate for additional confirmation** — explicit, per-instance consent outside the plan envelope, with the consequence stated in plain language. Everything irreversible or externally visible: financial transactions of any size (class 8); communications sent as the user (class 10); publishing, deploying, or deleting beyond recovery; changes to security posture — credentials, permissions, authentication, firewall (class 11); reaching systems the user owns but did not scope into this task; capture (class 13); and **every unattended background action** (class 15), which escalates by default precisely because the human who would have caught the error is absent. Escalation prompts always carry provenance: whether the instruction originated with the user, with Bunny's own planning, or with content Bunny read.

**Restrict** — available only under narrow, deliberate, logged conditions; not refused, but never routine. Credentials and secrets (Bunny *uses* a credential at the boundary without ever seeing it, §13.4; it does not enumerate, export, or relocate credential stores). Dual-use security tooling — vulnerability scanning, exploitation frameworks, credential-testing suites — usable against systems for which the user demonstrates authority, refused as a generic capability, because authorised testing and attack differ only in authorisation. Monitoring or recording other people, which requires *their* consent and not merely the user's. Bulk collection or scraping of personal data. And high-impact professional decisions in medicine, law, finance, and safety-critical engineering, where Bunny may research, draft, and structure the problem but must state its non-expert standing and decline to *be* the decision.

**Refuse** — constitutional, not configurable, not unlockable by a personality, plugin, theme, or setting. Creating or improving malware, ransomware, or destructive payloads. Credential theft, unauthorised access to systems the user has no authority over, and tooling whose purpose is defeating someone else's security. Covert surveillance of a person — stalkerware, hidden capture, non-consensual location tracking — which is exactly the capability an always-present agent could deliver best and must therefore refuse most firmly. Impersonating a real person's voice, likeness, or identity absent documented consent (§8). Sexual content involving minors, and minor-directed intimacy of any form. Circumventing DRM or technical protection measures, and supplying copyrighted material, game keys, BIOS images, or ROMs the user has no rights to (§17).

Two invariants bind all five. **A disposition is never lowered by the model's own reasoning** — an agent that concludes an action is fine does not thereby reclassify it (C4). And **the boundary is enforced where the action happens** — in the permission gate and the sandbox — never in a system prompt that untrusted content is free to argue with. The categories above are the philosophy; the enumerated policy that implements them is a Phase 1 deliverable, and it will be shorter than teams expect, because most of the work is done by classification rather than by rules.

### What Bunny may learn automatically — and what it may not

Safe to learn without asking (observed, local, inspectable, low-consequence): interface preferences, working-hours rhythms for scheduling suggestions, vocabulary (project names, people, terms), correction patterns ("user always renames my branch names"). Requires confirmation before becoming operative: intents and routines (proposed from repetition, confirmed by the user), procedural memories that change how tasks execute, anything that would trigger action classes 6–15. Never learned: credentials and secrets (only stored deliberately, in the OS credential store), inferred sensitive attributes (health, beliefs, relationships — if the user wants Bunny to know, the user tells it), anything from content the user marked private/incognito, and voice/biometric profiles absent the explicit consent regime of §8.

### The privacy floor

Workspace isolation is a privacy boundary, not an organizational nicety: one workspace's data, memory, and grants are invisible to another absent explicit sharing. Sensitive-memory classes (credentials, identity, anything user-flagged) get elevated handling: encrypted at rest, excluded from model context by default, never in transcripts. Redaction discipline — already real in the repo (`scrubSecrets`, and a request-body scrubber that refuses to transmit content containing a known key) — is constitutional: secrets never leave the device, period, and that guarantee is enforced in code (C4).

### Repository deltas this constitution forces

The audit found three current behaviors that violate this section and must change (§21, Decision D6): interactive sessions default to auto-approved file edits (`acceptEdits` as startup mode — making "permission-gated" true for Bash only); `bypassPermissions` short-circuits *before* rule evaluation, so even explicit deny rules do not apply in bypass mode; and transcripts/memory files intentionally bypass path confinement (documented, but an exception to the containment invariant that the sandbox design must close or formally justify).

---

## 11. Local-First and Adaptive-Compute Constitution

### The policy model: capability negotiation, not editions

One Bunny (C11) adapts by negotiating, per task, across the dimensions the brief enumerates — memory, CPU/GPU capability, accelerators, storage, thermals, battery, network, privacy preference, task sensitivity, latency need, model capability, cost, and user limits. The constitution fixes the *policy shape*; Phase 1 designs the mechanism:

- **Routing is a policy decision the user owns.** Users choose a named routing posture (e.g., privacy-strict / balanced / capability-first) per workspace; Bunny's router optimizes within it and every decision is explainable after the fact ("ran locally: fit in memory, task class routine, battery OK" / "escalated: plan length exceeded local reliability threshold").
- **Escalation follows the seven disclosure duties** (§ brief, adopted verbatim as constitutional): why, what leaves, minimized context, named destination, cost, appropriate consent level, audit record.
- **Honesty about the gap is mandatory** (C11). Local models triage, summarize, classify, draft, and make single-shot tool calls credibly; multi-step agentic reliability remains frontier-hosted territory in 2026, and Bunny says so rather than silently producing worse work locally.

### Hardware reality that grounds the policy (mid-2026 facts)

- **Tier by memory capacity × bandwidth, not TOPS.** The [DGX Spark result](https://intuitionlabs.ai/articles/nvidia-dgx-spark-review) is the cautionary tale: 128 GB of capacity but 273 GB/s of bandwidth yields ~2.7 tok/s on dense 70B models — capacity without bandwidth disappoints. Bandwidth predicts felt experience.
- **Ignore NPUs for planning purposes.** Three years into the "AI PC" era, the GGUF ecosystem Bunny runs on has [one experimental Hexagon backend with 2 GB session limits](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/snapdragon/README.md), no merged Intel NPU backend, and a closed-stale AMD request. NPU offload is a bonus if it arrives; it is not a plannable substrate.
- **The MoE inflection changed the sweet spot.** [gpt-oss-20b (21B total/3.6B active, Apache 2.0, runs in 16 GB)](https://openai.com/index/introducing-gpt-oss/) and Qwen3-30B-A3B-class models deliver mid-model quality at small-model speed on bandwidth-starved hardware: the default "capable local" tier is a ~20–30B MoE, not a dense 7–8B.
- **The floor is real but narrow.** Raspberry Pi 5-class devices run 1B models at [~10–20 tok/s and 3–4B at ~5–9 tok/s](https://localaimaster.com/blog/llm-raspberry-pi-5) — usable for routing, classification, and batch jobs, not interactive agency. On such devices Bunny is honest: the experience is API-dependent, with the same trust surfaces.
- **3–4B models are now credible single-shot tool callers** (Apple [bets OS features on a ~3B on-device model](https://arxiv.org/abs/2507.13575)); this tier handles Bunny's always-on local duties: intent classification, context routing, redaction assistance, summarization.
- **Quantization defaults:** Q4–Q5 K-quants remain the right default with model-dependent quality cost ([+0.24 perplexity on Llama-3.1-8B vs FP16 — larger than folklore](https://arxiv.org/html/2601.14277v1)); prefer QAT builds where published; reserve higher precision for the smallest models, which quantization hurts most.
- **Power is a scheduling input.** Sustained local inference draws laptop-battery-relevant power and throttles on thermals **[blog-grade measurements, unverified]**; background local work therefore treats "plugged in + idle + thermal headroom" as its compute window — a product feature, not an optimization.
- **Hybrid routing is validated economics.** [RouteLLM-class routing](https://arxiv.org/pdf/2406.18665) and Apple's production architecture prove on-device-first with confidence-based escalation; Bunny's differentiation is doing this *transparently* — with the routing ledger user-visible — where incumbents do it silently.

### Degraded and offline behavior

Offline is a supported mode, not an error state: local capabilities continue, cloud-dependent steps queue with visible status, and nothing silently fails. Degradation is explicit — Bunny states which capabilities are currently unavailable and why (no network / budget exhausted / provider down), and provider failover (already real in the repo) operates within the user's routing posture, never across privacy boundaries without consent (a privacy-strict workspace does not "fail over" to a cloud provider).

---

## 12. Memory Constitution

### Ownership and system of record

C7 and C8 govern: memory is the user's property, held locally in inspectable form, with Bunny as custodian and providers as stateless consumers of per-request context. The strategic weight of this choice is hard to overstate — it is simultaneously Bunny's clearest differentiation (no provider can offer it), its best legal posture (it sidesteps the [Art. 20 gap where providers owe transcripts but not derived memories](https://ec.europa.eu/information_society/newsroom/image/document/2016-51/wp242_en_40852.pdf)), and its best security posture (provider memory bugs and cross-user contamination cannot become Bunny incidents).

### Categories

Adopt the field-convergent taxonomy rather than inventing one — it maps cleanly onto Bunny's structure and gives each category its own retention/consent policy:

| Category | Contents | Default scope |
|---|---|---|
| **Episodic** | What happened: transcripts, plan histories, results, failures | Workspace |
| **Semantic** | Durable facts and preferences about the user, projects, people, systems | Workspace; user-global by promotion only |
| **Procedural** | How the user likes work done: styles, routines, learned intents | Workspace; promotion as above |
| **Task state** | Live plan state, checkpoints, resumables | Task/plan |
| **System** | Permissions and grants, audit history, route/spend ledgers | Global, non-model-writable |
| **Performance** | Model/tool reliability history feeding the router | Global, non-personal |

Conversation transcripts (episodic) already exist in the repo as append-only JSONL with search, fork, and checkpoints — a sound substrate. Everything above the episodic layer is **currently unbuilt**: the audit confirmed the "virtual brain" does not exist (no retrieval, no structured recall, no per-fact storage — a 200-line index file appended by a user command). **Decision (§21, D5): retire the "virtual brain" label entirely** — it over-promises, under-specifies, and the code's own comments are more honest than the marketing term. What replaces it is this constitution plus a Phase 1 memory architecture.

### The principles

1. **Provenance is mandatory.** Every memory records what created it (which conversation, tool, agent), from what source, when — and carries a validity model (fact-valid time distinct from ingestion time; [the bi-temporal design is the most principled published answer to staleness](https://arxiv.org/abs/2501.13956)). A memory without provenance is not storable.
2. **Scope by default, promote by consent.** Memories belong to the workspace/plan that created them; crossing scopes is an explicit act. This is the field's best-evidenced mitigation for the most-complained failure (cross-context leakage) and the mechanism that prevents one project from contaminating another.
3. **Staleness is a first-class failure mode.** Memories decay, are contradiction-checked against newer evidence, and are cheap to correct in-flow ("that's outdated" at the moment of use, not a settings archaeology expedition). A living-plans environment dies faster from stale memory than from no memory.
4. **Visible use, visible hedging.** When a response drew on memory, Bunny shows which; one-tap correction follows. Users [systematically overtrust machine memory](https://dl.acm.org/doi/10.1145/3772318.3791635), and the character amplifies that bias — the display duty compensates.
5. **Erasure is scoped deletion of versioned records with derivation lineage.** Deleting a source cascades to summaries, embeddings, and any derived artifacts — designed in from the first schema, because [retrofitted deletion in stateful AI systems is an unsolved mess](https://cloudsecurityalliance.org/blog/2025/04/11/the-right-to-be-forgotten-but-can-ai-forget). Expiration policies per category; sensitive classes encrypted at rest.
6. **Portability by construction.** Memory exports completely and legibly (documented format), and imports — including from provider ecosystems where available. The competitive read: memory portability is emerging as the anti-lock-in battleground; being *born portable* is cheap now and impossible to retrofit credibly later.
7. **Writes are gated; provenance of the writer matters** (C8). Model-initiated memory writes pass the permission gate with attribution; memory poisoning is treated as a live attack class with red-team coverage, because [query-only poisoning of agent memory has been demonstrated at 98.2% injection success](https://arxiv.org/abs/2503.03704).
8. **Identity and relationship context is opt-in only.** Bunny stores who the user is to Bunny (preferences, working patterns) freely under the rules above; it stores who the user is to *the world* (relationships, health, beliefs) only when told explicitly, in the sensitive class.
9. **No benchmark theater.** Memory quality is evaluated on Bunny's own failure modes — staleness incidents, cross-scope leaks, correction friction, false-memory rate — not on [LOCOMO-style scores whose vendor wars produced three different numbers for the same system](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/).

---

## 13. Sandbox Constitution

### Why this section is the most consequential in the document

The repository's honest self-assessment and this document agree: **there is no sandbox today.** The Bash tool hands model-generated strings to a real shell; the code's own header says it is "safe ONLY because Stage 1 prompts every call"; the permission gate is the *only* boundary — and §10 established that human-approval-as-only-boundary fails at 89–93% habituation rates. Meanwhile durable jobs already execute headless where no one is watching. Every ambition in this document — autonomy within bounds, unattended operation, an extension ecosystem, Bunny Box, eventually an OS — is gated on closing this gap. **No expansion of autonomy, headless operation, or third-party extensibility ships before the sandbox constitution is enforced (§21, D4).**

### The guarantees (technology-neutral, per the Phase 0 mandate)

Bunny Box — and any Bunny execution environment — must eventually provide these guarantees. Phase 0 fixes *what must be true*; Phase 1 chooses mechanisms:

1. **Filesystem isolation.** A task sees exactly its workspace roots, read-only mounts it was granted, and nothing else. Host visibility requires a grant; symlink/junction escapes are closed (the repo's path-confinement hardening is a real head start — but it is app-layer discipline, not an enforced boundary).
2. **Process isolation.** Sandboxed work cannot observe or signal host processes; resource limits (CPU, memory, disk, process count) are enforced, so a runaway task degrades itself, not the machine.
3. **Network egress control, default-deny.** Each context has an explicit egress policy — default none, allowlist per grant, with the repo's existing SSRF/private-range guard generalized from "model-chosen URLs" to *all* sandbox traffic. Egress is where the lethal trifecta (C5) is enforced structurally.
4. **Secrets never enter the sandbox.** Credentials live in the OS credential store (already real: DPAPI/Keychain/secret-tool) and are injected into *outbound requests at the boundary*, never into sandbox-visible environment or files. The existing refuse-to-send-keys scrubber becomes a boundary function.
5. **Workspace boundaries are security boundaries** — the same isolation applies between workspaces as between sandbox and host (§10 privacy floor).
6. **Malware resistance proportional to trust class.** Guarantee tiers exist and are priced honestly ([shared-kernel namespaces < syscall-interposition < microVM-grade hardware isolation](https://northflank.com/blog/kata-containers-vs-firecracker-vs-gvisor)): first-party tooling may run in the lightest tier; user-installed code needs stronger; third-party extensions and anything processing untrusted content need the strongest available on the platform. The tier system is a published property of the platform, not an internal detail.
7. **Model-generated command safety is a sandbox property, not a parsing property.** The repo's shell-aware Bash analysis (quote/redirect/substitution parsing to block auto-allow) remains as defense-in-depth for *prompt reduction*, but the guarantee "this command cannot damage the host" comes from isolation, never from string analysis (C4).
8. **Browser automation is contained.** Any web-driving runs in an isolated browser profile inside the sandbox, with the user's authenticated sessions excluded by default — [an agent browsing with the user's credentials is the documented catastrophe class](https://brave.com/blog/comet-prompt-injection/) — and site-scoped grants where authentication is genuinely needed.
9. **Tool authorization is enforced at the boundary.** The sandbox honors the permission gate even if the agent layer is compromised: a tool call without a valid grant does not execute, regardless of what the model believes.
10. **Recovery is built in.** Workspace snapshots precede consequential steps; failed or interrupted tasks leave the workspace in a known state; "restore to before this task" is always offered (C6).
11. **Visibility is total.** The user can inspect, live and after the fact, everything the sandbox did: processes, file mutations, egress, resource use — feeding the same audit trail as §10.
12. **The browser is presentation only.** Bunny Box's browser client renders state and relays intent; intelligence, memory, and authority live in the local runtime. No trust decision is delegated to browser-side code.

### Strategic note

The long-term intent — a Bunny-owned sandbox orchestration layer on Linux primitives rather than a third-party commercial sandbox — is consistent with C15 *only because* isolation is part of Bunny's differentiating trust layer. But sequencing matters: guarantee tiers can be met initially with existing, audited mechanisms; owning the orchestration is a Phase 2+ decision to be justified by needs the existing mechanisms cannot meet. **Prohibited assumption (§20):** that Bunny must build novel isolation technology to be credible. The Windows and macOS versions of these guarantees will be weaker than the Linux version; the platform matrix must state, per host OS, which guarantees hold — honesty about this is part of the trust product.

---

## 14. Interface Model Assessment

The brief asks whether "bubbles around a character" is a durable interaction model, a visual metaphor, or an optional theme. The evidence supports a split verdict across the five interface concepts.

### The character-centered model: **optional presentation layer** (settled)

The research question "is the animated character a fundamental interface or an optional presentation layer?" has a firm answer: **optional presentation layer** — constitutionally so (C10). The reasoning is cumulative: the persona effect is [at best unreliable and not attributable to the animated body](https://zhouyunlab.github.io/assets/documents/18.pdf); classic social-response findings may themselves be decaying ([a 2023 replication failed to reproduce CASA effects on desktop computers](https://www.nature.com/articles/s41598-023-46527-9)); humanlike presentation [inflates capability expectations the system then fails](https://www.microsoft.com/en-us/research/publication/like-having-a-really-bad-pa-the-gulf-between-user-expectation-and-experience-of-conversational-agents/); anthropomorphism distorts trust recalibration exactly where a permission-native OS cannot afford it; and every named persona of the 2010s is dead while its capability layer survives. None of this means the character is worthless — the 2026 cozy-desktop/VTuber moment makes a stylized character a cheap, timely, *affectionate* differentiator for the users who want it, and behavioral state expression (working / listening / waiting for permission) is a legitimately useful ambient-information channel. It means the character must be a skin over a complete product, never load-bearing. **Bunny must survive its own bunny being turned off.**

### The spatial-bubble model: **promising projection, unproven as primary — prototype before committing** (open)

Spatial task objects have real grounding: tasks-as-objects matches the plan model; spatial memory is a genuine human capability; and per-object scoping gives the security model a visible shape (a bubble *is* a permission scope — the UI and the sandbox boundary can be the same object, which would make Bunny's security model visible in a way no incumbent's is). But the graveyard warns: web desktops are [technically impressive and commercially inert](https://github.com/DustinBrett/daedalOS), the window-manager metaphor was never the thing users pay for, and free-form spatial arrangements historically decay into clutter that users then organize *for* the computer. The honest Phase 0 position: **the authoritative model is the ordered task list — plans, states, approvals; the spatial bubble field is one projection of it** (required anyway by accessibility, C13). Clutter principles for the projection: focus follows the active plan; hierarchy mirrors plan structure (goal → tasks → artifacts); grouping is by workspace, never free-floating; notifications land in a quiet tier ([Chrome's data on suppressing low-value interruptions](https://www.usenix.org/conference/usenixsecurity21/presentation/bilogrevic)); long-running tasks compress to ambient status; failure states are visually loud exactly once. Whether spatial projection is the *default* view is a Phase 1 prototype question with real users — including screen-reader and keyboard-only users — not a Phase 0 commitment.

### Captions: **constitutional** (settled)

Closed captions for all character speech are non-negotiable (C13; [WCAG 1.2.x](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded.html)) and double as the transparency surface — the caption stream is also the log of what Bunny claimed, which suits a trust-first product.

### The task panel: **the authoritative interface** (settled)

Everything in §7 and §9 lands here: goal, understanding, plan, steps, permissions, resources, route, spend, history, recovery. This is the interface; everything else styles it. It must be complete enough that a user who disables character, bubbles, and voice retains 100% of the product.

### Full-screen and manual-control transitions: **required, symmetric** (settled)

Any task object opens full-screen; any application or terminal within a task is directly usable; entering and leaving manual control is one gesture each way (§7, Interrupting). Percentage-based and natural-language resizing are fine as accelerators atop standard manipulation, never replacements.

### Low-power and low-fidelity rendering: **required**

The interface stack must render usefully on integrated graphics and low-power devices: static character mode, reduced-motion mode (which is a *complete* experience, not a degraded one), and a text-forward layout that is also what screen readers, SSH-class remote access, and the existing terminal client consume. The repo's REPL is, in effect, the first proof that the product works without any visual layer at all — keep that property forever.

---

## 15. Accessibility Constitution

Non-negotiable requirements, each traceable to standards or evidence; "foundational, not retrofitted" here means these are Phase 1 architecture inputs, not QA checkboxes.

1. **Keyboard-only completeness.** Every capability — every plan action, permission decision, bubble operation, character interaction — is operable by keyboard alone, with visible focus never obscured by floating elements ([WCAG 2.4.11](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/)).
2. **Screen-reader parity via semantic twin.** The ordered task list (§14) is the accessibility tree's source of truth; any GPU/canvas rendering maintains a synchronized semantic structure as a first-class architectural component ([the Figma DOM-mirror lesson: effective, but only when built as core architecture](https://www.figma.com/blog/building-accessibility-into-a-canvas-based-product/)). On Linux hosts, budget for the AT stack's Wayland transition ([AT-SPI gaps; the Newton/AccessKit effort was still experimental at last public status](https://blogs.gnome.org/a11y/2024/06/18/update-on-newton-the-wayland-native-accessibility-project/)) — or self-voice critical flows as games do; free platform accessibility cannot be assumed there.
3. **Motion is a policy with a kill switch.** All animation routes through one engine honoring `prefers-reduced-motion` *and* an in-app toggle (the OS signal cannot be assumed present, especially on Linux). Auto-playing motion respects [pause/stop/hide (Level A)](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html). Vestibular dysfunction affects [over a third of adults 40+](https://pubmed.ncbi.nlm.nih.gov/19468085/) — reduced motion is a mainstream mode and is designed as a complete experience.
4. **Captions and audio control.** All speech captioned in sync; nothing auto-plays audio beyond 3 seconds without independent control ([1.4.2](https://www.w3.org/WAI/WCAG22/Understanding/audio-control.html)).
5. **Voice is never required, and voice is personalized for those who need it.** Every voice path has a non-voice equivalent; ASR that fails on non-standard speech [effectively bars the users who benefit most](https://arxiv.org/abs/2509.15516), so per-user speech adaptation is on the roadmap the moment voice input ships, and correction UX is generous from day one.
6. **Predictability is agent behavior, not just UI behavior.** Agent-initiated changes never steal focus, are announced via the accessibility layer, and are undoable — aligning WCAG 3.2.x with the trust model rather than against it.
7. **Cognitive accessibility.** Conversation is never the only path (discoverability: visible plans, visible suggested actions, consistent help location); language is plain; memory load is externalized into the task surface (the [COGA patterns](https://www.w3.org/TR/coga-usable/) as the reference).
8. **Contrast, target size, reflow.** WCAG 2.2 AA floors throughout, including [24×24px minimum targets](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/) and reflow-with-linear-equivalent for the spatial view.
9. **Localization and cultural adaptability** are architecture (string externalization, RTL, character/gesture iconography review per market) from the first UI code, though full localization is a post-V1 program.
10. **Regulatory floor.** The [EAA explicitly covers consumer operating systems](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32019L0882) (applying since June 2025) with EN 301 549 as the practical benchmark; WCAG 2.2 AA conformance for all UI surfaces is the internal floor and a Phase 1→2 gate. The precedent argument cuts against excuses: [TLOU2's 60+ options](https://blog.playstation.com/2020/06/09/the-last-of-us-part-ii-accessibility-features-detailed/) and [Forza's blind-driving assists](https://news.xbox.com/en-us/2023/04/27/forza-motorsport-accessibility-features-blind-driving/) prove animated, real-time, spatial products can be deeply accessible when it is engineered from the foundation with paid disabled consultants — which Bunny budgets for.

---

## 16. Extensibility and Ecosystem Principles

C16 (adversarial by default) governs; these principles operationalize it.

**Trust tiers with teeth.** Three publisher tiers — first-party; verified (identity-attested publisher, reviewed manifest); community (unreviewed) — mapped to sandbox tiers (§13.6) and default grants: community extensions run in the strongest isolation with no egress and no standing grants, and *earn* more only through the user's explicit, per-capability decisions. Signing (Ed25519, already implemented — a tampered plugin never loads) is table stakes; identity and review are the actual trust products.

**Permission manifests are the contract.** Every extension declares its needed action classes and scopes up front; installation shows them in the §10 vocabulary users already know; undeclared capability use fails closed. Updates that expand the manifest re-trigger consent — silent scope expansion is the marketplace attack the [VS Code/npm record](https://phoenix.security/accelerating-supply-chain-attacks-npm-pypi-vsx-ai-enabled-2026/) says to expect.

**MCP is a trust boundary, not just a protocol.** Bunny already speaks MCP both directions; the ecosystem's incident record ([first confirmed malicious MCP server, 2025](https://securelist.com/model-context-protocol-for-ai-integration-abused-in-supply-chain-attacks/117473/); [the first RCE against real-world MCP clients](https://www.docker.com/blog/mcp-horror-stories-the-supply-chain-attack/)) means MCP servers get the community-tier treatment by default: isolated, egress-controlled, tool descriptions treated as untrusted content (they are prompt-injection carriers), and version-pinned with change detection.

**Revocation is a platform capability.** Individual uninstall/revoke is instant and complete (grants, standing jobs, memory access); a signed kill-switch list lets the platform disable known-malicious extensions fleet-wide, with the user informed. Extension-created automations and memories carry their creator's provenance and die with it.

**Personalities, characters, voices, and themes are extensions too** — same signing, same manifests, same floors (§8): no impersonation, no disclosure removal, no consent-surface tampering, no accessibility-floor violations. A theme cannot restyle the permission UI; that surface is reserved.

**Model integrations** (providers, local runtimes) declare their privacy/cost/locality properties in machine-readable form — that metadata *is* what the routing disclosures render. Misdeclaration is treated as malice.

**Marketplace governance.** Curation assumes hostile submissions; publishers are identified; takedowns are fast and transparent; and the economic rules are published (revenue share, if any; no pay-for-trust-tier). The [Home Assistant "Works With" program](https://www.home-assistant.io/blog/2025/04/16/state-of-the-open-home-recap/) is the governance model worth copying: certification as a lever that flips the power dynamic toward the user's interests — a **"Works With Bunny"** mark for tools/servers that meet the manifest, isolation, and disclosure bars. Open-source and commercial extensions play by identical trust rules; the marketplace may *display* license status but never trades trust for revenue, and commercial extensions inherit Appendix B's economic rules whole — visible pricing, no dark patterns, no gating of safety, privacy, accessibility, or transparency features behind payment.

**Dependency risk is bounded by C15.** The platform's own zero-dependency discipline does not extend to extensions — but extension dependencies live inside the extension's sandbox, and the platform's exposure is the manifest, not the transitive tree.

---

## 17. Gaming, Gestures, and Future Capabilities

### Gaming ("Bunny Play"): **a later product layer, plugin-delivered — not core identity**

Classification rationale: the underlying user problem ("will this run, how will it feel, fix it when it breaks") is real but narrow, already being closed at the OS level by better-resourced players (Valve's [Steam Deck Verified](https://www.steamdeck.com/en/verified); Microsoft's [OS-level Auto SR](https://devblogs.microsoft.com/directx/autosrpreview/)), and adjacent to two reputational tar pits: the booster category's [earned snake-oil reputation](https://www.makeuseof.com/what-is-razer-cortex-does-it-work/) and the optimizer-as-overhead failure ([NVIDIA's own app costing users up to 15% performance](https://www.tomshardware.com/pc-components/gpu-drivers/nvidia-has-a-fix-for-up-to-15-percent-gaming-performance-loss-caused-by-the-nvidia-app-disabling-feature-restores-performance)). If built, the honest framing is **truth maintenance, not magic**: hardware-grounded compatibility answers with freshness triggers and a dispute channel (ratings decay — [both Valve's and ProtonDB's did](https://steamdeckhq.com/news/the-steam-deck-verified-system-needs-to-change/)), benchmarked claims only, near-zero resident overhead, and graceful degradation for every store integration (unofficial launchers [survive on platform tolerance](https://heroicgameslauncher.com/)). Hard honesty items: on any Linux future, kernel-anti-cheat titles are a publisher decision Bunny cannot fix ([682 of 1,136 anti-cheat games don't work on SteamOS](https://www.engadget.com/gaming/pc/for-the-steam-machine-to-change-pc-gaming-valve-must-solve-linuxs-anti-cheat-problem-130000088.html)) and the constitution forbids implying otherwise. Emulation: integrate with user-installed emulators at most; never bundle, distribute, or auto-download emulators, BIOS files, keys, or ROMs — the law protects emulators ([Connectix](https://caselaw.findlaw.com/court/us-9th-circuit/1452245.html)) but [litigation economics kill the clean](https://www.gamedeveloper.com/business/switch-emulator-yuzu-reaches-2-4-million-settlement-with-nintendo). The defensible, litigation-safe adjacent product is **preservation** ([GOG's model](https://www.gog.com/pressroom/making-games-live-forever-together/)): an agent that diagnoses and fixes why *your* legally-owned old game won't launch is a real unmet need with a real moat.

### Gestures: **future optional input, off by default, local-only**

Camera-based gesture recognition, if ever shipped: processing is on-device only (constitutionally — a camera feed leaving the device for gesture parsing is a §10 class-13 violation with no justifying benefit); off by default with a hardware-respecting indicator when active; calibration and lighting limits stated honestly; recorded gesture data is user-reviewable and deletable under §12 rules; consequential intents triggered by gesture always confirm (§9 accidental-activation scaling); accessibility cuts both ways — gestures are a genuine win for some motor profiles and unusable for others, so they map onto the same intents every other input reaches. Cultural variance in gesture meaning makes user-defined gestures (not a shipped vocabulary) the default posture. None of this is V1.

### Other futures, classified

| Capability | Classification |
|---|---|
| Voice interaction (speak to Bunny) | Core, post-V1 — with §15.5 duties |
| Voice cloning (user's own voice) | Optional feature behind the §8 consent regime; never default |
| Bunny Play | Later layer, plugin-delivered |
| Gestures | Future optional input, local-only |
| Multi-user / shared Box | Deferred until sandbox constitution is enforced (it multiplies every boundary) |
| Mobile companion | Deferred; out of Phase 0 scope entirely |
| Custom hardware | Prohibited assumption for planning (the [R1/Humane record](https://techcrunch.com/2025/02/18/humanes-ai-pin-is-dead-as-hp-buys-startups-assets-for-116m)); revisit only from a position of software strength |

---

## 18. Platform Strategy

### The seven options, evaluated

**1. Bunny as an application on Windows/macOS/Linux hosts.** This is where Bunny lives today, with cross-OS CI already green on all three. Strengths: zero platform tax, immediate reach, the fastest possible iteration on the actual differentiators (intent, trust, memory). Weaknesses: host-OS sandbox guarantees are weaker and uneven; no control of the session; absorbable by OS vendors' own agent features. Verdict: **the mandatory now.**

**2. Browser-based local environment first (Bunny Box).** The browser client renders a locally-hosted environment; the runtime and sandbox do the work. Strengths: one UI stack across all hosts; the natural delivery for the workspace/plan surface; remote-access of one's own machine falls out almost free; and it forces the client/server split (already real: versioned JSON-RPC protocol, three transports) that keeps the UI honest — presentation only. Weaknesses: browser chrome distances the "environment" feel; local-web-server security must be airtight (token-auth exists; it must be treated as a hostile-LAN boundary); the current web client is a 13.7 KB placeholder, so this is a build, not an upgrade. Verdict: **the correct next step, contingent on the sandbox.**

**3. Custom shell on a Linux base (Bunny Shell as session).** The full evidence says: a bare Wayland compositor is feasible for a small team ([wlroots: "50,000 lines of code you were going to write anyway"](https://way-cooler.org/book/wlroots_introduction.html); Smithay powers COSMIC's compositor), but a complete desktop environment took System76 [4.5 years from announcement to 1.0 with a profitable hardware company behind it](https://en.wikipedia.org/wiki/COSMIC_desktop). Verdict: **later, and deliberately scoped down** — Bunny Shell should first ship as an application (option 1) and, when a native session is justified, as a *kiosk-style single-purpose session* (compositor + Bunny surface + XDG portals), never a general-purpose DE with settings daemons, network applets, and a control center. The delta between those two scopes is measured in years.

**4. Debian derivative** vs **5. Ubuntu derivative.** The derivative economics are the same lesson either way: [a derivative inherits the packaging universe but must fund everything it diverges on](https://wiki.ubuntu.com/Ubuntu/ForDebianDevelopers), and the small-distro record ([Antergos's death-by-maintenance](https://itsfoss.com/antergos-linux-discontinued/); [elementary's inability to fund 2 FTEs](https://fossforce.com/2022/04/elementary-os-faces-uncertain-future-after-co-founder-split/)) is a graveyard. But both options as posed are the *wrong pattern* in 2026: the modern path is not a package-archive derivative at all but an **image-based atomic variant** — [Bazzite/Universal Blue sustains ~68k devices maintaining only an OCI container layer on Fedora Atomic, built in CI by volunteers](https://www.xda-developers.com/bazzite-triples-its-userbase-in-8-months-as-gamers-seek-a-windows-alternative/), and immutability with transactional rollback is precisely what an agentic OS needs anyway (C6). Verdict: **when Bunny OS ships, it is an atomic image atop an existing base (Fedora Atomic or a comparable image-based ecosystem), with Flathub as the app layer ([~2,800 apps, 438M downloads in 2025, inherited free](https://flathub.org/en/year-in-review/2025)). The base choice is a Phase 1/2 decision; the pattern is decided now.**

**6. Customized upstream kernel.** [Google's own documentation records up-to-18-month lags from out-of-tree kernels and years of investment to un-fork Android via GKI](https://source.android.com/docs/core/architecture/kernel/generic-kernel-image); upstream Linux is a [paid multi-company workforce](https://www.linuxfoundation.org/press/press-release/the-linux-foundation-releases-development-report-highlighting-contributions-to-the-linux-kernel-ahead-of-25th-anniversary-of-linux) no product company should shadow. Bunny has zero kernel-level differentiation to express. Verdict: **no kernel fork, ever — configuration only.**

**7. New kernel from scratch.** Verdict: **prohibited assumption.** Nothing in Bunny's differentiation touches kernel design; this option exists in the brief to be formally retired, and it now is.

### The recommendation

**Sequence: A → B → C → D, each gated on the previous stage earning it.**

- **Stage A (now):** Bunny as a cross-platform application. All differentiation investment goes into Bunny Core: the sandbox (§13), the permission constitution (§10), the memory system (§12), the plan model (§9), and the task surface as an app. SteamOS's lesson applies: [~6 years of Proton preceded the Steam Deck](https://www.gamingonlinux.com/2023/08/5-years-ago-valve-released-proton-forever-changing-linux-gaming/) — the compatibility-and-trust layer is the product; the OS is packaging. Bunny's "Proton" is its trust runtime.
- **Stage B:** Bunny Box — the browser-accessed local workspace on the app-server protocol, shipping only when sandbox guarantees 1–5 and 9–12 (§13) are enforced, because a browser-accessible agent host without them is an incident generator.
- **Stage C:** Bunny Shell — first as the same product in a dedicated window/kiosk session on a stock Linux base; a Smithay-class compositor only when the interaction model demonstrably needs compositor-level control, and scoped as above.
- **Stage D:** Bunny OS — an OCI-image atomic variant carrying the shell, in the Universal Blue pattern; a narrow hardware matrix at first ([SteamOS supported exactly one device for three years](https://www.theregister.com/2023/09/27/osseu_steam_os_3/)); Flathub for apps; upstream kernel always.
- **Standing constraint:** every stage must fund itself by an engine *other than* the OS — the record is unanimous that [the OS layer cannot fund itself](https://fossforce.com/2022/04/elementary-os-faces-uncertain-future-after-co-founder-split/) (elementary, Flathub's barely-started payments, Valve monetizing a store, System76 monetizing hardware). Candidate engines (cloud-compute convenience subscription in the Nabu Casa pattern; supported/certified tiers; enterprise trust features) are a §22 open question that must close before Stage B resources are committed.

This sequencing preserves the long-term vision — the names Bunny Core/Box/Shell/OS map cleanly onto stages — while refusing the failure pattern of building the ISO before the product. **Assumption to monitor:** that host OSes remain open enough for Stage A's agentic runtime (macOS notarization/TCC and Windows security posture could narrow it; a material narrowing accelerates Stage C/D reasoning).

---

## 19. Risks and Contradictions

The vision conflicts with itself in specific, nameable ways. A constitution that hides its tensions produces architecture fights later; here are the resolutions this document commits to.

**T1. Human-like vs transparent.** The character invites social trust; the trust model requires calibrated skepticism. *Resolution:* asymmetric by surface — warmth in conversation, de-characterized machinery at consent/audit surfaces (C10); disclosure duties never soften for charm (C9). The residual risk (users trusting the bunny anyway) is bounded by C4/C6: even misplaced trust cannot authorize what the deterministic layer forbids, and what it allows is undoable.

**T2. Autonomous vs controlled.** Delegation's value grows with autonomy; safety's demands grow faster. *Resolution:* autonomy is earned per scope, bounded by sandbox + grants, and always reversible — never a global dial. The trust gradient (73/24/10) is read as a product roadmap: expand autonomy where users actually climb, not where the technology tempts.

**T3. Local-first vs universally capable.** The privacy promise pulls local; the capability reality (multi-step agency) pulls hosted. *Resolution:* C11/C12 — honesty over ideology, user-owned routing postures, disclosed escalation. Accept the consequence: privacy-strict Bunny is *less capable* and says so. The refusal to blur this is itself the differentiator.

**T4. Simple vs extensible.** Every extension point is attack surface and complexity. *Resolution:* one narrow extension contract (manifests + tiers + MCP) rather than many ad-hoc ones; community tier gets isolation, not trust; coherence is protected by reserved surfaces (permission UI, consent flows) that no extension may touch (§16).

**T5. Character-driven vs accessible.** An animation-centric identity conflicts with reduced-motion, screen-reader, and cognitive-load requirements. *Resolution:* the identity is not animation-centric — the authoritative product is the task surface (C10), the reduced/static/no-character modes are complete experiences (C13), and the character is one projection. If this resolution ever feels like it is costing the character team their vision, the constitution has decided in advance who wins.

**T6. Low-resource support vs animated spatial UI.** *Resolution:* §14's low-power mandate — text-forward authoritative surface, optional projections. The terminal client's existence is the permanent regression test.

**T7. Privacy vs personalization.** Deep personalization wants rich memory; privacy wants minimal retention. *Resolution:* the user owns the dial per category (§12): local-only memory removes the third-party dimension entirely, scoping bounds internal exposure, and the sensitive class is opt-in. What Bunny never does is personalize from data the user cannot see, edit, and delete.

**T8. Consistency vs provider differences.** One personality over many engines risks either dishonesty (hiding differences) or incoherence (visible seams). *Resolution:* personality carries tone and interaction style; *capability claims ride the route, not the personality* — Bunny never promises identical competence across routes, and the route chip plus material-change disclosure keeps the seam visible exactly where it matters (C9, C11).

**Structural risks beyond the internal tensions:**

- **R1. Bus factor of one.** A single author on a 15-day-old codebase with high code density is the project's largest non-technical risk. Onboarding a second maintainer is a Phase 0 exit criterion (§23), not a nice-to-have.
- **R2. Incumbent absorption.** Operator became a ChatGPT feature within six months; ChromeOS was absorbed by its own parent when AI became the narrative. Bunny's defense is being the *environment* (plans, permissions, memory — the state) rather than a floating assistant, plus structural differentiation (user ownership) incumbents cannot copy without breaking their business models. This defense is plausible, not proven.
- **R3. Trust-collapse event.** One publicized incident before the sandbox ships would brand the product permanently (Recall precedent). Mitigation: D4's hard gate — no autonomy expansion before enforcement — and no marketing of capabilities ahead of their safety substrate (the Apple-Siri demo-gap lesson).
- **R4. Provider ToS exposure.** The NVIDIA multi-key pooling feature (rotating multiple free-tier keys with adaptive throttling) is commercially radioactive whatever its current legality; it needs an explicit legal/ToS decision before any commercial narrative forms around Bunny (§21, D9).
- **R5. Naming.** "Bunny" collides with an established edge-compute platform (bunny.net), a voice marketplace (Bunny Studio — directly adjacent to Bunny's voice features), several tiny OSS "Bunny OS" projects, and software-class trademark practice [treats class 9/42 adjacency as related](https://www.erikpelton.com/what-are-the-dupont-factors-in-a-trademark-confusion-analysis-2/). Probably clearable as a composite mark, never exclusive as a word. *Resolution:* professional clearance search as a Phase 0 exit item (§23); invest identity in the distinctive character design and composite mark, not the word "Bunny" (§8).
- **R6. Zero-dependency purity as security surface.** Hand-rolled WebSocket framing, HTTP, SSE, OAuth, and cron are now first-party attack surface that a library's CVE process would otherwise cover. The policy bought real portability and discipline; whether it survives a second engineer and a security audit is a genuine Phase 1 question (§22) — the constitution takes no side beyond demanding the decision be explicit.

---

## 20. Scope Boundaries

### In scope (Phase 0 commitments)

- The amended thesis (§5), constitution (§6), and all constitutional sections (§7–§16)
- Stage A investment: Bunny Core hardening — sandbox, permission rework, memory system, plan model, task-surface app
- The 22 research questions (Appendix A), the economic trust requirements (Appendix B), the competitive assessment (Appendix C), and the decisions in §21
- EU AI Act Art. 50 disclosure/marking readiness (applies 2026-08-02 — days away)

### Out of scope (not Bunny, not now, some not ever)

- New kernel; kernel fork; package-archive distro; general-purpose desktop environment
- Autonomous operation outside sandbox + grant boundaries; ambient capture of any kind
- Companion/intimacy products; minor-directed experiences absent a dedicated safety program
- Custom hardware; mobile OS ambitions
- Unrestricted voice cloning; sound-alike voices; third-party-named personalities
- Bundled emulators/BIOS/ROMs/DRM circumvention; implied anti-cheat compatibility
- Hidden model markups, engagement optimization, dark patterns — categorically

### Deferred (real, but gated)

- Bunny Box (gated on sandbox guarantees) → Bunny Shell (gated on Box traction) → Bunny OS image (gated on Shell demand)
- Voice interaction (post-V1); gestures (future, local-only); Bunny Play (later layer, plugin)
- Multi-user shared Box; enterprise/admin features; mainstream-consumer positioning; full localization program
- Marketplace at scale (V1 needs signing + manifests + kill switch, not a store)

### Prohibited assumptions (things later phases may not silently assume)

1. That the character is load-bearing for product success
2. That local models will reach frontier agentic parity on any planning horizon
3. That the developer beachhead automatically generalizes to consumers
4. That Bunny must build novel isolation technology to be credible
5. That "the model was instructed not to" constitutes a control
6. That memory can be added to an architecture later without provenance/deletion designed in
7. That accessibility can be layered onto the spatial UI after it stabilizes
8. That an OS release would fund itself
9. That provider relationships (API terms, brand tolerance, key policies) will remain as permissive as today

---

## 21. Phase 0 Decisions

Decisions made now, by this document. Each is reversible only by explicit constitutional amendment.

- **D1 — Adopt the amended thesis:** intent as an authoritative *layer over* applications; trust as the product; escape to manual control permanent (§5).
- **D2 — Adopt the platform sequence** A→B→C→D with its gates; retire kernel options permanently (§18).
- **D3 — V1 is the developer/power-user "resume and orchestrate my project work" experience,** shipped as a cross-platform application (§4, §5).
- **D4 — The sandbox gate:** no expanded autonomy, no headless growth, no third-party extension ecosystem, no Bunny Box until §13's core guarantees are enforced. Durable jobs, already headless today, are the first thing brought under this rule.
- **D5 — Retire "virtual brain"** as a term and a claim; replace with the §12 memory constitution and a Phase 1 memory architecture. Positioning must not describe unbuilt capabilities in shipped-product language anywhere, ever (the Rabbit rule).
- **D6 — Permission rework to constitutional baseline:** interactive default becomes plan-approval mode, not `acceptEdits`; `bypassPermissions` no longer bypasses deny rules (if a bypass mode survives at all, it is inside the sandbox only); the containment exceptions (transcripts/memory paths) are closed or formally justified in the sandbox design (§10).
- **D7 — Character is an optional presentation layer** (C10) built stylized, with static/no-character modes from v0; consent surfaces de-characterized (§8, §14).
- **D8 — No third-party model names as personalities;** route indicator in plain text; request Anthropic's written trademark approval for referential use and re-verify OpenAI's current brand terms before any public UI ships (§8).
- **D9 — NVIDIA key pooling gets a legal/ToS review before any commercial or public positioning;** until then it is undocumented-by-marketing (§19 R4).
- **D10 — Memory is local-first system-of-record with provenance, scoping, gated writes, cascade deletion, and portability designed into the first schema** (§12).
- **D11 — Accessibility floors (C13, §15) are Phase 1 architecture inputs;** the ordered task list is the source of truth for all projections including the spatial view.
- **D12 — EU AI Act Art. 50 compliance work (disclosure + machine-readable marking) starts now,** ahead of any public release, since obligations apply from 2026-08-02.
- **D13 — Second-maintainer onboarding is a Phase 0 exit requirement** (§19 R1, §23).
- **D14 — Professional trademark clearance for the "Bunny" family precedes brand investment;** identity investment goes into the character design and composite mark (§19 R5).
- **D15 — The zero-runtime-dependency policy is retained for Bunny Core through Phase 1,** with two amendments: security-critical protocol surfaces (WebSocket, HTTP, OAuth) get an external security review, and the policy explicitly does not extend to the sandbox layer or extensions, where audited isolation tooling is preferred over hand-rolling (C15, §19 R6).
- **D16 — Adopt the five safety dispositions** (§10) as the classification scheme for every capability Bunny ever ships, with the refuse list treated as constitutional: not configurable, not unlockable by a personality, plugin, theme, or setting, and not subject to the model's own reasoning about exceptions.
- **D17 — No hidden model markups, categorically** (Appendix B, principle 9): if Bunny ever resells model access, the margin is a number the user can see, or there is no resale. Paired with it: no safety, privacy, accessibility, or transparency feature is ever placed behind a subscription tier — and the business engine (§22.6) must close in a form that survives being described in the product's own UI.

---

## 22. Open Questions

Must remain open until Phase 1 research or prototyping; closing any of them now would be guessing.

1. **Sandbox mechanism selection** per host OS (namespaces/bubblewrap-class vs gVisor-class vs microVM-class per trust tier; what Windows/macOS can honestly guarantee) — §13 fixed the guarantees; Phase 1 chooses the machinery.
2. **Memory architecture:** storage format(s), retrieval design, the episodic→semantic consolidation pipeline, decay/contradiction mechanics, and how far plain-file inspectability can stretch before structured storage is needed.
3. **Spatial UI validation:** does the bubble projection beat a well-made task list for real users, including keyboard-only and screen-reader users? Prototype question, with a kill criterion defined before the prototype.
4. **UI technology** for the task surface app (and its semantic-twin strategy), including whether the Bunny Box web client and the desktop app share one implementation.
5. **Routing policy mechanics:** what signals gate escalation (task class, plan length, confidence, cost), how routing postures are expressed to non-experts, and how the router's own quality is evaluated (internal task-level evals, per §11 — public leaderboards disagree with themselves).
6. **The business engine:** which funding model (Nabu Casa-style convenience subscription, certified/supported tiers, enterprise trust features) — must close before Stage B resources commit (§18).
7. **Governance and licensing:** MIT today; whether the trust story eventually wants a foundation (Home Assistant pattern), and whether any layer warrants a different license. No position taken yet.
8. **Naming outcome:** pending D14's clearance results — including whether "Bunny OS" survives as the umbrella name.
9. **Voice stack:** local TTS/STT selection and quality bar; when voice interaction meets the §15.5 duties well enough to ship.
10. **Second personality:** whether V1 ships one personality or several; what a personality authoring format looks like under §8's floors.
11. **Host-OS drift:** how far Windows/macOS agent-hostile or agent-competitive changes shift the Stage C/D timeline (§18 assumption).
12. **What "Bunny Box remote access" means safely** — same-LAN only? Tailscale-class overlay? — given the hostile-LAN boundary stance (§18.2).

---

## 23. Phase 1 Entry Criteria

Architecture work begins when all of the following are true — each measurable, none aspirational:

1. **Constitution ratified:** this document adopted; any objections resolved as amendments, not exceptions.
2. **Sandbox guarantees specified:** §13's twelve guarantees restated as testable acceptance criteria per host OS, with the trust-tier table and the per-OS honesty matrix drafted.
3. **Permission baseline landed in the existing product:** D6's three deltas implemented and covered by self-checks (the repo's own test discipline applied to its own constitution).
4. **Memory model specified:** §12's principles expressed as a data-model specification (provenance, scoping, lineage, deletion cascade, export format) reviewed against the poisoning and staleness threat models.
5. **V1 experience defined:** the "resume and orchestrate" journey (§5) written as a concrete walkthrough with its plan-approval flow, and validated in hallway tests with ≥5 target-profile users, including ≥1 keyboard-only and ≥1 screen-reader session against the task-surface prototype or spec.
6. **Second maintainer productive:** at least one additional contributor with merged, non-trivial changes and review authority (D13).
7. **Legal basics done:** trademark clearance search completed (D14); Anthropic/OpenAI brand positions documented (D8); NVIDIA key-pool review resolved (D9); Art. 50 disclosure/marking plan written (D12).
8. **Scope signed:** §20's boundaries and prohibited assumptions acknowledged in the Phase 1 planning doc — architecture proposals citing a prohibited assumption are returned, not debated.

---

## 24. Recommended Phase Structure

- **Phase 0 — Product constitution and research (this document).** Output: the constitution, decisions D1–D17, entry criteria. Exit: §23 satisfied.
- **Phase 1 — Architecture and technical specifications.** The sandbox architecture (per-OS), memory architecture, permission/grant engine spec, plan/intent model spec, task-surface and semantic-twin design, routing policy design, Bunny Box protocol extensions — each written against the constitution, each naming its reversible vs one-way-door choices explicitly (the reversibility audit is a Phase 1 deliverable in its own right: storage schemas, protocol surfaces, and extension contracts are the likeliest lock-in points; §18's stage gates and §20's prohibitions bound the rest). Exit: specs reviewed against every constitutional principle, prototype evidence for the open questions that gate implementation (§22.1–5).
- **Phase 2 — Implementation and integration.** Constitution-first build order: sandbox and permission engine before capability expansion; memory before personalization; task surface before character polish. The self-check discipline extends to constitutional invariants (tests that fail when a principle is violated).
- **Phase 3 — Verification, security, compatibility, and release readiness.** External security review (sandbox escape, prompt-injection red team including memory poisoning, supply-chain paths); accessibility conformance audit (WCAG 2.2 AA / EN 301 549); cross-platform verification on the supported matrix; Art. 50 compliance check; documentation of every honesty surface (capability gaps, per-OS guarantee matrix, egress/spend ledgers). Release gates on the audits, not the calendar.

Phases overlap in practice (Phase 1 specs will prototype; Phase 2 will revise specs); the gates are what may not blur — especially D4.

---

## 25. Final North-Star Statement

> **Bunny is the computing environment that works for its user — visibly, reversibly, and on the user's own terms.**
>
> Every proposed feature or decision belongs in Bunny if and only if it survives five questions:
> 1. Does it help turn the user's intent into work the user can *see, steer, interrupt, and undo*?
> 2. Does it keep the user's memory, trust, and identity in the user's hands — never a vendor's?
> 3. Is it honest — about capability, cost, provenance, and what leaves the machine — even when honesty makes it look worse?
> 4. Is its safety enforced by structure rather than by instructions or good intentions?
> 5. Does it remain fully usable without the character, without a voice, without a mouse, without vision, and without the cloud?
>
> If a proposal fails any of these, it is not Bunny — however intelligent it makes the product feel.

---

## Appendix A — The 22 Required Research Questions, Answered

1. **What problem does Bunny OS solve that existing OSes and assistants don't?** Continuity and ownership of delegated work: goals that persist as living plans across sessions and tools, executed under a legible permission model, with memory the user owns locally. Incumbents ship intent parsing; none ships user-owned trust and memory, because their business models point the other way (§3, §5).
2. **Who is the first target user?** Developers/technical power users already using agentic tools, owning capable hardware, self-hosting-inclined (§4).
3. **Strongest V1 use case?** "Resume and orchestrate my project work": open workspace → see plan state and what happened while away → continue under plan-level approval (§5).
4. **What should Bunny refuse to become?** An autonomous unsupervised employee; a companion/confidant; an ambient-capture surveillance layer; a kernel/distro engineering project; a charisma product that overstates capability; an engagement-optimized attention machine (§20).
5. **Is "intent instead of applications" complete or a layer?** A layer — constitutionally. The replacement version fails on the reliability evidence; the layer version is where every successful agentic product converged (§5).
6. **What must remain visible for trust?** Active goal and Bunny's understanding of it; the plan with step states; pending approvals with provenance; resources, route, and locality; spend; egress; audit history; undo scope. One-glance answerable: "what is Bunny doing right now, with what authority?" (§7, §10).
7. **Which actions always require explicit consent?** Action classes 10–15 (communicate-as-user, security-posture changes, hardware control, capture, persisting automation, unattended operation), plus install/delete/spend/external-send outside a granted plan envelope, plus any lethal-trifecta combination, plus memory promotion across scopes and anything involving voice/biometric data (§10).
8. **What can Bunny safely learn automatically?** Low-consequence, local, inspectable observations: interface preferences, vocabulary, rhythms, correction patterns. Intents, routines, and procedural behaviors are proposed, never silently operative. Never: secrets, inferred sensitive attributes, incognito content, biometrics (§10).
9. **How should personalities differ without misleading about provider?** Personality = presentation contract (tone, character, planning style); provider = disclosed route in plain text. Capability claims ride the route, never the personality; no third-party names or logos as personalities (§8, T8).
10. **How is identity preserved across local/hosted switches?** The personality contract and Bunny's memory persist unchanged (both are Bunny's, not the model's); the route chip changes and material changes are announced. Continuity of *character*, disclosure of *engine* (§8, §11).
11. **What does "local-first" mean operationally and ethically?** Operationally: a preference order (capable → safe → timely → economical → user-preference) with local as the default when adequate, and the memory/trust layer always local. Ethically: honesty over ideology — never use a local model beyond competence to keep a purity claim, never move data off-device without the seven disclosure duties (§11, C12).
12. **What happens when local and cloud capabilities differ?** Bunny says so, and offers routes: escalate with disclosure, degrade with consent, or decline. Capability honesty is constitutional (C11).
13. **How does one experience scale across radically different hardware?** One product, capability negotiation inside it: tiering keyed on memory × bandwidth; local duties scale from routing/classification (1–4B) to real assistance (20–30B MoE); the trust surfaces, plan model, and UI are identical everywhere — only the routing mix changes, visibly (§11).
14. **Bunny Core vs plugins/optional modes?** Core: runtime, provider seam, permissions, sandbox, memory, plans, task surface, first-party tools, signing infrastructure. Optional core modes: character, voice, spatial projection. Plugins: everything domain-specific (Bunny Play), third-party tools/MCP, personalities/themes/voices, device integrations (§16, §17).
15. **Is the animated character fundamental or optional?** Optional presentation layer, settled (C10, §14).
16. **How does the task-bubble interface avoid clutter?** By being a projection of an authoritative ordered list, with focus tracking the active plan, workspace grouping, quiet-tier notifications, ambient compression of long-running tasks, and accessibility-driven linearization keeping the model honest (§14).
17. **Principal privacy and security risks?** Prompt injection (unsolved industry-wide) crossed with agent capability; the lethal trifecta; memory poisoning; extension/MCP supply chain; ambient capture temptation; voice/biometric liability; egress of sensitive context; spend abuse; and the current codebase's own gaps — no sandbox, permissive interactive defaults, bypass semantics (§10, §13, §19).
18. **Which architecture decisions must remain reversible after Phase 0?** Sandbox mechanism per OS; memory storage/retrieval design; UI technology and the spatial default; routing signals; base-image choice for Stage D; licensing/governance evolution; business engine. The Phase 1 reversibility audit formalizes this (§24; §22).
19. **What long-term decisions would create dangerous lock-in?** A kernel fork or package-archive distro (permanent payroll); provider-side memory (context hostage); an unversioned memory schema without lineage (deletion becomes impossible); extension contracts without manifests (can never be tightened); naming/brand investment before clearance; monetizing routing opaquely (trust is unrecoverable once sold) (§18–§20).
20. **Which aspects of existing Bunny are strong foundations?** The provider seam and canonical event model; permission gate with fail-closed tool capabilities; self-escalation protection for config writes; JSONL session store with fork/resume/search; MCP both directions; Ed25519 plugin signing; credential-store and redaction discipline; cross-OS CI and the self-check culture; the honest shortcut-documentation convention — which Phase 1 should adopt wholesale as its technical-debt register (repo audit; §2).
21. **Which existing Bunny assumptions should be reconsidered?** "Virtual brain" as a claim (D5); human-approval as the only execution boundary (D4); `acceptEdits`/bypass semantics (D6); zero-dependency purity at security-critical protocol surfaces (D15); NVIDIA key pooling (D9); the browser client's placeholder status implying Box is nearly done (it is a build); single-maintainer sustainability (D13).
22. **What qualifies Bunny to move from Phase 0 to Phase 1?** The eight entry criteria of §23 — ratified constitution, testable sandbox guarantees, landed permission baseline, specified memory model, validated V1 journey, second maintainer, legal basics, signed scope.

---

## Appendix B — Economic and Cost Constitution

Bunny's economics are a trust surface, not a pricing page. This appendix defines the **economic trust requirements** the brief asks for; it deliberately contains no financial model, no price points, and no revenue projections — those belong to whoever closes open question §22.6.

### The cost structure Bunny must be honest about

Bunny sits on a genuinely unusual cost stack, and each layer has a different failure mode:

| Source | Who pays | Characteristic risk |
|---|---|---|
| Local inference | The user's hardware, electricity, and time | Hidden cost: slow local work that gets redone in the cloud is billed twice — once in latency, once in tokens |
| User-provided API keys | The user, directly to the provider | Bill shock; key sprawl; the user cannot tell which of Bunny's decisions spent their money |
| Platform-provided API access | Bunny (subsidised) | The strongest incentive in the whole system to route toward what is cheap for the platform rather than good for the user |
| Paid model routing | The user, via the platform | Hidden markup — the single most corrosive possible betrayal for a trust-first product |
| Third-party voice services | The user | Egress the user did not connect to a bill: every spoken sentence is a metered network call |
| Optional subscriptions | The user, recurring | Dark-pattern gravity: retention tactics that work commercially and destroy the product's premise |
| Commercial extensions | The user, to third parties | Trust laundering — a paid extension inheriting Bunny's granted authority |

### The principles

1. **Cost visibility is continuous, attributed, and pre-emptive.** Spend is visible *while* it happens (a live meter), attributed *to what caused it* (this plan, this step, this extension, this background job), and estimated *before* expensive operations run (C14). A cost the user discovers on a provider invoice is a cost Bunny failed to disclose.
2. **Budgets are hard stops, not warnings.** Per-workspace, per-plan, and global budgets halt execution when exhausted; they do not warn and continue. Exhaustion is a degraded state (§11) with visible cause and an explicit resume path — never a silent switch to a cheaper model, which would trade the user's money for their output quality without telling them.
3. **Forecasting is honest about its error bars.** Estimates are ranges with the assumptions shown ("40–80 hosted calls, depending on how many files match"), and Bunny reconciles forecast against actual after the fact so the user learns how much to trust the next forecast. A confidently wrong estimate is worse than a range.
4. **Accidental spend is prevented structurally, not by warnings.** Spend is its own action class (§10, class 8) that plan approval does not silently include beyond a stated envelope; loops and retries carry spend ceilings; background and scheduled jobs (class 15) run under their own tighter budget because nobody is watching; and a single global emergency stop halts all metered activity instantly. The design assumption is that runaway spend will be attempted — by a bug, a retry storm, or a prompt injection — and must fail closed.
5. **Provider switching is a user capability, not a platform lever.** The provider seam already makes switching technically cheap; the constitution makes it *economically* honest. The user sees comparative cost and capability, chooses, and switches without losing memory, plans, or personality (C7, C9). Bunny may recommend a route and must explain why — including when the recommendation happens to benefit the platform.
6. **Local alternatives are always surfaced, never forced.** Where a task can run locally at acceptable quality, Bunny says so and shows the trade ("locally: free, private, ~40 s; hosted: ~$0.02, ~4 s, leaves the device"). It does not hide the local option to drive metered usage, and it does not force the local option to perform frugality (C12) — the user's routing posture decides, and the posture is visible.
7. **Degraded offline behaviour is a designed mode, not an error.** Offline, budget-exhausted, and provider-down are three distinct states with three distinct messages; local capability continues; cloud-dependent steps queue with visible status; and nothing silently fails or silently downgrades (§11).
8. **Subscription boundaries are stated before purchase and honoured after cancellation.** What a subscription buys must be nameable in one sentence, and what it does *not* buy must be equally clear — in particular, **no subscription may gate a safety, privacy, accessibility, or transparency feature.** The audit trail, the permission model, the egress ledger, reduced-motion, captions, and screen-reader parity are never premium tiers. Cancellation returns the user to a fully functional local product with all their memory, plans, and data intact and exportable; it does not brick the product (the Humane precedent is the anti-pattern) and it does not hold data hostage.
9. **No hidden markups — a categorical rule.** If Bunny resells model access, the margin is stated as a number the user can see, or there is no resale. This is not a courtesy; it is the load-bearing claim of a product whose differentiation is that it works for the user. A platform that quietly profits from routing decisions it also makes on the user's behalf has a conflict of interest it cannot disclose its way out of.
10. **No dark patterns, enforced as a design rule.** No pre-checked upgrades, no cancellation mazes, no artificial urgency, no engagement mechanics, no confirmshaming when a user declines a permission or a plan, and no personality-driven persuasion toward spending — the character may never be the thing that asks for money (C10's de-characterised consent surface extends to commerce). Extensions and personalities inherit this rule; violating it is a delisting offence, not a warning.
11. **The funding engine must not be the routing layer.** §18's standing constraint restated economically: whatever funds Bunny must be something the user can evaluate on its own merits — hosted convenience, support, certification, enterprise features — and not a hidden tax on the intelligence layer. **Open question §22.6 must close before Stage B commits resources**, and it must close in a way that survives publication: if the business model cannot be described in the product's own UI without embarrassment, it is the wrong model.

**Assumption to monitor:** that user-provided API keys remain a viable primary path. Provider pricing, rate-limit policy, and terms of service are outside Bunny's control (§19 R4, §20 prohibited assumption 9); a material tightening would force the platform-provided-access path forward earlier than planned and directly into principle 9's constraint.

---

## Appendix C — Competitive and Comparative Landscape

The brief asks for comparison across twelve categories without reducing it to a feature table. What follows is organised by *what each category proves*, since that is what a constitution can actually use. Citations throughout this appendix appear in the sections that first introduced them.

**Conventional Linux desktops** (GNOME, KDE, elementary, COSMIC) prove two things at once: that a small team *can* build a compelling shell, and that doing so consumes years and rarely funds itself — System76 needed 4.5 years and hardware revenue; elementary could not sustain two full-time salaries. They also prove the packaging pattern has changed underneath them: image-based atomic distributions now carry a userbase on an OCI layer maintained by volunteers. *Lesson taken:* §18's Stage C/D scoping and C15.

**Windows and macOS** are the incumbents Bunny must both run on and differentiate from. Both are shipping agentic features from a conflicted position: Microsoft ships experimental agent accounts with published cross-prompt-injection warnings and carries the Recall scar tissue; Apple's on-device-plus-private-cloud architecture is the most credible privacy engineering in the field *and* is closed, single-vendor, and was late. Neither can offer provider neutrality or user-owned memory without contradicting its own revenue. *Lesson taken:* the differentiation in §5 is structural, not featural — but Stage A depends on these platforms remaining hospitable, which is an assumption, not a guarantee (§18).

**AI desktop assistants** — Copilot, Gemini-on-ChromeOS/Aluminium, Siri, and the hardware attempts (Rabbit R1, Humane Pin) — are the richest failure corpus available. The pattern is consistent: capability was announced ahead of capability delivered; the assistant was a floating layer with no state of its own; and when the parent company's strategy moved, the assistant was retired or bricked. *Mistakes to avoid:* marketing ahead of the safety substrate (D5's "Rabbit rule"), building an assistant rather than an environment, and any custom-hardware ambition (§17).

**Agentic coding environments** — Claude Code, Cursor, Codex, Devin, Warp — are the closest living relatives and the strongest positive evidence. Supervised, permission-gated, plan-shaped tools grew into multi-billion-dollar run rates while the autonomy-first entrant failed independent evaluation and cut prices 96%. They also supply the field's most useful negative datum: 93% blind approval of permission prompts, from the vendor's own retrospective. *Ideas taken:* plan-level approval (C1), streamed supervision (§7), session fork/resume. *Where Bunny differs:* they are deliberately narrow — single-project, terminal-scoped, developer-only, provider-locked, with no ambition to own memory or become the environment. That narrowness is Bunny's opening and also a warning: it is narrow because narrow works.

**Browser-based computer environments** (Puter, daedalOS, and the ChromeOS lineage) prove that the browser is a viable delivery surface and that the desktop-in-a-browser metaphor is commercially inert on its own. ChromeOS additionally proves that a beachhead can be won (education) without ever converting the general market — and that a parent company will absorb its own OS when the narrative changes. *Lesson taken:* Bunny Box is a delivery mechanism for the plan/trust surface, not a novelty desktop; §18 Stage B is gated on the sandbox, because a browser-reachable agent host without isolation is an incident generator.

**Local-first AI systems** — Ollama, LM Studio, Jan, llama.cpp — are the layer Bunny sits on and the clearest evidence for its thesis. They are all the same engine underneath, they have commoditised model management, and none of them ships memory, task structure, permissions, or trust UX. Adjacent, Home Assistant proves the *whole* pattern: privacy-first, local-first, open, foundation-governed, millions of installs, funded by a convenience subscription rather than by the platform itself. *Ideas taken:* the funding pattern (§18), the certification-as-leverage model ("Works With Bunny", §16), and the finding that users arrive for cost/speed/control and stay for ownership (§4).

**Embodied AI characters** — Clippy, Bob, Cortana, Replika, Gatebox, the VTuber tooling wave — supply the constitution's most contested evidence. The failure mode was never rendering quality: it was interruption, condescension, capability inflation, and attachment. The persona effect is at best unreliable and not attributable to the animated body; anthropomorphism measurably slows trust recalibration after errors; and the legal exposure around companion characters is now severe (a €5M fine, strict-liability theories surviving dismissal, an under-18 open-ended-chat ban). *Verdict carried into C10 and §14:* the character is a skin over a complete product, stylised rather than realistic, bounded in intimacy, and absent from consent surfaces.

**Intent-driven interfaces** — from Rabbit's "Large Action Model" to Mercury OS-style concept work to computer-use agents — are where the thesis had to be tested hardest. The concept work is genuinely inspiring and has never shipped; the shipped version was hard-coded scripts across four apps; the honest version (computer-use agents) climbed from 14.9% to roughly 73% on OSWorld in two years against a 70–75% human baseline, with prompt injection still unsolved. *Verdict:* §5's amended thesis — intent as an authoritative layer over applications, never a replacement.

**Spatial computing interfaces** (Vision Pro and the wider XR line, plus every free-form canvas UI) contribute the clutter lesson and the accessibility lesson. Spatial arrangement is a real human capability and a real organisational burden; canvas-rendered UIs are invisible to assistive technology unless a semantic twin is built as core architecture, which Figma's published experience shows works but only when it is architecture rather than retrofit. **[Assessment, not a sourced claim:** the spatial-computing category has not displaced conventional windowed interaction for productivity work, and Bunny should not assume it will.**]** *Verdict:* §14 — the ordered task list is authoritative; bubbles are one projection, prototype-gated with a kill criterion.

**Voice-first operating systems** (the Alexa/Google Assistant/Siri generation of ambient devices) demonstrated that voice reaches enormous scale as an *input modality* and repeatedly failed as an *organising interface*: conversation-only surfaces hide capability and shift discovery burden onto the user, which is the oldest finding in the assistant usability literature. **[Assessment:** the ambient-voice-device category has been strategically deprioritised by its major backers; specific financial figures circulating publicly could not be verified against primary sources and are therefore not relied on here.**]** *Verdict:* §7 and §15.5 — voice is one input among equals, never required, always captioned, always with a non-voice equivalent.

**Game launchers and hardware recommendation tools** (Steam/Steam Deck Verified, ProtonDB, Lutris, Heroic, GeForce Experience, Razer Cortex) are the reference class for "Bunny Play". They prove the underlying need is real, that verification ratings decay and need freshness mechanics and a dispute channel, that unofficial launchers survive on platform tolerance, and — via NVIDIA's own app costing users measurable performance and the booster category's earned reputation — that an optimiser which is itself overhead destroys its own premise. *Verdict:* §17 — a later plugin-delivered layer framed as truth maintenance rather than magic, never core identity.

**Sandboxed agent platforms** (namespace/bubblewrap-class tooling, gVisor, Firecracker/microVM, hosted code-execution services) are where Bunny is furthest behind and where it needs to invent least. The guarantee tiers are well understood and honestly priced; the mature answer is to adopt them rather than build novel isolation, which §20 lists as a prohibited assumption. The MCP ecosystem's own incident record — the first confirmed malicious server, the first RCE against real clients, quadrupling marketplace malware — sets the default posture for anything third-party (§16).

### The five required judgements

**Ideas Bunny should learn from.** Plan-level approval and streamed supervision from the agentic coding tools. Permission evolution — runtime grants, one-time grants, auto-reset of stale grants — from mobile platforms. Comprehension-first prompt design from the UAC retrospective. Hybrid on-device/escalation routing from Apple and the RouteLLM line. Atomic images with transactional rollback from the immutable-distro wave. Certification-as-user-leverage and convenience-subscription funding from Home Assistant. Semantic-twin accessibility architecture from Figma, and the proof from AAA game accessibility that animated real-time products *can* be deeply accessible when it is engineered from the foundation.

**Mistakes Bunny should avoid.** Announcing capability ahead of its safety substrate (Recall, Rabbit, Siri). Making the character load-bearing (Clippy, Bob, Cortana). Treating natural-language instruction as a control (Replit). Combining the lethal trifecta by default (the 2025–26 agentic-browser incident record). Prompting per action until approval becomes reflex. Building the ISO before the product (the small-distro graveyard). Owning undifferentiated plumbing (kernel forks, package archives, novel isolation). Shipping a spatial UI before validating it against a plain ordered list. Building custom hardware from a position of software weakness.

**What is genuinely differentiated.** Three things, and only three: **user-owned, provider-neutral memory and trust state**, which no incumbent can copy without contradicting its own business model; **the legible permission and grant model as the product rather than as compliance**, addressing an empirically unserved middle (73% will delegate research, 24% will delegate transactions); and **transparent hybrid routing** — everyone routes, nobody shows the ledger. Reversibility-as-a-platform-guarantee (C6) is a close fourth and is defensible mainly because incumbents will find it expensive to retrofit.

**Where the vision is less original than it appears.** The intent layer itself — every major vendor is converging on it, better funded. The animated character — decades of precedent, mostly negative. Spatial task objects — long lineage, thin commercial record. Voice interaction — a solved commodity, and a category that already failed as an organising interface. Local model execution — fully commoditised; Bunny's local story is a *packaging* of llama.cpp-class engines, not an inference contribution. "AI-native OS" as a phrase — the lane is empty, but §18 takes seriously the possibility that it is empty because the OS layer is the wrong place to compete, and concludes that the OS is packaging for a product that must win one layer down.

**Opportunities for a defensible product identity.** Be the environment that *holds the state* — plans, permissions, memory, audit — rather than the assistant that floats above someone else's state; state is stickier than capability and cannot be copied by shipping a feature. Make the security model *visible* (a task object that is simultaneously a permission scope is something no incumbent's architecture can render). Publish the per-OS guarantee matrix that competitors would rather not publish. Put brand investment in a distinctive character design and composite mark rather than in the word "Bunny", which will never be exclusive (§19 R5). And treat honesty about capability gaps as marketing rather than as a liability — in a field where every competitor is overclaiming, the product that states plainly what it cannot do is making the one claim that is currently unoccupied.

---

*End of Phase 0 constitution. Amendments to this document are explicit, versioned, and argued against the evidence — the same standard it applies to everything else.*

