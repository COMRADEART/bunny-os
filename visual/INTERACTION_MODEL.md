# Bunny interaction model

## Principles

1. Keyboard and pointer paths are peers.
2. The focused control is always visible and its name predicts the result.
3. Search results declare whether they open, change, run, require approval, or
   require elevated privilege before activation.
4. Proposed, executing, completed, failed, and rolled-back states are distinct.
5. Conventional desktop functions continue when Bunny services are disabled or
   unavailable.

## Spatial model

The top bar answers **where am I and what is active?** The adaptive dock answers
**what can I enter or return to?** The overview answers **what is open across my
work?** The Command Palette answers **what can I do next?** The right-side Bunny
panel answers **what is Bunny doing, why, and with what authority?**

## Command Palette

`Super+Space` opens a modal, keyboard-first palette. Results are grouped in this
order: windows, applications, workspaces, settings, recent items, Bunny actions,
diagnostics, and power. Arrow keys move, Enter activates, and Escape closes.
Search remains useful with Bunny disabled.

An action result carries an explicit verb badge. Privileged and approval-bound
results open the Approval Center with details; they never execute from search.
Power actions open the platform confirmation path.

## Panels

Quick Settings originates from the top-right status area. The Assistant and
Approval surfaces enter from the right and retain the triggering control as the
focus return point. Escape dismisses a transient panel unless an authentication
or critical approval flow owns focus.

## Approval resistance

Approval cards begin with no affirmative selection. Sensitive and privileged
cards require an explicit choice after details are available. Critical cards
visually separate `Deny` and `Approve`, focus a neutral inspection control, and
state irreversible scope in text. Expired requests cannot be approved.

## Layout modes

- **Normal** preserves standard Bunny chrome and notifications.
- **CompactLayout** selects explicit compact variants without hiding features.
- **FocusMode** hides the dock until summoned and suppresses only non-critical
  Bunny activity. Security, approval, critical system, battery-critical, and
  accessibility entry points remain present. A labeled exit stays in the top
  bar.
