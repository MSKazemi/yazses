"""Local Voice Timer (ADR-v2-093) + Focus-Class Auto-Profile (ADR-v2-094) — pure cores."""
from __future__ import annotations

from yazses.focusprofile.resolve import classify_focus, resolve_profile
from yazses.voicetimer.parse import format_duration, parse_duration, parse_timer_command


# ---- voice timer -----------------------------------------------------------

def test_parse_duration():
    assert parse_duration("25 minutes") == 25 * 60
    assert parse_duration("2 hours 30 minutes") == 2 * 3600 + 30 * 60
    assert parse_duration("an hour") == 3600
    assert parse_duration("half an hour") == 1800
    assert parse_duration("nothing here") is None


def test_format_duration():
    assert format_duration(3600 + 1800) == "1 hour 30 minutes"
    assert format_duration(25 * 60) == "25 minutes"
    assert format_duration(45) == "45 seconds"
    assert format_duration(0) == "0 seconds"


def test_parse_timer_command():
    assert parse_timer_command("set a timer for 25 minutes") == ("set", 1500)
    assert parse_timer_command("remind me in an hour") == ("set", 3600)
    assert parse_timer_command("cancel the timer") == ("cancel", None)
    assert parse_timer_command("timer") is None            # no duration
    assert parse_timer_command("hello there") is None


# ---- focus-class profile ---------------------------------------------------

def test_classify_focus():
    assert classify_focus("Alacritty") == "terminal"
    assert classify_focus("nvim") == "editor"
    assert classify_focus("firefox") == "browser"
    assert classify_focus("Slack") == "chat"
    assert classify_focus("LibreOffice Writer") == "office"
    assert classify_focus("some-random-app") == "unknown"


def test_resolve_profile_defaults_and_rules():
    assert resolve_profile("bash", "kitty", None) == "shell"
    assert resolve_profile("main.py — nvim", "nvim", None) == "code"
    assert resolve_profile("", "unknownthing", None) is None
    # user rules override the class default
    rules = [("jupyter", "notebook")]
    assert resolve_profile("Untitled - Jupyter", "firefox", rules) == "notebook"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "voicetimer" in slugs and "focusprofile" in slugs
    assert Config().voicetimer.enabled is False and Config().focusprofile.enabled is False
