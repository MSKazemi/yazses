"""Pure settings-window model (no Qt)."""
from yazses.config import Config
from yazses.settingsui.model import build_settings_model
from yazses.system.features import grouped_features


def _rows():
    model = build_settings_model(Config())
    return [row for group in model.groups for row in group.rows]


def test_matches_yazses_features_groups_and_order():
    model = build_settings_model(Config())
    expected = grouped_features(Config())
    assert [g.category for g in model.groups] == [c for c, _, _ in expected]
    assert [g.blurb for g in model.groups] == [b for _, b, _ in expected]
    for group, (_, _, feats) in zip(model.groups, expected):
        assert [row.slug for row in group.rows] == [f.slug for f in feats]


def test_row_reflects_live_config_state():
    rows = {r.slug: r for r in _rows()}
    commands = rows["commands"]
    assert commands.enabled is True  # DEFAULT_ON
    assert commands.toggleable is True
    cocktail = rows["cocktail"]
    assert cocktail.enabled is False
    assert cocktail.toggleable is True


def test_core_feature_is_not_toggleable():
    rows = {r.slug: r for r in _rows()}
    dictation = rows["dictation"]
    assert dictation.toggleable is False


def test_unwired_feature_is_not_toggleable_even_though_it_has_writes():
    rows = {r.slug: r for r in _rows()}
    # "reask" is designed (has on_writes) but listed in features._UNWIRED — a
    # settings toggle for it would silently write a key nothing reads.
    reask = rows["reask"]
    assert reask.toggleable is False


def test_experimental_flag_matches_tier():
    rows = {r.slug: r for r in _rows()}
    assert rows["cocktail"].experimental is True
    assert rows["commands"].experimental is False


def test_tier_label_is_the_same_string_features_shows():
    from yazses.system.features import find_feature

    feat = find_feature(Config(), "commands")
    rows = {r.slug: r for r in _rows()}
    assert rows["commands"].tier_label == feat.tier_label


# --- help material carried onto each row ------------------------------------


def test_rows_carry_the_same_help_material_features_info_prints():
    from yazses.system.features import find_feature

    feat = find_feature(Config(), "meeting")
    row = {r.slug: r for r in _rows()}["meeting"]
    assert row.why == feat.why
    assert row.use_case == feat.use_case
    assert row.example == feat.example
    assert row.note == feat.note
    assert row.on_writes == feat.on_writes
    assert row.packages == tuple(feat.pip_packages)


def test_every_toggleable_row_knows_what_it_writes():
    for row in _rows():
        if row.toggleable:
            assert row.on_writes, f"{row.slug} cannot say what enabling it changes"


def test_rows_know_their_shipped_default():
    rows = {r.slug: r for r in _rows()}
    assert rows["commands"].default_enabled is True     # ships on
    assert rows["streaming"].default_enabled is False   # opt-in
    assert rows["dictation"].default_enabled is None    # not a switch at all
    assert rows["reask"].default_enabled is None        # designed, not wired


def test_the_model_carries_the_defaults_a_reset_targets():
    from yazses.system.features import default_state

    model = build_settings_model(Config())
    assert model.defaults == default_state()
    assert set(model.defaults) <= {row.slug for row in model.rows()}
