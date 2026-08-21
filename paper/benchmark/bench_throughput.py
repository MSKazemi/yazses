"""Time to *finished text*, by dictation and by typing, on the same prompts.

The gap this closes is stated plainly elsewhere in the project and had no
instrument behind it:

    "YazSes has **not run a controlled throughput study against typing**; that
    experiment is an open research question, deliberately listed as unanswered
    rather than guessed at."  — docs/comparison.md

Five other benchmarks live here and none measures throughput: `bench_wer` scores
accuracy on read audiobook speech, `bench_latency` times a decode, `bench_vad`
scores a gate. All useful, none of them the number a user feels.

**What it measures, and why that framing.** Time to *finished* text, not time to
first transcript. A fast recogniser producing text that needs three corrections is
slower than a slow one that does not — this project's own streaming benchmark
already shows the principle in the other direction. So the clock stops when the
participant says the text is right, and corrections are counted on the way.

**What it does not do.** It does not recruit anyone. `docs/research/agenda.md`
settles the method — MacKenzie & Soukoreff's protocol, Soukoreff & MacKenzie's
unified error metric, Vertanen & Kristensson's phrase set, preregistered — and
names the binding constraint as participants. This is the instrument for that
study, not the study. Even n=8 within-subjects would be the first such number
published for this class of tool.

**What it will not let you claim.** One participant is a pilot. The JSON records
`n_participants` and the summary says so, because a single-person figure quoted as
a throughput result would be exactly the kind of unsourced number this project has
had to correct elsewhere.

Usage:

    uv run python paper/benchmark/bench_throughput.py --mode typing
    uv run python paper/benchmark/bench_throughput.py --mode dictation
    uv run python paper/benchmark/bench_throughput.py --mode typing --phrases 5 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# A short, memorable, punctuation-light set in the spirit of Vertanen &
# Kristensson's phrase set, plus the four cases this project knows break: numbers,
# proper nouns, code, and a bilingual line. A phrase set without those measures a
# tool nobody uses.
PHRASES: tuple[str, ...] = (
    "the quick brown fox jumps over the lazy dog",
    "please call me back when you get a chance",
    "my account number is four one nine two seven",
    "send it to Nadia in the Helsinki office",
    "the function returns None when the list is empty",
    "we should meet at half past three on Thursday",
    "salam, can you send me the report by Friday",
    "the total came to sixty two euros and fifty cents",
)


@dataclass
class Trial:
    """One prompt, attempted once."""

    prompt: str
    produced: str
    seconds: float
    corrections: int = 0


@dataclass
class Session:
    mode: str
    trials: list[Trial] = field(default_factory=list)


def levenshtein(a: str, b: str) -> int:
    """Edit distance — the basis of the unified error metric.

    Written out rather than imported: `jiwer` is in the benchmark dependency
    group, and this file must stay runnable for a `--dry-run` on a checkout that
    has not installed it.
    """
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def words_per_minute(text: str, seconds: float) -> float:
    """Entry rate, using the standard 5-character word.

    Characters, not whitespace-delimited words, because that is what the entry-rate
    literature uses and a comparison against published typing figures has to be on
    the same footing.
    """
    if seconds <= 0:
        return 0.0
    return (len(text) / 5.0) / (seconds / 60.0)


def error_rate_pct(prompt: str, produced: str) -> float:
    """Uncorrected error rate: edit distance over the longer string, as a percent."""
    span = max(len(prompt), len(produced))
    if span == 0:
        return 0.0
    return 100.0 * levenshtein(prompt.strip(), produced.strip()) / span


def summarise(session: Session) -> dict:
    """Aggregate a session into the numbers a result file should carry."""
    trials = session.trials
    if not trials:
        return {"n_trials": 0}

    total_seconds = sum(t.seconds for t in trials)
    total_chars = sum(len(t.produced) for t in trials)
    rates = [words_per_minute(t.produced, t.seconds) for t in trials]
    errors = [error_rate_pct(t.prompt, t.produced) for t in trials]

    return {
        "n_trials": len(trials),
        # One person is a pilot, not a study. Recorded so the number can never be
        # quoted without it.
        "n_participants": 1,
        "mode": session.mode,
        "total_seconds": round(total_seconds, 2),
        "wpm_mean": round(sum(rates) / len(rates), 2),
        "wpm_median": round(sorted(rates)[len(rates) // 2], 2),
        "uncorrected_error_rate_pct_mean": round(sum(errors) / len(errors), 2),
        "corrections_total": sum(t.corrections for t in trials),
        "corrections_per_trial": round(sum(t.corrections for t in trials) / len(trials), 2),
        "chars_total": total_chars,
    }


def run_typing(phrases: tuple[str, ...], reader=input, clock=time.monotonic) -> Session:
    """Type each phrase. The clock stops when the line is submitted."""
    session = Session(mode="typing")
    for phrase in phrases:
        print(f"\n  TYPE: {phrase}")
        start = clock()
        produced = reader("     > ")
        session.trials.append(Trial(phrase, produced, clock() - start))
    return session


def run_dictation(
    phrases: tuple[str, ...], reader=input, clock=time.monotonic
) -> Session:
    """Dictate each phrase into this terminal using YazSes, then press Enter.

    Deliberately measures the *whole* loop the user actually lives in — hold,
    speak, release, read what appeared, fix it — rather than instrumenting the
    daemon. Instrumenting the pipeline would measure the pipeline; this measures
    the person plus the pipeline, which is what "faster than typing" means.
    """
    session = Session(mode="dictation")
    for phrase in phrases:
        print(f"\n  SAY: {phrase}")
        print("     (dictate it here, correct it until it is right, then press Enter)")
        start = clock()
        produced = reader("     > ")
        elapsed = clock() - start
        corrections = 0
        answer = reader("     how many times did you re-dictate or fix it? [0] ")
        try:
            corrections = int((answer or "0").strip() or 0)
        except ValueError:
            corrections = 0
        session.trials.append(Trial(phrase, produced, elapsed, corrections))
    return session


def run(mode: str, n_phrases: int) -> dict:
    phrases = PHRASES[: max(1, min(n_phrases, len(PHRASES)))]
    session = run_typing(phrases) if mode == "typing" else run_dictation(phrases)
    out = summarise(session)
    print(
        f"\n[throughput] mode={out.get('mode')}  n={out.get('n_trials')}  "
        f"wpm_median={out.get('wpm_median')}  "
        f"errors={out.get('uncorrected_error_rate_pct_mean')}%  "
        f"corrections={out.get('corrections_total')}  "
        f"— ONE participant: a pilot, not a result.",
        flush=True,
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("typing", "dictation"), required=True)
    ap.add_argument("--phrases", type=int, default=len(PHRASES))
    ap.add_argument("--dry-run", action="store_true", help="print the prompts and exit")
    args = ap.parse_args(argv)

    if args.dry_run:
        for phrase in PHRASES[: args.phrases]:
            print(f"  {phrase}")
        return 0

    from _common import write_result

    payload = run(args.mode, args.phrases)
    write_result(f"throughput_{args.mode}", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
