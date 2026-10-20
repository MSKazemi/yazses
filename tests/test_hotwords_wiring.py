"""`hotwords` folded into guarded vocabulary correction (ADR-v2-069 "Wiring", #164).

The N-best rescorer had no producer (faster-whisper exposes no N-best list), so `[hotwords]`
became a second switch and a second term source for `postprocess/vocab_correct.py`. Decisions
under test: off means byte-identical and imports nothing new; on means the existing guarded
corrector runs, with `[hotwords] terms` added; no new rewriting rule exists, so the no-damage
direction is checked against ordinary prose.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from yazses.config import Config, load_config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.postprocess.hotwords import merge_terms
from yazses.system import features
from yazses.system.features import _UNWIRED, default_enabled_slugs, feature_status

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def daemon_factory(monkeypatch, tmp_path):
    """Build a Daemon whose personal dictionary is a sandboxed file, never the host's."""
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    vocab = tmp_path / "vocabulary.txt"
    monkeypatch.setattr("yazses.system.vocabulary.vocab_path", lambda _d: vocab)

    def make(*, hotwords=False, terms=(), vocab_correction=False, dictionary=(), opted_in=None):
        vocab.write_text("\n".join(dictionary) + ("\n" if dictionary else ""), encoding="utf-8")
        cfg = Config()
        cfg.hotwords.enabled = hotwords
        # A deliberate enable writes both keys; `opted_in=False` builds the stale seeded shape.
        cfg.hotwords.opted_in = hotwords if opted_in is None else opted_in
        cfg.hotwords.terms = list(terms)
        cfg.stt.vocab_correction = vocab_correction
        return Daemon(config=cfg, platform=get_platform())

    return make


MISHEARD = "deploy it to cubernetties today"
FIXED = "deploy it to Kubernetes today"


# ---- the switch -------------------------------------------------------------

def test_off_by_default_and_text_is_returned_untouched(daemon_factory):
    assert Config().hotwords.enabled is False and Config().hotwords.terms == []
    d = daemon_factory(dictionary=["Kubernetes"])
    event: dict = {}
    assert d._correct_vocabulary(MISHEARD, event) == MISHEARD
    assert event == {}


def test_hotwords_on_corrects_from_the_personal_dictionary(daemon_factory):
    d = daemon_factory(hotwords=True, dictionary=["Kubernetes"])
    event: dict = {}
    assert d._correct_vocabulary(MISHEARD, event) == FIXED
    assert event["vocab_corrections"] == [("cubernetties", "Kubernetes")]


def test_config_terms_extend_the_dictionary(daemon_factory):
    d = daemon_factory(hotwords=True, terms=["Kubernetes"])
    assert d._correct_vocabulary(MISHEARD, {}) == FIXED


def test_config_terms_are_ignored_while_hotwords_is_off(daemon_factory):
    # Only the switch that owns the key may read it: vocab_correction alone must not
    # start correcting toward words the user listed under a disabled feature.
    d = daemon_factory(hotwords=False, vocab_correction=True, terms=["Kubernetes"])
    assert d._correct_vocabulary(MISHEARD, {}) == MISHEARD


def test_the_existing_switch_is_unchanged(daemon_factory):
    d = daemon_factory(vocab_correction=True, dictionary=["Kubernetes"])
    assert d._correct_vocabulary(MISHEARD, {}) == FIXED


def test_a_broken_terms_value_cannot_stop_dictation(daemon_factory):
    d = daemon_factory(hotwords=True, dictionary=["Kubernetes"])
    d._config.hotwords.terms = [None, 7, "", "  "]          # a hand-edited config
    assert d._correct_vocabulary(MISHEARD, {}) == FIXED


# ---- the no-damage direction (AGENTS rule 9) -------------------------------

def test_ordinary_prose_is_never_rewritten(daemon_factory):
    """Run the corrector over this repo's own prose with a realistic hotword list.

    A guard that fires on ordinary speech teaches people to dismiss it. The four guards
    in vocab_correct are the only ones; this proves they hold for the words a user is
    most likely to list, on a few thousand words of real English.
    """
    corpus = " ".join(
        (REPO / name).read_text(encoding="utf-8")
        for name in ("docs/how-to/performance-tuning.md", "docs/models.md", "docs/architecture.md")
    )
    assert len(corpus.split()) > 2000
    d = daemon_factory(hotwords=True, terms=["Kubernetes", "Grafana", "PostgreSQL", "Ardebili",
                                             "Terraform", "Prometheus"])
    event: dict = {}
    assert d._correct_vocabulary(corpus, event) == corpus
    assert "vocab_corrections" not in event


def test_a_correct_transcript_is_a_fixed_point(daemon_factory):
    d = daemon_factory(hotwords=True, dictionary=["Kubernetes"])
    assert d._correct_vocabulary(FIXED, {}) == FIXED


# ---- the pure merge ----------------------------------------------------------

