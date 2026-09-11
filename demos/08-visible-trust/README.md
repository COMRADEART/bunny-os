# Visible Trust demo (host-runnable)

This is the strongest honest demonstration of the user-facing Trust /
approval path that a development host can run **without** a Fedora 44
image-builder, nested KVM guest, or GNOME session.

It is **not** a stable release, **not** a pilot GO, and **not** boot
evidence. `gate-stable-release` remains `NO-GO`. Physical hardware,
independent reviews, and production keys are unchanged.

## One command

From the repository root:

```text
python3 demos/08-visible-trust/run.py
```

or, with `make`:

```text
make demo-visible-trust
```

The run writes a timestamped directory under `demos/08-visible-trust/out/`
and points `out/latest` at it. Open:

- `out/latest/WALKTHROUGH.md` — what to show a reviewer
- `out/latest/report.json` — machine-readable result
- `out/latest/frames/waiting_for_approval.html` — the Trust prompt
- `out/latest/screenshots/*.png` — state-bound frames (Chrome, when present)

Checked-in copies of a successful cloud-host run live under `evidence/`.

## What the command actually does

| Step | Surface | Needs |
|---|---|---|
| Host probe | KVM / QEMU / Podman / GTK / Chrome | nothing |
| Capability inspect + plan | `bunny-os capability --simulate laptop` | Python |
| Companion granted + denied | `companion.demo.run_demo` | Python |
| Approval ≠ timeout | `ApprovalIsNotASlowAnswerTests` | Python |
| Visible Trust prompt | production `TrustPrompt` → HTML | Python |
| Drive Allow / Deny | accessible names `Allow this Bunny action` / `Deny this Bunny action` through `TrustGate` | Python |
| Screenshots | Chrome headless | optional |

AT-SPI inside GNOME is **NOT_RUN** on a host without the guest desktop.
The accessible names are the same strings the guest harness presses; the
press here is the production gate, not a protocol-side `resolve_approval`
that skips the question.

## What still needs Fedora + KVM

The guest photograph is a different demo. On a Fedora 44 image-builder host:

```text
make build-shell-test-image
python3 demos/09-guest-trust/run.py
```

See `demos/09-guest-trust/README.md`. Those steps wait on `BUNNY_SESSION_READY`,
type the resize request, and press the buttons at their AT-SPI extents. A host
with `/dev/kvm` and QEMU but no `image-builder` records `NOT_RUN` rather than
faking a guest.

## Security boundaries

- Deny-by-default: an unknown accessible name, including
  `Always allow everything`, is a denial.
- No `alwaysAllowEverything` control is drawn.
- Deny is focused; Return / Escape deny.
- The surface cannot grant. `TrustGate` checks the ticket.
- The work deadline still ends a hung *post-approval* worker. Time spent
  planning toward a question, and time spent waiting for a person, do not
  become "the runtime did not finish".
