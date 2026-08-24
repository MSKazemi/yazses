"""Where does large-v3's run-to-run instability actually come from?

`decode-determinism-large-v3-test-other.json` establishes that
`condition_on_previous_text` is what drives the runaway insertions, and that the
temperature fallback is the sampled rescue for them. Reading faster-whisper says the
flag is consulted in exactly two places, both **after** a window is decoded, and both
only setting `prompt_reset_since` for the *next* window. So on a decode that makes a
single pass the flag is provably inert.

That reading invites an inference which decides whether any of this reaches YazSes at
all: a hold-to-talk burst is a few seconds, a window is 30 s, therefore one pass,
therefore conditioning cannot affect dictation and the finding is a long-form concern
only (`yazses transcribe`, Meeting Mode).

The inference is wrong, and this measures why. `seek` does not advance by a full window;
it advances to the **last timestamp the model emitted**. A model that closes its final
segment early leaves the rest of the audio for another pass, so a 6 s clip can take two
passes and the second one is prompted with the first one's text.

Two things are recorded per utterance, both mechanical:

  passes        how many times the window loop ran (faster-whisper's own DEBUG line)
  prompt_lens   how many previous-text tokens each pass was handed

The second is the load-bearing one. Equal pass counts across the two arms with a
non-empty prompt on pass 2 in one of them and an empty prompt in the other is direct
evidence that the flag acts on ordinary dictation-length audio -- not an inference from
duration. Nothing here scores WER; a pass count is not a quality claim.

A third counter settles the model-scoping question the WER arms cannot. The
temperature fallback is the only sampled step in the pipeline, so it is the only thing
that can make a decode non-reproducible. `decode-determinism-base.en-test-other.json`
finds `base.en` bit-identical across five baseline decodes *and* identical to its own
`greedy` arm, which is what you would see if the fallback simply never fires on that
model. That is an inference from equal hashes; faster-whisper logs each failed decode
attempt, so it can be counted instead.

  fallback_events   decode attempts rejected by the compression-ratio or logprob gate

The first version of this file expected the count to be zero on `base.en` -- that was
the inference, and it is wrong: `base.en` reaches the fallback and is reproducible
anyway. Firing is not differing. When every temperature on the ladder is rejected,
faster-whisper takes the best average-logprob result it saw, and that can be the
temperature-0 decode, so an escalation can leave the output exactly where it started.
What the count establishes is the weaker, true thing: which model reaches the only
sampled step in the pipeline at all.

    python paper/benchmark/probes/decode_mechanism.py test-clean base.en 40
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bench_wer  # noqa: E402
from _common import (  # noqa: E402
    librispeech_subset,
    load_audio,
    percentile,
    subset_digest,
    write_result,
)

#: The DEBUG line faster-whisper logs once per iteration of its window loop. Counting
#: the library's own message rather than reimplementing the loop is deliberate: the
#: seek arithmetic is exactly what is under test, so a local copy of it would be
#: measuring this file instead of the library.
PASS_MARKER = "Processing segment at"

#: faster-whisper logs one of these per *rejected* decode attempt, immediately before it
#: climbs the temperature ladder. Counting them measures the fallback directly rather
#: than inferring it from two runs happening to agree.
FALLBACK_MARKERS = (
    "Compression ratio threshold is not met",
    "Log probability threshold is not met",
)

ARMS: dict[str, dict] = {
    "conditioned": {},
    "no_context": {"condition_on_previous_text": False},
}


class _PassCounter(logging.Handler):
    """Count window-loop iterations, attributing each to the utterance in flight."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.current: str = ""
        self.passes: dict[str, int] = {}
        self.fallbacks: dict[str, int] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if PASS_MARKER in msg:
                self.passes[self.current] = self.passes.get(self.current, 0) + 1
            elif any(m in msg for m in FALLBACK_MARKERS):
                self.fallbacks[self.current] = self.fallbacks.get(self.current, 0) + 1
        except Exception:  # a probe must never break the decode it observes
            pass


