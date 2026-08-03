# V3 security model

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## The one sentence

The compositor renders trusted backend state and returns explicit user input.
It decides nothing, stores no secret, and holds no privilege.

## What the compositor must never do

These twelve prohibitions are held as data in
`compositor/bunny-shell/src/security.rs` so the report and the tests read one
list rather than two.

| # | Prohibition | How it is prevented |
|---|---|---|
| 1 | Run arbitrary shell text | No type in the action model carries a command line |
| 2 | Store authentication secrets | The compositor never receives one |
| 3 | Bypass approvals | Only `ExplicitApprove` reaches `Approved` |
| 4 | Invent backend state | Success states require backend confirmation |
| 5 | Create privileged files directly | The compositor runs as the user with `NoNewPrivileges` |
| 6 | Access user files without a user action | File access goes through the file-chooser portal |
| 7 | Send telemetry | No network client exists in the crate |
| 8 | Enable remote access | No remote protocol is implemented |
| 9 | Expose screen content without consent | Capture requires a portal token and a visible indicator |
| 10 | Alter release evidence | Enforced by a test that diffs the branch |
| 11 | Alter qualification gates | Enforced by the same test |
| 12 | Create production signing keys | No signing code exists on this branch |

## Structural, not filtered

The three properties that matter most are enforced by the shape of the types,
not by a check that could be forgotten.

### Typed text cannot become a process

`ShellAction` has no `RunShellCommand(String)` variant. A launch is
`LaunchDesktopEntry { entry_id }`, and `entry_id` is resolved against a trusted
registry built from desktop entries. Before the lookup, `is_desktop_entry_id`
rejects anything containing a path separator, whitespace, a shell
metacharacter, a newline or a NUL.

Ten hostile inputs are tested against it, including `rm -rf /`,
`sh -c 'curl evil'`, `$(whoami)`, backticks, pipes and a newline-smuggled
`/bin/sh`. The command palette applies the same rule one layer up: a query that
matches no result produces no results. There is no "run this as a command"
fallback for typed text to fall into.

### An approval cannot be granted without an explicit approval

`resolve_approval` has exactly one path to `Approved`, and it requires
`ExplicitApprove`. Dismissed, expired, defaulted and no-input all deny. An
approval card that cannot state its full blast radius — requester, operation,
affected resources, privilege, network impact, data impact, reversibility,
reason, expiration — does not render, and an unrenderable card cannot be
approved even by an explicit approve.

No card has a default action, critical or ordinary. `default_action()` returns
`None` unconditionally, so there is no button an Enter keypress can land on.

### The compositor never sees a password

The lock screen is a separate `ext-session-lock-v1` client. It collects the
secret and passes it to an isolated helper that talks to PAM; the helper returns
a boolean. `AuthenticationHelper` has no method that returns, stores or logs a
secret, and its `__repr__` is written explicitly so a traceback cannot print
what a default repr would have.

With no PAM service configured the answer is `HELPER_UNAVAILABLE`, never
`SUCCESS`. An unimplemented helper cannot be mistaken for a working one.

`redact()` exists because keystrokes pass through the seat: any code path that
logged user input would be a leak, so the safe behaviour is the easy one.

## Fail-closed lock

The lock is fail-closed in both directions:

- **Locking hides the desktop before any lock surface exists.** The policy state
  changes on the lock request, not on the first surface, so there is no window
  in which the desktop is still being composed.
- **A hotplugged output cannot show the desktop.** Adding an output while locked
  marks the lock incomplete and the new output still refuses desktop content.
- **A crashed lock client leaves the session locked.** `LockedClientGone` is
  terminal: claiming successful authentication from that state does not unlock,
  because the client that could prove authentication is gone.

The renderer enforces this too. While locked, `collect_elements` returns *only*
lock surfaces — the desktop is not merely covered, it is not composed at all.

## Screen capture

Two independent conditions, both required:

1. The portal granted the capture for a source the user explicitly selected.
2. The privacy indicator can actually be shown.

If the indicator cannot be displayed the capture is refused. Capture without a
visible indicator is precisely the failure the rule exists to prevent, so a
missing indicator fails closed rather than proceeding quietly.

`unrestricted_compositor_screenshot_permitted()` returns `false` for every
application. The compositor implements no screencopy protocol, and would refuse
even if it did: a screenshot path that bypasses the portal bypasses consent.

Character Mode cannot obscure the capture indicator. The indicator lives in the
top bar and the character can never occupy the top bar, so this holds by
construction rather than by a check.

## Clipboard

Clipboard data is owned by the offering client for as long as that client lives.
The compositor holds a reference to the offer, not the bytes; reading requires a
transfer from the owner, so when the owner exits the offer dies with it. Nothing
is written to disk.

`wlr-data-control` is deliberately **not** enabled. It grants unrestricted
clipboard read to any client that binds it, with no consent step — a
clipboard-stealing capability by design.

Sensitive-clipboard clearing was evaluated and deliberately left off. Silently
emptying a clipboard loses data the user expected to keep, so it needs an
explicit setting rather than a default.

## Privilege separation

The compositor runs as the user. `bunny-shell-session.service` sets
`NoNewPrivileges=yes` and `PrivateTmp=yes`. Everything privileged is delegated:

| Need | Delegated to |
|---|---|
| Authentication | PAM, through an isolated helper |
| File access | `xdg-desktop-portal` file chooser |
| Screen capture | `xdg-desktop-portal` ScreenCast, plus PipeWire |
| Privileged operations | The existing Bunny approval backend |
| Power actions | The session backend |

## Known weaknesses

Stated because a security model that lists only its strengths is marketing.

- **The memory-safety claim covers Bunny's code only.** Mesa, libinput,
  xkbcommon, GTK and Xwayland are C. Rust removes the memory-corruption class
  from the shell policy Bunny writes, not from the stack underneath it.
- **Layer-shell namespaces are self-asserted.** A client can claim
  `bunny-top-bar`. V3 mitigates the consequence — an unrecognised namespace gets
  no exclusive zone and no privileged role — but does not authenticate the
  claim. A `wp_security_context_v1` restriction is a V4 requirement.
- **`ext-foreign-toplevel-list` is off for this reason.** It lets any client
  enumerate every window; it wants a security-context restriction before it is
  turned on.
- **No portal backend was written**, so portal consent behaviour is
  xdg-desktop-portal-gtk's and was not exercised here — there was no session bus
  with a portal running in the measurement environment.
- **The approval backend is not connected.** The approval surface was tested
  against its own state machine, not against the real Bunny backend.
