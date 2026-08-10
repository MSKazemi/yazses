from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yazses.config import ProfilesConfig

@dataclass
class ResolvedProfile:
    tone: str = ""

def resolve_profile(app_class: str, config: ProfilesConfig) -> ResolvedProfile:
    """Resolve tone profile for an app via glob pattern matching. First match wins."""
    if not app_class or not config:
        return ResolvedProfile()
    for pattern, profile_name in config.app.items():
        if fnmatch.fnmatch(app_class.lower(), pattern.lower()):
            return ResolvedProfile(tone=profile_name)
    return ResolvedProfile()
