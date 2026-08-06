# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The genuine adapters, and the factory the service wires them from.

Local: :mod:`~companion.agents.adapters.ollama` and
:mod:`~companion.agents.adapters.llamacpp` over loopback HTTP,
:mod:`~companion.agents.adapters.llamacli` as an allowlisted subprocess.
Remote: :mod:`~companion.agents.adapters.openai_compat`,
:mod:`~companion.agents.adapters.anthropic` and
:mod:`~companion.agents.adapters.gemini`, each of which refuses to touch the
network without an explicit remote configuration and a resolvable credential.

None of these is a placeholder. An absent runtime probes to a structured
unavailable result with the reason; nothing here reports success it did not
observe.
"""

from __future__ import annotations

from typing import Mapping

from ..adapter import ProviderAdapter
from .anthropic import AnthropicAdapter
from .gemini import GeminiAdapter
from .llamacli import LlamaCliAdapter
from .llamacpp import LlamaCppAdapter
from .ollama import OllamaAdapter
from .openai_compat import OpenAiCompatAdapter

__all__ = [
    "AnthropicAdapter",
    "GeminiAdapter",
    "LlamaCliAdapter",
    "LlamaCppAdapter",
    "OllamaAdapter",
    "OpenAiCompatAdapter",
    "default_adapters",
]


def default_adapters() -> Mapping[str, ProviderAdapter]:
    """Every adapter this build ships, keyed by the id configurations use."""
    adapters = (
        OllamaAdapter(),
        LlamaCppAdapter(),
        LlamaCliAdapter(),
        OpenAiCompatAdapter(),
        AnthropicAdapter(),
        GeminiAdapter(),
    )
    return {item.adapter_id: item for item in adapters}
