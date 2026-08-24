"""Does `[stt] beam_size` earn its latency?

`config.py` said beam 1 was "measurably faster and measurably worse". Neither half had
been measured, and both turned out to be wrong at the shipped default: the speed-up is
~11-16% of decode (tens of milliseconds on a dictation burst), and "worse" reverses on
`small.en` / `test-clean`, where beam 1 is the *better* of the two.

Scored on the same speaker-stratified LibriSpeech subset the published WER table uses,
through the shipping engine factory, so a row here is comparable with a row there.
`test-other` is available as a second split because the effect is larger on hard audio
than on clean, which a clean-only sweep would report as "beam does not matter".

Each row also carries **per-utterance error counts**, which is what makes the table
answerable rather than merely readable. The differences at stake are fractions of a
point -- 4.01 against 4.07, 9.46 against 9.84 -- and at 200 utterances the interval on
a single WER is wider than every gap in the grid. Two bare percentages cannot settle
that, and reading the table as a ranking is the mistake the counts exist to prevent.
They also make the comparison *paired*: every beam width decodes the same utterances,
so `analyze_beam.py` can bootstrap the **difference** and throw away the variance the
two conditions share, which is nearly all of it.
"""
from __future__ import annotations

import time

from _common import librispeech_subset, load_audio
from bench_wer import _bootstrap_wer_ci

GRID = tuple([("base.en", b) for b in (1, 2, 3, 5, 8)] + [("small.en", b) for b in (1, 5)])


def parse_grid(spec: str) -> tuple[tuple[str, int], ...]:
    """`"tiny.en:1,2,5;small.en:2"` -> the (model, beam) pairs to sweep.

    The default grid answers the published question. A caller filling a gap in it --
    the widths `latency/governor.py` actually selects, on the models it actually
    selects -- needs a different one, and must not overwrite the published artifact
    with a partial sweep to get it. Hence a spec here *and* a required `--name`.
    """
    out: list[tuple[str, int]] = []
    for chunk in spec.split(";"):
        if not chunk.strip():
            continue
        model, _, beams = chunk.partition(":")
        if not beams:
            raise SystemExit(f"grid entry {chunk!r} has no beam widths; use model:1,2,5")
        for b in beams.split(","):
            out.append((model.strip(), int(b)))
    if not out:
        raise SystemExit(f"grid spec {spec!r} selected nothing")
    return tuple(out)


def run(n: int, split: str = "test-clean", grid=GRID) -> dict:
    import jiwer
    from whisper_normalizer.english import EnglishTextNormalizer

    from yazses.config import SttConfig
    from yazses.stt.factory import build_engine

    normalize = EnglishTextNormalizer()

    subset = librispeech_subset(n, stratified=True, split=split)
    total_audio_s = sum(dur for _, _, _, dur in subset)

    # A beam width that never reaches the decoder makes every row identical, and the
    # finding is then "beam does not matter" -- exactly the wrong conclusion to draw
    # from a broken probe. Prove the knob is live before measuring with it.
    probe = build_engine(SttConfig(model="base.en", language="en",
                                   compute_type="int8", beam_size=3))
    if probe._decode_kwargs(None).get("beam_size") != 3:
        raise SystemExit("beam_size does not reach the decoder; fix the probe first")
    del probe

    rows = []
    for model, beam in grid:
        engine = build_engine(SttConfig(model=model, language="en",
                                        compute_type="int8", beam_size=beam))
        refs, hyps, decode_s = [], [], 0.0
        for _utt, wav, ref, _dur in subset:
            audio = load_audio(wav)
            t0 = time.monotonic()
            hyp = engine.transcribe(audio)
            decode_s += time.monotonic() - t0
            refs.append(normalize(ref))
            hyps.append(normalize(hyp))
        pairs = [(r, h) for r, h in zip(refs, hyps) if r]
        measure = jiwer.process_words([r for r, _ in pairs], [h for _, h in pairs])
        # Scored one utterance at a time as well as in aggregate. jiwer's corpus call
        # returns totals, and an interval -- or any paired comparison against another
        # beam width -- needs to know which utterance each error came from. The
        # aggregate above is kept as the published figure rather than recomputed from
        # these, so the two can be checked against each other.
        per_utt = []
        for ref, hyp in pairs:
            one = jiwer.process_words([ref], [hyp])
            per_utt.append((one.substitutions + one.deletions + one.insertions,
                            len(ref.split())))
        ci_low, ci_high = _bootstrap_wer_ci(per_utt)
        row = {
            "model": model,
            "beam_size": beam,
            "split": split,
            "wer_pct": round(measure.wer * 100, 2),
            "wer_ci95": [ci_low, ci_high],
            "per_utt_errors": [e for e, _ in per_utt],
            "per_utt_ref_words": [w for _, w in per_utt],
            "substitutions": measure.substitutions,
            "deletions": measure.deletions,
            "insertions": measure.insertions,
            "decode_seconds": round(decode_s, 1),
            "rtf": round(decode_s / total_audio_s, 4),
        }
        rows.append(row)
        print(f"[beam] {model} beam={beam} ({split}): WER {row['wer_pct']}% "
              f"(95% CI {ci_low}-{ci_high})  "
              f"RTF {row['rtf']}  ({row['decode_seconds']}s)", flush=True)
        del engine

    return {
        "config": {
            "n_utterances": len(subset),
            "total_audio_seconds": round(total_audio_s, 1),
            "split": split,
            "compute_type": "int8",
        },
        "rows": rows,
    }


if __name__ == "__main__":
    import sys

    from _common import provenance, write_result

    flags = {a.split("=", 1)[0]: a.split("=", 1)[1]
             for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]

    n = int(positional[0]) if positional else 200
    split = positional[1] if len(positional) > 1 else "test-clean"
    grid = parse_grid(flags["--grid"]) if "--grid" in flags else GRID
    name = flags.get("--name", f"beam-{split}")
    if "--grid" in flags and "--name" not in flags:
        raise SystemExit(
            "--grid needs --name: a partial sweep written to `beam-<split>` would "
            "displace the published grid with a subset of itself."
        )

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = run(n, split, grid)
    out["provenance"] = provenance(stamp)
    write_result(name, out)
