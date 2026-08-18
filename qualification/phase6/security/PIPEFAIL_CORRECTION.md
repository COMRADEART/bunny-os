# A correction to the Phase 5 security evidence

**Phase 5's conclusion was right. Its stated evidence was wrong, and the probe
that produced it could only ever have given one answer.**

Phase 5 recorded, in `qualification/phase5/security/route/binary-symbol-probe.txt`
and repeated in `SCAN_ROUTE_DISCREPANCY.md`:

> neither `/usr/bin/skopeo` nor `/usr/bin/podman` contains those packages, so
> grype excludes them when it can read symbols

`/usr/bin/podman` contains them. It carries **28** `golang.org/x/crypto/ssh*`
package paths, including `knownhosts`, and the named symbol
`hostKeyDB.IsRevoked` that the same document recorded as **absent**.

---

## 1. Why the probe could only answer NO

`symbol-qualifiers.sh` runs under `set -uo pipefail` and asks:

```sh
if strings -a "${target}" | grep -qF 'golang.org/x/crypto/ssh/knownhosts'; then
```

`grep -q` exits at the **first** match. That closes the pipe; `strings` is
killed by `SIGPIPE`; and `pipefail` promotes the pipeline's status to **141**.
A non-zero status sends the `if` to its `else` branch — so a **match** is
reported as **no match**.

Measured, on the same binary, by `pipefail_control.sh`:

```
== the Phase 5 idiom, verbatim (pipefail ON) ==
  knownhosts -> NO
== the same idiom with pipefail OFF ==
  knownhosts -> YES
== the pipeline's exit status on a match, under pipefail ==
  status=141  (0 would be a match; 141 is SIGPIPE reaching pipefail)
== control: a string that is genuinely absent ==
  status=1  (1 is a real no-match)
== counted without a pipeline at all ==
  occurrences: 3
```

Under `pipefail`, that test answers NO whether the string is present or absent.
It has no true-positive branch. `/usr/bin/skopeo` returned NO as well, and
**that answer was correct** — which is exactly why nothing looked wrong.

This is the fifth instance in this project of a check that passed while
measuring something other than what it named, and the first where the defect was
in a shell idiom rather than in a harness's logic.

---

## 2. What is actually true

Two dimensions decide a Go finding, and Phase 5 measured only one of them.

| | `/usr/bin/podman` | `/usr/bin/skopeo` |
| --- | --- | --- |
| `golang.org/x/crypto` version | **v0.53.0** | v0.46.0 |
| Fixed at | v0.52.0 | v0.52.0 |
| Version vulnerable? | **no — already past the fix** | yes |
| `x/crypto/ssh*` packages linked | **28, including `knownhosts`** | **0** |
| Named symbols present | `hostKeyDB.IsRevoked`, `keyring.Add`, `Dial`, `NewClientConn`, … | none |

So the seven `x/crypto` Criticals do not apply to either binary — **for two
entirely different reasons**:

* **podman** carries the vulnerable *code* at a version where it is **already
  fixed**;
* **skopeo** carries a vulnerable *version* of the module with the affected
  *code not linked at all*.

Neither binary is simultaneously on a vulnerable version and carrying the
affected code. Phase 5 asserted one explanation and it happened to be the
skopeo one.

**Phase 5 had no version data at all**, so it could not have reached the podman
answer. `strings | grep` cannot see a build-info version; the tab-separated
`dep\t<path>\t<version>` records are what a scanner matches a version range
against, and nothing in the Phase 5 route read them.

### The one Critical that survives both dimensions

| | version | fixed at | vulnerable version? | named symbols present? |
| --- | --- | --- | --- | --- |
| **GHSA-p77j-4mvh-x3m3** in `/usr/bin/podman` | grpc **v1.72.2** | v1.73.0 | **yes** | **yes** — `Server.Serve`, `Server.ServeHTTP`, `Server.handleStream` |
| GHSA-p77j-4mvh-x3m3 in `/usr/bin/skopeo` | grpc v1.79.3 | v1.73.0 | no | yes |

This is precisely and only what the whole-image binary scan reported:
`candidate-fixed.json` records **one** Critical, `GHSA-p77j-4mvh-x3m3`, located
at `/usr/bin/podman`.

**The scanner was right about all eight, for eight individually correct
reasons.** What was missing was any account of *why*, per advisory, which is
what an independent reviewer needs in order to check it rather than trust it.

---

## 3. Why the SBOM route said eight

`skopeo`'s build info declares `golang.org/x/crypto v0.46.0`. An SBOM carries
the module and its version and nothing about which packages were linked, so
module-granularity matching flags all seven `x/crypto` Criticals against it.

The image's actual `ssh` code lives in `podman`, at v0.53.0, where it is fixed.
The module-granularity result therefore attributes **skopeo's version** to code
that only exists in **podman** — two binaries merged into one finding.

That is not a scanner defect. It is what module granularity means, and it is why
`SCAN_ROUTE_DISCREPANCY.md` was right to insist that the conservative number is
the one a disposition must be argued against. This document does not change that
rule; it supplies the argument the reviewer needs to evaluate it.

---

## 4. What was corrected, and what was not

**Corrected:** the claim that `/usr/bin/podman` does not contain the
`x/crypto/ssh` packages; and the claim that `hostKeyDB.IsRevoked` is absent from
it. Both are false. `evidence/symbols.json` and `evidence/exposure.json` carry
the measurements.

**Not corrected, because it was right:** the conclusion that the seven
`x/crypto` Criticals do not apply at function granularity, the finding that the
July database had no Fedora 44 data, and the instruction to disposition against
the conservative count.

**Not changed:** every disposition remains `PENDING_REVIEW`. Nothing here is a
disposition. §4 forbids `NOT_APPLICABLE` on the grounds that Bunny does not
intentionally invoke a component, and "the version is already fixed" is a claim
for the reviewer to verify, not for the project to self-certify.

**Phase 5's evidence files are not edited.** This is a correction *record*, in
Phase 6's directory, naming what it corrects. §18: historical evidence stays
independently identifiable.

---

## 5. The instruments

| File | What it does |
| --- | --- |
| `symbol_probe.py` | reads each shipped binary's bytes for the database-named symbols in both Go linker spellings, and extracts build-info module versions. **No shell pipeline anywhere.** |
| `exposure_probe.py` | sweeps every ELF ≥ 2 MB under `/usr/bin`, `/usr/sbin`, `/usr/libexec`, `/usr/lib*` for the named modules; records rpm and python presence |
| `pipefail_control.sh` | reproduces the Phase 5 idiom's failure, with a genuine no-match control alongside |

Both probes search for a symbol in **two** spellings — `path.Type.Method` and
`path.(*Type).Method` — because the Go linker writes a pointer-receiver method
the second way. The database's own spelling, `hostKeyDB.IsRevoked`, appears
**zero** times in `/usr/bin/podman` as a literal; the linker form
`golang.org/x/crypto/ssh/knownhosts.(*hostKeyDB).IsRevoked` is present. A probe
that searched only the database spelling would report the symbol absent and be
wrong in the same direction as the `pipefail` defect — which is why both
spellings are searched and the form that matched is recorded per symbol.
