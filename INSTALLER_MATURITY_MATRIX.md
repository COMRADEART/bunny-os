# Installer maturity matrix

§55.13. Every claim this phase could make, and the highest evidence level that
actually supports it.

Commit `28f62a24` and later. §52's ladder:
IMPLEMENTED · UNIT TESTED · HOST RUNTIME VALIDATED · VM RUNTIME VALIDATED ·
PHYSICAL HARDWARE VALIDATED · RELEASE QUALIFIED.

**Nothing in this phase has reached VM RUNTIME VALIDATED.** No installation has
run. The rule the previous phases established applies here in full: a suite going
green while the drawn surface is wrong is the failure mode this project has
already shipped once, so a row saying HOST RUNTIME VALIDATED is a row that has
been looked at on a real display and no further.

---

## §56's definition of done, item by item

| Required | Level | Note |
|---|---|---|
| installation media boots into the Bunny setup experience | IMPLEMENTED | ISO building; the autostart entry now launches `bunny-setup` rather than the four dead buttons |
| Bunny Companion visibly guides setup | HOST RUNTIME VALIDATED | drawn on a real display; §26 fallback to text-only is code, not a run |
| accessibility can be enabled before installation | HOST RUNTIME VALIDATED | second screen; four text scales produce four different stylesheets |
| language/region/keyboard work | IMPLEMENTED | collected and rendered into the kickstart; never applied to a real system |
| storage selection is safe and explicit | HOST RUNTIME VALIDATED | eight of nine gates exercised — see the storage report |
| destructive confirmation names the disk/action | HOST RUNTIME VALIDATED | wrong phrase refused over a real socket |
| encryption flow works | UNIT TESTED | LUKS2 directives rendered; no volume has been created |
| account creation works | UNIT TESTED | yescrypt hash rendered `--iscrypted`; no account created |
| privacy preferences persist | IMPLEMENTED | `Choices` round-trips and refuses secrets; nothing has crossed a reboot |
| appearance preferences persist | IMPLEMENTED | same |
| Bunny presentation mode persists | IMPLEMENTED | five modes including Off on both sides now; applied by `first_run/apply.py`, never yet across a real reboot |
| optional application selection works | HOST RUNTIME VALIDATED | real catalogue; Photoshop and Microsoft 365 correctly unavailable with honest reasons |
| progress reflects real installer state | UNIT TESTED | engine→Companion map is total; no percentage anywhere |
| installation completes on a disposable VM disk | **NOT ESTABLISHED** | the §44 requirement |
| installed system boots | **NOT ESTABLISHED** | |
| user logs in | **NOT ESTABLISHED** | |
| first-run experience appears | IMPLEMENTED | `first_run/alpha.py` via `cli.py`; the setup choices are now applied before it draws |
| personalized desktop reflects setup choices | **NOT ESTABLISHED** | |
| keyboard-only installation runs | IMPLEMENTED | focus lands on the first control per screen; no run has completed by keyboard alone |
| Orca-driven representative installation runs | **NOT ESTABLISHED** | AT-SPI walked, Orca not run |
| 200 % text remains usable | HOST RUNTIME VALIDATED | 13 states × 7 configurations, no clipping against a declared 1024×768 |
| high contrast remains usable | HOST RUNTIME VALIDATED | same |
| reduced-motion setup remains usable | UNIT TESTED | every transition renders `0ms`; asserted, not watched |
| offline/minimal installation | IMPLEMENTED | journey C exists in the harness, unrun |
| deliberate failure does not produce success | UNIT TESTED | journey D exists in the harness, unrun |
| no terminal required for normal installation | HOST RUNTIME VALIDATED | every step is a control in the accessibility tree |

## Components

