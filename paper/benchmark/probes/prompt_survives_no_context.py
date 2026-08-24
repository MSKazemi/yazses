"""Does `initial_prompt` still reach the decoder when conditioning is turned off?

`decode-determinism-large-v3-test-other.json` shows that
`condition_on_previous_text=False` removes the repetition loops the temperature
fallback exists to rescue, and is bit-reproducible. Before that becomes a default, one
question it **cannot** answer has to be settled: YazSes primes Whisper's `initial_prompt`
with the user's personal dictionary and the app's own name
(`stt/vocabulary.py::merge_initial_prompt`, via `core/daemon.py::_effective_initial_prompt`).
The LibriSpeech runs decoded with no prompt at all, so a benchmark win there is silent
about whether the change quietly disables the vocabulary.

Reading faster-whisper says it does not, but only for the first window. `all_tokens` is
seeded with the prompt tokens at `prompt_reset_since = 0`, so the first window's prompt
is the user's; after each window, `not condition_on_previous_text` sets
`prompt_reset_since = len(all_tokens)`, so every later window is prompted with nothing --
dropping the vocabulary along with the previous text.

That is a source reading, and a source reading is a hypothesis. This measures it, with no
semantic judgement involved: decode the same audio with and without a biasing prompt, and
ask only whether the **text changed**. If a prompt changes the output, it reached the
decoder.

  short  a single sub-30 s utterance -- one window, which is what a hold-to-talk burst is
  long   utterances concatenated past 30 s -- at least two windows

The two halves of the long case are separated by **word timestamps**, not by a word
count. An earlier version of this file split on a fixed count and reported that the
prompt still acted after the boundary; that was the probe being wrong, not the library.
A 48 s clip holds around eighty words in its first window, so a twelve-word head left
most of window one sitting in the "tail".

The prediction being tested: with conditioning off, the prompt still moves the *short*
case and still moves the *opening* of the long case, but the tail of the long case is
untouched. If the short case does not move, the personal dictionary is broken by the
change and it must not ship on the dictation path.

    python paper/benchmark/probes/prompt_survives_no_context.py test-clean small.en
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import bench_wer  # noqa: E402
from _common import load_audio, librispeech_subset, write_result  # noqa: E402

#: Nonsense proper nouns. Real words would risk the model producing them for acoustic
#: reasons; these cannot be confused with anything in LibriSpeech, so any change in the
#: output is attributable to the prompt rather than to the audio.
BIAS = "Glorbax Zindalor Kweepthorne Vanterix."

SAMPLE_RATE = 16000
WINDOW_S = 30.0


def _decode(engine, audio, prompt: str, condition: bool) -> tuple[str, list]:
    """One decode, with the arm applied at the engine's own kwargs seam.

    Returns joined text *and* per-word timestamps, because the window boundary is the
    whole question and only a timestamp can find it.
    """
    original = engine._decode_kwargs

    def _with_arm(task=None):
        kwargs = dict(original(task))
        kwargs["condition_on_previous_text"] = condition
        return kwargs

    engine._decode_kwargs = _with_arm
    try:
        text, words = engine.transcribe_words(audio, initial_prompt=prompt or None)
        return text.strip(), list(words)
    finally:
        engine._decode_kwargs = original


def _split_at_window(words: list, boundary: float = WINDOW_S) -> tuple[str, str]:
    """Words decoded inside the first 30 s window, and words after it.

    The first version of this probe split on a fixed *word count*, which was wrong and
    said so: in a 48 s clip the first window holds roughly eighty words, so a 12-word
    "head" put the entire late part of window one into the "tail". A prompt effect
    anywhere in window one then showed up as an effect after the boundary -- the probe
    manufacturing the very finding it was built to test. The boundary is a time, so it
    has to be found with a time.
    """
    head = [w.text for w in words if w.start < boundary]
    tail = [w.text for w in words if w.start >= boundary]
    return " ".join(head).strip(), " ".join(tail).strip()


def run(split: str, model: str) -> dict:
    subset = librispeech_subset(40, stratified=False, split=split)

    short_id, short_flac, _, short_dur = subset[0]
    short = load_audio(short_flac)

    clips, ids, total = [], [], 0.0
    for utt_id, flac, _, dur in subset:
        clips.append(load_audio(flac))
        ids.append(utt_id)
        total += dur
        if total > WINDOW_S * 1.6:
            break
    long = np.concatenate(clips)

    engine = bench_wer._build("faster-whisper", model)
    cases = {}
    for name, audio, meta in (
        ("short", short, {"utterance": short_id, "seconds": round(short_dur, 2)}),
        ("long", long, {"utterances": ids, "seconds": round(total, 2)}),
    ):
        for condition in (True, False):
            plain, pw = _decode(engine, audio, "", condition)
            biased, bw = _decode(engine, audio, BIAS, condition)
            ph, pt = _split_at_window(pw)
            bh, bt = _split_at_window(bw)
            cases[f"{name}_condition_{str(condition).lower()}"] = {
                **meta,
                "windows_expected": max(1, int(meta["seconds"] // WINDOW_S) + 1),
                "words_in_first_window": sum(
                    1 for w in pw if w.start < WINDOW_S),
                "words_after_first_window": sum(
                    1 for w in pw if w.start >= WINDOW_S),
                "prompt_changed_output": plain != biased,
                "prompt_changed_first_window": ph != bh,
                "prompt_changed_after_first_window": pt != bt,
                "text_without_prompt": plain,
                "text_with_prompt": biased,
            }

    short_off = cases["short_condition_false"]
    long_off = cases["long_condition_false"]
    long_on = cases["long_condition_true"]
    # The long case can only say something about *the difference between the arms* if
    # the prompt reaches past the first window when conditioning is ON. If it does not
    # even then, both arms look identical after the boundary for a reason that has
    # nothing to do with the setting -- the prompt's influence simply did not carry
    # that far in this sample -- and reading that as "the change drops the vocabulary
    # after window one" would be attributing an absence to the arm.
    discriminating = long_on["prompt_changed_after_first_window"]
    return {
        "config": {
            "dataset": f"LibriSpeech {split}", "model": model,
            "bias_prompt": BIAS, "window_seconds": WINDOW_S,
            "question": (
                "does initial_prompt still reach the decoder when "
                "condition_on_previous_text=False?"
            ),
        },
        "probe": {
            "measured": (
                "Whether turning off condition_on_previous_text silently disables "
                "YazSes's personal-vocabulary initial_prompt, by testing whether a "
                "biasing prompt still changes the decoded text -- on a single-window "
                "clip (a hold-to-talk burst) and on a multi-window one."
            ),
            "produced_by": "paper/benchmark/probes/prompt_survives_no_context.py",
        },
        "cases": cases,
        "finding": {
            "prompt_still_applies_to_a_single_window": short_off["prompt_changed_output"],
            "prompt_still_applies_to_the_first_window_of_a_long_file":
                long_off["prompt_changed_first_window"],
            "prompt_still_applies_after_the_first_window":
                long_off["prompt_changed_after_first_window"],
            "long_file_case_is_discriminating": discriminating,
            "reading": (
                (
                    "A hold-to-talk burst is a single window, and the prompt still "
                    "changes its decode with conditioning off -- so the personal "
                    "dictionary is NOT disabled by the change on the dictation path."
                    if short_off["prompt_changed_output"]
                    else "The prompt no longer changes a single-window decode: the "
                         "personal dictionary IS disabled by the change. It must not "
                         "ship on the dictation path."
                )
                + (
                    " The long-file half is inconclusive: with conditioning ON the "
                    "prompt did not change anything past the first window either, so "
                    "this sample cannot separate the two settings there. Whether long "
                    "files lose the vocabulary after window one is left to the source "
                    "reading, not settled here."
                    if not discriminating
                    else " With conditioning ON the prompt does reach past the first "
                         "window, and with it OFF it does not -- so a long file keeps "
                         "the vocabulary only for its first window."
                )
            ),
        },
    }


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 else "test-clean"
    model = sys.argv[2] if len(sys.argv) > 2 else "small.en"
    payload = run(split, model)
    for k, v in payload["finding"].items():
        print(f"  {k}: {v}", flush=True)
    print(f"wrote {write_result(f'probes/prompt-vs-no-context-{model}-{split}', payload)}")


if __name__ == "__main__":
    main()
