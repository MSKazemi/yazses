"""Spoken Temporal Normalizer (ADR-v2-057) + Mid-Utterance Self-Repair (ADR-v2-058) — pure."""
from __future__ import annotations

from datetime import datetime

from yazses.selfrepair.repair import apply_self_repair
from yazses.temporal.resolve import resolve_temporal

# A fixed reference: Wednesday 2026-07-01.
NOW = datetime(2026, 7, 1, 9, 0, 0)


# ---- temporal --------------------------------------------------------------

def test_today_tomorrow_yesterday():
    assert resolve_temporal("due today", NOW) == "due Wed Jul 1 2026"
    assert resolve_temporal("due tomorrow", NOW) == "due Thu Jul 2 2026"
    assert resolve_temporal("was yesterday", NOW) == "was Tue Jun 30 2026"


def test_next_weekday():
    # next Friday from Wed Jul 1 → Fri Jul 3
    assert resolve_temporal("meet next Friday", NOW) == "meet Fri Jul 3 2026"


def test_next_weekday_same_day_rolls_forward():
    # "next Wednesday" from a Wednesday → the following week
    assert resolve_temporal("ship next Wednesday", NOW) == "ship Wed Jul 8 2026"


def test_this_weekday_and_in_n():
    assert resolve_temporal("this Friday", NOW) == "Fri Jul 3 2026"
    assert resolve_temporal("in 3 days", NOW) == "Sat Jul 4 2026"
    assert resolve_temporal("in 2 weeks", NOW) == "Wed Jul 15 2026"


def test_temporal_plain_and_empty():
    assert resolve_temporal("no dates here", NOW) == "no dates here"
    assert resolve_temporal("", NOW) == ""


# ---- self-repair -----------------------------------------------------------

def test_no_i_mean_replaces_prev_token():
    assert apply_self_repair("email Sarah no I mean Sara about the deck") == "email Sara about the deck"


def test_make_that():
    assert apply_self_repair("set it to five make that six") == "set it to six"


def test_chained_repairs():
    assert apply_self_repair("call Bob no I mean Rob no I mean Rick now") == "call Rick now"


def test_self_repair_plain_and_empty():
    assert apply_self_repair("nothing to repair here") == "nothing to repair here"
    assert apply_self_repair("") == ""


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "temporal" in slugs and "self_repair" in slugs
    assert Config().temporal.enabled is False and Config().commands.self_repair is False
