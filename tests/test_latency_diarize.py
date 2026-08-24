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

def _cfg(draft="", beam=5):
    return GovernorConfig(base_model="base.en", light_model="tiny.en", draft_model=draft,
                          high_load=85.0, low_load=40.0, base_beam=beam)


def test_high_load_uses_light_policy():
    p = pick_policy(95.0, _cfg())
    assert p == DecodePolicy("tiny.en", 2, False)


def test_low_load_speculative_when_draft_present():
    assert pick_policy(20.0, _cfg(draft="distil")) == DecodePolicy("base.en", 5, True)
    # no draft configured → no speculation even when idle
    assert pick_policy(20.0, _cfg()).speculative is False


def test_mid_load_balanced():
    p = pick_policy(60.0, _cfg(draft="distil"))
    assert p == DecodePolicy("base.en", 5, False)


# ---- the base policies must not invent a beam width ------------------------
#
# `pick_policy` hardcoded `beam_size=5` on both base paths. Two things followed,
# and the second is the one nothing was watching.
#
# A user who set `[stt] beam_size` got 5 anyway for as long as the governor was
# on -- a documented key silently discarded by an unrelated feature.
#
# And `EnginePool` is keyed on `(model, beam_size)`. The daemon builds it with
# `base_key = (stt.model, stt.beam_size)`, which for the shipped config is
# `(model, 0)`: "pass nothing, let the engine choose". A base policy answering
# `(model, 5)` misses that key on every normal-load burst, so the pool starts a
# background load of a **second copy of the model already in memory** -- which
# pool.py's own docstring names as the thing its design prevents. Nothing failed
# and nothing was logged as wrong; the process simply held two engines.


def test_the_base_policy_returns_the_configured_beam_not_one_of_its_own():
    for beam in (0, 1, 2, 5, 8):
        assert pick_policy(60.0, _cfg(beam=beam)).beam_size == beam
        assert pick_policy(20.0, _cfg(draft="distil", beam=beam)).beam_size == beam


def test_the_shipped_default_means_pass_nothing():
    """`[stt] beam_size` defaults to 0 and the base policy must carry that through
    rather than substituting the width faster-whisper happens to use."""
    from yazses.config import SttConfig

    assert SttConfig().beam_size == 0
    assert pick_policy(60.0, _cfg(beam=SttConfig().beam_size)).beam_size == 0


def test_the_base_policy_hits_the_pool_key_the_daemon_already_loaded():
    """The regression, stated as the pool sees it: no build, ever, at normal load."""
    from yazses.latency.pool import EnginePool

    built: list = []
    queued: list = []
    for beam in (0, 2, 5):
        pool = EnginePool(
            lambda m, b: built.append((m, b)),
            ("base.en", beam),
            "the-engine-already-loaded",
            spawn=queued.append,
        )
        policy = pick_policy(60.0, _cfg(beam=beam))
        assert pool.get(policy.model, policy.beam_size) == "the-engine-already-loaded"
    assert built == [], f"the base policy triggered a build: {built}"
    assert queued == [], "the base policy queued a background model load"


def test_the_light_policy_still_switches_model_and_narrows_the_beam():
    """The other direction: fixing the base path must not flatten the light one,
    which is the whole point of the governor. Its beam width is decided by
    measurement -- see `governor.LIGHT_BEAM` and
    paper/results/beam-governor-test-other.json."""
    from yazses.latency.governor import LIGHT_BEAM

    for beam in (0, 2, 5, 8):
        p = pick_policy(95.0, _cfg(beam=beam))
        assert p.model == "tiny.en"
        assert p.beam_size == LIGHT_BEAM


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
