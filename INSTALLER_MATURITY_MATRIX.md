# Installer maturity matrix

§55.13. Every claim this phase could make, and the highest evidence level that
actually supports it.

Commit `28f62a24` and later. §52's ladder:
IMPLEMENTED · UNIT TESTED · HOST RUNTIME VALIDATED · VM RUNTIME VALIDATED ·
PHYSICAL HARDWARE VALIDATED · RELEASE QUALIFIED.

**Five unattended installations have completed and verified on VM disks**
(2026-08-15/16; `qualification/installer-journeys/evidence/`, narrative in
`INSTALLATION_RUNTIME_REPORT.md`), and journey A's disk has booted twice on
its own. Rows below saying VM RUNTIME VALIDATED cite that evidence. The rule
the previous phases established still applies to every other row: a suite
going green while the drawn surface is wrong is the failure mode this project
has already shipped once, so a row saying HOST RUNTIME VALIDATED is a row
that has been looked at on a real display and no further.

---

## §56's definition of done, item by item

| Required | Level | Note |
|---|---|---|
| installation media boots into the Bunny setup experience | VM RUNTIME VALIDATED | five journeys booted the medium to a driven setup surface; BOOT-1..9 checkpoints before that |
| Bunny Companion visibly guides setup | VM RUNTIME VALIDATED | photographed mid-journey ("I need to know where to install…", screenshot manifest); §26 text-only fallback is still code, not a run |
| accessibility can be enabled before installation | VM RUNTIME VALIDATED | journey B enabled Largest text, high contrast and reduced motion on the second screen and completed |
| language/region/keyboard work | IMPLEMENTED | driven through in every journey; `locale.conf`/`vconsole.conf` absent on the installed target — application is an open finding, not a pass |
| storage selection is safe and explicit | VM RUNTIME VALIDATED | real candidates with per-disk refusal annotations photographed; guest and harness verified the target independently |
| destructive confirmation names the disk/action | VM RUNTIME VALIDATED | `ERASE /dev/vda A0EDDF` typed by hand in completing journeys; journey D's wrong phrase left the button disabled and the disk empty |
| encryption flow works | VM RUNTIME VALIDATED | LUKS2 volume created (journeys A, B); opens with the typed passphrase across two real boots |
| account creation works | VM RUNTIME VALIDATED | `alex` on disk with root locked, verified from outside; greeter shows the account on both boots |
| privacy preferences persist | IMPLEMENTED | `choices.json` absent on the target — the §45 handoff has not crossed the reboot |
| appearance preferences persist | IMPLEMENTED | same |
| Bunny presentation mode persists | IMPLEMENTED | same; `first_run/apply.py` has never run on an installed system |
| optional application selection works | HOST RUNTIME VALIDATED | journeys exercised only the Skip path in the VM |
| progress reflects real installer state | VM RUNTIME VALIDATED | the seven-step plan and live Now/Detail rows photographed during a real install; no percentage anywhere |
| installation completes on a disposable VM disk | **VM RUNTIME VALIDATED** | the §44 requirement: five completions, externally verified |
| installed system boots | VM RUNTIME VALIDATED | two boots, one overlay, `graphical.target` both times, journal-verified |
| user logs in | **NOT ESTABLISHED** | the greeter is photographed; no login has been driven |
| first-run experience appears | IMPLEMENTED | blocked behind the login that has not happened |
| personalized desktop reflects setup choices | **NOT ESTABLISHED** | and cannot pass while `choices.json` is missing from the target |
| keyboard-only installation runs | IMPLEMENTED | the driver clicks through AT-SPI actions; that is not a keyboard-only run |
| Orca-driven representative installation runs | **NOT ESTABLISHED** | AT-SPI walked, Orca not run |
| 200 % text remains usable | VM RUNTIME VALIDATED | journey B completed at 200 % on 1024×768; both frames clean (screenshot manifest) |
| high contrast remains usable | HOST RUNTIME VALIDATED | journey B toggled it and completed, but the drawn result was not compared against a high-contrast reference |
| reduced-motion setup remains usable | UNIT TESTED | journey B toggled it and completed; motion itself was never measured |
| offline/minimal installation | VM RUNTIME VALIDATED | journey C re-run with no NIC in the machine; no offline penalty (`INSTALLATION_OFFLINE_REPORT.md`) |
| deliberate failure does not produce success | VM RUNTIME VALIDATED | journey D: refused-as-expected, empty disk confirmed from outside |
| no terminal required for normal installation | VM RUNTIME VALIDATED | five journeys completed through the accessibility tree alone |

