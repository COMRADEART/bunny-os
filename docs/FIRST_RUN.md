# First-run experience

`bunny-first-run` is separate from Anaconda and runs as the new user. It is resumable and writes only a private per-user JSON state file atomically. It never stores a password, provider key, recovery key, hardware serial, or raw credential; providers use Secret Service aliases.

The steps are Welcome, Language and region, Keyboard, Privacy, Updates, User profile, Bunny introduction, Provider setup, Local-model setup, Search locations, Permissions overview, Backup and recovery, and Finish. Closing the window saves progress and leaves the desktop usable.

Privacy defaults are telemetry off, cloud AI unconfigured, remote diagnostics off, screen/microphone/camera off, no search locations, and plugin network denied. Provider/model/backup setup is skippable. Bunny can be enabled at login, launched manually, set local-only, or configured later. No multi-gigabyte model is downloaded automatically and no local-model speed is promised without a runtime benchmark.

Search accepts individual locations only; the entire home/root/parent cannot be selected. Completion offers Bunny Shell, update status, known hardware limitations, diagnostics, and getting-started material. A provider or model failure never blocks completion.

The present GTK flow and state model pass host source tests but have not run in GNOME, under Orca, at 200% scale, or across users.

