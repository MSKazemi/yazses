"""Language → model/ITN routing (pure) — ADR-v2-072.

Map a detected language (with confidence) to the model + ITN locale to load, falling back to a
default below a confidence gate or for unregistered languages. Pure and deterministic; the LID
call and the model files live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelChoice:
    """The routing result: ``language``, the ``model`` to load, and the ``itn`` locale."""
    language: str
    model: str
    itn: str = ""


@dataclass
class LangRegistry:
    """Per-language model/ITN overrides over a default, with a confidence gate."""
    default_model: str
    default_itn: str = ""
    models: dict = field(default_factory=dict)   # language code → model
    itn: dict = field(default_factory=dict)       # language code → ITN locale
    min_confidence: float = 0.5


def route_language(language: str, confidence: float, registry: LangRegistry) -> ModelChoice:
    """Pick the model + ITN for a detected language. Pure.

    Below ``registry.min_confidence`` (or for an unknown/blank language), route to the default.
    """
    lang = (language or "").lower().strip()
    if not lang or confidence < registry.min_confidence:
        return ModelChoice(lang or "und", registry.default_model, registry.default_itn)
    model = registry.models.get(lang, registry.default_model)
    itn = registry.itn.get(lang, registry.default_itn)
    return ModelChoice(lang, model, itn)
