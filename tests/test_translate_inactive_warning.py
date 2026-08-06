"""Enabling translation that cannot run must say so, not silently transcribe.

`translation_task` correctly returns None for an unsupported combination — but the
*experience* of enabling "translate to French" and getting untranslated French back,
with nothing in the log, is indistinguishable from translation being broken.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from yazses.config import Config, TranslateConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.translate.mode import inactive_reason, translation_task


def _cfg(**kw) -> TranslateConfig:
    return replace(TranslateConfig(), **kw)


# --- pure reason ---------------------------------------------------------------

def test_disabled_translation_has_no_reason_to_report():
    assert inactive_reason(_cfg()) is None


def test_the_working_combination_reports_no_reason():
    cfg = _cfg(enabled=True, backend="whisper", target="en")
    assert translation_task(cfg) == "translate"
    assert inactive_reason(cfg) is None


def test_an_unimplemented_backend_is_named_as_such():
    cfg = _cfg(enabled=True, backend="seamless", target="fr")
    assert translation_task(cfg) is None
    reason = inactive_reason(cfg)
    assert reason is not None
    assert "not implemented in this build" in reason


def test_a_non_english_target_explains_whispers_limit():
    cfg = _cfg(enabled=True, backend="whisper", target="fr")
    assert translation_task(cfg) is None
    reason = inactive_reason(cfg)
    assert reason is not None
    assert "only translate into English" in reason


def test_english_aliases_are_accepted():
    assert inactive_reason(_cfg(enabled=True, target="english")) is None


# --- daemon warn-once ----------------------------------------------------------

def _daemon() -> Daemon:
    return Daemon(config=Config(), platform=get_platform())


def test_warn_feature_inert_logs_once_not_per_burst(caplog):
    d = _daemon()
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            d._warn_feature_inert("translate", "the 'seamless' backend is missing")
    assert len(caplog.records) == 1
    assert "[translate] is enabled but inactive" in caplog.records[0].getMessage()


def test_no_reason_means_no_warning(caplog):
    d = _daemon()
    with caplog.at_level(logging.WARNING):
        d._warn_feature_inert("translate", None)
    assert caplog.records == []


def test_distinct_features_each_get_their_own_warning(caplog):
    d = _daemon()
    with caplog.at_level(logging.WARNING):
        d._warn_feature_inert("translate", "reason a")
        d._warn_feature_inert("denoise", "reason b")
    assert len(caplog.records) == 2
