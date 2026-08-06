# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent providers: local-first text generation behind the canonical runtime.

This package is the §2 pipeline from "sanitized generation request" to "text,
structured output, or tool proposal", and nothing on either side of it. The
canonical runtime — sessions, tasks, lifecycle, approvals, tool authority,
privacy, cancellation, recovery, presentation — stays where it was; a provider
here *proposes* and *produces*, and every act that could touch the machine or
the user runs back through :mod:`companion.tools` and :mod:`companion.approvals`
exactly as if no provider existed.

The import boundary is the same one :mod:`companion.voice` and
:mod:`companion.speech` live behind, enforced by the same kind of AST test:
nothing in this package imports the runtime, the store, the task model, the
approval gate, the executors or the broker. The one seam to the task side is
:mod:`companion.agent_bridge`, which lives *outside* this package for that
reason, the way :mod:`companion.capability_bridge` does.

Module map:

:mod:`~companion.agents.descriptor`
    The §3 provider descriptor, the six-word standing ladder, and the type
    decision that keeps credentials out of every record: no field for one.
:mod:`~companion.agents.request` / :mod:`~companion.agents.context`
    The §6 bounded request and the §7 canonical context builder — closed
    source set, per-item provenance, overflow refused rather than trimmed.
:mod:`~companion.agents.credentials`
    §5: presence is reportable, values are :class:`Secret` and do not
    serialize. File sources are refused for symlinks, loose modes, foreign
    owners and unapproved locations.
:mod:`~companion.agents.stream` / :mod:`~companion.agents.structured`
    §11's ordering contract in one assembler; §12's local validation against
    schemas only this build names, with bounded, recorded repair.
:mod:`~companion.agents.usage` / :mod:`~companion.agents.health`
    §16's measured/reported/estimated discipline and pre-flight ceilings;
    §17's circuit with the authentication asymmetry.
:mod:`~companion.agents.adapter` / :mod:`~companion.agents.wire` /
:mod:`~companion.agents.adapters`
    The adapter contract and the genuine implementations — Ollama and
    llama.cpp server over loopback HTTP, llama-cli as an allowlisted
    subprocess, and the three remote wire formats (OpenAI-compatible,
    Anthropic, Gemini), which construct only from an explicit remote
    configuration. No placeholder reports success anywhere.
:mod:`~companion.agents.config` / :mod:`~companion.agents.registry`
    The user-edited configuration and §9's deterministic, fully-explained
    eligibility and selection, with §10's ladder that never falls through to
    remote on its own.
:mod:`~companion.agents.worker` / :mod:`~companion.agents.journal`
    The one generation thread, bounded queues, cancellation that releases
    resources, and the §19 journal that marks interrupted work interrupted
    instead of repeating it.
:mod:`~companion.agents.service`
    The §21 protocol operations, and nothing that mutates configuration.
"""

from __future__ import annotations

__all__ = [
    "AGENTS_SCHEMA_VERSION",
]

AGENTS_SCHEMA_VERSION = 1
