# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for Bunny Model Studio.

Everything here runs without torch, without a GPU and without the network. The
one test that needs a real model and a real training run is
``test_training_slice.py``, and it skips unless ``BUNNY_MODEL_STUDIO_HEAVY=1``
is set — so ``make test`` never downloads a model, and the evidence run is
something a person decides to do.
"""
