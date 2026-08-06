"""WordFind (ADR-v2-118) + LoadGuard (ADR-v2-121) — pure cores."""
from __future__ import annotations

from yazses.loadguard.policy import estimate_load, guard_policy
from yazses.wordfind.rank import rank_candidates

# ---- wordfind ---------------------------------------------------------------

def test_rank_top_hit():
    hits = rank_candidates("the word for when water turns to gas")
    assert hits[0][0] == "evaporation"
    assert hits[0][1] > 0


def test_rank_stopwords_only_and_empty():
    assert rank_candidates("the word for a thing") == []
    assert rank_candidates("") == []
    assert rank_candidates("xylophone zither quux") == []       # no overlap anywhere


def test_rank_deterministic_order_and_limit():
    hits = rank_candidates("water", limit=2)                    # evaporation + condensation tie
    assert [w for w, _ in hits] == ["condensation", "evaporation"]
    assert rank_candidates("water", limit=0) == []


def test_rank_user_lexicon_merges():
    hits = rank_candidates("small furry pet that purrs",
                           lexicon={"cat": "a small furry pet that purrs"})
    assert hits[0][0] == "cat" and hits[0][1] == 1.0


# ---- loadguard --------------------------------------------------------------

def test_estimate_load_empty_and_single_signal():
    assert estimate_load(None) == 0.0
    assert estimate_load({}) == 0.0
    assert estimate_load({"pause_ratio": 0.5}) == 0.5
    assert estimate_load({"pause_ratio": 2.0}) == 1.0           # clamped


def test_estimate_load_fuses_signals():
    calm = estimate_load({"pause_ratio": 0.1, "filler_rate": 0.0,
                          "speech_rate_wpm": 170, "self_corrections": 0})
    stressed = estimate_load({"pause_ratio": 0.6, "filler_rate": 0.12,
                              "speech_rate_wpm": 90, "self_corrections": 2})
    assert calm < 0.1 < stressed
    assert estimate_load({"speech_rate_wpm": 200}) == 0.0       # fast speech is not load


def test_guard_policy_tiers():
    assert guard_policy(0.9) == {"level": "high", "widen_confirmations": True, "defer_risky": True}
    assert guard_policy(0.55) == {"level": "elevated", "widen_confirmations": True,
                                  "defer_risky": False}
    assert guard_policy(0.1) == {"level": "normal", "widen_confirmations": False,
                                 "defer_risky": False}
    assert guard_policy(0.5, threshold=0.5)["level"] == "high"  # custom threshold


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "wordfind" in slugs and "loadguard" in slugs
    assert Config().wordfind.enabled is False and Config().loadguard.enabled is False
    assert Config().wordfind.max_candidates == 5 and Config().loadguard.threshold == 0.7
