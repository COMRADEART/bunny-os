# Notifications and activity

GNOME Shell remains the OS notification centre. Bunny Desktop, applications, updater jobs, plugins, local models, sandboxes, and system services use the freedesktop notification service in the owning user session; the root broker never injects UI into a session.

Bunny's bounded Core summary can expose notification metadata, running/queued/completed task state, provider activity, local-model activity, sandbox state, and plan progress. Core is authoritative. Shell state may be stale and therefore includes a monotonically increasing sequence; it never changes server task state directly.

Lock-screen projection hides every notification body and all actions. Notifications marked sensitive (the conservative default) also replace the title with `Sensitive notification`. This prevents prompt, filename, artifact, and file-content disclosure. Do Not Disturb and application notification preferences are user settings; GNOME owns actual delivery suppression.

History is bounded to 500 projected items per collection. Flood control, grouping, dismissal, actions, pause/resume/cancel, and real notification daemon interaction require the GNOME/Bunny VM suite before they can be marked runtime-verified.
