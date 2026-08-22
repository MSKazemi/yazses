"""Tests for learning the silence threshold from outcomes.

The behaviour being protected: hold the key, speak, get text — even when the configured
threshold no longer fits the microphone. The numbers below are the ones the real machine
produced, where a laptop's digital mic array gave mean|audio| of 0.003–0.005 at full gain
against a 0.0024 gate.
"""
from __future__ import annotations

import pytest

from yazses.audio.adaptive_vad import AdaptiveThreshold


def _gate(**kw) -> AdaptiveThreshold:
    return AdaptiveThreshold(**kw)


def test_no_suggestion_before_there_is_evidence():
    """One dropped burst is ordinary — a brushed key, a hold released before speaking."""
    gate = _gate()
    gate.observe_discard(0.0020)
    gate.observe_discard(0.0021)

    assert gate.suggest(current=0.0024) is None


def test_a_run_of_discards_below_the_gate_lowers_it_enough_to_pass():
    """The real failure: speech at 0.0020–0.0023 against a 0.0024 gate, typed nowhere."""
    gate = _gate()
    for level in (0.0020, 0.0022, 0.0023):
        gate.observe_discard(level)

    proposed = gate.suggest(current=0.0024)

    assert proposed is not None
    assert proposed < 0.0020, "must sit below the quietest burst that was being lost"
    assert proposed > 0, "and must remain a real gate"


def test_a_success_clears_the_streak():
    """Working dictation is proof the gate is fine; don't act on stale evidence."""
    gate = _gate()
    gate.observe_discard(0.0020)
    gate.observe_discard(0.0021)
    gate.observe_speech(0.0051)
    gate.observe_discard(0.0022)

    assert gate.suggest(current=0.0024) is None
    assert gate.streak == 1


def test_discards_above_the_gate_are_not_the_gate_s_fault():
    """Same symptom, different cause — a muted mic. Lowering the gate would fix nothing."""
    gate = _gate()
    for _ in range(5):
        gate.observe_discard(0.0090)  # above the gate, so something else rejected these

    assert gate.suggest(current=0.0024) is None


def test_a_dead_microphone_yields_no_suggestion():
    """All-zero audio: there is no threshold that makes silence into speech."""
    gate = _gate()
    for _ in range(5):
        gate.observe_discard(0.0)

    assert gate.suggest(current=0.0024) is None


def test_suggestion_never_goes_below_the_floor():
    """Room tone must not become speech, however quiet the rejected bursts were."""
    gate = _gate(min_threshold=0.0005)
    for _ in range(3):
        gate.observe_discard(0.00001)

    proposed = gate.suggest(current=0.0024)

    assert proposed is None or proposed >= 0.0005


def test_it_only_ever_lowers_the_gate():
    """Raising it is not automated: leaked noise is visible, lost speech is not."""
    gate = _gate()
    for level in (0.0020, 0.0022, 0.0023):
        gate.observe_discard(level)

    proposed = gate.suggest(current=0.0010)

    assert proposed is None, "already below these bursts — nothing to fix here"


def test_the_proposed_gate_would_have_passed_every_lost_burst():
    """The property that matters, stated directly."""
    levels = [0.0031, 0.0028, 0.0035, 0.0029]
    gate = _gate()
    for level in levels:
        gate.observe_discard(level)

    proposed = gate.suggest(current=0.0040)

    assert proposed is not None
    assert all(level > proposed for level in levels)


def test_reset_forgets_everything():
    gate = _gate()
    for level in (0.0020, 0.0021, 0.0022):
        gate.observe_discard(level)
    gate.reset()

    assert gate.streak == 0
    assert gate.suggest(current=0.0024) is None


@pytest.mark.parametrize("min_discards", [2, 3, 5])
def test_the_evidence_bar_is_configurable(min_discards):
    gate = _gate(min_discards=min_discards)
    for _ in range(min_discards - 1):
        gate.observe_discard(0.0020)
    assert gate.suggest(current=0.0024) is None

    gate.observe_discard(0.0020)
    assert gate.suggest(current=0.0024) is not None


# --- the daemon actually acts on it -------------------------------------------------


def test_daemon_persists_a_lowered_threshold_and_says_so(tmp_path, monkeypatch):
    """End to end: three lost bursts → config.toml is rewritten, user is told.

    Persistence is the point. A retune held only in memory would be undone by the next
    restart, so the user would rediscover the same silent failure tomorrow.
    """
    import types

    from yazses.config import Config, load_config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    config_file = tmp_path / "config.toml"
    config_file.write_text("[accessibility]\nvad_threshold = 0.0024\n", encoding="utf-8")

    daemon = Daemon(config=Config(), platform=get_platform())
    daemon._platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=config_file, data_dir=tmp_path),
    )
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        daemon, "_notify_mic", lambda title, body, **kw: notes.append((title, body))
    )

    for level in (0.0020, 0.0022, 0.0023):
        daemon._adaptive_vad.observe_discard(level)
    daemon._maybe_retune_threshold(0.0024)

    written = load_config(config_file).accessibility.vad_threshold
    assert written < 0.0020, "the saved gate must pass the bursts that were being lost"
    assert daemon._config.accessibility.vad_threshold == pytest.approx(written, rel=1e-3)
    assert notes, "a setting that changes itself silently is its own unreliability"


def test_daemon_leaves_the_config_alone_when_the_gate_is_not_at_fault(tmp_path):
    """A muted mic produces the same symptom; rewriting the config would be wrong."""
    import types

    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    config_file = tmp_path / "config.toml"
    original = "[accessibility]\nvad_threshold = 0.0024\n"
    config_file.write_text(original, encoding="utf-8")

    daemon = Daemon(config=Config(), platform=get_platform())
    daemon._platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=config_file, data_dir=tmp_path),
    )

    for _ in range(5):
        daemon._adaptive_vad.observe_discard(0.0)  # dead mic: nothing to hear
    daemon._maybe_retune_threshold(0.0024)

    assert config_file.read_text(encoding="utf-8") == original
