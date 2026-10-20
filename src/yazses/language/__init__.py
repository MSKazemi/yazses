"""Language-profile planning for coherent speech/output configuration.

This package is deliberately lightweight. Importing it performs no I/O, model loading,
network access, optional dependency import, or config mutation. Higher-level CLI/Settings
code can therefore use the same resolver for previews and real application.
"""

from yazses.language.plan import ConfigMutation, LanguagePlan, resolve_profile
from yazses.language.profiles import (
    LanguageProfile,
    LanguageProfileError,
    get_profile,
    list_profiles,
)
from yazses.language.status import LanguageStatus, derive_status

__all__ = [
    "ConfigMutation",
    "LanguagePlan",
    "LanguageProfile",
    "LanguageProfileError",
    "LanguageStatus",
    "derive_status",
    "get_profile",
    "list_profiles",
    "resolve_profile",
]
