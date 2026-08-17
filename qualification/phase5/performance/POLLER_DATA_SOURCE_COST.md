# The pollers' data-source cost, measured

**Phase 4's leading hypothesis for the idle-CPU regression is refuted as
stated.** The reads are not where the CPU goes.

## What was hypothesised

Phase 4 measured the shell's idle CPU at **2.07 %** of one core against
**0.80 %** at `7edd3fd` — a 1.27-point regression, steady rather than settling.
It named a mechanism without measuring it:

> A card that redraws a CPU ring every two seconds is a plausible home for most
> of 1.3 points, and it is the first thing to measure next.

Two claims are bundled there: the *read* the card performs, and the *redraw* it
performs. This measures the first.

## Instrument

`qualification/phase5/performance/poller-bench.js`, run under bare `gjs`.

It transcribes the four readers from
`shell/components/gnome-shell-extension/lib/services/telemetry.js` and imports
the **real** mount parser — `lib/services/storage.js` has no imports at all, so
`parseMountinfo` and `selectStorageMount` run unmodified. The `util.js` helpers
could not be imported: they pull in `St` and `Clutter`, which need a
compositor.

2000 iterations per reader, one warm pass discarded first so that the page
cache and the JIT are not attributed to whichever reader happened to run first.

## Result

Fedora 44 under WSL2, Intel Core Ultra 9 185H, 22 cores, kernel
`6.18.33.2-microsoft-standard-WSL2`. `/proc/self/mountinfo` is 39 lines.

| Reader | µs/call | Share | CPU/hour at 2 s |
| --- | ---: | ---: | ---: |
| storage (`/proc/self/mountinfo` + statfs) | **76.6** | **65.6 %** | 0.138 s |
| cpu (`/proc/stat`) | 18.9 | 16.2 % | 0.034 s |
| memory (`/proc/meminfo`) | 16.9 | 14.5 % | 0.030 s |
| temperature (`/sys`, path cached) | 4.4 | 3.8 % | 0.008 s |
| **total per 2 s tick** | **116.9** | | **0.210 s** |

**As a fraction of one core: 0.0058 %.**

A second run of the same benchmark gave 125.0 µs and 0.0063 %. Both are
reported because a single sample is a sample.

## What this settles

The regression is **1.27 percentage points**. The reads for the System overview
card cost **0.006** points. They are smaller by a factor of roughly **200**.

Even multiplying by every 2 s poller in the desktop — the overview card, the
system monitor card and the media widget — and adding the 3 s dock and the 5 s
top bar, the reads cannot plausibly account for more than a few hundredths of a
point. **Whatever moved idle CPU by 1.27 points, it is not the reading.**

Storage dominates *within* that total, at two thirds of it, and that is worth
fixing on its own terms: `/proc/self/mountinfo` is re-read and fully re-parsed
every two seconds to answer a question — which filesystem holds the user's
data, and how full is it — whose answer changes on the timescale of minutes.
But fixing it will not move the number Phase 4 recorded, and this file says so
in advance so that a later improvement is not credited with a change it did not
cause.

## What it does not settle, and why

**This is the read, not the redraw.** `SystemOverview.refresh()` ends with
`this._dial.queue_repaint()`, called on every tick regardless of whether the
value changed. In the qualification guest there is no GPU: `virtio-vga` with
`-display none` means Mutter composites through **llvmpipe**, in software, on
the CPU. A Cairo arc repainted every two seconds and a card relaid out around
it are paid for by the processor there in a way they are not on a machine with
a GPU — and in a way this benchmark, which draws nothing, cannot see.

So the hypothesis is not dead; it has been **narrowed to its second half**, and
the half that survives is the one that has to be measured inside a running
shell. That is what the in-extension instrumentation is for.

**This host is not the qualification guest.** Different kernel, different mount
table, 22 cores against 4. The *ranking* transfers; the absolute microseconds
do not. The guest's `/proc/self/mountinfo` on a bootc/ostree deployment carries
more entries than this host's 39, which makes the storage reader relatively
worse there, not better — still against a total that is two orders of magnitude
too small to matter.

## What follows

1. Instrument the pollers inside the extension: per-timer tick count, wall
   time, CPU time, redraw count, and **how often the data actually changed**.
   The last of those is the one that decides whether change-detection helps.
2. Measure idle CPU in the guest with the instrumentation reporting, so the
   attribution is made where the cost is paid.
3. Only then change cadences. §10's warning — "Do not sacrifice UI correctness
   for a benchmark" — has more force now that the obvious suspect has been
   cleared: a cadence reduced on this evidence would be a change made for no
   measured gain.
