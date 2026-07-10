"""MeetingConfig defaults + TOML load — ADR-v2-127."""
from __future__ import annotations

from yazses.config import Config, MeetingConfig, load_config


def test_meeting_defaults_are_dormant():
    m = MeetingConfig()
    assert m.enabled is False
    assert m.diarize is True            # strategy default (only runs when mode is on)
    assert m.notes is False
    assert m.retain_audio is False
    assert Config().meeting == m


def test_meeting_loads_from_toml(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[meeting]\nenabled = true\nmax_speakers = 4\nretain_audio = true\n"
        "notes = true\nnotes_model = \"/models/phi.gguf\"\n"
    )
    cfg = load_config(cfg_path)
    assert cfg.meeting.enabled is True
    assert cfg.meeting.max_speakers == 4
    assert cfg.meeting.retain_audio is True
    assert cfg.meeting.notes is True
    assert cfg.meeting.notes_model == "/models/phi.gguf"


def test_meeting_config_mirrors_recimport_fields():
    # finalize passes MeetingConfig straight to transcribe_file → it must expose these.
    m = MeetingConfig()
    for field in ("diarize", "backend", "max_speakers", "cluster_threshold", "model",
                  "language", "min_speaker_seconds", "name_threshold", "model_dir"):
        assert hasattr(m, field)
