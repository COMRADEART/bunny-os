# Bunny Companion Runtime and UX Shell implementation report

Date: 2026-08-03 (America/New_York)

This report describes the first functional Bunny Companion phase. It distinguishes implemented contracts and deterministic tests from visual, hardware, provider, and image qualification that has not run.

## 1. Repository assessment

The repository was initially clean on `main` at `70995eaccb42508abff34f25938a41e19be02f14`. The only open pull request was, and at the final read-only snapshot remained, draft PR #26, `feature/capability-image-integration` into `main`: “Capability control plane: image integration and reproducibility candidate (Commit C′ 339b629)”.

The exact candidate under qualification is `339b629524b2022fa33bcd373bd314f302ea82e4`, whose parent is `96112e99d6e1cd977845c95f88a47207e3596117`. The PR tip is `9d3b0ade961896bc93b65b262f356bd6b837af90`; it contains post-candidate evidence and harness work and is not itself the candidate.

At the 2026-08-04 UTC GitHub snapshot, both “Hermetic builder (H1/H2)” runs for the PR tip had completed successfully. The general Phase 1/2, qualification-evidence, and release-blocker workflows still concluded failure, so this report does not call the PR green or the candidate fully qualified.

Before implementation, the build-input closure for the post-candidate evidence range found no installed path. The companion work was then based on the PR tip, outside the exact candidate.

## 2. Branch and commit lineage

```text
70995eaccb42  main / origin/main at audit
  ...
96112e99d6e  candidate parent
339b629524b2  protected capability candidate C′
9d3b0ade9618  post-candidate PR tip and companion branch base
273a96719f1e  core companion runtime, shell, schemas, integration, and tests
ac87a84       approval/recovery, package, accessibility, and process-boundary hardening
```

Feature branch: `codex/companion-runtime-ux-shell`.

The branch was created directly from `9d3b0ade961896bc93b65b262f356bd6b837af90`. No candidate commit was amended, rebased, or rewritten. Core commit `273a96719f1e4ab980161e6e9ae1179ab9cf2de8` has that PR tip as its sole parent.

## 3. Qualification and build-impact classification

The feature is build-affecting and requires a new artifact and qualification cycle. Direct artifact-affecting paths are:

- The new `companion/` package, schemas, installed documentation, service entry point, user unit, preset, desktop entry, default SVG, shell code, GNOME action, and command entry points.
- `build/Containerfile` and `build/scripts/install-root.py`, which change the build context and installed layout.
- `systemd/user/bunny-shell.target`, which changes user-session activation.

The closure analyser identified 32 paths through statically resolved install routes. It labelled six paths context-only because `install-root.py` uses dynamic loops or derived destinations; manual inspection establishes that the GNOME extension and both shell entry points are installed, while the Containerfile and installer directly change construction. The analyser reported nine unresolved install calls, so its classifications are not represented as complete proof.

Non-artifact test/developer changes are the Makefile target, repository validator alias, task runner registration, and `tests/companion/`. Every commit still changes OCI revision metadata and `/usr/lib/bunny-os/release.json` when built.

Protected evidence verification after implementation:

- `qualification/capability-integration` tree at branch base: `89a3fe6784cc2e8e83a173aa9058836f1d8363fe`.
- The same tree at the feature tip: `89a3fe6784cc2e8e83a173aa9058836f1d8363fe`.
- `build/inputs/qualification-target.json` at candidate C′ remains blob `36e3b26a90e7f0f450d72a43581cf099b889edf8`.
- No working-tree or feature-range diff touches those protected paths.

## 4. Architecture

```text
user / GTK client / headless client
              |
      private bounded protocol
              |
      CompanionRuntime service
              |
        persistent TaskSession
              |
   AgentCoordinator -- one ExecutorAdapter
          |                 |
 read-only reviewers    capability/privacy/cost checks
          |                 |
 structured observations   ApprovalCentre
          \                 /
          ordered TaskEvent stream
                    |
         CompanionStateController
                    |
      visual / text / caption / voice adapters
```

The service owns task truth, provider policy, execution authority, approval validation, event order, and state projection. The GTK shell is a restartable client and never recalculates those decisions. The provider-free executor is deliberately limited to one private task-history operation and is not a simulated commercial provider.

## 5. File-by-file change summary

Runtime and contracts:

