"""``doctor`` says so when files and meetings would decode as English while dictation is not.

``[recimport] language`` and ``[meeting] language`` default to ``"en"`` and do not inherit
``[stt] language``, so setting only ``[stt] language = "fa"`` left ``yazses transcribe``
decoding Persian speech as English with no error and no warning.
"""

from __future__ import annotations

from yazses.config import Config, MeetingConfig, RecimportConfig, SttConfig
from yazses.system.doctor import _file_language_checks


def _cfg(stt_language: str, recimport: str = "en", meeting: str = "en") -> Config:
    cfg = Config()
    cfg.stt = SttConfig(model="small", language=stt_language)
    cfg.recimport = RecimportConfig(language=recimport)
    cfg.meeting = MeetingConfig(language=meeting)
    return cfg


def test_english_install_sees_nothing() -> None:
    assert _file_language_checks(Config()) == []


def test_persian_dictation_with_default_file_language_warns_for_both() -> None:
    rows = _file_language_checks(_cfg("fa"))
    assert len(rows) == 1 and rows[0][:2] == ("File transcription language", "WARN")
    assert "[recimport] language" in rows[0][2] and "[meeting] language" in rows[0][2]
    assert '"fa"' in rows[0][2]


def test_region_tag_counts_as_the_same_language() -> None:
    assert _file_language_checks(_cfg("fa-IR", recimport="fa", meeting="FA_ir")) == []


def test_only_the_stale_section_is_named() -> None:
    rows = _file_language_checks(_cfg("de", recimport="de", meeting="en"))
    assert "[meeting] language" in rows[0][2] and "[recimport]" not in rows[0][2]


def test_auto_detect_files_are_fine() -> None:
    assert _file_language_checks(_cfg("fa", recimport="", meeting="")) == []


def test_auto_detect_dictation_is_not_judged() -> None:
    assert _file_language_checks(_cfg("")) == []
