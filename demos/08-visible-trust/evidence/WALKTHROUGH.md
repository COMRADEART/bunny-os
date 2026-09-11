# Visible Trust demo walkthrough

This is a **host-runnable** demonstration. It is not a booted Fedora
guest, not hardware evidence, and not a stable-release GO.

- Host guest boot: `NOT_RUN` — this capture host had `/dev/kvm` and no QEMU
- Stable release: `NO-GO`
- Pilots: `BLOCKED`

## What to show a reviewer

1. `screenshots/waiting_for_approval.png` — the production TrustPrompt drawn,
   Deny focused (`Don't allow`), Allow present, no "Always allow everything".
   Headline: *Bunny Image Tool wants to open /home/bunny/Pictures/holiday.png.*
2. `screenshots/granted.png` / `denied.png` — the two answers after pressing
   the accessible names `Allow this Bunny action` / `Deny this Bunny action`
   through `TrustGate` (deny-by-default; a forbidden name is also a denial).
3. `frames/waiting_for_approval.html` — open locally to inspect ARIA labels.
4. This log: capability inspect/plan, companion granted/denied, deadline tests.

Reproduce on any development host:

```text
python3 demos/08-visible-trust/run.py
# or
make demo-visible-trust
```

## Capture result (20260911T013940Z)

- capability inspect/plan: PASS
- companion granted slice: PASS
- companion denied slice: PASS
- ApprovalIsNotASlowAnswerTests: 5 run, PASS
- visible Trust journey: PASS
- screenshots: 6/6 (idle, thinking, waiting_for_approval, granted, denied, failed)

Request typed: `Resize this to 100 pixels wide.`

Gate drive (same accessible names the guest harness presses):

- Allow → `allowed=true` (`user-allowed`)
- Deny → `allowed=false` (`user-denied`)
- `Always allow everything` → `allowed=false` (`user-denied`)

State transitions:

- `idle` → `thinking` — typed the resize request
- `thinking` → `waiting_for_approval` — runtime reached a permission question; deadline suspended
- `waiting_for_approval` → `granted` — pressed `Allow this Bunny action`
- `waiting_for_approval` → `denied` — pressed `Deny this Bunny action`

## Still needs Fedora + KVM hardware

- `make build-shell-image` / `vm-desktop-story.sh`
- AT-SPI press inside a GNOME session (`desktop-drive.py --journey {granted,denied,failing}`)
- `BUNNY_SESSION_READY` observed on a booted guest
- Physical Secure Boot / TPM / Orca qualification

None of those are claimed by this capture.
