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
* **Audio must be 2-D and between 0.1 s and 64 s**, enforced with bare
  `assert`s. Both bounds are reachable in normal use — a stray key tap produces
  a sub-0.1 s buffer, and a long dictated paragraph passes 64 s — and an
  `AssertionError` escaping into the daemon would look like a crash rather than
  a limit. Short buffers return "" (there is nothing there); long ones are
  **split on the silence gate** and the pieces joined, so a long burst degrades
  in accuracy at the seams rather than failing outright.

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
        *,
        initial_prompt: str | None = None,
        language: str | None = None,
    ) -> str:
        """Decode one burst. `initial_prompt`/`language` are not supported."""
        if initial_prompt:
            log.debug("Moonshine ignores initial_prompt; see vocab_correct (#73).")
        return self._decode(audio)

    def transcribe_words(
        self,
        audio: np.ndarray,
        *,
        initial_prompt: str | None = None,
        language: str | None = None,
    ) -> tuple[str, list["Word"]]:
        """Text plus per-word timings — which Moonshine does not expose.

        Returns an empty word list rather than inventing timings. Callers that
        need them (diarisation alignment, prosody) already treat an empty list as
        "this engine cannot do that" and degrade.
        """
        return self._decode(audio), []

    def decode_window(self, audio: np.ndarray) -> str:
        """Streaming seam — a window is short by construction, so plain decode."""
        return self._decode(audio)

    # ---- internals -------------------------------------------------------

    def _load(self):
        if self._model is None:
            import moonshine_onnx  # lazy: optional dep (`features enable stt-moonshine`)

            self._model = moonshine_onnx.MoonshineOnnxModel(model_name=self._model_name)
            log.info("Moonshine model %r loaded.", self._model_name)
        return self._model

    def _decode(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""
        seconds = len(audio) / _SAMPLE_RATE
        if seconds <= MIN_SECONDS:
            # Below upstream's floor there is nothing to decode; asserting would
            # turn "the user tapped the key" into a traceback.
            return ""
        if seconds >= MAX_SECONDS:
            return self._decode_long(audio)
        return self._decode_one(audio)

    def _decode_one(self, audio: np.ndarray) -> str:
        import moonshine_onnx

        waveform = np.asarray(audio, dtype=np.float32).reshape(1, -1)  # [batch, samples]
        result = moonshine_onnx.transcribe(waveform, self._load())
        return _first_text(result)

    def _decode_long(self, audio: np.ndarray) -> str:
        """Split past upstream's 64 s ceiling and join the pieces.

        Cutting on the silence gate rather than on a fixed offset means the seams
        land between utterances instead of mid-word wherever possible.
        """
        from yazses.audio.vad import is_silent

        chunk = int((MAX_SECONDS - 4.0) * _SAMPLE_RATE)   # leave headroom
        window = int(0.2 * _SAMPLE_RATE)
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
            text = self._decode_one(audio[start:end])
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
