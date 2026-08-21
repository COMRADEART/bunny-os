# Installer accessibility and screen-reader report

§55.5 and §55.6. What an assistive technology finds in the Bunny setup surface,
measured on a real accessibility bus rather than inferred from the code.

Commit `cab7730b`. Evidence:
`qualification/installer/setup-atspi.json` (per-screen AT-SPI walk),
`qualification/installer/setup-probe.json` (structure and scaling),
`qualification/design/story-manifest.json` (13 states × 7 configurations).

**Evidence level: HOST RUNTIME VALIDATED.** Every measurement below comes from
the real application running under GTK 4.22 on Fedora 44, walked over the real
AT-SPI bus. None of it comes from a booted installer ISO, and §55.6's "drive the
real installer with Orca" is therefore **not** discharged by this document — see
§7.

---

## 1. Accessibility comes second, and applies immediately

§8 requires accessibility to be available before the rest of setup. It is the
second screen in the flow — after the greeting, before language:

```
welcome → accessibility → language_region → keyboard → network → storage → …
```

That ordering is deliberate and the reason is circular otherwise: the person who
most needs 200 % text is the person least able to read the language list in order
to get to the setting that would enlarge it.

Six settings, all applied to the installer as they are set: text size, high
contrast, reduce motion, screen reader, captions, text-only Bunny.

"Applied immediately" is measured, not asserted. `SetupApplication.apply_theme`
re-renders the stylesheet from a resolved design-system theme on every
accessibility change, and the probe checks that the four offered sizes produce
four *different* stylesheets and four different body sizes:

| Text scale | Body size | Card metric |
|---|---|---|
| 100 % | 12 px | 304 px |
| 125 % | 15 px | — |
| 150 % | 18 px | — |
| 200 % | 24 px | 608 px |

A setting that were recorded and ignored would look identical from inside the
code that set it. `test_a_text_size_change_is_recorded_and_resolvable` and the
probe's `textScaleBodySizes` are what distinguish the two.

A text scale the design system cannot resolve raises rather than falling back:
a person who chose 200 % and silently got 100 % has been lied to by the surface
that offered it.

## 2. What Orca actually finds

All thirteen flow screens, walked over the accessibility bus:

| Screen | Focusable controls | Headings | Readable text nodes |
|---|---|---|---|
| welcome | 5 | `['Welcome']` | 7 |
| accessibility | 13 | `['Accessibility']` | 22 |
| language_region | 18 | `['Language and region']` | 26 |
| keyboard | 9 | `['Keyboard']` | 14 |
| network | 7 | `['Network']` | 14 |
| storage | 5 | `['Where to install']` | 10 |
| encryption | 7 | `['Encryption']` | 14 |
| account | 9 | `['Your account']` | 14 |
| privacy | 12 | `['Privacy']` | 22 |
| appearance | 14 | `['Appearance']` | 19 |
| companion_behaviour | 12 | `['Bunny']` | 22 |
| applications | 13 | `['Apps']` | 29 |
| review | 4 | `['Review']` | 37 |

**Exactly one heading per screen**, every focusable control named, and every
non-control string readable. No findings.

## 3. The defect this measurement found

**GTK 4.22 maps a plain `Gtk.Label` to the AT-SPI role `heading`.**

The first walk of the accessibility screen returned **twenty headings**. Among
them: the help text under every switch, the word "Normal" beside a radio button,
and the internal label GTK puts inside the Back button. To Orca's heading
navigation that screen had twenty destinations, one of which was a heading.

Verified as toolkit behaviour rather than an application mistake by building a
stock three-widget GTK4 application: a plain label there is a `heading` too.

The fix distinguishes two cases, and they are not interchangeable:

* **`PRESENTATION`** — the node stays but its name is stripped. Correct where a
  control's accessible name already carries the text. A field label whose switch
  is named *"High contrast. Stronger borders and a plain background behind every
  control."* is announced twice otherwise, once as a heading and once as a
  switch.
