"""Decode-latency percentiles, per model (#296).

Per-utterance decode time has always been measured and logged — the daemon writes
``Transcribed 3.2s audio in 740 ms (model small.en, ...)`` after every burst — but
it was never summarised, so the one number that predicts whether dictation *feels*
usable was only available by reading a log by eye.

## Why percentiles, and why not a mean

Decode time is right-skewed: most utterances are fast and a minority are slow. The
slow ones are the whole experience, because that is the moment you are sitting
there with the key already released, waiting. A mean averages that tail away and
looks fine the entire time; **p95 is the number that predicts "this feels laggy"**.

## Why per model

It turns "should I run `tiny.en` or `base.en` on this machine" from a guess into a
measurement the user already has the data for. `docs/benchmarks.md` gives figures
for one machine — this gives each user theirs, on their hardware, with their audio.

## What it deliberately does not do

* **It does not require `[learning]`.** A diagnostic that needs an opt-in corpus
  turned on is not available when you need it. Samples live in a bounded in-memory
  window owned by the daemon; nothing is written to disk and no audio or text is
  involved, so ADR-011 is untouched.
* **It does not report a percentile it cannot support.** p95 over six utterances
  is not a p95, and printing one without saying so invites reading it as one — so
  the count travels with the summary and `p95_ms` is ``None`` below
  :data:`MIN_SAMPLES_FOR_P95`.
* **It does not average over the lifetime of an install.** The window is bounded,
  so the numbers still move after a model change — which is exactly when someone
  looks at them.

Pure and dependency-free: a list of samples in, a summary out. The clock and the
event source are the caller's business.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# How many recent utterances to keep, per model. Large enough that p95 means
# something, small enough that a model or hardware change shows up quickly — and
# small enough that the memory is irrelevant (a few hundred floats).
DEFAULT_WINDOW = 200

# Below this, a "p95" is one of the two or three slowest samples wearing a
# statistical name. Reported as None rather than as a number nobody should trust.
MIN_SAMPLES_FOR_P95 = 20


@dataclass(frozen=True)
class LatencySummary:
    """Decode latency for one model over the recent window."""

    model: str
    count: int
    p50_ms: float
    p95_ms: float | None      # None until the window holds enough samples
    max_ms: float

    @property
    def p95_is_reportable(self) -> bool:
        return self.p95_ms is not None

    def describe(self) -> str:
        """One line, honest about how much it is based on."""
        head = f"{self.model}: p50 {self.p50_ms:.0f} ms"
        if self.p95_ms is None:
            return f"{head} (n={self.count}, too few for p95)"
        return f"{head}, p95 {self.p95_ms:.0f} ms (n={self.count})"


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of *values*.

    Nearest-rank rather than an interpolating variant on purpose: every result is
    a latency that actually happened, so "p95 = 910 ms" names a real utterance
    someone waited through rather than a weighted average of two of them.
    """
    if not values:
        raise ValueError("percentile of no samples")
    ordered = sorted(values)
    if fraction <= 0:
        return float(ordered[0])
    if fraction >= 1:
        return float(ordered[-1])
    # Nearest-rank: ceil(fraction * n), 1-indexed. The rounding guards the case
    # where 0.95 * 20 lands at 18.999999999999996 and silently picks rank 19.
    rank = math.ceil(round(fraction * len(ordered), 9))
    rank = min(max(rank, 1), len(ordered))
    return float(ordered[rank - 1])


def summarise(model: str, samples: Iterable[float]) -> LatencySummary | None:
    """Summarise one model's samples, or None when there are none."""
    values = [float(s) for s in samples if s is not None and float(s) >= 0.0]
    if not values:
        return None
    return LatencySummary(
        model=model,
        count=len(values),
        p50_ms=percentile(values, 0.50),
        p95_ms=percentile(values, 0.95) if len(values) >= MIN_SAMPLES_FOR_P95 else None,
        max_ms=max(values),
    )


class LatencyWindow:
    """A bounded, per-model window of recent decode times.

    Owned by the daemon and read over IPC. Not thread-safe by itself — the daemon
    records under the lock it already holds around the decode path.
    """

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._window = max(1, int(window))
        self._by_model: dict[str, deque[float]] = {}

    def record(self, model: str, decode_ms: float) -> None:
        """Note one decode. Bad input is dropped, never raised into dictation."""
        try:
            value = float(decode_ms)
        except (TypeError, ValueError):
            return
        # A negative or non-finite duration is a clock artefact, not a measurement.
        if not math.isfinite(value) or value < 0.0:
            return
        name = str(model or "unknown")
        samples = self._by_model.get(name)
        if samples is None:
            samples = self._by_model[name] = deque(maxlen=self._window)
        samples.append(value)

    def summaries(self) -> list[LatencySummary]:
        """One summary per model seen, most-sampled first."""
        out = [s for s in (summarise(m, v) for m, v in self._by_model.items()) if s]
        return sorted(out, key=lambda s: (-s.count, s.model))

    def as_dict(self) -> list[dict[str, object]]:
        """JSON-safe form for the `status` IPC payload."""
        return [
            {
                "model": s.model,
                "count": s.count,
                "p50_ms": round(s.p50_ms, 1),
                "p95_ms": round(s.p95_ms, 1) if s.p95_ms is not None else None,
                "max_ms": round(s.max_ms, 1),
            }
            for s in self.summaries()
        ]


def render_status_lines(entries: Sequence[dict] | None) -> list[str]:
    """The lines `yazses status` prints. Empty when nothing has been decoded yet.

    Kept here rather than in the CLI so the wording is tested with the maths, and
    so the count is impossible to drop on the way to the screen.
    """
    if not entries:
        return []
    lines = []
    for entry in entries:
        model = entry.get("model", "unknown")
        count = int(entry.get("count") or 0)
        p50 = entry.get("p50_ms")
        p95 = entry.get("p95_ms")
        if p50 is None:
            continue
        if p95 is None:
            lines.append(f"  latency:  {model} p50 {float(p50):.0f} ms "
                         f"(n={count}, need {MIN_SAMPLES_FOR_P95} for p95)")
        else:
            lines.append(f"  latency:  {model} p50 {float(p50):.0f} ms / "
                         f"p95 {float(p95):.0f} ms (n={count})")
    return lines
