# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Qualification evidence, and the instruments that grade it.

This directory is almost entirely *data*: recorded runs, journals, screenshots
and the records that bind them to an artifact. It is a Python package for one
reason — ``qualification.grader`` — and that package is here rather than under
``tools/`` or ``scripts/`` deliberately.

``qualification/`` is not a ``COPY`` root in ``build/Containerfile``. Nothing
in it reaches the image. A grader that lived in ``scripts/`` would be shipped
to every installed system and would make every change to the instrument a
change to the product, requiring a rebuild and a new artifact identity to fix
a typo in a check. Keeping it here means the instrument can be corrected
without disturbing the thing it measures — which is the separation Phase 4's
six harness defects were an argument for.
"""
