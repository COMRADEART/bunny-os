# Reconciliation: the prior renderer branch against the integrated companion

The character renderer had a prior implementation at `c2f2acf` on a branch of
the same name, built on `feature/companion-runtime-core` (`2f39d58`) — *before*
the integration phase produced the canonical presentation projection. It is
preserved at `archive/companion-character-renderer-c2f2acf`.

That branch is ~8,300 lines across 62 files and most of it is good. The
reconciliation below is therefore mostly "taken", with one structural change
that touches everything: **the renderer used to build its own projection from
raw task events, and now consumes the canonical one.**

---

## The structural change

| | |
| --- | --- |
| **Prior** | `companion/character/integration.py` held `context_from_events`, which walked `TaskEvent`s and built its own status sentences, approval tracking and notion of "working". `gtk_surface.py` opened `CompanionStore` directly and polled it. |
| **Now** | `integration.py` takes a `PresentationState` and imports nothing that could produce one. `surface.py` is handed the projection by the client. |
| **Why** | §2's architecture and §11's "must never construct task status from raw events independently". The prior design predated the canonical projection and was a *second interpretation of the record* — the thing the integration phase existed to remove. Two interpretations do not stay in agreement, and the one that draws the picture would eventually disagree with the one that decides whether the task finished. |
| **Enforced by** | `test_character_mapper.py::test_the_integration_module_cannot_read_the_record` and `test_character_cli_vertical.py::test_the_surface_never_reads_the_record_directly`, both reading the import graph. |

---

## File by file

| Prior file | Outcome | Notes |
| --- | --- | --- |
| `schema.py` | **Taken whole** | 585 lines covering every §3 field, with strict bounds, credential scanning and a data-only suffix allowlist. Nothing to improve. |
| `image.py` | **Taken whole** | Full PNG container validation with chunk CRCs and a bounded inflate; WebP RIFF bounds; APNG and animated WebP refused. The strongest single piece of the donor. |
| `package.py` | **Taken whole** | Whole-directory validation: links, hard links, device files, executable modes, undeclared files, digests, dimensions, metadata signatures. |
| `importer.py` | **Taken whole** | Archive inspection before extraction, bounded extraction, atomic staged install, trust registry with `built_in` unassertable by the user. |
| `errors.py` | **Taken whole** | Typed failures rooted in `CompanionError`. |
| `lipsync.py` | **Taken whole** | Generic shapes, monotonic timestamps, drift detection, cancellation, neutral on end. |
| `positioning.py` | **Taken whole** | Placement, safe areas, saved positions, no focus theft. |
| `renderer.py` | **Taken whole** | The interface, plus containment re-checked in `asset_path`. |
| `static_renderer.py` | **Taken whole** | The guaranteed fallback. |
| `animated_renderer.py` | **Taken whole** | Frame sequences, one-slot queue, dropped-frame counting, frame-rate cap. |
| `controller.py` | **Taken whole** | Renderer orchestration, restart with restore, lip-sync plumbing. |
| `defaults.py`, `performance.py`, `demo.py` | **Taken, field names updated** | Only the mapper's renamed inputs changed. |
| `bubble.py` | **Taken, one change** | `update()` gained a `persistent` argument. Persistence was derived from the kind alone, so an **error** bubble timed out after six seconds — a message about something going wrong, disappearing. |
| `adaptation.py` | **Rewired** | `from_execution_plan` (which re-parsed the capability execution plan) replaced by `from_recommendation`, consuming the canonical allowance. `audio-only` added, mapping to text for the *character*, since audio draws nothing. |
| `mapper.py` | **Rewired** | `StateMapperInput` now takes `presentation_phase` instead of `runtime_state` plus a dozen flags. `_select_state` no longer re-derives priority; it refines the canonical phase under a rank check. Added `CANONICAL_PHASE_STATES`, `STATE_PRIORITY`, `priority_rank`, `_NARROWINGS`, `_REFINABLE_PHASES`. |
| `integration.py` | **Replaced** | See above. |
| `diagnostics.py` | **Rewired** | `presentation_plan_from_assessment` now calls the canonical `select_presentation` rather than deriving an allowance itself. |
| `gtk_surface.py` | **Replaced by `surface.py`** | The prior file was a standalone GTK application with its own store poller, its own window and its own accessibility reading. The replacement is a GTK-free `CharacterPresenter` embedded in the companion window. |
| `schemas/companion-character-package-v1.schema.json` | **Taken whole** | |
| `assets/companion/characters/default-bunny/**` | **Taken whole** | Twelve original PNGs, a manifest and a licence. |
| `scripts/generate-default-character-assets.py` | **Taken whole** | The generator that produced the art, kept so it can be regenerated. |
| `shell/services/bin/bunny-companion-character` | **Dropped** | See below. |
| `shell/components/applications/art.comrade.BunnyCompanionCharacter.desktop` | **Dropped** | See below. |
| `shell/services/bunny_shell/ui.py` change | **Dropped** | It added a launcher button for the second application. |
| `build/scripts/install-root.py` change | **Taken and extended** | `copy_python_package` is better than the integration branch's `copy_tree` — source only, 0444, excludes fixtures — and replaced it. |
| `build/Containerfile` change | **Taken** | And it fixed a live defect; see below. |
| `capability/registry.py` comment | **Taken, reworded** | The installed manifest path is now real. |

## Two decisions worth stating

### One client, not two

The prior branch shipped `bunny-companion-character` as a **separate GTK
application** with its own desktop entry, its own window and its own polling
loop over the store. That was reasonable before the integration phase, which
did not yet have a client.

It is not reasonable now. The integration phase's completion standard includes
"the GTK shell is a restartable client" — singular — and two applications
polling one runtime is two places a user can be shown a different answer, two
processes to keep in step, and two things to restart. The character therefore
renders **inside** the companion window, driven by the same
`CompanionViewModel` that already holds the projection.

What was lost: a character that can float independently of the task panel. What
was kept: the placement policy, the scale controls and the compact view, which
the companion window already had.

### The `.svg` refusal stands, even though the shell ships one

`safe_package_path` refuses `.svg` in a character package while
`shell/assets/companion/default-bunny.svg` — the integration phase's static
asset — is an SVG. That is not an inconsistency:

* the shell asset is repository-owned, reviewed, and scanned for active content
  by `companion/characters.py` before it is drawn;
* a character *package* is untrusted third-party content, and SVG is a
  scriptable format whose safety depends entirely on the renderer's
  configuration.

A package may ship PNG and WebP, which cannot execute.

## A defect this branch found in the integration phase

`build/scripts/install-root.py` on `feature/companion-runtime-integration`
copies `capability/` and `companion/` into the image — but `build/Containerfile`
never copied those directories into the build context. `Path.rglob` over a
missing directory yields nothing and `mkdir(exist_ok=True)` succeeds, so the
build would have **silently installed two empty package directories**. Worse
than failing: `bunny-companion.service`'s `ConditionPathExists=/usr/lib/bunny-os/python/capability`
would have been satisfied by the empty directory, the service would have
started, and it would have failed on import at every restart.

Fixed here by adding the three `COPY` lines, and covered by
`test_character_cli_vertical.py::test_installed_image_copies_runtime_renderer_and_data_assets`,
which asserts the install script and the Containerfile agree.
