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

    def make(*, hotwords=False, terms=(), vocab_correction=False, dictionary=()):
        vocab.write_text("\n".join(dictionary) + ("\n" if dictionary else ""), encoding="utf-8")
        cfg = Config()
        cfg.hotwords.enabled = hotwords
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
    assert d.on_writes == (("hotwords", "enabled", "true", False),)
    cfg = Config()
    cfg.hotwords.enabled = True
    assert d.status(cfg) is True


# ---- config loading ----------------------------------------------------------

def test_terms_load_from_toml_and_an_old_boost_key_still_loads(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[hotwords]\nenabled = true\nboost = 3.5\nterms = ["Kubernetes", "Grafana"]\n',
                        encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.hotwords.enabled is True
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
