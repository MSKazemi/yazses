"""Built-in vocabulary always primed into Whisper's ``initial_prompt``.

``YazSes`` is a coined word the speech model has never seen in training, so it
mis-transcribes the spoken name ("yes ses", "yaz says", "yacht says", ...).
Whisper's ``initial_prompt`` is preceding *context* — listing the canonical
spelling biases the decoder toward it without forcing it into the output. We keep
the phrase short and neutral so it primes the name without making the model
hallucinate "YazSes" into unrelated speech.

:func:`merge_initial_prompt` is the single place that composes the effective
prompt: any configured/personal vocabulary first, then the built-in phrase
**last**. That order is the opposite of the obvious one and it is the only order
that keeps this module's promise — see :data:`PROMPT_TOKEN_BUDGET`.
"""
from __future__ import annotations

APP_NAME = "YazSes"

# A short natural sentence primes Whisper better than a bare token (it sees the
# word in context and in its canonical capitalisation).
BUILTIN_PROMPT = "The app is called YazSes."

#: How many prompt tokens a Whisper decode actually keeps.
#:
#: ``WhisperModel.max_length`` is 448 and ``get_prompt`` splices the prompt in as
#: ``previous_tokens[-(max_length // 2 - 1):]`` — the **last** 223 tokens. A longer
#: prompt is not rejected and does not warn: the front is silently discarded, and
#: the cut lands mid-word, so the model is handed a fragment.
#:
#: This module used to put the built-in phrase first, which is precisely the
#: position that gets cut. Measured with the real ``base.en`` tokenizer, a personal
#: vocabulary of 120 terms overflows by 25 tokens and takes the whole of
#: "The app is called YazSes." with it — the docstring above said the name was
#: always primed, and for anyone with a substantial vocabulary it had stopped being
#: primed at all, with nothing said.
#:
#: So the built-in phrase goes last. That is also the stronger position for it:
#: ``initial_prompt`` is preceding context, and the tokens nearest the audio carry
#: the most weight. Ordering fixes it for every prompt length and every language
#: without estimating anything — a character or word budget cannot be safe here,
#: because Whisper's English BPE spends up to 8 tokens on a single CJK word and
#: barely 1 on a common English one.
PROMPT_TOKEN_BUDGET = 223


def merge_initial_prompt(*parts: str | None) -> str | None:
    """Compose the effective ``initial_prompt`` from any extra parts (configured
    ``[stt] initial_prompt``, personal vocab) plus the built-in name vocabulary.

    The built-in phrase always comes **last**, so it survives the decoder's
    keep-the-tail truncation (:data:`PROMPT_TOKEN_BUDGET`); blank/``None`` parts
    are dropped. Always returns a non-empty string (the built-in name is always
    present), so callers never get ``None`` — but the signature mirrors the
    optional prompts they pass in.
    """
    chunks: list[str] = [part.strip() for part in parts if part and part.strip()]
    chunks.append(BUILTIN_PROMPT)
    merged = " ".join(chunks).strip()
    return merged or None