* **`PARAGRAPH`** — reports as `comment` and keeps its text. Correct for text
  that stands alone: Bunny's sentence, an `info` row, a progress line, a line of
  technical detail. Removing those would take content away from the one user who
  cannot see it.

A second defect surfaced during the fix: **`set_accessible_role()` after
construction is silently ignored for a `GtkLabel`.** The screen heading arrived
as a paragraph with the call sitting two lines above it. It is a construct
property now, and the probe asserts exactly one heading per screen so this cannot
return quietly.

## 4. Two false failures, recorded because they looked like defects

Both were mine, in the probe rather than the product, and both are the reason
this report leads with *how* it was measured:

1. Reading a name from `get_label()`/`get_text()` reported **every switch and
   entry as nameless**. A `Gtk.Switch` has neither method; the names were set
   correctly the whole time. GTK4 offers no way to read an accessible name back
   from a widget — only AT-SPI can answer the question.
2. Reading only `get_name()` showed a screen of **empty paragraphs**. A label's
   text is not its accessible name; it is behind the AT-SPI **Text interface**,
   which is what Orca uses for paragraphs.

A harness that reports a defect that is not there costs the same as one that
misses a defect that is.

## 5. One finding not fixed, and why

GTK4's `ScrolledWindow` publishes a **focusable `scroll pane` with no accessible
name**. Reproduced on a stock GTK4 application containing a single button.
Setting `GTK_ACCESSIBLE_PROPERTY_LABEL` on the ScrolledWindow and on its
viewport, before and after `set_child`, does not change it.

It is exempted **by name with its reason** and recorded under
`platformLimitations` in the evidence rather than filtered silently, because the
honest statement is "every control this surface creates has a name, and the
toolkit adds one that does not" — not "no findings".

The viewport is left focusable deliberately: at 200 % text, arrow-key scrolling
is how a keyboard user reaches a control that has moved below the fold.

## 6. Destructive consequences, and how they reach a screen reader

§38 requires Orca to clearly announce destructive consequences. This is
structural rather than remembered: `setup_view.Screen.__post_init__` **refuses to
construct** a screen whose `danger`-level warning text is not contained in its
`announcement`. A screen a screen-reader user could not be warned by cannot
exist.

The confirmation screen's announcement, verbatim:

> Confirm. Everything on QEMU HARDDISK — 80.0 GiB — /dev/vda will be erased. This
> cannot be undone. The new installation will be encrypted. To continue you must
> type the phrase ERASE /dev/vda 7D5628 exactly.

The warning box itself carries the text as the accessible name of a node with
role `alert`, so a change of target disk is announced rather than waiting for the
next focus move. Severity is in the words, never in the colour alone.

The destructive button's accessible name is *"Erase QEMU HARDDISK — 80.0 GiB —
/dev/vda and install Bunny OS"* while its visible label is "Erase and install".
An earlier version of the story harness failed that name for exceeding the screen
width — an accessible name is spoken, not drawn, and a check that failed it would
have pushed the name back toward "Confirm". The harness now checks names for
substance instead, and fails a destructive action announced as nothing more than
its own label.

## 7. What this does not establish

* **Orca has not been run.** This is an AT-SPI walk, which reads the same tree
  Orca reads, on the same bus. It is not Orca, and it says nothing about what
  Orca *says* — speech ordering, verbosity, or whether a live-region update is
  spoken at a useful moment.
* **Nothing was measured on the installer ISO.** §55.6 asks for the real
  installer driven by a screen reader; that requires the booted medium.
* **Keyboard-only completion (§37) is not established.** Focus lands on the first
  control of each screen and every action is a real focusable button, but no run
  has completed the flow using only the keyboard.
* **200 % and high contrast are structural claims here.** The story harness draws
  13 states in 7 configurations and finds no clipping against a declared
  1024×768 minimum, and the GTK stylesheet gives no control a fixed height — but
  §39 and §40 ask for the installer *run* at those settings, which is journey B.

Journey B exists in the harness (`BUNNY_JOURNEY=b` sets 200 % text, high
contrast and reduced motion through the in-guest driver) and has not been run.
