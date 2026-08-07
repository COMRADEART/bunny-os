# Bunny Companion Desktop Action Broker

The first phase in which the companion causes something to happen on a person's
desk. Everything before it produced information — text, speech, a transcript, a
drawn character, a provider's proposal. This produces **effects**, and an effect
on somebody's desktop cannot be taken back by deleting a record.

This report states what was built, what was measured, and what was not. Where
something was not run it is listed as NOT_RUN with the reason, not omitted.

---

## 1. Starting and final SHAs

| | |
|---|---|
| Base branch | `feature/companion-agent-providers` |
| Starting commit | `ef0c9572262acd8bd48b74ff7234573ac0b78d55` (verified head of the base branch) |
| Working branch | `feature/companion-desktop-actions` |
| Gate commit | *(filled at the gate run)* |
| Evidence commit | *(filled by the evidence commit)* |
| Final SHA | *(filled at closure)* |

Preflight, before the branch was created:

1. the full SHA of `ef0c957` was resolved and matched the branch head;
2. the working tree was clean;
3. the agent-provider post-gate range `3f07a6e..ef0c957` was analysed and
   reports **0 installed, 1 context-only, 12 unreachable** — the collector
   script and the report with its eleven evidence files;
4. the corrected build-input-closure analyzer was run, and its installer audit
   reports that `install-root.py` installs only what
   `build/scripts/install_routes.py` models;
5. no prior evidence tree was touched. `qualification/companion-linux/`,
   `companion-voice/`, `companion-voice-closure/`, `companion-speech-input/` and
   `companion-agent-providers/` are untouched by every commit on this branch;
6. no completed source branch was modified.

---

## 2. Branch lineage

```
feature/companion-runtime-core
  → feature/companion-runtime-integration
  → feature/companion-character-renderer
  → feature/companion-linux-validation
  → fix/companion-pause-approval-consistency
  → feature/companion-voice-runtime
  → fix/companion-voice-closure
  → feature/companion-speech-input
  → feature/companion-agent-providers        ef0c957
  → feature/companion-desktop-actions        (this phase)
```

---

## 3. Build impact

**This branch is build-affecting**, and says so before anything else because the
previous phase's report records what happens when that question is answered by
inspection: the closure analyser is run, and its answer is quoted.

`companion/` is installed wholesale by the `companion-package` route
(`copy_python_package`, `*.py` only, excluding `tests`/`testing`/`__pycache__`),
so every module added here lands at
`/usr/lib/bunny-os/python/companion/desktop/`.

*(Filled with the analyser's output at closure.)*

---

*(Sections 4–30 follow.)*