- `companion/__init__.py` — contract version constants.
- `companion/model.py` — typed state, task, executor/reviewer, tool, output, privacy, audio, and visual records with bounds and redaction.
- `companion/events.py` — typed event set, observed/generated distinction, size limits, redaction, UUIDs, and evidence references.
- `companion/store.py` — private SQLite task/event persistence, ordering, replay, deduplication, and recovery.
- `companion/state.py` — deterministic state machine, event projection, statuses derived from observed records, and reconnect restoration.
- `companion/providers.py` — agent, voice, speech-input, usage, local system voice, captions-only, fallback routing, and microphone-gate contracts.
- `companion/coordination.py` — one-executor coordinator, immutable reviewer context, structured arbitration, limits, and provider-free local adapters.
- `companion/approval.py` — visual approval projection over `DurableApprovalStore`, full scope checking, replay/expiry rejection, and boot-bound deadlines.
- `companion/presentation.py` — capability-plan-bounded adaptive selection, hysteresis, accessibility signals, placement, and window directives.
- `companion/characters.py` — strict data-only directory/ZIP package importer and hostile-input validation.
- `companion/runtime.py` — headless task orchestration, persistence, approvals, event/state emission, execution, captions, local voice, recovery, and cancellation.
- `companion/protocol.py` — private Unix socket protocol, peer-UID check, bounded JSON messages, reconnection, and development-only authenticated loopback fallback.
- `companion/gtk_shell.py` — GTK4 task shell, static companion, task panel, speech bubble, captions, reviewer cards, privacy state, and Approval Centre controls.
- `companion/cli.py` — service/client commands and explicit provider-free demonstration harness.

Schemas:

- `schemas/companion-state.schema.json` — 23-state display projection.
- `schemas/companion-task.schema.json` — persistent bounded task session.
- `schemas/companion-event.schema.json` — ordered observed/generated task event.
- `schemas/companion-approval.schema.json` — complete Approval Centre view.
- `schemas/companion-provider.schema.json` — agent, voice, and speech-input descriptors.
- `schemas/companion-character-package.schema.json` — data-only character package manifest.

Installed integration:

- `services/bunny-companion/bunny_companion_service.py` — installed service entry point.
- `systemd/user/bunny-companion.service` — private, bounded, hardened user service using Unix sockets only.
- `systemd/user/bunny-shell.target` — starts the runtime with the shell session.
- `config/systemd/60-bunny-os-user.preset` — globally enables the companion service.
- `shell/services/bin/bunny-companion` — visual/headless client entry point.
- `shell/services/bin/bunny-approvals` — opens the authoritative companion Approval Centre.
- `shell/services/bunny_shell/ui.py` — permits the fixed companion launch target.
- `shell/components/gnome-shell-extension/extension.js` — fixed “Open companion” shell action.
- `shell/components/applications/art.comrade.BunnyCompanion.desktop` — desktop launcher.
- `shell/assets/companion/default-bunny.svg` — hand-authored static fallback; not generated or provider-sourced.
- `build/Containerfile` — makes companion source available to image construction.
- `build/scripts/install-root.py` — read-only Python install route, service/assets, enablement, and post-install assertions.
- `release/validation.py` — resolves the service entry point in unit-program validation.
- `Makefile` and `scripts/task.py` — `test-companion` target and required documentation registration.

Documentation and templates:

- `docs/COMPANION_RUNTIME.md` — architecture, contracts, security, operation, and honest limitations.
- `docs/COMPANION_CHARACTER_GENERATION.md` — external-generation/import policy and ownership boundary.
- `docs/templates/companion-character-prompts.md` — all requested reference, pose, loop, sprite, 3D, and texture prompts.
- `docs/templates/character-package.template.json` — intentionally incomplete import template.
- `docs/APPROVAL_CENTRE.md` — authoritative companion Approval Centre integration.
- `COMPANION_IMPLEMENTATION_REPORT.md` — repository, implementation, verification, limitation, and reproducibility handoff.

Tests:

- `tests/companion/test_state_events.py` — states, transitions, ordering, replay, redaction, and recovery.
- `tests/companion/test_presentation.py` — hardware/accessibility degradation, pressure, hysteresis, and window policy.
- `tests/companion/test_coordination_approvals.py` — executor/reviewer limits, arbitration, cost/privacy, approval attacks, and boot expiry.
- `tests/companion/test_characters.py` — directory/archive schema and hostile-package cases.
- `tests/companion/test_voice_audio.py` — voice health/fallback/cancellation and microphone/remote-audio gates.
- `tests/companion/test_vertical_slice.py` — private protocol, UX model restart, approval, recovery, captions, and separate-process slice.
- `tests/companion/test_image_integration.py` — installed layout, service hardening, activation, assets, and credential/state exclusions.

## 6. Companion-state schema

