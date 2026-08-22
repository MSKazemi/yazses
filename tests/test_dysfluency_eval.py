"""Pre-registered evaluation gate for Dysfluency-Friendly Mode (ADR-015).

Encodes the Vision Card's LOFA-1 kill criteria as an automated regression gate:
- false-collapse rate < 2% on clean control text (must not damage clean speech)
- recall >= 60% on labelled dysfluency spans

These thresholds were set BEFORE measuring (no HARKing). Do not loosen them to
pass; fix the heuristic instead (or ship a narrower collapse and record it).
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import _collapse_dysfluencies

_DATA = json.loads(
    (Path(__file__).parent / "fixtures" / "disfluency" / "dysfluency_eval.json").read_text(encoding="utf-8")
)
_CFG = DisfluencyConfig(collapse_repetitions=True, collapse_prolongations=True)


def test_clean_control_false_collapse_under_2pct():
    controls = _DATA["clean_control"]
    changed = [s for s in controls if _collapse_dysfluencies(s, _CFG) != s]
    rate = len(changed) / len(controls)
    assert rate < 0.02, f"false-collapse {rate:.1%} on clean control: {changed}"


def test_dysfluent_recall_at_least_60pct():
    cases = _DATA["dysfluent"]
    hits = [c for c in cases if _collapse_dysfluencies(c["in"], _CFG) == c["out"]]
    recall = len(hits) / len(cases)
    assert recall >= 0.60, f"recall {recall:.1%} below 0.60"