## Components

| Component | Level | Evidence |
|---|---|---|
| `setup_view` — 18 screen builders | UNIT TESTED | a screen whose danger warning is not in its announcement cannot be constructed |
| `theme_css` — GTK4 CSS from shared tokens | HOST RUNTIME VALIDATED | no colour or size literal; 32 resolved themes |
| `frontend/setup` — the GTK surface | HOST RUNTIME VALIDATED | `setup-atspi.json`: 13 screens, one heading each, no unnamed control |
| `setup_state` — choices that cross the reboot | UNIT TESTED | round-trips; refuses secrets, unknown modes, unoffered scales |
| `backend/kickstart` | UNIT TESTED | 19 tests incl. duplicate-command and injection refusals |
| `backend/server` — the privileged socket | VM RUNTIME VALIDATED | five journeys crossed it end to end: token, phrase, teardown, failure kinds |
| `backend/anaconda` — the adapter | VM RUNTIME VALIDATED | drove anaconda-core 44 through five real installations |
| `AnacondaDBusExecutor` | **VM RUNTIME VALIDATED** | the full storage/payload choreography ran five times; the road there is the runtime report's defect ledger |
| `backend/progress` — stage mapping | VM RUNTIME VALIDATED | the mapped stages are what the Installing screen photographed |
| story harness — 26 states × 7 themes | HOST RUNTIME VALIDATED | 6 new checks, each with a negative control |
| `setup-drive.py` — in-guest §42 driver | VM RUNTIME VALIDATED | drove all five journeys from inside the medium |
| `vm-install-story.sh` — host harness | VM RUNTIME VALIDATED | five green runs and one honest refusal; kills qemu before any disk read |
| `verify-installed-choices.py` — §45 | VM RUNTIME VALIDATED | six disks read from outside; its own false-reading traps documented in the runtime report |

## Reports

| # | Report | State |
|---|---|---|
| 1 | Installer reuse map | `INSTALLER_REUSE_MAP.md` |
| 2 | Installer architecture | `INSTALLER_ARCHITECTURE_REPORT.md` |
| 3 | Setup design-system integration | `INSTALLER_DESIGN_SYSTEM_REPORT.md` |
| 4 | Storage safety | `INSTALLER_STORAGE_SAFETY_REPORT.md` |
| 5 | Accessibility installer | `INSTALLER_ACCESSIBILITY_REPORT.md` |
| 6 | Screen-reader | folded into #5, with its limits stated |
| 7 | Installation runtime | `INSTALLATION_RUNTIME_REPORT.md` |
| 8 | First-boot persistence | `INSTALLATION_FIRST_BOOT_REPORT.md` |
| 9 | Offline/minimal setup | `INSTALLATION_OFFLINE_REPORT.md` |
| 10 | Failure/recovery | `INSTALLATION_FAILURE_RECOVERY_REPORT.md` |
| 11 | Performance baseline | `INSTALLATION_PERFORMANCE_REPORT.md` |
| 12 | Screenshot evidence manifest | `INSTALLATION_SCREENSHOT_MANIFEST.md` |
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

**PHASE STATUS = INSTALLED AND REBOOTED.** §56's disqualifying sentence —
*"If the installer only renders but has not installed and rebooted into the
resulting OS"* — no longer applies: five installations completed on
disposable VM disks, each verified from outside, and the installed system
booted twice on its own with the chosen passphrase and account.

What still stands between this and a finished §56: **nobody has logged in.**
The login, the first-run experience, the personalization handoff
(`choices.json` is not on the target), locale/hostname application, Orca,
and a keyboard-only run are the open items — named in the table above and in
the runtime report's findings, not hidden under the headline.
