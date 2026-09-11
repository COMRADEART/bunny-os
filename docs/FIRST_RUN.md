# First-run experience

`bunny-first-run` is separate from Anaconda and runs as the new user. It is resumable and writes only a private per-user JSON state file atomically. It never stores a password, provider key, recovery key, hardware serial, or raw credential; providers use Secret Service aliases.

The person-facing flow is a short cinematic intro, not a Linux/systemd wizard: Welcome, name, timezone, accessibility, companion, voice, privacy, Ready. Microphone and speakers are skippable; typed Search and captions always work. Closing the window saves progress and leaves the desktop usable. Ready leaves Bunny in the corner, or hidden if that was chosen. The OS remains usable without the companion.

Privacy defaults are telemetry off, cloud memory off (`cloud_context=none`), remote diagnostics off, and plugin network denied. AI defaults to Automatic (local-first). “No online models ever” is Local only, not Cloud memory off. Cloud memory and a one-time online answer remain two consents. No multi-gigabyte model is downloaded automatically and no local-model speed is promised without a runtime benchmark.

The older thirteen-step persistence enum in `installer/first_run/state.py` (language, keyboard, updates, search locations, backup) remains for installer state compatibility. The Alpha window draws `companion.onboarding` and `installer.companion_flow.FIRST_RUN_STAGES`.

The present GTK flow and state model pass host source tests but have not run in GNOME, under Orca, at 200% scale, or across users.
