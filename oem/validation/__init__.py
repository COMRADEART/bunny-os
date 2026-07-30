"""OEM profile, overlay, and factory-state validation."""

from oem.validation.finalize import FACTORY_STATE_CHECKS, evaluate_finalisation
from oem.validation.overlay import OVERLAY_ALLOWED_ROOTS, validate_overlay
from oem.validation.profile import PROTECTED_SETTINGS, validate_profile

__all__ = [
    "FACTORY_STATE_CHECKS",
    "OVERLAY_ALLOWED_ROOTS",
    "PROTECTED_SETTINGS",
    "evaluate_finalisation",
    "validate_overlay",
    "validate_profile",
]