def test_merge_terms_keeps_first_spelling_and_drops_blanks():
    assert merge_terms(["Kubernetes", "YazSes"], ["kubernetes", " Grafana ", "", "  "]) == [
        "Kubernetes", "YazSes", "Grafana"]


def test_merge_terms_drops_non_strings_instead_of_raising():
    assert merge_terms([], [None, 3, "x" * 5]) == ["xxxxx"]
    assert merge_terms([], []) == []


# ---- registry honesty --------------------------------------------------------

def test_hotwords_is_wired_and_not_seeded_on_first_run():
    assert "hotwords" not in _UNWIRED
    assert "hotwords" not in default_enabled_slugs()      # a fresh install must not enable it
    row = next(f for f in feature_status(Config()) if f.slug == "hotwords")
    assert row.wired is True and row.on is False and row.name == "Hotwords"
    assert "not yet wired" not in row.tier_label


def test_the_slug_maps_to_the_package_the_daemon_really_uses():
    assert features.feature_packages("hotwords") == ("postprocess",)


def test_enabling_writes_the_key_the_daemon_reads():
    d = next(d for d in features._registry() if d.slug == "hotwords")
    assert d.on_writes == (("hotwords", "enabled", "true", False),
                           ("hotwords", "opted_in", "true", False))
    assert d.off_writes == (("hotwords", "enabled", "false", False),
                            ("hotwords", "opted_in", "false", False))
    cfg = Config()
    cfg.hotwords.enabled = True
    cfg.hotwords.opted_in = True
    assert d.status(cfg) is True


# ---- config loading ----------------------------------------------------------

def test_terms_load_from_toml_and_an_old_boost_key_still_loads(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[hotwords]\nenabled = true\nboost = 3.5\nterms = ["Kubernetes", "Grafana"]\n',
                        encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.hotwords.enabled is True
    assert cfg.hotwords.opted_in is False       # no opt-in in this file: loaded, not active
    assert cfg.hotwords.terms == ["Kubernetes", "Grafana"]
    assert cfg.hotwords.boost == 3.5            # retired but tolerated


# ---- zero cost when off ------------------------------------------------------

def test_a_default_start_imports_neither_the_adapter_nor_the_retired_package():
    probe = ("import json, sys\n"
             "import yazses.cli, yazses.core.daemon, yazses.config, yazses.main\n"
             "print(json.dumps(sorted(sys.modules)))\n")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         timeout=120, check=True, encoding="utf-8")
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    assert "yazses.postprocess.hotwords" not in loaded
    assert not [m for m in loaded if m == "yazses.biasing" or m.startswith("yazses.biasing.")]


# ---- the fresh opt-in: a seeded `enabled = true` is not a choice --------------
#
# First-run setup in v2.11.0-dev.9 through v2.13.0 wrote every recommended slug into a
# new config, wired or not, and hotwords was recommended then (the unwired exclusion in
# `default_enabled_writes` arrived in 79bb05a1, first released in v2.14.0). Those configs
# say `[hotwords] enabled = true`. Owner decision: nobody gets vocabulary correction
# silently, so that line alone must stay inert; only the current enable paths, which also
# write `opted_in = true`, switch it on.

#: Exactly what the old seeding left behind for this section.
SEEDED = "# YazSes configuration (created on first run).\n[hotwords]\nenabled = true\n"


def _seeded_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SEEDED, encoding="utf-8")
    return path


def test_a_seeded_enabled_true_does_not_activate_hotwords(tmp_path, daemon_factory):
    cfg = load_config(_seeded_config(tmp_path / "config.toml"))
    assert cfg.hotwords.enabled is True and cfg.hotwords.active is False
    assert cfg.hotwords.stale_enabled is True
    row = next(f for f in feature_status(cfg) if f.slug == "hotwords")
    assert row.on is False                       # every surface reads it as off

    d = daemon_factory(hotwords=True, opted_in=False, dictionary=["Kubernetes"],
                       terms=["Grafana"])
    event: dict = {}
    assert d._correct_vocabulary(MISHEARD, event) == MISHEARD
    assert event == {}
    assert "Grafana" not in d._vocabulary_terms()     # terms are not read either


def test_a_seeded_line_does_not_change_the_other_switch(daemon_factory):
    # `[stt] vocab_correction` is its own switch and keeps working as before.
    d = daemon_factory(hotwords=True, opted_in=False, vocab_correction=True,
                       dictionary=["Kubernetes"])
    assert d._correct_vocabulary(MISHEARD, {}) == FIXED


def test_the_opt_in_alone_activates_nothing(daemon_factory):
    d = daemon_factory(hotwords=False, opted_in=True, dictionary=["Kubernetes"])
    assert d._config.hotwords.active is False
    assert d._correct_vocabulary(MISHEARD, {}) == MISHEARD


