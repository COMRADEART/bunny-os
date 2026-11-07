# Adaptive Hybrid interaction contract (M1)

**Status:** Source contract for Hyprland-primary Bunny sessions  
**Compositor:** Hyprland (`BUNNY_DESKTOP_COMPOSITOR=hyprland`); GNOME remains for Safe Shell and transitional `bunny-gnome`  
**Design authority:** `docs/Bunny_OS_2_Adaptive_Hybrid_Spec.md`  
**Task truth:** `CompanionRuntime` + `PresentationProjector` only

## Layouts

| Layout | Purpose | Chrome |
|---|---|---|
| **Desktop** | Ordinary apps, Files, Terminal | Compact companion; task rail hidden |
| **Focus** | One primary work surface | Collapsible task rail (side ≥1500px, else drawer); compact companion |
| **Studio** | User-invoked expanded workspace | Side/drawer rail; companion only in free space |

Switching layout **retains** `taskId`, `eventSequence`, `approvalId`, and `artifactRefs` in `bunny-adaptive-layout` state. It does **not** restart agents, change permission authority, or invent progress.

CLI: `bunny-adaptive-layout {show,set,cycle,list,rail,waybar}`  
Keybinds (image-owned Hyprland): Super+D Desktop, Super+F Focus, Super+Shift+F Studio, Super+Tab cycle.

## Request submission

Typed and confirmed voice commands enter only through `CompanionGateway.submit_task` (same door). The shell may preview a plan; it must not execute tools or grant Trust.

## Event replay

UI clients resume from the last acknowledged per-task sequence after reconnect. The task rail is built by `bunny_shell.task_rail.build_task_rail` from presentation JSON only. Unknown event types degrade to a truthful generic status.

## Task selection and focus

Selecting a task updates the rail from that task’s projection. Window directives follow `companion.presentation.window_directive`: only outstanding approval may take focus; refreshes must not steal focus. Absolute Wayland placement is **not** available (`absolutePlacementAvailable: false`).

## Attention and notifications

Priority follows presentation phase priority: error / blocked / waiting_for_approval / disconnect outrank ordinary work animation. Lock screen must suppress sensitive content. Trust AT-SPI names remain `Allow this Bunny action` / `Deny this Bunny action`.

## Service disconnect

If the Companion daemon is down: Hyprland, dock/Waybar, Files, Terminal, and Safe Shell remain usable; chrome reports disconnected; restart replays authoritative events. Layout state alone is not task truth.

## Back to ordinary desktop

Super+D / `bunny-adaptive-layout set desktop` returns to Desktop layout without cancelling tasks. GDM still offers Bunny (Hyprland), Bunny (GNOME), and Bunny Safe Shell.
