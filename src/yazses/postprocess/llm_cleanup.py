"""Offline LLM reformatting of dictated text — Python-path counterpart of the
Rust v1.0 ``[cleanup]`` engine (see ``crates/yazses-llm/src/cleanup.rs``).

Runs *after* the deterministic disfluency filter and *before* injection. It is
fully optional and OFF by default (honours ADR-011: no behaviour change unless
``[filters.disfluency] llm_enabled`` is set). Two backends, resolved lazily:

1. **Local GGUF** via ``llama-cpp-python`` when ``llm_model`` points at a file
   (the offline-first path, mirroring :class:`~yazses.commands.slm_router.SLMRouter`).
2. **Ollama HTTP** at ``llm_endpoint`` via the standard library (no extra dep)
   when no local model is configured.

Every call returns the input text unchanged on: disabled, missing backend,
empty input, timeout, backend error, or a failed output guard. The guards
(length-ratio + critical-token preservation) match the Rust engine so the two
paths reject the same hallucinations.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import _is_protected

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from llama_cpp import Llama  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output guards (parity with crates/yazses-llm/src/cleanup.rs)
# ---------------------------------------------------------------------------

def _length_ratio_ok(input_text: str, output: str, min_ratio: float, max_ratio: float) -> bool:
    """True if ``len(output)`` is within ``[min, max] × len(input)``.

    Empty input always passes (nothing to compare).
    """
    inlen = len(input_text)
    if inlen == 0:
        return True
    ratio = len(output) / inlen
    return min_ratio <= ratio <= max_ratio


def _critical_tokens(text: str) -> list[str]:
    """Tokens that must survive reformatting: anything a proper noun / code id.

    Reuses the disfluency filter's :func:`_is_protected` heuristic (uppercase,
    underscore, slash, dot) plus any token containing a digit, so the two
    offline passes agree on what is meaning-critical.
    """
    out: list[str] = []
    for raw in text.split():
        tok = raw.strip(",;:!?")
        if not tok:
            continue
        if _is_protected(tok) or any(c.isdigit() for c in tok):
            out.append(tok)
    return out


def _tokens_preserved(input_text: str, output: str) -> bool:
    """True if every critical token from the input appears in the output."""
    return all(tok in output for tok in _critical_tokens(input_text))


# ---------------------------------------------------------------------------
# Cleaner
# ---------------------------------------------------------------------------

class LlmCleaner:
    """Reformats dictated text with a local or Ollama-backed LLM.

    Construction is cheap and never raises; backend resolution is deferred to
    the first :meth:`cleanup` call so a missing model only disables the feature.
    """

    def __init__(self, config: DisfluencyConfig) -> None:
        self._config = config
        self._enabled = config.llm_enabled
        self._model: Llama | None = None
        self._model_tried = False

    @property
    def enabled(self) -> bool:
        """Whether cleanup will attempt a reformat (master switch only)."""
        return self._enabled

    def cleanup(self, text: str, custom_prompt: str | None = None) -> str:
        """Reformat *text*; return it unchanged on any failure or guard rejection."""
        if not self._enabled or not text.strip():
            return text

        try:
            cleaned = self._complete(text, custom_prompt)
        except Exception:  # never let cleanup break the dictation pipeline
            logger.exception("LLM cleanup raised unexpectedly — returning input")
            return text

        if cleaned is None:
            return text
        cleaned = cleaned.strip()

        if (
            not cleaned
            or not _length_ratio_ok(
                text, cleaned, self._config.llm_min_length_ratio, self._config.llm_max_length_ratio
            )
            or not _tokens_preserved(text, cleaned)
        ):
            logger.debug("LLM cleanup output rejected by guards — returning input")
            return text
        return cleaned

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _complete(self, text: str, custom_prompt: str | None) -> str | None:
        """Run the configured backend; ``None`` means 'no usable backend'."""
        if self._config.llm_model:
            return self._complete_local(text, custom_prompt)
        if self._config.llm_endpoint:
            return self._complete_ollama(text, custom_prompt)
        return None

    def _prompt(self, text: str, custom_prompt: str | None) -> str:
        prompt = custom_prompt if custom_prompt is not None else self._config.llm_system_prompt
        return f"{prompt}\n\nText:\n{text}\n\nReformatted:"

    def _complete_local(self, text: str, custom_prompt: str | None) -> str | None:
        model = self._load_local_model()
        if model is None:
            return None
        result: Any = model.create_completion(
            self._prompt(text, custom_prompt),
            max_tokens=self._config.llm_max_tokens,
            temperature=0.0,
        )
        try:
            return str(result["choices"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:
            logger.debug("LLM cleanup: unexpected completion structure (%s)", exc)
            return None

    def _load_local_model(self) -> Llama | None:
        if self._model is not None:
            return self._model
        if self._model_tried:
            return None
        self._model_tried = True

        if not Path(self._config.llm_model).is_file():
            logger.warning("LLM cleanup disabled: model file not found at %r", self._config.llm_model)
            return None
        try:
            from llama_cpp import Llama  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            logger.debug("LLM cleanup local backend unavailable: llama-cpp-python not installed")
            return None
        try:
            self._model = Llama(model_path=self._config.llm_model, n_ctx=2048, verbose=False)
            logger.info("LLM cleanup loaded local model from %r", self._config.llm_model)
        except Exception:
            logger.exception("LLM cleanup disabled: failed to load model from %r", self._config.llm_model)
            return None
        return self._model

    def _complete_ollama(self, text: str, custom_prompt: str | None) -> str | None:
        payload = json.dumps(
            {
                "model": "qwen2.5:1.5b",
                "prompt": self._prompt(text, custom_prompt),
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": self._config.llm_max_tokens},
            }
        ).encode()
        url = self._config.llm_endpoint.rstrip("/") + "/api/generate"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        timeout_s = max(0.1, self._config.llm_timeout_ms / 1000.0)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - localhost only
                body = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.debug("LLM cleanup Ollama backend unavailable (%s)", exc)
            return None
        response = body.get("response")
        return str(response) if isinstance(response, str) else None


def build_cleaner(config: DisfluencyConfig) -> LlmCleaner | None:
    """Return an :class:`LlmCleaner`, or ``None`` when cleanup is disabled.

    Mirrors ``learning.capture.build_writer`` so the daemon can keep the
    feature fully dormant by holding ``None``.
    """
    if not config.llm_enabled:
        return None
    return LlmCleaner(config)
