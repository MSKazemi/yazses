from __future__ import annotations

from unittest.mock import patch

from yazses.config import Config, SttConfig
from yazses.system.doctor import _language_profile_checks


def _cfg(stt: SttConfig) -> Config:
    cfg = Config()
    cfg.stt = stt
    return cfg


def test_doctor_reports_default_english_profile_ok():
    rows = _language_profile_checks(_cfg(SttConfig()))

    assert rows == [
        (
            "Language profile",
            "OK",
            "en — English speech; Han-script normalisation off",
        )
    ]


def test_doctor_reports_incoherent_mandarin_with_high_level_fix():
    cfg = _cfg(
        SttConfig(
            model="base.en",
            language="zh",
            chinese_script="simplified",
        )
    )

    rows = _language_profile_checks(cfg)

    assert rows[0][0:2] == ("Language profile", "FAIL")
    assert "English-only" in rows[0][2]
    assert "yazses language set zh-CN" in rows[0][2]


def test_doctor_reports_unpinned_mandarin_script_as_warning():
    cfg = _cfg(SttConfig(model="small", language="zh", chinese_script=""))

    rows = _language_profile_checks(cfg)

    assert rows[0][0:2] == ("Language profile", "WARN")
    assert "zh-CN" in rows[0][2]
    assert "zh-TW" in rows[0][2]


def test_doctor_reports_missing_opencc_as_degraded_not_bricked():
    cfg = _cfg(
        SttConfig(
            model="small",
            language="zh",
            chinese_script="traditional",
        )
    )

    with patch("yazses.system.deps.missing_modules", return_value=["opencc"]):
        rows = _language_profile_checks(cfg)

    assert rows[0][0:2] == ("Language profile", "OK")
    script = next(row for row in rows if row[0] == "Chinese script")
    assert script[1] == "WARN"
    assert "OpenCC is missing" in script[2]
    assert "yazses language set zh-TW" in script[2]


def test_doctor_reports_opencc_ready_but_mandarin_commands_not_yet_wired():
    cfg = _cfg(
        SttConfig(
            model="small",
            language="zh",
            chinese_script="simplified",
        )
    )

    with patch("yazses.system.deps.missing_modules", return_value=[]):
        rows = _language_profile_checks(cfg)

    script = next(row for row in rows if row[0] == "Chinese script")
    commands = next(row for row in rows if row[0] == "Mandarin commands")
    assert script[1] == "OK"
    assert commands[1] == "WARN"
    assert "English-only" in commands[2]


def test_doctor_does_not_claim_profiles_for_unrelated_manual_languages():
    cfg = _cfg(SttConfig(model="small", language="de", chinese_script=""))

    assert _language_profile_checks(cfg) == []


def test_doctor_omits_command_warning_when_commands_are_disabled():
    cfg = _cfg(
        SttConfig(
            model="small",
            language="zh",
            chinese_script="simplified",
        )
    )
    cfg.commands.enabled = False

    with patch("yazses.system.deps.missing_modules", return_value=[]):
        rows = _language_profile_checks(cfg)

    assert not any(row[0] == "Mandarin commands" for row in rows)
