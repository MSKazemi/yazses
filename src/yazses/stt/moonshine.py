"""Moonshine STT engine behind the `SttEngine` seam (#74).

Moonshine is built for short segments on CPU — which is exactly the shape of
hold-to-talk dictation, where a burst is a few seconds and latency is felt
directly. `useful-moonshine-onnx` needs only `onnxruntime` and `tokenizers`: no
torch, no numpy ceiling, so it costs far less to install than the alternatives.

Two properties of the upstream API drive this adapter, both read out of the
published wheel rather than assumed:

* **`transcribe()` returns a batch.** It ends in `decode_batch(tokens)`, so the
  result is a *list* of strings; taking it as a string would silently yield
  `"['hello']"` in the user's document.
* **Audio is passed 1-D, and must be between 0.1 s and 64 s**, both enforced
  with bare `assert`s. The duration bounds are reachable in normal use — a stray
  key tap produces a sub-0.1 s buffer, and a long dictated paragraph passes 64 s
  — and an `AssertionError` escaping into the daemon would look like a crash
  rather than a limit. Short buffers return "" (there is nothing there); long
  ones are **split on the silence gate** and the pieces joined, so a long burst
  degrades in accuracy at the seams rather than failing outright.

  The shape is the subtle half, and this adapter had it backwards. The message
  in upstream's assertion says `[batch, samples]`, but it is checked *after*
  `load_audio` has already done `audio[None, ...]`, so what the **caller** must
  supply is the un-batched array. Passing `(1, N)` yields `(1, 1, N)` and fails
  that assertion for every utterance.

`initial_prompt` is ignored: Moonshine has no prompt conditioning, the same as
Parakeet. Personal vocabulary is recovered afterwards instead — see
`postprocess/vocab_correct.py` (#73), which is engine-agnostic for this reason.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yazses.config import SttConfig
    from yazses.postprocess.prosody import Word

log = logging.getLogger(__name__)

DEFAULT_MODEL = "moonshine/base"

# Upstream's own bounds, asserted inside `transcribe`. Mirrored here so we can
# stay inside them deliberately instead of catching an AssertionError.
MIN_SECONDS = 0.1
MAX_SECONDS = 64.0

_SAMPLE_RATE = 16000


class MoonshineEngine:
    """`SttEngine` implementation over `useful-moonshine-onnx`."""

    def __init__(self, config: "SttConfig") -> None:
        name = (getattr(config, "model", "") or "").strip()
        # `[stt] model` may still hold another engine's checkpoint when the user
        # switches engines; anything that is not a moonshine name is not loadable
        # here, and guessing would fail deep inside onnxruntime.
        self._model_name = name if name.startswith("moonshine/") else DEFAULT_MODEL
        if name and not name.startswith("moonshine/"):
            log.warning(
                "[stt] model %r is not a Moonshine checkpoint — using %r. "
                "Moonshine names look like 'moonshine/tiny' or 'moonshine/base'.",
                name, self._model_name,
            )
        # Imported here, not lazily at first decode, so a missing optional
        # dependency surfaces while `stt/factory.py` can still fall back to
        # faster-whisper. Deferring it would turn an absent package into a failed
        # first dictation instead of a warning at startup — the same reason
        # ParakeetEngine imports in __init__.
        import moonshine_onnx  # noqa: F401

        self._model = None

    # ---- SttEngine -------------------------------------------------------

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = _SAMPLE_RATE,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> str:
        """Decode one burst. `initial_prompt`/`task` are accepted and ignored.

        The signature matches `SttEngine` exactly — including the positional
        `sample_rate` and the `task` the daemon always passes — so the call sites
        need no per-engine branch. Getting this wrong is not a typing nicety: the
        daemon would have raised on an unexpected keyword at the first dictation.
        """
        if initial_prompt:
            log.debug("Moonshine ignores initial_prompt; see vocab_correct (#73).")
        if task and task != "transcribe":
            log.warning("Moonshine cannot %r; transcribing instead.", task)
        return self._decode(audio, sample_rate)

    def transcribe_words(
        self,
        audio: np.ndarray,
        sample_rate: int = _SAMPLE_RATE,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> "tuple[str, list[Word]]":
        """Text plus per-word timings — which Moonshine does not expose.

        Returns an empty word list rather than inventing timings. Callers that
        need them (diarisation alignment, prosody) already treat an empty list as
        "this engine cannot do that" and degrade.
        """
        return self._decode(audio, sample_rate), []

    def decode_window(self, audio: np.ndarray) -> str:
        """Streaming seam — a window is short by construction, so plain decode."""
        return self._decode(audio, _SAMPLE_RATE)

    # ---- internals -------------------------------------------------------

    def _load(self):
        """Load the ONNX model, preferring the local Hugging Face cache.

        `MoonshineOnnxModel` fetches its weights from the hub and, like
        `onnx_asr.load_model`, takes no offline switch -- so without this a fully
        cached model still waits on a hub revalidation round-trip that has **no
        timeout** (`system/hfcache.py` records 1.9 s cached against >180 s not).
        `stt/parakeet.py` has always done this; the constructor form is why the guard
        in `tests/test_model_cache_first.py` did not notice that its sibling did not,
        since that check looked for named loader calls and this is a class call.
        """
        if self._model is None:
            import moonshine_onnx  # lazy: optional dep (`features enable stt-moonshine`)

            from yazses.system.hfcache import load_cache_first

            self._model = load_cache_first(
                lambda: moonshine_onnx.MoonshineOnnxModel(model_name=self._model_name),
                what=f"the Moonshine model {self._model_name!r}",
            )
            log.info("Moonshine model %r loaded.", self._model_name)
        return self._model

    def _decode(self, audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> str:
        if audio is None or len(audio) == 0:
            return ""
        seconds = len(audio) / max(1, int(sample_rate))
        if seconds <= MIN_SECONDS:
            # Below upstream's floor there is nothing to decode; asserting would
            # turn "the user tapped the key" into a traceback.
            return ""
        if seconds >= MAX_SECONDS:
            return self._decode_long(audio, sample_rate)
        return self._decode_one(audio, sample_rate)

    def _decode_one(self, audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> str:
        import moonshine_onnx

        # **1-D on purpose.** Upstream's `transcribe` calls `load_audio`, which ends in
        # `return audio[None, ...]` for anything that is not a path — it adds the batch
        # axis itself, unconditionally. Handing it an already-batched `(1, N)` array
        # produces `(1, 1, N)` and trips the very assertion this used to be shaped
        # around, on every single utterance.
        waveform = np.asarray(audio, dtype=np.float32).reshape(-1)
        result = moonshine_onnx.transcribe(waveform, self._load())
        return _first_text(result)

    def _decode_long(self, audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> str:
        """Split past upstream's 64 s ceiling and join the pieces.

        Cutting on the silence gate rather than on a fixed offset means the seams
        land between utterances instead of mid-word wherever possible.
        """
        from yazses.audio.vad import is_silent

        rate = max(1, int(sample_rate))
        chunk = int((MAX_SECONDS - 4.0) * rate)   # leave headroom
        window = int(0.2 * rate)
        pieces: list[str] = []
        start = 0
        while start < len(audio):
            end = min(start + chunk, len(audio))
            if end < len(audio):
                # Walk back to the quietest window so the cut lands in a pause.
                cut = end
                for probe in range(end, start + chunk // 2, -window):
                    if is_silent(audio[probe - window:probe]):
                        cut = probe
                        break
                end = cut
            text = self._decode_one(audio[start:end], sample_rate)
            if text:
                pieces.append(text)
            start = end
        return " ".join(pieces)


def _first_text(result) -> str:
    """Upstream returns `decode_batch(...)` — a list. Take the first item.

    Treating the list as a string is the bug this exists to prevent: it would put
    a literal `['hello world']`, brackets and quotes included, into the document.
    """
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, (list, tuple)):
        return str(result[0]).strip() if result else ""
    return str(result).strip()
