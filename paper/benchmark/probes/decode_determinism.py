"""Is the run-to-run instability the sampling fallback, and can it be turned off?

`largev3-instability-test-other.json` established the *what*: across four decodes of
the same 200 utterances, `large-v3` scored 87 substitutions and 15 deletions every
single time and 101-144 insertions -- so its recognition is bit-deterministic and only
the text it adds moves. The mechanism is faster-whisper's temperature fallback: when a
segment fails the compression-ratio or average-log-probability check, it is re-decoded
by **sampling** from a ladder of temperatures, and a sampled rescue is a different
sentence every time.

That was an inference from one artifact plus a documented mechanism. This tests it, and
tests the thing a user actually cares about, which is not the same question:

  A  baseline            what ships today: faster-whisper's defaults, fallback ladder on
  B  no fallback         temperature=0.0 -- one greedy pass, no sampled rescue
  C  no fallback, no ctx  temperature=0.0 and condition_on_previous_text=False
  D  no ctx              condition_on_previous_text=False, fallback ladder left ON

Arm D was added after A-C ran, because A-C between them do not contain the setting
YazSes would actually ship. Conditioning is the *cause* of the repetition loops the
fallback exists to rescue -- B and C differ in nothing else, and B emits 466 insertions
where C emits 40 -- so the interesting change removes the cause and keeps the safety
net. C removes both at once and cannot say whether the net is still earning anything.
D is also the one arm whose determinism is genuinely open: it keeps the sampled rescue,
so it is reproducible only if, with conditioning off, the fallback never fires at all.

**This is a product question before it is a paper question.** YazSes types its output
into the user's document. A dictation daemon that emits a different sentence each time
the same words are said is a defect a user experiences directly, and an inserted clause
nobody spoke is worse than a dropped word: the dropped word is visible, the fluent
hallucination is not. If arm B is deterministic *and* no worse on WER, then
`temperature=0.0` is a one-line change to `stt/faster_whisper.py::_decode_kwargs` that
makes dictation reproducible. If arm B is deterministic and *worse*, the fallback is
buying something and the honest answer is to say so and leave it on.

Two things are recorded that a WER table cannot express:

* **A hash of the concatenated hypotheses per run.** Equal WER does not mean equal text
  -- two runs can trade an insertion for another insertion elsewhere and score the same.
  The hash is what makes "deterministic" a checkable claim rather than a summary that
  happens to agree.
* **Which utterance ids differ from the arm's first run.** A spread reported as a number
  says the model is noisy; a list of utterance ids says *where*, which is what makes the
  finding traceable to a specific piece of audio by anyone holding LibriSpeech.

Deliberately not a `bench_*.py`: it answers whether a decode setting should change, once.

    python paper/benchmark/probes/decode_determinism.py 5 test-other 200 large-v3
"""
from __future__ import annotations

import gc
import hashlib
import json
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import jiwer  # noqa: E402

import bench_wer  # noqa: E402
from _common import (  # noqa: E402
    RESULTS_DIR,
    load_audio,
    librispeech_subset,
    percentile,
    write_result,
)

#: The three decode settings, and what each one is testing. `None` is "pass nothing",
#: which is what ships -- written as an empty dict rather than omitted from the table so
#: that the baseline goes through exactly the same code path as the arms it is compared
#: against. An arm that skips the wrapper is not a control.
ARMS: dict[str, dict] = {
    "baseline": {},
    "greedy": {"temperature": 0.0},
    "greedy_no_context": {"temperature": 0.0, "condition_on_previous_text": False},
    "no_context": {"condition_on_previous_text": False},
}


def _patched(engine, extra: dict):
    """Add *extra* to every decode this engine performs, without touching the engine.

    Routing through the shipping `FasterWhisperEngine` rather than constructing a
    `WhisperModel` here is the point: the number has to describe what YazSes does, and
    the engine applies `[stt] language`, the beam width and the task on every path. So
    the arm is applied at the one seam those already go through -- which is also the
    exact place the fix would land if an arm wins.
    """
    original = engine._decode_kwargs

    def _with_arm(task=None):
        kwargs = dict(original(task))
        kwargs.update(extra)
        return kwargs

    engine._decode_kwargs = _with_arm
    return engine


def _release(engine) -> None:
    """Drop *engine* and the native model behind it, cycle and all.

    This is not tidiness. `_patched` installs a closure on the engine that closes over
    the engine's own bound `_decode_kwargs`, so the engine references itself, and a
    self-referencing object is reachable only by the cycle collector -- which runs when
    it feels like it. CTranslate2's weights are native memory freed by the model's
    destructor, not by the last Python reference going out of scope, so a deferred
    collection leaves ~4 GB per run resident. The first attempt at this experiment built
    a fresh engine for each of the 15 runs, reached 64.8 GB on a 62 GB box with no swap,
    and was OOM-killed at run 19 of 20 -- after three and a half hours, having written
    nothing.

    Rebuilding per run is kept deliberately: it is what makes "identical text" a claim
    about the *setting* rather than about a warm model that happened not to drift.
    """
    engine.__dict__.pop("_decode_kwargs", None)  # break the cycle
    engine._model = None
    del engine
    gc.collect()


def _score(refs: list[str], hyps: list[str]) -> dict:
    pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
    m = jiwer.process_words([r for r, _ in pairs], [h for _, h in pairs])
    return {
        "wer": round(m.wer * 100, 2),
        "substitutions": m.substitutions,
        "deletions": m.deletions,
        "insertions": m.insertions,
        "hits": m.hits,
        "n_scored_utterances": len(pairs),
    }