The version 1 state schema includes every requested state and all required identity, revision, timestamp, status, progress/tool, agent, approval, presentation, privacy, locality, and explanation fields. `ALLOWED_TRANSITIONS` is an explicit deny-by-default matrix. Self-transitions are revision updates; unlisted cross-state transitions fail. Status strings are deterministic event projections or generated descriptions that cite observed event IDs. There is no chain-of-thought field.

## 7. Task schema

The version 1 task schema persists classification, capabilities, privacy, locality, cost, latency, offline requirement, one executor, reviewers, phase, progress, approvals, tools, outputs, errors, cancellation, timestamps, and audit references. Request text is bounded and credential-shaped material is redacted before persistence; display records contain summaries and opaque output references rather than raw tool payloads.

## 8. Event schema

All 23 requested event types are present. SQLite assigns strict per-task sequence numbers in an immediate transaction. Stable UUID event IDs support identical replay deduplication; mismatched reuse and out-of-order sequences fail. Events are limited to 32 KiB, payload depth/items are bounded, sensitive keys/text are redacted, and generated descriptions must cite observed evidence.

## 9. Provider interface

`AgentProvider` exposes provider/model identity, capabilities, context limit, tools, streaming, structured output, image/audio features, locality, cost, privacy, authentication state, availability, health, cancellation, and usage. It contains no credential field. No OpenAI, Anthropic, Google, xAI, Kimi, GLM, or remote-node adapter is fabricated.

## 10. Executor and reviewer rules

The coordinator accepts exactly one executor assignment. A reviewer receives `ReadOnlyReviewContext`, which excludes the stored request body and has no execution, filesystem, desktop, approval, or routing method. Reviewers produce the requested structured observation and cannot approve themselves. Timeouts and malformed observations become explicit warnings rather than inferred verdicts.

## 11. Arbitration policy

Observations are preserved. Differences are grouped deterministically by category and evidence, material disagreement is surfaced, and executor revision is permitted but never silent override. Destructive/privacy-sensitive execution still requires scoped approval. Review rounds, tokens, tool calls, cost, elapsed time, and shared context are bounded; reviewers do not enter conversation loops. Consensus is explicitly not represented as correctness.

## 12. Approval Centre implementation

GTK renders requested action, reason, agent, affected data, destination/provider, locality, cost, resource impact, alternatives, expiration, and Approve/Deny/Cancel. The service revalidates request, plan, transition, destination, and provider destination. Expired, superseded, replayed, or changed records authorize nothing. Unanswered remains pending. A Linux boot-identity marker safely expires pending monotonic deadlines across a reboot while preserving same-boot service recovery.

## 13. Voice interface

The provider-neutral voice contract includes identity, language, style, speed, streaming, cancellation, format, locality, cost, privacy, health, and fallback. `VoiceRouter` refuses unapproved remote or paid voices and selects healthy ordered fallbacks. `SystemVoiceProvider` is a real optional local adapter for Speech Dispatcher, eSpeak NG, or macOS `say`; captions remain when it is absent or fails. Voice cloning and sample upload are not implemented.

## 14. Speech-input interface

The contract covers push-to-talk, wake interaction, explicitly enabled continuous conversation, local/remote locality, partial/final transcript callbacks, cancellation, silence timeout, availability, and privacy. `MicrophoneController` requires an explicit interaction and raises the persistent indicator before provider activation. It refuses disabled microphones, silent activation, unenabled continuous mode, and unapproved remote transmission. No production speech recognizer is claimed.

## 15. Character-package schema

Version 1 includes creator/license/name/version, renderer, assets, thumbnail/fallback, skeleton, every required animation, lip sync, expressions, resource estimates, minimum capability, hashes, and optional provenance/metadata. Validation rejects unknown executable hooks, undeclared files, executable types/modes, symlinks, traversal, absolute/drive paths, duplicate ZIP entries, encryption, suspicious compression, oversized assets/packages, hash/size mismatch, missing static fallback/license/animations, unsupported renderer, excessive resources, and credential-shaped metadata.

## 16. Adaptive-presentation logic

The existing `bunny.companion` capability-plan decision is a hard ceiling. Runtime signals can only reduce it along `full-3d -> lightweight-3d -> animated-2d -> static-image -> audio-only -> text-only`. Memory, GPU/VRAM, displays, audio, battery, thermals, foreground load, pressure, preferences, accessibility, headless state, and remote-render permission are considered. Degradation is immediate and recovery needs three healthy samples. Rendering degradation never cancels a task, and captions remain in the typed stream.

## 17. Accessibility implementation

The shell exposes captions, selectable task/status text, accessible button/field labels, keyboard activation, GTK/AT-SPI semantics, system text scaling, high-contrast-compatible theme colors, visible listening/speaking states, speech-rate bounds, no-hands-compatible audio presentation, and text-only fallback. Reduced motion/no animation overrides decoration in runtime policy. Physical assistive-technology testing has not run.

