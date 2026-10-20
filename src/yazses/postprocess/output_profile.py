"""Language output profiles: one registry keyed by the configured STT language (FA-01, #509).

Language-specific clean-up of what the decoder returned used to be a hard-coded
branch per language in ``stt/factory.py`` (Han script for Chinese, then Persian).
A *profile* is the small boundary that stops that growing: the factory asks the
registry "what, if anything, owns the output for this language?" and wraps the
engine once, the same single-chokepoint rule the existing wrappers follow. The
design is the Persian language-support plan, §4.2 (``design/specs/persian-language-support-plan.md``,
draft PR #483, issue #509).

Two rules, both load-bearing:

* **Keyed by ``[stt] language``, never by the UI locale.** The language the speech
  is *decoded as* decides how its text is cleaned; the language of the menus does
  not. A French UI dictating Persian gets the Persian profile; a Persian UI
  dictating English gets none. ``profile_for`` therefore takes the STT language
  string and nothing else.
* **No profile means pass-through.** Every language without a registered profile —
  English included — gets :class:`PassThroughProfile`, which builds no normaliser,
  so the factory returns the engine untouched: no wrapper, no per-utterance cost,
  byte-identical output.

``build_normaliser(stt)`` deliberately has the same shape as
``postprocess.han_script.build_han_normaliser`` (``SttConfig -> text->text | None``),
so Chinese script normalisation can later register here as a ``zh`` profile
without changing this interface. It is *not* moved now. Transliteration is a
different operation and does not belong in this layer.

Pure and dependency-free: importing this module pulls in nothing heavy.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol

from yazses.postprocess.persian_text import build_persian_normaliser, is_persian_language

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yazses.config import SttConfig

Normaliser = Callable[[str], str]


class OutputProfile(Protocol):
    """What the factory needs from a language's output profile."""

    language_code: str

    def build_normaliser(self, stt: "SttConfig") -> Normaliser | None:
        """Return a text->text transform for *stt*, or ``None`` for "leave the text alone"."""
        ...


class PassThroughProfile:
    """The profile of every language that owns no output rules. Changes nothing."""

    language_code = ""

    def build_normaliser(self, stt: "SttConfig") -> Normaliser | None:
        return None


class PersianProfile:
    """Persian (``fa``). Delegates to the FA-02 normaliser (#511), which stays opt-in.

    The transform itself lives in ``postprocess.persian_text`` and is still gated
    by ``[stt] persian_normalisation`` (off by default), so selecting this profile
    for ``language = "fa"`` alone changes no output.
    """

    language_code = "fa"

    def build_normaliser(self, stt: "SttConfig") -> Normaliser | None:
        return build_persian_normaliser(stt)


PASS_THROUGH: OutputProfile = PassThroughProfile()
PERSIAN: OutputProfile = PersianProfile()

# Canonical language code -> profile. Aliases are folded to the code by
# `canonical_language` before the lookup, so this table stays one row per language.
_REGISTRY: dict[str, OutputProfile] = {PERSIAN.language_code: PERSIAN}


def canonical_language(language: object) -> str:
    """Fold *language* (``"FA"``, ``"fa-IR"``, ``"persian"`` ...) to its registry key."""
    if is_persian_language(language):
        return PERSIAN.language_code
    return str(language or "").strip().lower()


def profile_for(language: object) -> OutputProfile:
    """Return the output profile for the configured **STT** language.

    Takes the STT language only — the UI locale is intentionally not an input.
    Unknown, empty and non-string values resolve to pass-through, never raise.
    """
    return _REGISTRY.get(canonical_language(language), PASS_THROUGH)
