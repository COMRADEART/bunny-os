# Bunny Companion runtime and UX shell

## Boundary

The Bunny Companion is a user-session service, not an animation embedded in a window. `bunny-companion.service` owns task sessions, provider selection, executor/reviewer coordination, scoped approvals, event persistence, presentation state, captions, and local voice dispatch. The GTK application is a restartable client over a private local protocol. Closing the GTK window does not signal cancellation and does not stop the service.

The implemented flow is:

```text
user request
  -> CompanionRuntime task session
  -> AgentCoordinator (one executor)
  -> capability-plan and privacy constraints
  -> ApprovalCentre (existing capability approval records)
  -> ExecutorAdapter
  -> ReviewerAdapter read-only observations
  -> ordered TaskEvent stream
  -> CompanionStateController
  -> GTK/text/caption/SystemVoice presentation adapters
```

Only typed records cross into the UI. The UI does not decide capability, locality, provider, approval validity, tool authority, or task success. A button returns the request id plus the original plan, transition, destination, and provider destination. The service rejects a changed, expired, superseded, or replayed scope before any executor is called.

## Process and persistence

The installed service entry point is `/usr/libexec/bunny-companion-service`. On Bunny OS it listens at `$XDG_RUNTIME_DIR/bunny-companion/runtime.sock`, mode 0600, and verifies the Unix peer uid where the platform exposes `SO_PEERCRED`. State lives under the service's private `StateDirectory=bunny-companion`:

- `companion.sqlite3`: bounded task snapshots and ordered task events.
- `approvals.json`: the existing capability `DurableApprovalStore` format.

The socket accepts one bounded JSON request per connection. Supported operations are `health`, `submit`, `tasks`, `snapshot`, `resolve_approval`, and `cancel`. Event replay is paged by per-task sequence. On Python builds without Unix sockets, development tests use a random loopback port plus a random token held in a private endpoint file; installed Bunny OS uses Unix sockets.

SQLite assigns each task sequence under `BEGIN IMMEDIATE`. `eventId` is unique and `(taskId, sequence)` is unique. An identical event id is a deduplicated replay; the same id with different content is rejected. A supplied sequence other than the next expected value is rejected. Event payloads are recursively bounded and redact credential-shaped fields and text.

## State and task contracts

The normative schemas are:

- `schemas/companion-state.schema.json`
- `schemas/companion-task.schema.json`
- `schemas/companion-event.schema.json`
- `schemas/companion-approval.schema.json`
- `schemas/companion-provider.schema.json`
- `schemas/companion-character-package.schema.json`

`companion/model.py` supplies the corresponding Python types. Every companion state carries the session and task identity, revision, start timestamp, deterministic status, optional progress/tool, executor, reviewers, approval state, visual/audio hints, privacy indicators, locality, and explanation reference. Status comes from task events and structured observations. There is no field for chain-of-thought.

Task records contain the requested fields but store only redacted, bounded request text and a SHA-256 reference. They contain no API key field, raw tool result, full screen capture, microphone sample, or model reasoning. Display outputs are bounded summaries plus opaque references.

## Executors, reviewers, and arbitration

`AgentCoordinator` enforces exactly one executor assignment per task. `ExecutorAdapter` owns planning, execution, and cancellation. `ReviewerAdapter` receives an immutable projection containing the display summary, classification, permitted capability names, privacy class, and redacted task events. It has no tool, file, desktop, approval, or provider-routing method.

Review is bounded by rounds, context bytes, provider tokens, tool calls, cost, and elapsed time. A timeout becomes a structured warning; malformed output is ignored and recorded as a quality warning. Reviewers never talk to one another. Arbitration groups observations by category and evidence references, preserves every observation, detects differing suggested actions, allows the executor to revise, and surfaces material disagreement. It always records that consensus does not guarantee correctness.

The provider-free slice uses `HarmlessLocalExecutor`. Its only operation records a digest and sanitized result in the companion task history. It cannot invoke a command, browse, control a desktop, choose a path, or contact a network. `LocalSafetyReviewer` observes its proposed event and has no execution authority. These are local deterministic adapters, not fake OpenAI, Anthropic, Google, xAI, Kimi, GLM, or other provider integrations.

## Capability plan and adaptive presentation

At service start, the runtime calls the existing capability discovery/score/budget/plan pipeline and consumes the `bunny.companion` decision. The GTK client never probes hardware. A supplied capability plan can be used for deterministic tests. If assessment cannot run, the runtime explicitly reports a conservative text-only fallback; it does not invent hardware.