## 18. Privacy and security boundaries

There is no start-up screen, microphone, or camera capture; no automatic remote transfer or paid provider; no generic command/desktop tool; no executable package content; no package credentials; no reviewer access beyond the immutable projection; and no hidden reasoning storage. State and socket paths are private and reject symlink substitution. The user service is bounded and restricted to `AF_UNIX`. UI state carries remote-provider, screen-sharing, audio-transmission, paid-service, reviewer-context, modification, and microphone indicators.

## 19. Test results

Final isolated-worktree results:

- `python scripts/task.py test-companion`: 97 run; 96 passed and 1 skipped because the optional local `jsonschema` Python package is unavailable.
- `python scripts/task.py test-capability`: 803 run; 793 passed and 10 existing environment-dependent skips.
- `python scripts/task.py test-shell`: 4 passed.
- `python scripts/task.py test-approvals`: 2 passed.
- `python scripts/task.py validate`: PASS for JSON, schema headers/local references, Python compilation, desktop entries, XML/SVG, license declarations, committed evidence consistency, GNOME syntax, unit-program resolution, shell layout, and capability manifests.

Validation reported honest environment skips: Bash syntax, ShellCheck, PyYAML workflow parsing, and installed-Fedora `systemd-analyze`. Full image build, VM boot, hardware, visual, audio-device, and physical accessibility tests did not run.

## 20. End-to-end vertical-slice result

PASS at the service/protocol/UX-controller level without a commercial provider. The suite starts the service entry point in a separate process, creates a session, chooses the fixed local executor, emits real planning/tool events, records an observation-only reviewer result, exposes a scoped approval, approves through the same `CompanionViewModel` method used by GTK, completes the fixed local operation, emits caption/voice events, restores through new UI clients, rejects approval replay, and restores completed state after runtime restart. The static SVG and GTK view code are installed and parsed, but no rendered GTK pixels or physical audio output were verified.

## 21. Known limitations

- No real commercial/remote AI, remote compute, browser, coding, or desktop-control adapter.
- No production speech-recognition adapter and no voice cloning.
- No animated 2D or 3D renderer; only a static authored fallback ships.
- No booted Bunny OS image or installed systemd service test for this feature.
- No GTK visual regression, multi-monitor compositor, click-through input-region, focus, screen-reader, or switch-device run.
- No physical microphone, speaker, GPU, thermal, battery, or constrained-node measurement.
- Unix peer credentials and Linux boot identity are target behavior; the Windows test fallback uses a private random loopback token only for development.
- Complete Draft 2020-12 instance validation was skipped locally because `jsonschema` is absent; schema headers and local references passed repository validation.
- No reproducibility build has been performed for the companion artifact.

## 22. Unverified assumptions

- Target Fedora supplies compatible GTK4/PyGObject and user-service `StateDirectory` behavior.
- GNOME/Wayland APIs used by the shell match the target image versions.
- The target exposes `SO_PEERCRED` and `/proc/sys/kernel/random/boot_id` as expected.
- A local speech executable, if present, accepts the documented fixed argument form and has a functioning audio device.
- Current-machine capability assessment returns the installed `bunny.companion` decision on the eventual image.
- Compositor-level snapping/click-through will need a later explicit shell protocol rather than portable GTK calls.

## 23. Remaining work for final visual design

Run and iterate the GTK shell on a booted image; create signed/licensed animated packages; add verified compositor integration for geometry, snapping, click-through, focus, fullscreen, and active-monitor selection; establish responsive typography/high-contrast visual QA; add screenshot/interaction/accessibility regression fixtures; and validate all presentations with actual display hot-plug and workload pressure.

## 24. Remaining work for real AI providers

Add provider registries and policy-backed adapters one at a time; integrate authentication through a secret store outside all task/event/UI records; require explicit egress, cross-provider context, paid-use, and remote-destination approvals; implement streaming/cancellation/usage reconciliation; sandbox real browser/coding tools behind the capability applicator; and qualify failure, retry, retention, billing, and privacy behavior for each provider. Interface presence is not evidence that a provider works.

## 25. Reproducibility implications

This feature deliberately changes installed image inputs and cannot reuse candidate C′ evidence. Candidate C′, its target blob, and its evidence tree remain unchanged. A new candidate must be cut from the finalized companion branch and run through clean hermetic same-host repeatability, independent builders, installed-path checks, image inspection, boot/service tests, and any required hardware/accessibility gates. The two successful H1/H2 runs on PR #26 apply only to its `9d3b0ad` tip, not to this companion branch.
