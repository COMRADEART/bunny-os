<!-- SPDX-FileCopyrightText: 2026 ComradeArt -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# The Bunny session: what starts, in what order, and what may fail

This is the §12 dependency graph. It documents the user-session units that make
up Bunny OS Alpha 0.1, the order they resolve in, and — the part that matters
most — **which of them are allowed to fail without taking the companion down**.

## The graph

```text
graphical-session.target                    (the desktop session, GNOME/GDM)
        │
        ├── bunny-config-dir.service        oneshot: create the user's config tree
        ├── bunny-first-boot.service        oneshot: per-user first-boot state
        │
        ├── bunny-companion.service         the runtime. Long-lived, owns the store,
        │        │                          the tasks and the event stream.
        │        │                          RuntimeDirectory=bunny-companion → the socket
        │        │                          StateDirectory=bunny-companion  → the store
        │        │
        │        └── (inside the same process, all optional)
        │              ├── voice runtime          voice_enabled
        │              ├── speech-input runtime   speech_enabled
        │              ├── agent providers        agents_enabled
        │              └── desktop action broker  desktop_enabled
        │
        ├── bunny-companion-window.service  optional GTK client; installed but
        │        │                          not started at login. Wants= the runtime.
        │        │                          An explicit user launch opens a window.
        │        └── ConditionEnvironment=|WAYLAND_DISPLAY |DISPLAY
        │
        └── bunny-first-run.service         oneshot, until the completion marker exists
```

The runtime starts at login; the GTK client does not. Bunny Shell renders the
desktop character, bubble and input, so autostarting the client would create a
second assistant window over the first. When a person explicitly opens that
client, the split remains load-bearing: **closing the window must not stop a
task**. The runtime outlives every window in the session, which is why it is a
unit at all rather than something the GTK application starts for itself.

## What may fail

This is the section §12 exists for. Optional provider failure must not restart
the main companion service, and none of the following is a hard requirement for
the runtime to start:

| Component | If it is missing or broken | The runtime |
| --- | --- | --- |
| Fedora Vosk runtime / bundled recognition model | speech health exposes `STT_RUNTIME_MISSING`, `STT_MODEL_MISSING` or `STT_MODEL_CORRUPT`; push-to-talk is unavailable and typed input remains | starts |
| Ollama / llama.cpp | provider selection finds nothing eligible; typed input still produces a task | starts |
| Audio output | `voice_*` degrades to captions | starts |
| Microphone | push-to-talk reports unavailable | starts |
| 3D graphics | the presentation ladder descends to 2D, static or text | starts |
| A character package | text-only presentation | starts |
| The portal / a file manager | the actions that need them report unavailable per action | starts |

The **one** hard requirement is the capability runtime, and it is expressed as a
condition rather than as a crash:

```ini
ConditionPathExists=/usr/lib/bunny-os/python/capability
```

The companion imports the capability runtime for every routing decision. Without
it there is no capability authority, and a runtime that improvised one would be
deciding where work may run using rules nobody reviewed. The condition names the
missing dependency in the journal instead of producing an `ImportError` at every
restart attempt.

## Restart discipline

Both units are bounded, and the bounds are different because the failures are
different.

`bunny-companion.service` — `Restart=on-failure`, `StartLimitBurst=4` in 60s.
A runtime that respawned for ever would hide a store it cannot read behind a
restart loop. Four attempts and then a failed unit is a state somebody notices.

`bunny-companion-window.service` — `Restart=on-failure`, `StartLimitBurst=4` in
120s, **and** a counter inside the launcher. Three consecutive launches that do
not reach a usable window arm Bunny Safe Mode for the next start, so the fourth
start produces something a person can act on rather than a fourth crash. That is
§34's "reboot must not enter a permanent crash loop", implemented as a file in
the state directory rather than as a hope.

## Sandboxing, and the one place it differs

The runtime unit is heavily confined: `ProtectSystem=strict`, `ProtectHome=read-only`,
`RestrictAddressFamilies=AF_UNIX`, `MemoryDenyWriteExecute=yes`,
`SystemCallFilter=@system-service`.

The window unit is confined too, with one deliberate exception:
**`MemoryDenyWriteExecute` is absent.** Mesa's shader compilers and llvmpipe's
JIT map executable pages, and a window that is killed the moment it draws in 3D
is not a hardened window — it is a broken one. The window holds no durable state,
makes no outbound connection (`RestrictAddressFamilies=AF_UNIX AF_NETLINK`), and
is a client of a runtime that keeps the stricter profile.

## Ordering, and why `Wants` rather than `Requires`

The window `Wants=bunny-companion.service` and `After=` it. Not `Requires=`:

* a window that refused to start because the runtime was not up yet would be a
  window nobody sees on a slow first boot;
* the launcher waits for the socket with a bound, and produces an actionable
  reason if it never appears — which is a better failure than a unit that never
  ran at all;
* `PartOf=graphical-session.target` on both means logging out stops both, which
  is the behaviour a session should have.

## What is *not* in this graph

No system-level Bunny service is part of the companion. `bunny-system-broker.socket`,
`bunny-health-check.service` and the update units are the operating system's, and
the companion neither requires nor talks to them. A companion that needed a
system service to draw a character would be a companion that could not run for a
user who does not have that service.

There is also no `bunny-companion.socket`. Socket activation would mean the
runtime started when something connected to it, and the thing that connects is
the window — which would make closing the last window and reopening it a *new*
runtime with a cold view of a task that was still running.
