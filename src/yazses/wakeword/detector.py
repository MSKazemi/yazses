"""Wake-word activation decision (pure) — ADR-v2-033.

Decide whether a keyword-spotter detection should start a dictation turn: the score must
clear the threshold and a cooldown must have elapsed (false-accept guard). Pure and
deterministic; the spotter model lives behind the ``wakeword`` extra.
"""
from __future__ import annotations


def should_activate(score, since_last_ms, config) -> bool:
    """Return True when a wake-word detection should start recording.

    Fires only when ``score`` is at least ``threshold`` and ``since_last_ms`` (time since the
    last activation) is at least ``cooldown_ms`` — the debounce that blocks repeated
    false-accepts. Disabled config never activates. Pure.
    """
    if not getattr(config, "enabled", False):
        return False
    threshold = float(getattr(config, "threshold", 0.5))
    cooldown = float(getattr(config, "cooldown_ms", 2000))
    if score < threshold:
        return False
    if since_last_ms < cooldown:
        return False
    return True