def test_features_enable_activates_a_seeded_config(sandbox_paths):
    from typer.testing import CliRunner

    from yazses.cli import app

    cfg_file = _seeded_config(sandbox_paths.config_file)
    runner = CliRunner()
    result = runner.invoke(app, ["features", "enable", "hotwords", "--no-install"])
    assert result.exit_code == 0, result.output
    cfg = load_config(cfg_file)
    assert cfg.hotwords.active is True
    assert next(f for f in feature_status(cfg) if f.slug == "hotwords").on is True

    result = runner.invoke(app, ["features", "disable", "hotwords"])
    assert result.exit_code == 0, result.output
    cfg = load_config(cfg_file)
    assert cfg.hotwords.active is False and cfg.hotwords.stale_enabled is False


def test_the_settings_toggle_activates_a_seeded_config(tmp_path):
    from yazses.settingsui.controller import SettingsController
    from yazses.system.configedit import set_config_key

    cfg_file = _seeded_config(tmp_path / "config.toml")
    ctrl = SettingsController(
        lambda: load_config(cfg_file),
        lambda section, key, value, quote: set_config_key(cfg_file, section, key, value,
                                                          quote=quote),
        lambda modules: [],
    )
    assert ctrl.set_enabled("hotwords", True).ok is True
    assert load_config(cfg_file).hotwords.active is True


def test_a_fresh_install_stays_off(tmp_path):
    from yazses.system.firstrun import ensure_recommended_config

    assert Config().hotwords.active is False
    cfg_file = tmp_path / "config.toml"
    assert ensure_recommended_config(cfg_file) is True
    text = cfg_file.read_text(encoding="utf-8")
    assert "opted_in" not in text
    cfg = load_config(cfg_file)
    assert cfg.hotwords.active is False and cfg.hotwords.stale_enabled is False
    assert not [w for w in features.default_enabled_writes() if w[0] == "hotwords"]
    assert features.default_state()["hotwords"] is False


def test_reset_leaves_a_seeded_line_alone(tmp_path):
    # It already reads as off, which is the default, so a reset has nothing to write.
    cfg = load_config(_seeded_config(tmp_path / "config.toml"))
    assert "hotwords" not in [f.slug for f, _ in features.default_drift(cfg)]


# ---- saying why: doctor and the features surfaces ------------------------------

def test_doctor_explains_a_seeded_line_and_names_the_command(tmp_path):
    from yazses.system.doctor import _hotwords_optin_check

    row = _hotwords_optin_check(load_config(_seeded_config(tmp_path / "config.toml")))
    assert row is not None
    name, status, detail = row
    assert name == "Hotwords"
    assert status == "SKIP"           # informational: it must not turn the verdict yellow
    assert "[hotwords] enabled = true" in detail and "not active" in detail
    assert "yazses features enable hotwords" in detail


def test_doctor_is_silent_for_every_other_config():
    from yazses.system.doctor import _hotwords_optin_check

    assert _hotwords_optin_check(Config()) is None
    cfg = Config()
    cfg.hotwords.enabled = cfg.hotwords.opted_in = True
    assert _hotwords_optin_check(cfg) is None
    cfg = Config()
    cfg.hotwords.opted_in = True
    assert _hotwords_optin_check(cfg) is None


def test_the_doctor_run_prints_the_row(sandbox_paths, monkeypatch, capsys):
    """The row must reach the real `run_doctor` output, not only exist as a function."""
    from yazses.system import doctor

    _seeded_config(sandbox_paths.config_file)
    seen: list = []
    real = doctor._format_check

    def spy(name, status, detail):
        seen.append((name.strip(), status))
        return real(name, status, detail)

    monkeypatch.setattr(doctor, "_format_check", spy)
    try:
        doctor.run_doctor(check_mic=False)
    except SystemExit:
        pass
    assert ("Hotwords", "SKIP") in seen
    assert "yazses features enable hotwords" in capsys.readouterr().out


def test_features_info_and_the_list_say_why(sandbox_paths):
    from typer.testing import CliRunner

    from yazses.cli import app

    _seeded_config(sandbox_paths.config_file)
    runner = CliRunner()
    info = runner.invoke(app, ["features", "info", "hotwords"])
    assert info.exit_code == 0, info.output
    assert "not active" in info.output and "yazses features enable hotwords" in info.output
    listing = runner.invoke(app, ["features", "--category", "accuracy"])
    assert listing.exit_code == 0, listing.output
    assert "[hotwords] enabled = true" in listing.output


def test_the_features_surfaces_say_nothing_extra_on_a_clean_config(sandbox_paths):
    from typer.testing import CliRunner

    from yazses.cli import app

    runner = CliRunner()
    info = runner.invoke(app, ["features", "info", "hotwords"])
    assert info.exit_code == 0, info.output
    assert "not active" not in info.output
    assert features.inactive_reason("hotwords", Config()) == ""
    assert features.inactive_reason("streaming", Config()) == ""
