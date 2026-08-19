"""A capability the config turns on that no code reads must not render as "on".

`features enable` refuses an unwired capability outright, so this state cannot be
*created* today. It can still be *inherited*: `_UNWIRED` did not exist until v2.14,
and before it, first-run seeding wrote every RECOMMENDED slug into `config.toml` --
eight of which are unwired. Any config seeded in that window carries dead keys.

On the maintainer's own machine two of them (`corrdict`, `spelling`) were on, and
every discovery surface agreed they were working:

    │  ● ON   Self-Learning Correction Dictio…  corrdict  planned — designed, not yet wired
    ┌─ Accuracy & correction  (2/20 on)

    ● ON  Self-Learning Correction Dictionary  [corrdict]  (planned — …)
      Designed but not yet wired into this build — it cannot be enabled yet.

The card contradicts itself four lines apart, and the group count claimed two
accuracy capabilities were running when the true number was zero. `features
disable` already explained the case correctly -- which is the surface you would
only run if you already knew.

Both facts live on the same object one field apart (`on`, `wired`); nothing
compared them.
"""
from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from yazses.cli import app
from yazses.config import Config
from yazses.system.features import Feature, feature_status, unwired_slugs

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(result) -> str:
    return _ANSI.sub("", result.output)


def _an_unwired_toggleable_slug() -> str:
    """A real registry slug that is unwired and can be turned on in the config."""
    feats = [f for f in feature_status(Config()) if not f.wired and f.toggleable]
    assert feats, (
        "no unwired toggleable capability left in the registry — every one was "
        "wired up. This whole guard is then obsolete: delete it deliberately "
        "rather than letting it pass on an empty set."
    )
    return feats[0].slug


def _config_with(slug: str) -> Config:
    """A default Config with exactly *slug* turned on, via its own `on_writes`."""
    cfg = Config()
    feat = next(f for f in feature_status(cfg) if f.slug == slug)
    for section, key, value, _quote in feat.on_writes:
        setattr(getattr(cfg, section), key, value == "true")
    return cfg


@pytest.fixture
def _cfg_with_a_dead_key(monkeypatch):
    slug = _an_unwired_toggleable_slug()
    cfg = _config_with(slug)
    assert next(f for f in feature_status(cfg) if f.slug == slug).on, (
        f"{slug} did not read back as on — the fixture set the wrong key, and "
        "every assertion below would then be testing the default config"
    )
    monkeypatch.setattr("yazses.config.load_config", lambda *a, **k: cfg)
    return slug


# --- the pure rule ------------------------------------------------------------

def _feature(*, on: bool, wired: bool) -> Feature:
    return Feature(name="X", on=on, note="", slug="x", tier="optional", wired=wired)


def test_on_and_unwired_is_inert() -> None:
    assert _feature(on=True, wired=False).inert is True


def test_on_and_wired_is_not_inert() -> None:
    assert _feature(on=True, wired=True).inert is False


def test_off_and_unwired_is_not_inert() -> None:
    """Off is off. The unwired half alone must not colour a correct config."""
    assert _feature(on=False, wired=False).inert is False


def test_off_and_wired_is_not_inert() -> None:
    assert _feature(on=False, wired=True).inert is False


def test_a_default_config_has_no_inert_capability() -> None:
    """The shipped defaults must never produce the state this guard describes."""
    inert = [f.slug for f in feature_status(Config()) if f.inert]
    assert inert == [], f"default config turns on unwired capabilities: {inert}"


# --- the list -----------------------------------------------------------------

def test_the_list_does_not_badge_a_dead_key_as_on(_cfg_with_a_dead_key) -> None:
    slug = _cfg_with_a_dead_key
    out = _plain(runner.invoke(app, ["features"]))
    row = next(ln for ln in out.splitlines() if f" {slug} " in ln or ln.endswith(slug))
    assert "◌" in row, f"inert capability rendered without the inert badge: {row!r}"
    assert "● ON" not in row, f"inert capability still claims to be on: {row!r}"


def test_the_group_count_does_not_count_a_dead_key(_cfg_with_a_dead_key) -> None:
    """The header read `(2/20 on)` on a machine where the true number was zero.

    Asserted against the *computed* truth rather than a literal, because the dead
    key's group may also hold genuinely working capabilities. The second assertion
    is the one that does the work: it pins that the naive count -- what the header
    printed before this pass -- is a different number, so a code path that ignored
    `inert` entirely could not still satisfy the first.
    """
    slug = _cfg_with_a_dead_key
    cfg = _config_with(slug)
    feats = feature_status(cfg)
    cat = next(f.category for f in feats if f.slug == slug)
    in_cat = [f for f in feats if f.category == cat]
    truth = sum(1 for f in in_cat if f.on and f.wired)
    naive = sum(1 for f in in_cat if f.on)
    assert naive == truth + 1, (
        "the fixture's dead key is not in this group, so the counts cannot differ "
        "and this test would pass without checking anything"
    )

    out = _plain(runner.invoke(app, ["features"]))
    header = next(ln for ln in out.splitlines() if ln.startswith(f"┌─ {cat}"))
    on_n = int(re.search(r"\((\d+)/\d+ on\)", header).group(1))
    assert on_n == truth, f"inert capability counted as on: {header!r}"


