"""Normalise Chinese output to one Han script (`[stt] chinese_script`).

Whisper decodes Mandarin into whichever Han script its training data favoured for
that utterance, and it is not consistent: on 20 clean 16 kHz Mandarin utterances
(ASCEND test split, `small` model) it answered in Traditional characters for 13 of
them, mid-session, with no way for the user to ask for anything else. A mainland
user dictating 简体中文 therefore watches 繁體字 land in their editor.

The damage is larger than it looks, because the recognition was usually *right*:
character error rate against the Simplified references was 35.9% as typed, but
16.9% once the script mismatch was normalised away. Over half of what read as a
bad recognizer was really a wrong-script renderer.

Conversion is one direction of a reversible mapping, so it cannot repair a
mishearing — it only stops a correct transcription from arriving in the wrong
script. Off by default: Taiwan and Hong Kong users want the Traditional output
this would convert away, so the script has to be stated, not guessed.

Dependency-light on purpose: ``opencc`` is imported inside the converter, so the
base install never pays for it, and an absent dependency degrades to "leave the
text alone" after one honest warning rather than breaking dictation.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yazses.config import SttConfig

log = logging.getLogger(__name__)

SIMPLIFIED = "simplified"
TRADITIONAL = "traditional"

# Accepted spellings for each target, so a config written as "zh-Hans", "hans" or
# "simplified" all mean the same thing. BCP-47 subtags are included because that
# is what users copy out of locale settings and other tools.
_ALIASES = {
    SIMPLIFIED: SIMPLIFIED,
    "simplified": SIMPLIFIED,
    "simp": SIMPLIFIED,
    "hans": SIMPLIFIED,
    "zh-hans": SIMPLIFIED,
    "zh_hans": SIMPLIFIED,
    "zh-cn": SIMPLIFIED,
    "cn": SIMPLIFIED,
    TRADITIONAL: TRADITIONAL,
    "trad": TRADITIONAL,
    "hant": TRADITIONAL,
    "zh-hant": TRADITIONAL,
    "zh_hant": TRADITIONAL,
    "zh-tw": TRADITIONAL,
    "zh-hk": TRADITIONAL,
    "tw": TRADITIONAL,
}

# OpenCC conversion configs. t2s/s2t are the character-level mappings; the
# phrase-aware variants (tw2sp etc.) additionally rewrite regional vocabulary,
# which is a different and more opinionated job than the one asked for here.
_OPENCC_CONFIG = {SIMPLIFIED: "t2s", TRADITIONAL: "s2t"}

# CJK Unified Ideographs (+ Extension A) and the compatibility block. Enough to
# answer "is there any Han here at all", which is all the fast path needs.
_HAN_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))


def resolve_script(value: str | None) -> str:
    """Return the canonical target script, or ``""`` when conversion is off.

    Unknown values resolve to off rather than raising: per the project's config
    rule, no config value may stop the daemon starting.
    """
    key = (value or "").strip().lower().replace(" ", "")
    if not key or key in ("off", "none", "no", "auto", "false"):
        return ""
    script = _ALIASES.get(key)
    if script is None:
        log.warning(
            "[stt] chinese_script = %r is not recognised — leaving Chinese output "
            "unconverted. Valid values: %r, %r, or \"\" to disable.",
            value, SIMPLIFIED, TRADITIONAL,
        )
        return ""
    return script


def contains_han(text: str) -> bool:
    """True when *text* holds at least one Han character.

    The fast path for the common case: an English dictation burst should not pay
    for a conversion that cannot change it.
    """
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in _HAN_RANGES)
        for ch in text
    )


def build_han_normaliser(stt: "SttConfig") -> Callable[[str], str] | None:
    """Return a text→text converter for `[stt] chinese_script`, or ``None``.

    ``None`` means "do nothing" and is returned when conversion is switched off,
    when the value is unrecognised, or when ``opencc`` is not installed — the
    caller then leaves the model's output exactly as it came.
    """
    script = resolve_script(getattr(stt, "chinese_script", ""))
    if not script:
        return None

    try:
        from opencc import OpenCC
    except ModuleNotFoundError:
        from yazses.system.backends import probe_backend

        status = probe_backend(
            script,
            adapter="yazses.postprocess.han_script",
            requires=("opencc",),
            extra="chinese",
        )
        log.warning(
            "[stt] chinese_script = %r but %s — Chinese output is left in "
            "whichever script the model produced.",
            script, status.message,
        )
        return None

    converter = OpenCC(_OPENCC_CONFIG[script])

    def normalise(text: str) -> str:
        if not text or not contains_han(text):
            return text
        return converter.convert(text)

    return normalise
