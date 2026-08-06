"""Tests for the Tier 2 SLM intent router (yazses.commands.slm_router).

All tests mock llama-cpp-python; the real library is never required.
"""
from __future__ import annotations

import importlib
import sys

from yazses.commands.grammar import CommandIntent, IntentType

# ---------------------------------------------------------------------------
# Disabled-router tests (no model, no library)
# ---------------------------------------------------------------------------


def test_router_disabled_empty_path():
    """An empty model_path must disable the router; classify always returns None."""
    from yazses.commands.slm_router import SLMRouter

    router = SLMRouter(model_path="", threshold=0.75)
    assert not router.enabled
    assert router.classify("run the tests") is None


def test_router_disabled_missing_file(tmp_path):
    """A non-existent file path must disable the router."""
    from yazses.commands.slm_router import SLMRouter

    nonexistent = str(tmp_path / "does_not_exist.gguf")
    router = SLMRouter(model_path=nonexistent, threshold=0.75)
    assert not router.enabled
    assert router.classify("save file") is None


def test_router_disabled_no_llama_cpp(tmp_path, monkeypatch):
    """When llama_cpp is absent from sys.modules the router must stay disabled."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    # Hide llama_cpp from the import machinery.
    monkeypatch.setitem(sys.modules, "llama_cpp", None)  # type: ignore[call-overload]

    import yazses.commands.slm_router as slm_mod
    importlib.reload(slm_mod)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    assert not router.enabled
    assert router.classify("go to line 42") is None

    # Restore the module to a clean state so other tests are unaffected.
    importlib.reload(slm_mod)


# ---------------------------------------------------------------------------
# Inference tests (model present and "loaded")
# ---------------------------------------------------------------------------


def _build_mock_llama(mocker, response_text: str):
    """Return a (mock_Llama_class, mock_instance) pair that yields response_text."""
    mock_cls = mocker.MagicMock()
    mock_instance = mocker.MagicMock()
    mock_cls.return_value = mock_instance
    mock_instance.create_completion.return_value = {
        "choices": [{"text": response_text}]
    }
    return mock_cls, mock_instance


def _patch_llama(mocker, model_file, mock_cls):
    """Patch sys.modules with a fake llama_cpp, reload the router module, and return it."""
    fake_llama_cpp = mocker.MagicMock()
    fake_llama_cpp.Llama = mock_cls
    mocker.patch.dict("sys.modules", {"llama_cpp": fake_llama_cpp})

    import yazses.commands.slm_router as slm_mod
    importlib.reload(slm_mod)
    return slm_mod


def test_classify_returns_none_below_threshold(tmp_path, mocker):
    """Confidence below threshold must produce None."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    low_conf_json = '{"intent": "terminal", "action": "run_tests", "args": {}, "confidence": 0.50}'
    mock_cls, _ = _build_mock_llama(mocker, low_conf_json)
    slm_mod = _patch_llama(mocker, model_file, mock_cls)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    assert router.enabled
    result = router.classify("run the tests please")
    assert result is None


def test_classify_returns_intent_above_threshold(tmp_path, mocker):
    """Confidence at or above threshold must return a CommandIntent."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    high_conf_json = '{"intent": "terminal", "action": "run_tests", "args": {}, "confidence": 0.95}'
    mock_cls, _ = _build_mock_llama(mocker, high_conf_json)
    slm_mod = _patch_llama(mocker, model_file, mock_cls)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    assert router.enabled

    result = router.classify("run tests please")
    assert result is not None
    assert isinstance(result, CommandIntent)
    assert result.action == "run_tests"
    assert result.intent == IntentType.TERMINAL


def test_classify_returns_none_on_dictate_intent(tmp_path, mocker):
    """When the model returns intent='dictate' the router must return None."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    dictate_json = '{"intent": "dictate", "action": "inject", "args": {}, "confidence": 0.98}'
    mock_cls, _ = _build_mock_llama(mocker, dictate_json)
    slm_mod = _patch_llama(mocker, model_file, mock_cls)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    result = router.classify("hello world")
    assert result is None


def test_classify_returns_none_on_json_parse_error(tmp_path, mocker):
    """Malformed JSON from the model must produce None rather than an exception."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    mock_cls, _ = _build_mock_llama(mocker, "this is NOT json {{{{")
    slm_mod = _patch_llama(mocker, model_file, mock_cls)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    result = router.classify("some utterance")
    assert result is None


def test_classify_catches_model_exception(tmp_path, mocker):
    """An exception raised by the model must be caught and classify must return None."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    mock_cls = mocker.MagicMock()
    mock_instance = mocker.MagicMock()
    mock_cls.return_value = mock_instance
    mock_instance.create_completion.side_effect = RuntimeError("GPU out of memory")

    slm_mod = _patch_llama(mocker, model_file, mock_cls)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    assert router.enabled
    result = router.classify("go to line 99")
    assert result is None


def test_classify_args_forwarded(tmp_path, mocker):
    """Named args from the model JSON must be propagated into CommandIntent.args."""
    model_file = tmp_path / "model.gguf"
    model_file.touch()

    args_json = '{"intent": "navigate", "action": "go_to_line", "args": {"n": "42"}, "confidence": 0.90}'
    mock_cls, _ = _build_mock_llama(mocker, args_json)
    slm_mod = _patch_llama(mocker, model_file, mock_cls)

    router = slm_mod.SLMRouter(str(model_file), threshold=0.75)
    result = router.classify("go to line forty two")
    assert result is not None
    assert result.action == "go_to_line"
    assert result.args == {"n": "42"}
