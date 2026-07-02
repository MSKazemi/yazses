"""Dictation Reflow outline builder (ADR-v2-038) — pure reflow."""
from __future__ import annotations

from yazses.reflow.outline import reflow


def test_reflow_splits_sentences_into_bullets():
    out = reflow("we should ship it. the tests pass.")
    assert out == "- we should ship it\n- the tests pass"


def test_reflow_strips_leading_markers():
    out = reflow("First we design. Next we build. Finally we test.")
    assert out == "- we design\n- we build\n- we test"


def test_reflow_flags_action_items():
    out = reflow("the report is done. action item send it to Sam.")
    assert out == "- the report is done\n- [ ] send it to Sam"


def test_reflow_i_need_to_is_action():
    assert reflow("I need to call the vendor.") == "- [ ] I need to call the vendor"


def test_reflow_empty():
    assert reflow("") == ""
    assert reflow("   ") == ""


def test_reflow_single_sentence_no_marker():
    assert reflow("just one thought here") == "- just one thought here"


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "reflow" in [f.slug for f in feature_status(Config())]
    assert Config().reflow.enabled is False
