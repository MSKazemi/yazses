"""``[gesture.chords]`` is checked when the config is loaded, not only when the daemon starts.

``gesture.engine.parse_chords`` is the one place a chord is understood. ``load_config_checked``
asks it early so ``yazses doctor`` and the log name the bad line with the same wording the
runtime uses; a refused chord is skipped, never repaired into a neighbouring one.
"""
from __future__ import annotations

from yazses.config import Config, load_config_checked


def _load(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


def test_the_shipped_default_reports_nothing():
    assert Config().gesture.chords == {}
    assert Config().gesture.hold_ms == 800 and Config().gesture.onset_rewind_ms == 150


def test_a_good_hold_chord_loads_clean(tmp_path):
    loaded = _load(tmp_path, '[gesture]\nenabled = true\n[gesture.chords]\n"jaw_open+hold" = "recenter"\n')
    assert loaded.problems == []
    assert loaded.config.gesture.chords == {"jaw_open+hold": "recenter"}


def test_a_bad_token_is_named_at_load_with_the_valid_ones(tmp_path):
    loaded = _load(tmp_path, '[gesture.chords]\n"jaw_open+wink" = "recenter"\n')
    messages = [str(p) for p in loaded.problems]
    assert len(messages) == 1
    assert "wink" in messages[0] and "hold" in messages[0] and "[gesture.chords]" in messages[0]


def test_hold_with_only_a_momentary_token_is_named_at_load(tmp_path):
    loaded = _load(tmp_path, '[gesture.chords]\n"nod+hold" = "recenter"\n"hold" = "recenter"\n')
    messages = [str(p) for p in loaded.problems]
    assert len(messages) == 2 and all("momentary" in m for m in messages)


def test_the_plain_chord_and_its_hold_variant_are_reported_together(tmp_path):
    loaded = _load(
        tmp_path, '[gesture.chords]\n"smile" = "recenter"\n"smile+hold" = "pause_pointer"\n'
    )
    assert len(loaded.problems) == 1 and "neither binding is used" in str(loaded.problems[0])


def test_a_zero_or_negative_hold_duration_falls_back_to_the_default(tmp_path):
    for value in ("0", "-5"):
        loaded = _load(tmp_path, f"[gesture]\nhold_ms = {value}\n")
        assert loaded.config.gesture.hold_ms == 800
        assert any(p.key == "hold_ms" for p in loaded.problems)


def test_a_negative_rewind_falls_back_and_zero_turns_it_off(tmp_path):
    assert _load(tmp_path, "[gesture]\nonset_rewind_ms = -1\n").config.gesture.onset_rewind_ms == 150
    assert _load(tmp_path, "[gesture]\nonset_rewind_ms = 0\n").config.gesture.onset_rewind_ms == 0