The capability plan is a ceiling. Live presentation policy may only degrade beneath it. It considers available memory, GPU readiness, available VRAM, displays, audio output, battery, thermal pressure, memory pressure, foreground CPU load, user preference, reduced motion, no-animation, headless state, and remote-rendering permission. Degradation is immediate; recovery needs three healthy samples. The underlying task is never stopped because rendering or speech degraded.

The implementation ladder is `full-3d -> lightweight-3d -> animated-2d -> static-image -> audio-only -> text-only`. Missing display selects approved local audio or text. Missing audio retains captions. Reduced motion/no animation overrides decorative animation. The first package ships only a static SVG fallback; no 3D renderer or generated character is claimed.

## UX and window behavior

`companion/gtk_shell.py` implements center, docked, compact, task-panel, speech-bubble, text-only, and audio-oriented presentations as views of the same state. It shows current task, phase, executor, reviewer observations, tool, progress, approval, errors, captions, privacy indicators, and results.

Window policy is deterministic and testable in `companion/presentation.py`: snap preference, active monitor selection, always-on-top preference, passive click-through eligibility, focus preservation, full-screen compaction/hiding, and notification suppression are represented in `WindowDirective`. GTK implements hide, restore, minimize, keyboard activation, default window-manager dragging, sizing, and guarded always-on-top where the compositor API exposes it. GNOME Wayland deliberately owns absolute placement and focus; the application does not pretend it can move a surface to arbitrary coordinates. A future Shell protocol is still required for verified active-window bounds, click-through input regions, and compositor-level snapping.

The default shell avoids focus changes during event refresh. Opening the application or Approval Centre is a user action and may focus it. Approval controls, task text, captions, and privacy state have accessible labels and selectable text. The UI supports keyboard activation and GTK/AT-SPI screen readers. Reduced-motion and no-animation are enforced in runtime presentation selection. Physical screen-reader, switch-device, multi-display, and full-screen application tests have not run for this phase.

## Voice and speech input

`AgentProvider`, `VoiceProvider`, and `SpeechInputProvider` are replaceable contracts. Agent descriptors name model capabilities, context, tools, streaming, structured output, image/audio support, locality, cost, privacy, authentication state, availability, health, cancellation, and usage. There are no credentials in a descriptor.

`SystemVoiceProvider` is a real, optional local adapter for Speech Dispatcher, eSpeak NG, or the macOS system `say` command. It uses argument arrays, supports cancellation, and sends no data remotely. If none is present, the event stream records degradation and synchronized captions remain. No voice cloning or voice-sample upload exists.

`MicrophoneController` is the mandatory activation gate for speech input. It refuses absent/disabled microphones, silent activation, unenabled continuous conversation, and unapproved remote audio. The visible/transmitting indicator is raised before a provider can start and cleared on failure or cancellation. No production speech-recognition adapter is claimed in this slice.

## Privacy and security boundaries

- No screen, microphone, or camera capture occurs on service start.
- No commercial, paid, or remote provider is registered by default.
- The local vertical slice has no generic command or arbitrary-path tool.
- Reviewer context excludes the stored request body and includes only the sanitized display/task event projection.
- Character packages are data-only and reject traversal, symlinks, executable files/modes, hidden undeclared files, oversized entries, suspicious compression, excessive resources, missing license/fallback, unsupported renderers, and hash mismatch.
- UI state shows remote-provider, screen-sharing, audio-transmission, paid-service, reviewer-context, system-modification, and microphone indicators.
- Unanswered approval remains pending and authorizes nothing.

## Running the provider-free slice

Start the user service and open the UI:

```text
systemctl --user start bunny-companion.service
bunny-companion
```

For a headless protocol demonstration:

```text
bunny-companion vertical-slice
bunny-companion approve TASK_ID
```

`--auto-approve` exists only as an explicit deterministic test-harness option. Normal operation always waits at the Approval Centre.

## Known limitations

- No commercial or remote AI, voice, or speech-recognition adapter is implemented.
- No executable browser, coding, or desktop-control adapter is connected in the first slice.
- The GTK UI is implemented but has not been visually or assistive-technology validated on a booted Bunny OS image in this development environment.
- System voice availability is discovered, not guaranteed; captions are the verified fallback.
- The shipped character is a static fallback. Animated 2D and 3D renderer adapters remain future work.
- GNOME compositor integration for verified click-through, active application geometry, cross-monitor snapping, and focus policy remains future work.
- The new installed paths are build-affecting and require a new reproducibility and image-qualification candidate. They do not change the already qualified capability candidate commit.