def _instrument_prompt(model, sink: dict) -> None:
    """Record how many previous-text tokens each pass is handed.

    Wraps `WhisperModel.get_prompt`, which is where `previous_tokens` -- the slice
    `all_tokens[prompt_reset_since:]` the flag controls -- is turned into a prompt.
    """
    original = model.get_prompt

    def _wrapped(tokenizer, previous_tokens, *args, **kwargs):
        sink.setdefault(sink["_current"], []).append(len(previous_tokens))
        return original(tokenizer, previous_tokens, *args, **kwargs)

    model.get_prompt = _wrapped


def _measure(engine, subset, audio, arm_kwargs: dict) -> list[dict]:
    counter = _PassCounter()
    lg = logging.getLogger("faster_whisper")
    prior_level, prior_prop = lg.level, lg.propagate
    lg.setLevel(logging.DEBUG)
    lg.propagate = False  # observing must not spray DEBUG onto the operator's console
    lg.addHandler(counter)

    prompts: dict = {"_current": ""}
    _instrument_prompt(engine._model, prompts)

    original = engine._decode_kwargs

    def _with_arm(task=None):
        kw = dict(original(task))
        kw.update(arm_kwargs)
        return kw

    engine._decode_kwargs = _with_arm

    try:
        for (utt_id, _, _, _), a in zip(subset, audio):
            counter.current = utt_id
            prompts["_current"] = utt_id
            counter.passes.setdefault(utt_id, 0)
            engine.transcribe(a)
    finally:
        lg.removeHandler(counter)
        lg.setLevel(prior_level)
        lg.propagate = prior_prop

    rows = []
    for utt_id, _, _, dur in subset:
        lens = prompts.get(utt_id, [])
        rows.append({
            "utt_id": utt_id,
            "duration_s": round(float(dur), 2),
            "passes": counter.passes.get(utt_id, 0),
            "fallback_events": counter.fallbacks.get(utt_id, 0),
            "prompt_lens": lens,
            # The question is only ever about passes after the first: pass 1 is
            # prompted with the initial_prompt (here, nothing) under either setting.
            "later_pass_prompted": any(n > 0 for n in lens[1:]),
        })
    return rows


def summarise(rows: list[dict]) -> dict:
    passes = [r["passes"] for r in rows]
    multi = [r for r in rows if r["passes"] > 1]
    hist: dict[str, int] = {}
    for p in passes:
        hist[str(p)] = hist.get(str(p), 0) + 1
    return {
        "n_utterances": len(rows),
        "pass_histogram": dict(sorted(hist.items(), key=lambda kv: int(kv[0]))),
        "multi_pass_utterances": len(multi),
        "multi_pass_fraction": round(len(multi) / len(rows), 3) if rows else 0.0,
        "later_pass_prompted_utterances": sum(1 for r in rows if r["later_pass_prompted"]),
        "fallback_events": sum(r["fallback_events"] for r in rows),
        "utterances_with_fallback": sum(1 for r in rows if r["fallback_events"]),
        "max_duration_s": round(max((r["duration_s"] for r in rows), default=0.0), 2),
        "median_duration_s": round(percentile([r["duration_s"] for r in rows], 50), 2),
        "multi_pass_median_duration_s": (
            round(percentile([r["duration_s"] for r in multi], 50), 2) if multi else None
        ),
    }


