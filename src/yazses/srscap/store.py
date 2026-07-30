"""Persistent spaced-repetition card store (JSON file) — ADR-v2-112.

A durable deck of cloze cards + their SM-2 state, stored next to ``config.toml`` as
``srscap.json``, so ``yazses srs`` captures and schedules reviews across invocations (the
``srscap.cards`` cores are otherwise pure with no runtime entry point). Reuses
:class:`~yazses.srscap.cards.Sm2State` / :func:`~yazses.srscap.cards.sm2_schedule` for
scheduling. Pure filesystem/logic — unit-testable with ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.srscap.cards import Card, Sm2State, sm2_schedule


def srscap_path(config_dir) -> Path:
    return Path(config_dir) / "srscap.json"


def load_cards(path) -> list[dict]:
    """Return the stored deck (empty if absent/unreadable)."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def _save(path, cards: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_card(path, card: Card) -> list[dict]:
    """Append a new card (with a fresh SM-2 state); return the full deck."""
    cards = load_cards(path)
    cards.append({
        "front": card.front, "back": card.back, "cloze": card.cloze,
        "reps": 0, "interval": 0, "ease": 2.5,
    })
    _save(path, cards)
    return cards


def review_card(path, index: int, grade: int) -> dict:
    """Apply an SM-2 ``grade`` (0–5) to card ``index`` (0-based); return the updated card.

    Raises ``IndexError`` if the card doesn't exist.
    """
    cards = load_cards(path)
    if not (0 <= index < len(cards)):
        raise IndexError(f"no card #{index + 1} (deck has {len(cards)})")
    c = cards[index]
    state = Sm2State(reps=int(c.get("reps", 0)), interval=int(c.get("interval", 0)),
                     ease=float(c.get("ease", 2.5)))
    nxt = sm2_schedule(state, grade)
    c.update({"reps": nxt.reps, "interval": nxt.interval, "ease": round(nxt.ease, 4)})
    _save(path, cards)
    return c
