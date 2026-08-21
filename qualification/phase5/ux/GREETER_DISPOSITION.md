# The greeter is not Bunny's — decision, and why it stays that way for Alpha

**Decision: recorded as an Alpha limitation. Not implemented in Phase 5.**

§12A of the Phase 5 directive asks a question rather than assigning work:

> Determine whether the Alpha product requires Bunny branding at the greeter.
> If yes: implement branding, test login, verify session assembly.
> If no: document it explicitly as an Alpha limitation.
> **Do not change it merely for cosmetic reasons if that risks the
> login/session architecture.**

This is the second branch, taken deliberately, and the reasoning is recorded
here so that it is a decision on the record rather than an omission.

## What a person actually sees

Read off `g10`'s and `g12`'s greeter screenshots in
`qualification/phase4/release-candidate/`: the login screen is stock GNOME with
Fedora's logo and a generic avatar. Everything *after* login is Bunny — the
shell, the dock, the Companion, the wallpaper. The first screen a person meets
says Fedora.

It is not a defect in anything Phase 4 built. It is a thing that was never
built.

## Why not now

**The login gate is passing, and it was expensive.** Login is one of nine gates
currently at PASS. Getting there cost a P0 in Phase 3 — AccountsService session
seeding — and the fix is templates that give every daemon-created account
`Session=bunny`. Phase 4 then had to prove it a second time on a second account
(`g10`, robin) after the first attempt typed one account's password into
another account's field.

Greeter branding is not a wallpaper change. It means touching GDM's own session
— its dconf profile, its `greeter.dconf-defaults`, and on Fedora the
`gnome-shell` GDM mode — which is the same surface AccountsService and session
selection live on. The Phase 3 P0 was in that surface.

**The trade is bad at Alpha.** What is bought: the first screen carries the
product's name. What is risked: a gate that says a person can log in. An alpha
tester who cannot log in has no product; an alpha tester who logs in past a
Fedora logo has the whole product one second later.

**It cannot be done without a rebuild in any case**, and the qualification cost
is not the branding — it is re-running the login journeys (`g1`, `g10`) and the
first-run wizard to show the session still assembles. That is most of a
qualification chain for a logo.

## What "yes" would require, so the estimate is on the record

If a later phase decides the answer is yes:

1. A GDM dconf profile in the image carrying the Bunny logo, background and
   accent — `/etc/dconf/db/gdm.d/`, not the user profile.
2. The `org.gnome.login-screen` keys: `logo`, `banner-message-enable`,
   `banner-message-text`.
3. An icon at a path GDM's own session can read. The greeter runs as `gdm`,
   not as the user, so an asset under `/usr/share/bunny-os/` needs mode `0444`
   and a parent directory the `gdm` user can traverse. This is the step most
   likely to fail silently — a greeter that cannot read its logo draws the
   stock one and logs nothing a person would look for.
4. **Re-qualification of login, not of the greeter**: `g1` (first login and the
   11-choice wizard), `g10` (a second account reaching the Bunny desktop), and
   a boot of an encrypted machine, because the greeter sits behind the LUKS
   prompt and a change to the graphical target's ordering is exactly the class
   of defect the display-stack phase spent five mechanisms on.
5. A negative control: a deliberately unreadable logo asset, to prove the
   check can tell "branded" from "fell back to stock". Without it, a passing
   run and a silently-stock run are the same screenshot to an automated grader
   — and §5's whole subject is graders that cannot fail.

## Status in the tracker

Carried as **ALPHA UX**, not a release blocker, under the Phase 5 §22
classification. It does not appear in the release-gate matrix, because no gate
in that matrix asks about branding; it appears in `KNOWN_LIMITATIONS.md` as a
thing an alpha tester will see and should not be surprised by.
