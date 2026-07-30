# OEM tests

Test code lives in `tests/oem` and `tests/factory`, following the repository convention that all Python tests are discovered from the `tests/` tree by `python scripts/task.py test`.

```text
tests/oem/test_oem_profile.py       profile, overlay, and qualification rejection tests
tests/factory/test_factory_finalize.py   factory-state cleanup and handoff refusal tests
```

Run them with:

```text
make test-oem
make test-factory
```

Both are included in `make gate-phase-7-source`.
