"""Perceived latency: speech-end -> text, for the batch and streaming paths.

The decode latency in ``bench_latency.py`` answers "how long does the model take".
This answers the question a *user* asks, and the one competing products advertise:
**after I stop speaking, how long until the text is there?**

Two paths are measured under the same conditions:

1. **Batch** (``[streaming] enabled = false``, the default) — the whole utterance is
   decoded on release, so speech-end -> text *is* the full decode.
2. **Streaming** (``[streaming] enabled = true``, ADR-002 LocalAgreement) — rolling
   windows are decoded *while* the user speaks and stable prefixes are injected as
   they are confirmed. Audio is therefore fed at **real time** here, exactly as a
   microphone would deliver it; feeding it faster would invent a machine that hears
   the future and would make every number below meaningless.

The streaming path is measured on three axes, because "latency" alone hides what it
actually buys:

- ``time_to_first_text_s`` — speech-start -> first stable prefix appears on screen.
  This is the number streaming genuinely improves; the batch path cannot show a
  character before release.
- ``visible_at_release_pct`` — how much of the final transcript is *already typed*
  when the user lets go of the key.
- ``speech_end_to_final_s`` — speech-end -> the final committed text.
  ``StreamingEngine.commit()`` re-decodes the whole buffer, so this is expected to
  match (or, under decode-loop CPU contention, exceed) the batch path. Streaming
  moves text earlier; it does not make the final decode cheaper. Measuring it is the
  only way to say that honestly.
"""
from __future__ import annotations

import time

import numpy as np

from _common import load_audio, librispeech_subset, percentile

MODELS = ["tiny.en", "base.en"]
CHUNK_MS = 100  # mirrors the daemon's capture chunking granularity
PARTIAL_INTERVAL_MS = 300  # StreamingConfig.partial_interval_ms default


def _summary(values: list[float]) -> dict:
    return {
        "median": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
        "mean": round(sum(values) / len(values), 3) if values else 0.0,
        "n": len(values),
    }


def _batch_once(engine, audio: np.ndarray) -> tuple[float, str]:
    """Speech-end -> text for the default path: one decode of the whole utterance."""
    t0 = time.monotonic()
    text = engine.transcribe(audio)
    return time.monotonic() - t0, (text or "").strip()


def _stream_once(engine, audio: np.ndarray) -> dict:
    """Feed one utterance in real time through StreamingEngine; time what a user sees.

    Returns time-to-first-text (from speech start), characters visible at release,
    and speech-end -> final committed text.
    """
    from yazses.stt.streaming import StreamingEngine

    stream = StreamingEngine(engine, partial_interval_ms=PARTIAL_INTERVAL_MS)
    chunk = int(16000 * CHUNK_MS / 1000)
    stream.start()

    speech_start = time.monotonic()
    first_text_at: float | None = None
    visible_chars = 0
    partials = 0

    for i in range(0, len(audio), chunk):
        stream.push(audio[i : i + chunk])
        # Drain whatever the decode loop has confirmed so far, exactly as the
        # daemon's injection loop would.
        p = stream.get_partial()
        if p is not None:
            partials += 1
            visible_chars = p.char_count
            if first_text_at is None:
                first_text_at = time.monotonic()
        # Real-time pacing: a microphone delivers CHUNK_MS of audio every CHUNK_MS.
        target = speech_start + (i + chunk) / 16000.0
        remaining = target - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    p = stream.get_partial()
    if p is not None:
        partials += 1
        visible_chars = p.char_count
        if first_text_at is None:
            first_text_at = time.monotonic()

    speech_end = time.monotonic()
    final = (stream.commit() or "").strip()
    final_at = time.monotonic()

    return {
        "time_to_first_text_s": (
            None if first_text_at is None else first_text_at - speech_start
        ),
        "speech_end_to_final_s": final_at - speech_end,
        "visible_chars_at_release": visible_chars,
        "final_chars": len(final),
        "partials": partials,
    }


def run(n: int) -> dict:
    from yazses.stt.faster_whisper import FasterWhisperEngine

    subset = librispeech_subset(n)
    durations = [d for _, _, _, d in subset]

    out: dict = {
        "config": {
            "n_utterances": len(subset),
            "audio_duration_median_s": round(percentile(durations, 50), 2),
            "chunk_ms": CHUNK_MS,
            "partial_interval_ms": PARTIAL_INTERVAL_MS,
            "feed": "real-time (1x); audio is paced as a microphone delivers it",
        },
        "models": {},
    }

    for model_name in MODELS:
        print(f"[streaming] {model_name}: loading ...", flush=True)
        engine = FasterWhisperEngine(model_name=model_name)
        # Warm the model so the first utterance does not pay lazy-init cost.
        engine.transcribe(np.zeros(16000, dtype=np.float32))

        batch_s: list[float] = []
        first_text_s: list[float] = []
        final_s: list[float] = []
        visible_pct: list[float] = []
        no_partial = 0

        for i, (_, flac, _, _) in enumerate(subset):
            audio = load_audio(flac)

            b_s, _ = _batch_once(engine, audio)
            batch_s.append(b_s)

            r = _stream_once(engine, audio)
            final_s.append(r["speech_end_to_final_s"])
            if r["time_to_first_text_s"] is None:
                no_partial += 1
            else:
                first_text_s.append(r["time_to_first_text_s"])
            if r["final_chars"] > 0:
                visible_pct.append(
                    100.0 * min(r["visible_chars_at_release"], r["final_chars"])
                    / r["final_chars"]
                )

            print(
                f"  {model_name}: {i + 1}/{len(subset)} "
                f"batch={b_s:.2f}s final={r['speech_end_to_final_s']:.2f}s "
                f"visible={visible_pct[-1] if visible_pct else 0:.0f}%",
                flush=True,
            )

        out["models"][model_name] = {
            "batch_speech_end_to_text_s": _summary(batch_s),
            "streaming_speech_end_to_final_s": _summary(final_s),
            "streaming_time_to_first_text_s": _summary(first_text_s),
            "streaming_visible_at_release_pct": _summary(visible_pct),
            "utterances_with_no_partial_before_release": no_partial,
        }
        print(f"[streaming] {model_name}: {out['models'][model_name]}", flush=True)
        del engine

    return out


if __name__ == "__main__":
    import sys

    from _common import write_result

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    write_result("streaming", run(n))
