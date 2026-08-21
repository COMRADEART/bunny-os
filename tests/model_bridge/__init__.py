# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the model adapter runtime bridge.

Everything here runs without a model, a GPU, an inference server or the
network. The one suite that needs all four is ``test_runtime_slice.py``, which
skips unless ``BUNNY_MODEL_BRIDGE_HEAVY=1`` — so the ordinary suite stays
something people run, and the real evidence stays something somebody decides
to produce.
"""
