"""Persistent word-goal state (JSON file) — ADR-v2-092.

A durable ``{count, goal}`` for a writing session, stored next to ``config.toml`` as
``wordgoal.json`` so ``yazses wordgoal`` accumulates across invocations (the
``WordGoalTracker`` core is otherwise in-memory with no runtime entry point). Pure
filesystem/logic — unit-testable with ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path


def wordgoal_path(config_dir) -> Path:
    return Path(config_dir) / "wordgoal.json"


def load_state(path) -> dict:
    """Return ``{"count": int, "goal": int}`` (zeros if absent/unreadable)."""
    p = Path(path)
    if not p.exists():
        return {"count": 0, "goal": 0}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {"count": max(0, int(data.get("count", 0))), "goal": max(0, int(data.get("goal", 0)))}
    except (ValueError, OSError, TypeError, AttributeError):
        # AttributeError: valid JSON that is not an object has no `.get`. The docstring
        # promises zeros for anything unreadable, and a string where a table belongs is
        # unreadable -- `yazses wordgoal status` used to answer it with a traceback.
        return {"count": 0, "goal": 0}


def save_state(path, *, count: int, goal: int) -> dict:
    """Write and return the ``{count, goal}`` state (both clamped to ≥ 0)."""
    state = {"count": max(0, int(count)), "goal": max(0, int(goal))}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state