def _digest(hyps: list[str]) -> str:
    return hashlib.sha256("\n".join(hyps).encode("utf-8")).hexdigest()[:16]


def run(repeats: int, split: str, n: int, model: str, on_arm=None, only=None) -> dict:
    arms = {k: v for k, v in ARMS.items() if only is None or k in only}
    if not arms:
        raise SystemExit(f"no such arm; known arms are {', '.join(ARMS)}")
    subset = librispeech_subset(n, stratified=True, split=split)
    refs = [bench_wer._normalize(ref) for _, _, ref, _ in subset]
    ids = [utt_id for utt_id, _, _, _ in subset]
    audio = [(load_audio(flac), dur) for _, flac, _, dur in subset]

    out: dict = {
        "config": {
            "dataset": f"LibriSpeech {split}",
            "n_utterances": len(subset),
            "model": model,
            "repeats": repeats,
            "arms": {k: (v or "faster-whisper defaults") for k, v in arms.items()},
            "normalizer": "whisper_normalizer.english.EnglishTextNormalizer",
        },
        "arms": {},
    }

    for arm, extra in arms.items():
        runs = []
        first_hyps: list[str] | None = None
        for r in range(repeats):
            engine = _patched(bench_wer._build("faster-whisper", model), extra)
            hyps, rtfs = [], []
            t_arm = time.monotonic()
            for (a, dur) in audio:
                t0 = time.monotonic()
                hyps.append(bench_wer._normalize(engine.transcribe(a)))
                dt = time.monotonic() - t0
                rtfs.append(dt / dur if dur > 0 else 0.0)
            row = _score(refs, hyps)
            row["run"] = r
            row["hypothesis_sha256_16"] = _digest(hyps)
            row["rtf_median"] = round(percentile(rtfs, 50), 3)
            row["decode_seconds_total"] = round(time.monotonic() - t_arm, 1)
            if first_hyps is None:
                first_hyps = hyps
                row["differs_from_run0"] = []
            else:
                row["differs_from_run0"] = [
                    ids[i] for i, (a_, b_) in enumerate(zip(first_hyps, hyps)) if a_ != b_
                ]
            runs.append(row)
            _release(engine)
            print(
                f"[det] {arm} run {r}: WER={row['wer']}% ins={row['insertions']} "
                f"sha={row['hypothesis_sha256_16']} "
                f"differs={len(row['differs_from_run0'])}",
                flush=True,
            )
        out["arms"][arm] = {"runs": runs, "summary": summarise(runs)}
        # Checkpoint after every arm rather than once at the end. Each arm is ~35 minutes
        # of decoding, and the run this replaces lost all three of them to a kill in the
        # last one. A partial artifact says which arms completed; nothing says nothing.
        if on_arm is not None:
            on_arm(out)
    return out


def summarise(runs: list[dict]) -> dict:
    """Pure over *runs*, so a re-reading of the artifact reproduces it without decoding.

    `identical_text` is the claim, and it is deliberately not derived from the WER: two
    runs that trade one insertion for another score the same and are not the same text.
    """
    wers = [r["wer"] for r in runs]
    digests = {r["hypothesis_sha256_16"] for r in runs}
    out: dict = {
        "identical_text": len(digests) == 1,
        "distinct_outputs": len(digests),
        "wer_min": min(wers),
        "wer_max": max(wers),
        "wer_spread": round(max(wers) - min(wers), 2),
        "wer_mean": round(sum(wers) / len(wers), 3),
    }
    for field in ("insertions", "substitutions", "deletions"):
        vals = [r[field] for r in runs]
        out[f"{field}_min"] = min(vals)
        out[f"{field}_max"] = max(vals)
        out[f"{field}_spread"] = max(vals) - min(vals)
    differing = {u for r in runs for u in r["differs_from_run0"]}
    out["n_utterances_ever_differing"] = len(differing)
    out["utterances_ever_differing"] = sorted(differing)
    return out


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    split = sys.argv[2] if len(sys.argv) > 2 else "test-other"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    model = sys.argv[4] if len(sys.argv) > 4 else "large-v3"
    # A comma-separated arm list writes a *separately named* artifact. Filing a
    # single-arm run under the three-arm name would let `write_result` move the
    # complete measurement into `history/` and leave the partial one standing as
    # the current result -- a re-run destroying evidence, which is the failure the
    # non-destructive archive was built to prevent.
    only = sys.argv[5].split(",") if len(sys.argv) > 5 else None
    suffix = f"-{'-'.join(only)}" if only else ""
    name = f"probes/decode-determinism-{model}-{split}{suffix}"
    # The checkpoint is written *beside* the archive, not through `write_result`, and
    # deliberately: `write_result` files any change to an existing artifact under
    # `results/history/` so that a re-run can never destroy a measurement. Routing three
    # checkpoints of one run through it would fill that directory with two half-finished
    # payloads and call them superseded measurements, which is the opposite of what the
    # history is for. A partial is not a result; it is what survives a kill.
    partial = RESULTS_DIR / f"{name}.partial.json"

    def checkpoint(payload: dict) -> None:
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[det] checkpoint -> {partial} ({len(payload['arms'])} arms)", flush=True)

    payload = run(repeats, split, n, model, on_arm=checkpoint, only=only)
    print(f"wrote {write_result(name, payload)}", flush=True)
    partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
