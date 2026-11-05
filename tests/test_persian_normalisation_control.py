"""The Settings control for `[stt] persian_normalisation` (Persian text, off by default).

The window's Features page is generated from the `system/features.py` registry, so the
control is a registry row: no Qt is needed to test it. These tests pin the things that
would make the checkbox lie: it is reachable, it maps to the right key, it is off for an
existing install, and switching it on and off moves that one key and nothing else.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tempfile

from yazses.config import Config, load_config
from yazses.settingsui.model import build_settings_model
from yazses.system import features
from yazses.system.configedit import set_config_key

SLUG = "persian-normalisation"


def _row():
    model = build_settings_model(Config())
    rows = [row for group in model.groups for row in group.rows if row.slug == SLUG]
    assert len(rows) == 1, f"expected exactly one settings row for {SLUG!r}"
    return rows[0]


def _feature() -> features.Feature:
    feature = features.find_feature(Config(), SLUG)
    assert feature is not None
    return feature


def _load_after(*write_lists) -> dict:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yazses-persian-"))
    path = tmp / "config.toml"
    path.write_text("", encoding="utf-8")
    for writes in write_lists:
        for section, key, value, quote in writes:
            set_config_key(path, section, key, value, quote=quote)
    return dataclasses.asdict(load_config(path))


def test_control_is_in_the_multilingual_group_with_a_label_and_help_text():
    model = build_settings_model(Config())
    groups = [g for g in model.groups if any(r.slug == SLUG for r in g.rows)]
    assert [g.category for g in groups] == [features.CAT_LANG]
    assert "Persian" in _row().label
    # The help text must say what it does and what it does not do.
    note = _feature().why  # the registry's help text; `note` is the config location
    assert "Only applies when [stt] language is Persian" in note
    assert "not a grammar corrector" in note
    assert "Off by default" in note


def test_control_maps_to_the_stt_key_only():
    feature = _feature()
    assert {(s, k) for s, k, *_ in feature.on_writes} == {("stt", "persian_normalisation")}
    assert {(s, k) for s, k, *_ in feature.off_writes} == {("stt", "persian_normalisation")}


def test_control_is_off_by_default_for_a_fresh_and_an_existing_install():
    assert Config().stt.persian_normalisation is False
    assert _row().enabled is False
    assert _row().toggleable is True


def test_switching_it_on_and_off_moves_only_that_key():
    language = [("stt", "language", "fa", True)]
    base = _load_after(language)
    on = _load_after(language, _feature().on_writes)
    assert on["stt"]["persian_normalisation"] is True
    assert {k: v for k, v in on.items() if k != "stt"} == {
        k: v for k, v in base.items() if k != "stt"
    }
    assert {k: v for k, v in on["stt"].items() if k != "persian_normalisation"} == {
        k: v for k, v in base["stt"].items() if k != "persian_normalisation"
    }

    off = _load_after(language, _feature().on_writes, _feature().off_writes)
    assert off["stt"]["persian_normalisation"] is False
    assert off == {**base, "stt": {**base["stt"], "persian_normalisation": False}}


def test_enable_caveat_warns_when_the_language_is_not_persian():
    english = Config()
    english.stt.language = "en"
    advice = features.enable_caveat(SLUG, english)
    assert advice is not None and "not Persian" in advice

    persian = Config()
    persian.stt.language = "fa"
    assert features.enable_caveat(SLUG, persian) is None
