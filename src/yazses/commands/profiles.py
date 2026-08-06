"""Per-app command profile loader."""
from __future__ import annotations

from dataclasses import dataclass, field

from yazses.config import CommandsConfig


@dataclass
class ProfileRegistry:
    profiles: dict[str, str] = field(default_factory=dict)

    def resolve(self, profile_hint: str) -> str:
        """Return the profile name to use. Falls back to 'default'."""
        if profile_hint in self.profiles:
            return self.profiles[profile_hint]
        return "default"


def load_profiles(config: CommandsConfig) -> ProfileRegistry:
    """Build a ProfileRegistry from CommandsConfig."""
    return ProfileRegistry(profiles={})
