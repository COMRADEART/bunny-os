# SPDX-License-Identifier: Apache-2.0
"""Optional end-to-end encrypted sync — device-side client.

Scope and non-scope, stated up front because this is the subsystem most likely to
be misread:

* This package defines and validates the *envelope format*, the *key hierarchy
  structure*, the *pairing protocol*, and the *conflict rules*.
* It does **not** implement authenticated encryption, key derivation, or key
  agreement in Python. Bunny OS does not invent cryptographic primitives and does
  not hand-roll AEAD. The repository's established practice is to call a reviewed
  implementation out of process (see ``build/scripts/sign-stable-rc.py``, which
  shells out to ``openssl pkeyutl`` rather than importing a crypto library).
* The cryptographic executor is therefore absent in a source-only checkout and
  reports itself unavailable rather than pretending to encrypt. See
  ``docs/SYNC_CRYPTOGRAPHY.md`` and ``docs/adr/ADR-020-end-to-end-encrypted-sync.md``.

Sync is optional. Bunny OS is fully usable with no account, and no core function
degrades when sync is disabled or the service is unreachable.
"""
