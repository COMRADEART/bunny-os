"""Bunny Shell user-session services.

The package intentionally contains no privileged execution primitive.  System
mutations remain requests to the Phase 1 broker and Bunny actions remain
requests to Bunny Core.
"""

SHELL_CONTRACT_VERSION = "1.0.0"
WORKSPACE_SCHEMA_VERSION = 1
SETTINGS_SCHEMA_VERSION = 1
SEARCH_SCHEMA_VERSION = 1

__all__ = [
    "SEARCH_SCHEMA_VERSION",
    "SETTINGS_SCHEMA_VERSION",
    "SHELL_CONTRACT_VERSION",
    "WORKSPACE_SCHEMA_VERSION",
]
