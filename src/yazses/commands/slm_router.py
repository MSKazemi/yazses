"""Tier 2 SLM intent router — natural-language fallback after Tier 1 regex grammar.

Uses llama-cpp-python (optional) to classify transcripts that the regex grammar
could not match. Disabled automatically when the library is missing or no model
file is configured.

The model's answer is constrained and then re-checked (`commands/slm_schema.py`):
decoding runs under a JSON-schema grammar built from the Tier-1 action table when the
installed binding supports one, and the decoded answer is validated in plain code
either way. Only a known action with in-bounds, user-spoken arguments leaves here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.commands.grammar import CommandIntent, IntentType
from yazses.commands.slm_schema import (
    InvalidRouterOutput,
    output_schema,
    prompt_catalogue,
    validate,
)

if TYPE_CHECKING:
    # Only imported for type hints; real import is deferred to __init__.
    from llama_cpp import Llama  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are a voice command classifier. Classify the utterance as one of the known intents.
Return ONLY valid JSON on one line: {{"intent": "<name>", "action": "<action>", "args": {{}}, "confidence": <0.0-1.0>}}

Known intents: {catalogue}

Examples:
"close this tab" -> {{"intent": "edit", "action": "save", "args": {{}}, "confidence": 0.5}}
"go to line forty two" -> {{"intent": "navigate", "action": "go_to_line", "args": {{"n": 42}}, "confidence": 0.95}}
"run the tests please" -> {{"intent": "terminal", "action": "run_tests", "args": {{}}, "confidence": 0.92}}
"hello world" -> {{"intent": "dictate", "action": "inject", "args": {{}}, "confidence": 0.98}}

Utterance: "{transcript}"
Classification:"""

