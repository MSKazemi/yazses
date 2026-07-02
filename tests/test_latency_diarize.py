"""Adaptive Latency Governor (ADR-v2-073) + Diarized Conversation Capture (ADR-v2-074) — pure cores."""
from __future__ import annotations

from yazses.diarize.labels import (
    SpeakerLabelMap,
    canonical_speaker,
    parse_rename,
    render_attributed_markdown,
)
from yazses.latency.governor import DecodePolicy, GovernorConfig, pick_policy


# ---- latency governor ------------------------------------------------------

def _cfg(draft=""):
    return GovernorConfig(base_model="base.en", light_model="tiny.en", draft_model=draft,
                          high_load=85.0, low_load=40.0)


def test_high_load_uses_light_policy():
    p = pick_policy(95.0, _cfg())
    assert p == DecodePolicy("tiny.en", 1, False)


def test_low_load_speculative_when_draft_present():
    assert pick_policy(20.0, _cfg(draft="distil")) == DecodePolicy("base.en", 5, True)
    # no draft configured → no speculation even when idle
    assert pick_policy(20.0, _cfg()).speculative is False


def test_mid_load_balanced():
    p = pick_policy(60.0, _cfg(draft="distil"))
    assert p == DecodePolicy("base.en", 5, False)


# ---- diarize labels --------------------------------------------------------

def test_canonical_speaker():
    assert canonical_speaker("SPEAKER_01") == "speaker_1"
    assert canonical_speaker("speaker two") == "speaker_2"
    assert canonical_speaker("nobody") is None


def test_parse_rename_variants():
    assert parse_rename("call speaker two Alice") == ("speaker_2", "Alice")
    assert parse_rename("rename speaker 1 to Bob") == ("speaker_1", "Bob")
    assert parse_rename("speaker 3 is Carol") == ("speaker_3", "Carol")
    assert parse_rename("hello there") is None


def test_label_map_display_and_rename():
    m = SpeakerLabelMap()
    assert m.display("SPEAKER_00") == "Speaker 0"     # default pretty
    assert m.rename("speaker 0", "Alice") is True
    assert m.display("SPEAKER_00") == "Alice"
    assert m.rename("nobody", "X") is False
    assert m.display("weird-id") == "weird-id"        # unrecognized passes through


def test_apply_command():
    m = SpeakerLabelMap()
    assert m.apply_command("call speaker one Dana") is True
    assert m.display("speaker 1") == "Dana"
    assert m.apply_command("do nothing") is False


def test_render_attributed_markdown_merges_runs():
    m = SpeakerLabelMap()
    m.rename("speaker 0", "Alice")
    m.rename("speaker 1", "Bob")
    turns = [("speaker_0", "hi there"), ("speaker_0", "how are you"), ("speaker_1", "good thanks")]
    assert render_attributed_markdown(turns, m) == (
        "**Alice:** hi there how are you\n"
        "**Bob:** good thanks"
    )


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "latency" in slugs and "diarize" in slugs
    assert Config().latency.enabled is False and Config().diarize.enabled is False
