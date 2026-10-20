"""Canonical language profiles and aliases.

Profiles are presets over canonical config, not a second persistent source of truth.
The actual YazSes settings remain in the STT/commands config; callers derive which
profile a configuration resembles instead of storing an active-profile flag.
"""
from __future__ import annotations

from dataclasses import dataclass


class LanguageProfileError(ValueError):
    """A requested high-level language profile cannot be resolved safely."""


@dataclass(frozen=True)
class LanguageProfile:
    """One supported high-level speech/output combination."""

    id: str
    aliases: tuple[str, ...]
    label: str
    speech_language: str
    output_script: str
    command_language: str
    recommended_engine: str
    recommended_model: str


_EN = LanguageProfile(
    id="en",
    aliases=("en",),
    label="English",
    speech_language="en",
    output_script="",
    command_language="en",
    recommended_engine="faster-whisper",
    recommended_model="base.en",
)

_ZH_CN = LanguageProfile(
    id="zh-CN",
    aliases=("zh-cn", "zh-hans"),
    label="Mandarin (Simplified Chinese)",
    speech_language="zh",
    output_script="simplified",
    command_language="zh",
    recommended_engine="faster-whisper",
    recommended_model="small",
)

_ZH_TW = LanguageProfile(
    id="zh-TW",
    aliases=("zh-tw", "zh-hant"),
    label="Mandarin (Traditional Chinese)",
    speech_language="zh",
    output_script="traditional",
    command_language="zh",
    recommended_engine="faster-whisper",
    recommended_model="small",
)

_PROFILES: tuple[LanguageProfile, ...] = (_EN, _ZH_CN, _ZH_TW)
_ALIAS_MAP = {
    alias: profile
    for profile in _PROFILES
    for alias in profile.aliases
}


def _normalise_id(value: str) -> str:
    return (value or "").strip().replace("_", "-").lower()


def list_profiles() -> tuple[LanguageProfile, ...]:
    """Return the stable, user-selectable P1 profiles."""

    return _PROFILES


def get_profile(requested: str) -> LanguageProfile:
    """Resolve requested to a canonical profile or raise an actionable error.

    zh-HK is intentionally not treated as Traditional Mandarin. Traditional Han is
    an output-script choice; Hong Kong speech may mean Cantonese, which needs its own
    model/evidence contract.
    """

    key = _normalise_id(requested)
    profile = _ALIAS_MAP.get(key)
    if profile is not None:
        return profile

    if key == "zh":
        raise LanguageProfileError(
            "'zh' does not choose an output script. Use 'zh-CN'/'zh-Hans' for "
            "Mandarin with Simplified output or 'zh-TW'/'zh-Hant' for Mandarin "
            "with Traditional output."
        )

    if key == "zh-hk":
        raise LanguageProfileError(
            "'zh-HK' is ambiguous for speech and is not a P1 YazSes profile. "
            "Traditional characters do not imply Cantonese or Mandarin. Use 'zh-TW' "
            "for Mandarin with Traditional output; Cantonese ('yue-HK') requires a "
            "separate model and validation milestone."
        )

    if key in {"yue", "yue-hk", "cantonese"}:
        raise LanguageProfileError(
            "Cantonese is not part of the Mandarin P1 profile set yet. It requires "
            "a separate speech model, command grammar, and validation evidence."
        )

    valid = ", ".join(profile.id for profile in _PROFILES)
    shown = requested if requested else "<empty>"
    raise LanguageProfileError(
        f"Unknown language profile {shown!r}. Available profiles: {valid}."
    )
