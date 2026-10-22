"""Predictive completion — the local llama.cpp generator (backend) — ADR-v2-016.

The heavy half of the feature, kept apart from the pure lifecycle in
``predict/session.py``. It reuses the llama.cpp runtime the LLM-cleanup path
(ADR-013), the SLM command router and Meeting notes already load — the
``llama-cpp-python`` package of the ``slm`` extra — so the feature adds no
dependency. ``llama_cpp`` is imported only inside :meth:`LlamaCompleter._load`, on
the worker thread, the first time a completion is asked for: enabling the feature
costs nothing at daemon start, and a missing model or package leaves it dormant.

The model only ever sees text this machine already typed; nothing is sent anywhere
(ADR-011, ADR-019 — there is no network primitive in this module).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: llama.cpp context window. The prompt is at most ``session.MAX_CONTEXT_CHARS``
#: characters (~100 tokens) plus ``[predict] max_tokens``, so this is ample.
_N_CTX = 512


def _have_llama() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        return False


def dormant_reason(
    model_path: str,
    *,
    have_llama: bool | None = None,
    model_exists: bool | None = None,
) -> str | None:
    """Why predictive completion cannot run, or ``None`` when it can. Pure with probes.

    Ordered by what the user has to do first, as ``meeting/notes.py`` orders the same
    three checks: a key to set, a package to install, a path to fix. ``find_spec``
    rather than an import, because importing llama_cpp loads native code and costs
    seconds — far too much for a question asked on the dictation path.
    """
    path = (model_path or "").strip()
    if not path:
        return "`[predict] model_path` is empty; point it at a local GGUF completion model"
    if have_llama is None:
        have_llama = _have_llama()
    if not have_llama:
        return "it needs llama-cpp-python, which is not installed"
    if model_exists is None:
        model_exists = Path(path).expanduser().is_file()
    if not model_exists:
        return f"`[predict] model_path` points at {path!r}, which is not a file"
    return None


class LlamaCompleter:
    """Continue a piece of dictated text with a local GGUF model.

    Construction is cheap and never raises. The model loads on the first
    :meth:`complete` call (which the daemon makes on a background thread), and a load
    failure is logged once and turns every later call into ``""``.

    ``factory`` builds the model from a path; it exists so tests never touch
    llama.cpp. Calls are serialised: one llama.cpp context is not thread-safe.
    """

    def __init__(
        self,
        model_path: str,
        max_tokens: int,
        *,
        factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._model_path = str(Path((model_path or "").strip()).expanduser())
        self._max_tokens = max(1, int(max_tokens or 1))
        self._factory = factory
        self._model: Any = None
        self._failed = False
        self._lock = threading.Lock()

    @property
    def failed(self) -> bool:
        """True once the model could not be loaded; the completer is then inert."""
        return self._failed

    def _load(self) -> Any:
        if self._model is not None or self._failed:
            return self._model
        try:
            factory = self._factory
            if factory is None:
                from llama_cpp import Llama  # type: ignore[import-untyped]  # noqa: PLC0415

                def _build(path: str) -> Any:
                    return Llama(model_path=path, n_ctx=_N_CTX, verbose=False)

                factory = _build
            self._model = factory(self._model_path)
            log.info("Predictive completion: loaded the local model from %r.", self._model_path)
        except Exception:
            self._failed = True
            log.warning(
                "Predictive completion: could not load the model at %r; no suggestions "
                "will be offered until the daemon restarts.",
                self._model_path,
                exc_info=True,
            )
        return self._model

    def complete(self, context: str) -> str:
        """The model's raw continuation of *context*, or ``""``. Never raises.

        Greedy (temperature 0) and stopped at the first newline: a suggestion is the
        rest of a line, and the same text should get the same offer twice.
        """
        prompt = (context or "").rstrip()
        if not prompt:
            return ""
        with self._lock:
            model = self._load()
            if model is None:
                return ""
            try:
                result: Any = model.create_completion(
                    prompt,
                    max_tokens=self._max_tokens,
                    temperature=0.0,
                    stop=["\n"],
                )
                return str(result["choices"][0]["text"])
            except Exception as exc:
                # The type only: an exception message from a generation call is not
                # something to put in a log a user may share.
                log.warning(
                    "Predictive completion: generation failed (%s); no suggestion.",
                    type(exc).__name__,
                )
                log.debug("Predictive completion failure", exc_info=True)
                return ""
