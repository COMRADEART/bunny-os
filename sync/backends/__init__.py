"""Cryptographic backends for optional encrypted sync.

A backend is a thin adapter over a reviewed implementation. Bunny OS defines no
primitive of its own; a backend selects parameters and calls someone else's
audited code.

``reference`` uses the ``cryptography`` package, which wraps OpenSSL. It is
soft-imported: absent, the whole subsystem reports unavailable and refuses every
operation rather than degrading. See ``sync/crypto.py``.
"""