class SLMRouter:
    """Tier 2 intent classifier backed by a local GGUF language model.

    When disabled (missing library or invalid model path) every call to
    :meth:`classify` returns ``None`` so the caller falls back to the Tier 1
    regex result transparently.
    """

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.75,
        extra_examples: list[str] | None = None,
    ) -> None:
        """Initialise the router.

        Parameters
        ----------
        model_path:
            Absolute or relative path to the GGUF model file.  An empty string
            or a path that does not exist on disk disables the router.
        threshold:
            Minimum confidence score (0–1) that the model must report for its
            classification to be accepted.  Responses below this value cause
            :meth:`classify` to return ``None``.
        extra_examples:
            Additional few-shot example lines (same format as the built-in
            examples) appended to the prompt. Produced by ``yazses tune`` and
            loaded from ``<data_dir>/few_shots.toml``; lets the corpus teach the
            router to stop misfiring on specific utterances.
        """
        self._enabled = False
        self._model: Llama | None = None
        self._threshold = threshold
        self._extra_examples = extra_examples or []
        self._grammar: Any = None

        if not model_path:
            logger.debug("SLMRouter disabled: model_path is empty")
            return

        if not Path(model_path).is_file():
            logger.warning("SLMRouter disabled: model file not found at %r", model_path)
            return

        try:
            from llama_cpp import Llama  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            logger.debug(
                "SLMRouter disabled: llama-cpp-python is not installed "
                "(install it with: pip install llama-cpp-python)"
            )
            return

        try:
            self._model = Llama(model_path=model_path, n_ctx=1024, verbose=False)
            self._enabled = True
            logger.info("SLMRouter loaded model from %r (threshold=%.2f)", model_path, threshold)
        except Exception:
            logger.exception("SLMRouter disabled: failed to load model from %r", model_path)
            return

        self._grammar = _build_grammar()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the router has a working model and will attempt inference."""
        return self._enabled

    @property
    def constrained(self) -> bool:
        """Whether decoding runs under the JSON-schema grammar.

        False on a binding without ``LlamaGrammar.from_json_schema``. Every answer is
        re-validated by `slm_schema.validate` regardless, so this changes how often
        the model's answer is thrown away, never what can be dispatched.
        """
        return self._grammar is not None

    def classify(self, transcript: str, profile: str = "default") -> CommandIntent | None:
        """Attempt to classify *transcript* using the local SLM.

        Parameters
        ----------
        transcript:
            Raw transcribed text that Tier 1 returned as ``DICTATE``.
        profile:
            Editor profile name (passed through for future per-profile
            prompt specialisation; not yet used).

        Returns
        -------
        CommandIntent or None
            ``None`` signals the caller to treat the utterance as plain
            dictation — either because the router is disabled, confidence is
            below threshold, the model output could not be parsed, or the
            model itself classified the text as ``dictate``.
        """
        if not self._enabled or self._model is None:
            return None

        try:
            return self._run_inference(transcript, profile)
        except Exception:
            logger.exception("SLMRouter.classify raised unexpectedly — returning None")
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, transcript: str) -> str:
        # Escape any embedded quotes so the model receives well-formed text.
        safe = transcript.replace('"', '\\"')
        prompt = _PROMPT_TEMPLATE.format(transcript=safe, catalogue=prompt_catalogue())
        if self._extra_examples:
            extra = "\n".join(self._extra_examples) + "\n"
            # Insert learned examples right before the utterance under test.
            prompt = prompt.replace("Utterance:", extra + "Utterance:", 1)
        return prompt

    def _complete(self, prompt: str) -> Any:
        assert self._model is not None
        if self._grammar is not None:
            try:
                # No "\n" stop under the grammar: the grammar ends the object itself,
                # and its whitespace rule may emit a newline mid-object.
                return self._model.create_completion(
                    prompt, max_tokens=128, temperature=0.0, grammar=self._grammar
                )
            except TypeError:
                # A binding whose create_completion predates the grammar keyword.
                logger.info("SLMRouter: this llama-cpp-python does not accept a grammar; "
                            "continuing unconstrained (answers are still re-validated).")
                self._grammar = None
        return self._model.create_completion(
            prompt, max_tokens=128, temperature=0.0, stop=["\n"]
        )

    def _run_inference(self, transcript: str, profile: str) -> CommandIntent | None:  # noqa: ARG002
        assert self._model is not None  # satisfied by enabled guard in classify()

        result: Any = self._complete(self._build_prompt(transcript))

        # llama-cpp-python returns a dict with a 'choices' list.
        try:
            raw_text: str = result["choices"][0]["text"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            logger.debug("SLMRouter: unexpected completion structure (%s): %r", exc, result)
            return None

        logger.debug("SLMRouter raw output: %r", raw_text)

        return self._parse_response(raw_text, transcript)

    def _parse_response(self, raw_text: str, original_transcript: str) -> CommandIntent | None:
        """Decode and re-validate one answer. The grammar is never trusted alone."""
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.debug("SLMRouter: JSON parse error (%s) for response %r", exc, raw_text)
            return None

        try:
            decision = validate(data, original_transcript)
        except InvalidRouterOutput as exc:
            logger.debug("SLMRouter: rejected answer (%s) — treating as dictation", exc)
            return None

        # DICTATE means the model thinks this is plain text; signal the caller
        # to inject it as-is rather than returning a CommandIntent.
        if decision.intent is IntentType.DICTATE:
            logger.debug("SLMRouter: model classified as DICTATE — returning None")
            return None

        if decision.confidence < self._threshold:
            logger.debug(
                "SLMRouter: confidence %.3f below threshold %.3f for action %r — returning None",
                decision.confidence,
                self._threshold,
                decision.action,
            )
            return None

        return CommandIntent(
            intent=decision.intent,
            action=decision.action,
            args=decision.args,
            raw_text=original_transcript,
        )


def _build_grammar() -> Any:
    """The output schema as a llama.cpp sampling grammar, or None.

    ``LlamaGrammar.from_json_schema(json_schema: str)`` converts a JSON Schema to GBNF
    in llama-cpp-python; ``create_completion`` takes it as ``grammar=``. A binding
    without it (or one whose converter rejects the schema) gets no grammar, and
    `slm_schema.validate` still decides every answer.
    """
    try:
        from llama_cpp import LlamaGrammar  # type: ignore[import-untyped]  # noqa: PLC0415

        grammar = LlamaGrammar.from_json_schema(json.dumps(output_schema()), verbose=False)
    except Exception:
        logger.info("SLMRouter: no JSON-schema grammar in this llama-cpp-python; "
                    "decoding unconstrained (answers are still re-validated).",
                    exc_info=True)
        return None
    logger.debug("SLMRouter: decoding under the action-table grammar")
    return grammar
