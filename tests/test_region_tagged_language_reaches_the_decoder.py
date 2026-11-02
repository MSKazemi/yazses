"""``[stt] language = "fa-IR"`` passed the capability check as "fa" and then crashed at decode.

`language/capability.py::normalise_language` folds ``fa-IR`` to ``fa`` before judging the
pairing, so config check and ``doctor`` said "supported". The engine and the file-decoder
settings kept the raw string, and faster-whisper's tokenizer rejects it with ``ValueError``
at the first decode.
"""

from __future__ import annotations

import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.config import MeetingConfig, RecimportConfig, SttConfig
from yazses.stt.decoder_settings import file_decoder_settings


@pytest.mark.parametrize(
    ("configured", "sent"),
    [("fa-IR", "fa"), ("FA_ir", "fa"), ("pt-BR", "pt"), ("zh-TW", "zh"), ("de", "de"), ("", "")],
)
def test_file_settings_fold_region_tags(configured: str, sent: str) -> None:
    for section in (RecimportConfig(language=configured, model="small"),
                    MeetingConfig(language=configured, model="small")):
        assert file_decoder_settings(SttConfig(), section).language == sent


def test_translate_keeps_auto_detect() -> None:
    settings = file_decoder_settings(SttConfig(), RecimportConfig(language="translate", model="small"))
    assert settings.task == "translate" and settings.language == ""


@needs_faster_whisper
def test_engine_sends_the_folded_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from yazses.stt import faster_whisper as fw

    monkeypatch.setattr(fw, "_load_model", lambda *a, **k: object())
    engine = fw.FasterWhisperEngine("small", language="fa-IR")
    assert engine._decode_kwargs(None) == {"language": "fa"}
    assert fw.FasterWhisperEngine("small", language="")._decode_kwargs(None) == {}
