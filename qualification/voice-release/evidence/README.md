<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stage 2 voice release evidence

Two trees, each with a `manifest.sha256` computed **on the builder, before
the copy to this checkout** — verify the copy against it, not the other way
around. `qualification/**` is `-text`, so git does not rewrite these bytes.

## `discovery/` — the 72ff8063 artifact (92 files)

The first `shell-test` image ever built from an exact commit for voice
(qcow2 `7d840788…`, provenance included). This is the run that found the
defects: the refused `voice_cancel`, the 60-second silent degradation, the
probe unit's start-timeout, and the fictional interruption instruments.
Its logs therefore show FAILING behaviour on purpose — `repro-a-next.log`,
`notts.log` (the 70-second variants), `stall-watch` output inside
`s2-logs`, and the truth-check that first failed because of its own grace
window. `harness/` holds the scripts exactly as run.

## `final/` — the 24168fbc artifact (66 files)

The rebuilt artifact (qcow2 `e302c16d…`, provenance included) and the full
acceptance labelled `s2b`: EE-1 with screenshots, four truth-check PASSes,
the genuine 130 ms interruption, the 21 s post-cancel recovery, the 11 s
honest no-provider settle, offline end-to-end, the device-loss trio, the
installed renderer slice report (`runs/slice-vr.json`, 16/18 + 2 NOT_RUN),
CPU/RSS samples, the latency table, and the three full-suite logs
(baseline 72ff8063, current 24168fbc, final 375fa830).

The matrix rows in `../matrix.json` cite files here by relative path.
