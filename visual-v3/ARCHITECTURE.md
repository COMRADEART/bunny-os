# V3 architecture

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## The shape of it

```
        display manager (GDM)
                |
        +-------+-------------------------------+
        |                    |                  |
      GNOME          Bunny Desktop        Bunny Shell
   (supported)          Preview           Experimental
                        (V2)                  (V3)
                                                |
                             bunny-shell-experimental-session
                                    (start gates, fails closed)
                                                |
                                    bunny-shell-supervisor
                                 (bounded restart, crash records)
                                                |
                                          bunny-shell
                                    (Rust + Smithay compositor)
                                                |
        +---------------------+-----------------+--------------------+
        |                     |                                      |
  layer-shell clients   xdg-shell clients                  ext-session-lock client
  (GTK 4 chrome)        (ordinary applications)            (GTK 4 lock screen)
        |                                                            |
  top bar, dock, launcher,                                  isolated PAM helper
  palette, quick settings,                                  (the compositor never
  notifications, assistant,                                  sees a password)
  approvals, character layer
```

## The decision that shapes everything else

**The compositor draws no shell chrome.** Every visible Bunny surface — the top
bar, the dock, the launcher, the command palette, Quick Settings, the
notification centre, the assistant panel, approval cards, the guide character,
the lock screen — is an ordinary Wayland client that the compositor composites
like any other window.

Three consequences follow, and they are the reason for the choice:

1. **Accessibility has a chance.** A surface drawn inside the compositor has no
   accessible representation at all — there is no AT-SPI for pixels. A GTK 4
   client carries GTK's accessibility implementation. This is the single
   largest risk in replacing GNOME Shell, and drawing chrome in the compositor
   would make it unsolvable rather than merely hard.
2. **The compositor stays small.** It handles protocol, input routing, window
   management policy and composition. It does not handle typography, icon
   themes, layout or state presentation.
3. **A chrome crash is not a session crash.** If the dock dies, the dock dies.
   The compositor keeps running and the supervisor is not involved.

The cost is real and is recorded in `KNOWN_LIMITATIONS.md`: the shell depends on
`wlr-layer-shell-v1`, an unstable protocol, and chrome start-up is a second
process launch rather than an in-process draw.

## Compositor internals

`compositor/bunny-shell/src/`:

| Module | Responsibility |
|---|---|
| `main.rs` | Start gates, backend setup, event loop, diagnostics output |
| `config.rs` | Configuration and the fail-closed start authorisation |
| `compositor.rs` | Protocol state and every Wayland handler |
| `output.rs` | Outputs, fractional scaling, rotation, hotplug |
| `input.rs` | Key binding table and pointer configuration |
| `window.rs` | Window model: geometry, states, modal relationships |
| `workspace.rs` | Workspaces, stated as global across outputs |
| `focus.rs` | Focus policy, including the anti-focus-stealing rules |
| `rendering.rs` | Stacking order and frame composition |
| `session.rs` | Lock state, fail-closed in both directions |
| `security.rs` | Typed actions, approval resolution, capture authorisation |
| `accessibility.rs` | Accessibility settings and an honest capability list |
| `xwayland.rs` | Optional XWayland and its documented consequences |
| `diagnostics.rs` | Diagnostics with observed/inferred/unavailable/unsupported |

The policy modules are pure logic with unit tests, so the properties that
matter — a notification cannot steal focus, a crashed lock client cannot reveal
the desktop, typed text cannot become a process — are tested without a display.

## The privilege boundary

The compositor runs as the user and holds no privilege. Three rules define the
boundary:

**It never runs shell text.** There is no type in `security.rs` that carries a
command line. A launch request is a desktop-entry identifier resolved against a
trusted registry; anything containing a path separator, whitespace or a shell
metacharacter is rejected before the lookup. The absence of the capability is
structural, not a filter that could be bypassed.

**It never decides an approval.** `resolve_approval` has exactly one path to
`Approved`, and it requires `ExplicitApprove`. A dismissed, expired or defaulted
dialog denies. Critical approvals may not pre-select an affirmative button.

**It never sees a password.** The lock screen is a separate client that talks to
an isolated PAM helper. The compositor learns only that authentication
succeeded. `redact()` exists because keystrokes pass through the seat and any
code path that logged them would be a leak.

## Session isolation

The experimental session is additive at every layer:

- `bunny-shell-experimental.desktop` declares `X-Bunny-Default-Session=false`
  and `X-Bunny-Release-Qualified=false`.
- The launcher refuses to start without `BUNNY_SHELL_EXPERIMENTAL=1`, refuses if
  GNOME has stopped being selectable, refuses if it has been made anyone's
  default, and refuses during a qualification run.
- `bunny-shell-experimental.target` is not wanted by `graphical-session.target`,
  so an ordinary login cannot pull it in.
- The units live in `sessions/`, not `systemd/`, because
  `build/scripts/install-root.py` copies `systemd/` into the qualified image
  wholesale. Nothing on this branch is installed by an image build.

## Crash recovery

The supervisor owns the restart policy so that the same bounded behaviour
applies to the packaged session and to a developer's nested run. The budget is
absolute: at most three restarts for the lifetime of a session, and at most one
consecutive restart after a rapid crash. A crash after a long healthy run resets
the *consecutive* counter but never the *total* budget, which is what makes an
endless loop impossible regardless of timing.

Wayland clients do not survive a compositor restart. Their connection is to the
compositor's socket, so when the process exits they exit. This is recorded in
every crash record rather than implied.
