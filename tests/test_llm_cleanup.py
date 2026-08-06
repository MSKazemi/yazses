"""Tests for the offline LLM dictation cleanup (Python path).

Mirrors the Rust engine's guarantees: disabled/missing-backend/empty/guard-fail
all return the input unchanged; only a guard-passing reformat is accepted.
"""
from __future__ import annotations

from yazses.config import DisfluencyConfig
from yazses.postprocess.llm_cleanup import (
    LlmCleaner,
    _critical_tokens,
    _length_ratio_ok,
    _tokens_preserved,
    build_cleaner,
)

# ── guards ──────────────────────────────────────────────────────────────────

def test_length_ratio_rejects_too_short_and_too_long():
    inp = "abcdefghijklmnopqrst"  # 20
    assert _length_ratio_ok(inp, "abcdefghijklmno", 0.5, 2.0)  # 15 ok
    assert not _length_ratio_ok(inp, "abcde", 0.5, 2.0)  # 5 too short
    assert not _length_ratio_ok(inp, "x" * 50, 0.5, 2.0)  # 50 too long


def test_length_ratio_empty_input_passes():
    assert _length_ratio_ok("", "", 0.5, 2.0)
    assert _length_ratio_ok("", "hello", 0.5, 2.0)


def test_critical_tokens_picks_numbers_ids_urls_proper_nouns():
    toks = _critical_tokens("deploy snake_case_fn to https://x.io at 0900 for Acme")
    assert "snake_case_fn" in toks
    assert "https://x.io" in toks
    assert "0900" in toks
    assert "Acme" in toks  # proper noun (uppercase) via _is_protected
    assert "deploy" not in toks


def test_tokens_preserved_detects_drops():
    assert _tokens_preserved("deploy at 0900", "Deploy at 0900.")
    assert not _tokens_preserved("deploy at 0900", "Deploy.")
    assert not _tokens_preserved("call snake_case_fn now", "Call it now.")


# ── cleaner behaviour ─────────────────────────────────────────────────────────

def _enabled_config() -> DisfluencyConfig:
    return DisfluencyConfig(llm_enabled=True, llm_model="", llm_endpoint="")


def test_build_cleaner_none_when_disabled():
    assert build_cleaner(DisfluencyConfig(llm_enabled=False)) is None


def test_build_cleaner_instance_when_enabled():
    assert isinstance(build_cleaner(DisfluencyConfig(llm_enabled=True)), LlmCleaner)


def test_disabled_returns_input():
    cleaner = LlmCleaner(DisfluencyConfig(llm_enabled=False))
    assert cleaner.cleanup("hello world") == "hello world"


def test_empty_input_returns_input():
    cleaner = LlmCleaner(_enabled_config())
    assert cleaner.cleanup("   ") == "   "


def test_no_backend_returns_input():
    # llm_model empty AND llm_endpoint empty → _complete returns None.
    cleaner = LlmCleaner(_enabled_config())
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_happy_path_accepts_reformat(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", return_value="Hello, world.")
    assert cleaner.cleanup("hello world") == "Hello, world."


def test_guard_rejects_dropped_token(mocker):
    cleaner = LlmCleaner(_enabled_config())
    # LLM drops the number "0900" → token guard rejects → input returned.
    mocker.patch.object(cleaner, "_complete", return_value="Deploy to prod.")
    assert cleaner.cleanup("deploy to prod at 0900") == "deploy to prod at 0900"


def test_guard_rejects_runaway_length(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", return_value="x " * 100)
    assert cleaner.cleanup("short input here") == "short input here"


def test_empty_model_output_returns_input(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", return_value="   ")
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_backend_exception_returns_input(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", side_effect=RuntimeError("boom"))
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_missing_local_model_file_disables_local_backend(mocker):
    cfg = DisfluencyConfig(llm_enabled=True, llm_model="/nonexistent/model.gguf", llm_endpoint="")
    cleaner = LlmCleaner(cfg)
    # No file → local backend yields None → cleanup returns input.
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_ollama_backend_used_when_no_local_model(mocker):
    cfg = DisfluencyConfig(llm_enabled=True, llm_model="", llm_endpoint="http://localhost:11434")
    cleaner = LlmCleaner(cfg)
    spy = mocker.patch.object(cleaner, "_complete_ollama", return_value="Clean text at 0900.")
    out = cleaner.cleanup("clean text at 0900")
    assert out == "Clean text at 0900."
    spy.assert_called_once()
