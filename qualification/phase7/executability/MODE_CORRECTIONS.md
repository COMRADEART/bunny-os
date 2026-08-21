# Mode corrections made when the executability gate was written

The gate's first rule — a mode-100755 file must open with `#!` — found ten
violations, all evidence *data* files carrying a stray executable bit from the
host that committed them:

```
evidence/reproducibility/hosted-attempt-3/H1-normalisation.json
evidence/reproducibility/hosted-attempt-3/H1-runner-environment.txt
evidence/reproducibility/hosted-attempt-3/H2-normalisation.json
evidence/reproducibility/hosted-attempt-3/H2-runner-environment.txt
evidence/reproducibility/three-builder/H1-normalisation.json
evidence/reproducibility/three-builder/H1-runner-environment.txt
evidence/reproducibility/three-builder/H2-normalisation.json
evidence/reproducibility/three-builder/H2-runner-environment.txt
qualification/reproducibility/commit-O/hermetic-H1-30752170761-builder-record.json
qualification/reproducibility/commit-O/hermetic-H2-30752176035-builder-record.json
```

Their **modes** were set to 100644. Their **content** is untouched: two of
them live under a frozen tree (`qualification/reproducibility/`), and both
evidence-immutability guards — which pin byte content — pass before and after
this change (`git diff` for these ten paths shows a mode line and zero content
hunks). No digest recorded anywhere changes, because no record pins a mode.

This is a correction to repository metadata, not to evidence. It is recorded
here rather than done silently because the paths sit inside trees this phase
declared frozen.

Real scripts were untouched: all twenty remaining 100755 files carry a
well-formed, CR-free shebang naming an allowlisted interpreter, and all 131
tracked `*.sh` blobs are LF in the index — measured by
`tests/release/test_script_executability.py`, whose run is `gate-run.log`
beside this file.