| Component | Level | Evidence |
|---|---|---|
| `setup_view` — 18 screen builders | UNIT TESTED | a screen whose danger warning is not in its announcement cannot be constructed |
| `theme_css` — GTK4 CSS from shared tokens | HOST RUNTIME VALIDATED | no colour or size literal; 32 resolved themes |
| `frontend/setup` — the GTK surface | HOST RUNTIME VALIDATED | `setup-atspi.json`: 13 screens, one heading each, no unnamed control |
| `setup_state` — choices that cross the reboot | UNIT TESTED | round-trips; refuses secrets, unknown modes, unoffered scales |
| `backend/kickstart` | UNIT TESTED | 19 tests incl. duplicate-command and injection refusals |
| `backend/server` — the privileged socket | HOST RUNTIME VALIDATED | `backend-probe.json`: 0600, peer-UID, token, replay, phrase |
| `backend/anaconda` — the adapter | IMPLEMENTED | contract verified against anaconda-core 44.30-2.fc44 by reading the package |
| `AnacondaDBusExecutor` | **IMPLEMENTED, NEVER RUN** | introspects and refuses; the highest-risk item in the phase |
| `backend/progress` — stage mapping | UNIT TESTED | total; progress cannot move backwards |
| story harness — 26 states × 7 themes | HOST RUNTIME VALIDATED | 6 new checks, each with a negative control |
| `setup-drive.py` — in-guest §42 driver | IMPLEMENTED | ships in the live image; never executed |
| `vm-install-story.sh` — host harness | IMPLEMENTED | never executed |
| `verify-installed-choices.py` — §45 | IMPLEMENTED | never executed |

## Reports

| # | Report | State |
|---|---|---|
| 1 | Installer reuse map | `INSTALLER_REUSE_MAP.md` |
| 2 | Installer architecture | `INSTALLER_ARCHITECTURE_REPORT.md` |
| 3 | Setup design-system integration | **not written** |
| 4 | Storage safety | `INSTALLER_STORAGE_SAFETY_REPORT.md` |
| 5 | Accessibility installer | `INSTALLER_ACCESSIBILITY_REPORT.md` |
| 6 | Screen-reader | folded into #5, with its limits stated |
| 7 | Installation runtime | **blocked on the run** |
| 8 | First-boot persistence | **blocked on the run** |
| 9 | Offline/minimal setup | **blocked on the run** |
| 10 | Failure/recovery | **blocked on the run** |
| 11 | Performance baseline | **blocked on the run** |
| 12 | Screenshot evidence manifest | **blocked on the run** |
| 13 | Final maturity matrix | this file |

## Known gaps that are not blocked on the VM

1. ~~`installer/first_run/app.py` collects nothing.~~ **Corrected.** That was
   true of the file and misleading about the product: nothing imported `app.py`
   — it was dead code superseded by `first_run/alpha.py`, which is what
   `cli.py` runs and which does collect. Reporting it as the first-run
   experience would have been a defect claimed against a module the system never
   loads. `app.py` is now deleted rather than left as a second wizard, because
   two of them is exactly the drift `companion_flow.py` opens by warning about.

   The **real** gap it was hiding: nothing applied the installation choices to
   the installed system at all. `first_run/apply.py` now does, wired into
   `cli.py` *before* the wizard draws — so the greeting itself appears at the
   chosen text size, and a person who dismisses onboarding in the first second
   still gets the theme, scale and Companion mode they chose. Eleven settings,
   each recording its own outcome; a `gsettings` schema this build lacks is
   reported, not raised.
2. ~~`companionModes.js` has four modes.~~ **Fixed.** `off` is a mode now on
   both sides. It had to be: `normaliseMode` resolved an unknown mode to
   `full`, so a person who chose Off during installation would have got the one
   thing they asked not to see — and only on the installed system, where nobody
   was looking. All five modes still produce exactly one announcement.
3. **GTK4's `ScrolledWindow` publishes a nameless focusable node.** Reproduced on
   a stock GTK4 application; not fixable from here. Exempted by name with its
   reason rather than filtered.
4. **`InstallationState.percent` still exists** and is exposed as
   `overallProgress`. Nothing in the surface reads it, and a test asserts no
   progress row carries a percentage, but the field remains available to tempt a
   future caller.

## The one number that matters

**PHASE STATUS = INCOMPLETE**, by §56's own terms: *"If the installer only
renders but has not installed and rebooted into the resulting OS."* It renders,
it refuses correctly, and it has not installed.