def run(split: str, model: str, n: int) -> dict:
    subset = librispeech_subset(n, stratified=True, split=split)
    audio = [load_audio(flac) for _, flac, _, _ in subset]

    arms: dict[str, dict] = {}
    for arm, extra in ARMS.items():
        engine = bench_wer._build("faster-whisper", model)
        rows = _measure(engine, subset, audio, extra)
        arms[arm] = {"summary": summarise(rows), "utterances": rows}
        print(f"  [pass] {arm}: {arms[arm]['summary']}", flush=True)

    cond, noctx = arms["conditioned"]["summary"], arms["no_context"]["summary"]
    same_passes = cond["pass_histogram"] == noctx["pass_histogram"]
    reaches_short_audio = (
        cond["later_pass_prompted_utterances"] > 0
        and noctx["later_pass_prompted_utterances"] == 0
    )
    return {
        "config": {
            "dataset": f"LibriSpeech {split}",
            "n_utterances": len(subset),
            "corpus_digest": subset_digest([u for u, _, _, _ in subset]),
            "model": model,
            "arms": {k: (v or "faster-whisper defaults") for k, v in ARMS.items()},
        },
        "probe": {
            "measured": (
                "Where large-v3's run-to-run instability comes from, counted rather "
                "than inferred: how many decode passes each sub-30s utterance takes, "
                "how many previous-text tokens each pass is handed, and how many decode "
                "attempts the temperature fallback rejects -- with conditioning on and off."
            ),
            "produced_by": "paper/benchmark/probes/decode_mechanism.py",
        },
        "arms": arms,
        "finding": {
            "all_utterances_under_one_window": cond["max_duration_s"] < 30.0,
            "multi_pass_fraction": cond["multi_pass_fraction"],
            "pass_count_is_unchanged_by_the_flag": same_passes,
            "conditioning_reaches_short_audio": reaches_short_audio,
            "fallback_events": cond["fallback_events"],
            "fallback_ever_fires": cond["fallback_events"] > 0,
            "reading": (
                (
                    f"{cond['multi_pass_utterances']} of {cond['n_utterances']} "
                    f"utterances take more than one decode pass despite none exceeding "
                    f"one 30s window (longest {cond['max_duration_s']}s). "
                    if cond["multi_pass_utterances"]
                    else "Every utterance decoded in a single pass. "
                )
                + (
                    (
                        f"With conditioning ON, "
                        f"{cond['later_pass_prompted_utterances']} of them had a later "
                        f"pass handed previous text; with it OFF, none did -- so the "
                        f"flag acts on ordinary dictation-length audio and the finding "
                        f"is not confined to long files."
                    )
                    if reaches_short_audio
                    else (
                        "The two arms do not separate on this sample, so it cannot "
                        "show the flag acting on short audio; that is left to the "
                        "source reading."
                    )
                )
                + (
                    (
                        f" The temperature fallback -- the only sampled step, and so "
                        f"the only thing that can make a decode differ between runs -- "
                        f"rejected no decode attempt at all on this model, across "
                        f"{cond['n_utterances']} utterances. A model that never reaches "
                        f"it is reproducible whatever the fallback is configured to do."
                    )
                    if not cond["fallback_events"]
                    else (
                        f" The temperature fallback rejected "
                        f"{cond['fallback_events']} decode attempts across "
                        f"{cond['utterances_with_fallback']} utterances, so this model "
                        f"does reach the sampled step. That is not the same as differing "
                        f"between runs: when every temperature is rejected the ladder "
                        f"ends by taking the best average-logprob result it saw, which "
                        f"can be the temperature-0 one. Whether the output actually "
                        f"moves is what decode-determinism.json measures."
                    )
                )
                + (
                    ""
                    if same_passes
                    else (
                        f" Turning it off also changes the pass counts themselves "
                        f"({cond['pass_histogram']} vs {noctx['pass_histogram']}): "
                        f"dropping the prompt changes what the model emits, which "
                        f"changes where seek lands. That is a consequence of the flag, "
                        f"not a confound -- the evidence above is counted per pass, "
                        f"not per utterance-length."
                    )
                )
            ),
        },
    }


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 else "test-clean"
    model = sys.argv[2] if len(sys.argv) > 2 else "base.en"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    payload = run(split, model, n)
    for k, v in payload["finding"].items():
        print(f"  {k}: {v}", flush=True)
    print(f"wrote {write_result(f'probes/decode-mechanism-{model}-{split}', payload)}")


if __name__ == "__main__":
    main()
