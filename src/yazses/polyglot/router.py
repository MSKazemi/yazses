"""Code-switch routing decision layer (pure) — ADR-v2-008.

Wraps the ``[polyglot]`` config + the ``lid`` primitives into one decision object
the daemon consults. The CS-adapted transcription model is user-supplied and
out-of-band (``[polyglot] adapter_path``); this layer only decides *when* that
adapter would be used and never loads a model itself, so it is fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.polyglot.lid import is_code_switched, parse_pair


@dataclass
class PolyglotRouter:
    enabled: bool
    pair: tuple[str, str] | None
    adapter_path: str
    mer_gate: float

    @classmethod
    def from_config(cls, cfg) -> "PolyglotRouter":
        """Build from a ``PolyglotConfig``; an invalid pair degrades to ``None``."""
        pair: tuple[str, str] | None = None
        if getattr(cfg, "enabled", False) and getattr(cfg, "pair", ""):
            try:
                pair = parse_pair(cfg.pair)
            except ValueError:
                pair = None
        return cls(
            enabled=bool(getattr(cfg, "enabled", False)),
            pair=pair,
            adapter_path=str(getattr(cfg, "adapter_path", "") or ""),
            mer_gate=float(getattr(cfg, "mer_gate", 0.0) or 0.0),
        )

    @property
    def active(self) -> bool:
        """True only when fully configured: enabled + valid pair + adapter present.

        Without a user-supplied adapter the feature stays dormant (the default
        English-only model cannot code-switch), so ``active`` is False by default.
        """
        return self.enabled and self.pair is not None and bool(self.adapter_path)

    def status_reason(self) -> str | None:
        """Human-readable reason the router is *not* active, or None when it is.

        Lets the daemon/doctor explain a half-configured ``[polyglot]`` section
        instead of silently doing nothing.
        """
        if not self.enabled:
            return None  # intentionally off — nothing to explain
        if self.pair is None:
            return "set [polyglot] pair to a valid code like 'fa-en'"
        if not self.adapter_path:
            return "set [polyglot] adapter_path to a code-switch adapter (out-of-band)"
        return None

    def should_route(self, span_languages) -> bool:
        """Whether an utterance's spans warrant the CS adapter.

        Requires the router to be active and the spans to code-switch *within* the
        configured pair. ``mer_gate`` (0..1) optionally requires the minority
        language to reach a fraction of the in-pair spans before routing
        (``0`` = route on any switch). Pure and deterministic.
        """
        if not self.active or self.pair is None:
            return False
        langs = list(span_languages)
        if not is_code_switched(langs, self.pair):
            return False
        if self.mer_gate <= 0:
            return True
        in_pair = [lang for lang in langs if lang in self.pair]
        if not in_pair:  # pragma: no cover — unreachable: is_code_switched guarantees ≥2 pair langs
            return False
        minority = min(in_pair.count(self.pair[0]), in_pair.count(self.pair[1]))
        return (minority / len(in_pair)) >= self.mer_gate
