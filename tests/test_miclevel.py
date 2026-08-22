import numpy as np

from yazses.system.miclevel import analyze, update_threshold_in_config


def test_analyze_empty_is_silent():
    stats = analyze(np.array([], dtype=np.float32), 16000)
    assert stats.is_silent is True
    assert stats.mean_abs == 0.0
    assert stats.recommended_threshold == 0.002


def test_analyze_speech_recommends_threshold_below_level():
    # Constant 0.06 amplitude → mean_abs 0.06, recommend half of that.
    audio = np.full(16000, 0.06, dtype=np.float32)
    stats = analyze(audio, 16000)
    assert abs(stats.mean_abs - 0.06) < 1e-4
    assert abs(stats.peak - 0.06) < 1e-4
    assert stats.recommended_threshold == 0.03
    assert stats.recommended_threshold < stats.mean_abs   # always passable
    assert stats.is_silent is False
    assert abs(stats.duration_s - 1.0) < 1e-6


def test_analyze_quiet_speech_clamped_to_floor():
    # Very quiet: half would be 0.0015, below the floor → clamp to 0.002.
    audio = np.full(16000, 0.003, dtype=np.float32)
    stats = analyze(audio, 16000)
    assert stats.recommended_threshold == 0.002


def test_update_threshold_replaces_existing_line(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[accessibility]\n# my comment\nvad_threshold = 0.0536\nmin_silence_ms = 500\n", encoding="utf-8")
    update_threshold_in_config(cfg, 0.004)
    text = cfg.read_text(encoding="utf-8")
    assert "vad_threshold = 0.004" in text
    assert "0.0536" not in text
    assert "# my comment" in text          # comments preserved
    assert "min_silence_ms = 500" in text


def test_update_threshold_inserts_under_existing_section(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[accessibility]\nmin_silence_ms = 500\n", encoding="utf-8")
    update_threshold_in_config(cfg, 0.004)
    text = cfg.read_text(encoding="utf-8")
    assert "vad_threshold = 0.004" in text
    assert "min_silence_ms = 500" in text


def test_update_threshold_appends_section_when_missing(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[stt]\nmodel = "base.en"\n', encoding="utf-8")
    update_threshold_in_config(cfg, 0.004)
    text = cfg.read_text(encoding="utf-8")
    assert "[accessibility]" in text
    assert "vad_threshold = 0.004" in text
    assert 'model = "base.en"' in text


def test_update_threshold_creates_file(tmp_path):
    cfg = tmp_path / "sub" / "config.toml"
    update_threshold_in_config(cfg, 0.004)
    assert cfg.exists()
    assert "vad_threshold = 0.004" in cfg.read_text(encoding="utf-8")