def test_the_legend_explains_the_badge_when_one_is_shown(_cfg_with_a_dead_key) -> None:
    out = _plain(runner.invoke(app, ["features"]))
    assert "◌ =" in out, "a badge appeared with nothing on screen explaining it"
    assert "features disable" in out, "the legend never says how to clear the key"


def test_the_legend_stays_off_a_clean_machine(monkeypatch) -> None:
    """Almost every config is clean; a third glyph in the legend would be noise."""
    monkeypatch.setattr("yazses.config.load_config", lambda *a, **k: Config())
    out = _plain(runner.invoke(app, ["features"]))
    assert "◌" not in out


# --- the info card ------------------------------------------------------------

def test_the_card_does_not_say_on_directly_above_cannot_be_enabled(
    _cfg_with_a_dead_key,
) -> None:
    slug = _cfg_with_a_dead_key
    out = _plain(runner.invoke(app, ["features", "info", slug]))
    assert "cannot be enabled yet" in out, "the card lost its unwired explanation"
    assert not out.startswith("● ON"), f"card still opens with ON: {out.splitlines()[0]!r}"
    assert out.startswith("◌"), f"card lost the inert badge: {out.splitlines()[0]!r}"


def test_the_card_tells_you_how_to_clear_the_dead_key(_cfg_with_a_dead_key) -> None:
    slug = _cfg_with_a_dead_key
    out = _plain(runner.invoke(app, ["features", "info", slug]))
    assert f"yazses features disable {slug}" in out


def test_the_card_stays_quiet_for_an_unwired_capability_that_is_off() -> None:
    """The cleanup advice is about *your config*, not about the capability."""
    slug = _an_unwired_toggleable_slug()
    out = _plain(runner.invoke(app, ["features", "info", slug]))
    assert "cannot be enabled yet" in out
    assert "doing nothing" not in out, "advised clearing a key that is not set"


def test_the_unwired_set_is_not_empty() -> None:
    """Pins the premise: with `_UNWIRED` empty every test above passes vacuously."""
    assert unwired_slugs(), "no unwired capability — see _an_unwired_toggleable_slug"


# --- the Settings window ------------------------------------------------------

def test_the_settings_window_does_not_tick_a_dead_key() -> None:
    """The window rendered a *ticked, greyed-out* box for a capability nothing reads.

    `docs/cli-reference.md` promises the window "is generated from the same feature
    registry as the CLI, so the two can never disagree" — so fixing only the CLI
    would have made that sentence false.
    """
    from yazses.settingsui.model import build_settings_model

    slug = _an_unwired_toggleable_slug()
    rows = [
        r for g in build_settings_model(_config_with(slug)).groups for r in g.rows
        if r.slug == slug
    ]
    assert rows, f"{slug} is not a row in the settings window"
    row = rows[0]
    assert row.enabled is False, "a capability nothing reads is shown as switched on"
    assert row.inert is True, "the row lost the fact that the config key is set"


def test_the_settings_help_names_the_stale_key(monkeypatch) -> None:
    from yazses.settingsui.help import help_text
    from yazses.settingsui.model import build_settings_model

    slug = _an_unwired_toggleable_slug()
    row = next(
        r for g in build_settings_model(_config_with(slug)).groups for r in g.rows
        if r.slug == slug
    )
    text = help_text(row)
    assert "does nothing" in text, f"help does not say the key is dead: {text!r}"
    assert f"yazses features disable {slug}" in text


def test_the_settings_help_stays_quiet_for_an_unwired_row_that_is_off() -> None:
    from yazses.settingsui.help import help_text
    from yazses.settingsui.model import build_settings_model

    slug = _an_unwired_toggleable_slug()
    row = next(
        r for g in build_settings_model(Config()).groups for r in g.rows if r.slug == slug
    )
    assert row.inert is False
    text = help_text(row)
    assert "shown, not offered" in text
    assert "disable" not in text, "advised clearing a key that is not set"


def test_the_on_filter_still_shows_a_dead_key(_cfg_with_a_dead_key) -> None:
    """Pins a decision, not a bug: `--on` asks what your *config* turns on.

    The group tally deliberately excludes an inert capability (nothing is
    happening); `--on` deliberately includes it (your config does say so, and this
    is the view where you would want to find a stale key). Deleting this test is
    the signal that the decision was revisited. Documented in
    `docs/cli-reference.md`.
    """
    slug = _cfg_with_a_dead_key
    out = _plain(runner.invoke(app, ["features", "--on"]))
    assert slug in out, "--on hid a key the config sets"
    row = next(ln for ln in out.splitlines() if slug in ln)
    assert "◌" in row, "--on showed it without the badge that says it does nothing"


def test_the_docs_describe_the_third_badge() -> None:
    """The badge is only honest if the page a reader lands on explains it."""
    from pathlib import Path as _Path

    ref = (_Path(__file__).resolve().parents[1] / "docs" / "cli-reference.md").read_text()
    assert "◌" in ref, "cli-reference.md documents two states for a three-state badge"
    assert "features disable" in ref
