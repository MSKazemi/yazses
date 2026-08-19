"""Orchestrates `yazses tune`: re-transcribe → analyze → present → apply.

Kept free of Typer/IO specifics (``echo``/``confirm`` are injected) so the flow
is unit-testable without a TTY or a real model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from yazses.config import Config
from yazses.learning.analysis import (
    Proposal,
    analyze_validated,
    apply_proposal,
    compute_edit_signals,
    retranscribe,
    toml_literal,
)
from yazses.learning.store import CorpusStore


def _format_eta(seconds: float) -> str:
    """A duration a person can act on. Pure.

    Coarse on purpose: the rate wanders with clip length, so "~52 min" claims a
    precision the measurement does not have. Rounded to 5 minutes above an hour and
    to a minute below it — enough to decide "wait" from "come back later", which is
    the only decision being supported.
    """
    if seconds < 90:
        return "under a minute left"
    minutes = seconds / 60
    if minutes < 60:
        return f"~{round(minutes)} min left"
    hours = minutes / 60
    if hours < 2:
        return f"~{round(minutes / 5) * 5} min left"
    return f"~{hours:.1f} h left"


def _eta(done: int, total: int, started: list[float], now: Callable[[], float]) -> str:
    """The trailing " — ~N min left", or "" when there is nothing honest to say.

    Silent rather than wrong in three cases: no start time recorded, no measurable
    elapsed time yet (a clock with one-second resolution can report 0.0), and the
    final tick, where an estimate of the time remaining is zero by definition and
    printing it reads as a fault.
    """
    if not started or done >= total:
        return ""
    elapsed = now() - started[0]
    if elapsed <= 0 or done <= 0:
        return ""
    remaining = (elapsed / done) * (total - done)
    return f" — {_format_eta(remaining)}"


def run_tune(
    store: CorpusStore,
    config: Config,
    config_path: Path,
    few_shots_path: Path,
    *,
    do_apply: bool,
    do_retranscribe: bool,
    transcribe_fn: Callable | None,
    echo: Callable[[str], None],
    confirm: Callable[[str], bool],
    limit: int | None = None,
    clock: Callable[[], float] | None = None,
) -> list[Proposal]:
    """Run the tuning flow. Returns the proposals that were applied.

    ``limit`` bounds re-transcription to the most recent N clips. ``clock`` is
    injected so the estimate below can be tested without waiting.
    """
    import time

    now = clock or time.monotonic
    if do_retranscribe and transcribe_fn is not None:
        # Announce the scale, then show movement. This is the slow step by a wide
        # margin -- on a real 3683-event corpus it ran for over eight minutes with
        # the model already cached and printed nothing at all, which is
        # indistinguishable from a hang. The count is a metadata query.
        started: list[float] = []

        def _progress(done: int, total: int) -> None:
            if total == 0:
                return
            if done == 0:
                started.append(now())
                echo(
                    f"Re-transcribing {total} captured clip(s) with the tune model — "
                    "the slow step; a large corpus can take a while."
                )
            elif done == total or done % 25 == 0:
                # "A while" is honest and useless: on a real corpus this runs for
                # hours, and a number is a decision ("run it overnight", "use
                # --limit"), while "a while" is not. The rate is only knowable once
                # some clips are done, so the estimate appears with the first count
                # rather than being guessed up front.
                #
                # ⚠ "about an hour" is what this comment and `--limit`'s help both
                # said, and it was wrong by 3-4x. Measured 2026-08-20: 50 clips in
                # 510 s wall clock with small.en on a laptop CPU -- 9.6 s each, and
                # a corpus sitting on the product's own default 500 MB cap holds
                # ~1460, i.e. **~3.9 h**. The understatement mattered precisely
                # because the number is the decision: an hour is something you wait
                # for, four hours is something you schedule.
                echo(f"  {done}/{total} clip(s)…{_eta(done, total, started, now)}")

        n = retranscribe(store, transcribe_fn, limit=limit, progress=_progress)
        echo(f"Re-transcribed {n} captured clip(s) for ground-truth comparison.")

    # Passive signal (a): infer corrections from re-dictations / "scratch that".
    events = store.events()
    edits = compute_edit_signals(events, config)
    for eid, sig in edits.items():
        store.set_edit_signal(eid, sig)
    if edits:
        echo(f"Inferred {len(edits)} likely correction(s) from follow-up dictations.")

    proposals = analyze_validated(store.events(), config)
    if not proposals:
        echo("No tuning proposals — the corpus looks clean or is too small yet.")
        return []

    echo(f"Found {len(proposals)} proposal(s):")
    applied: list[Proposal] = []
    for i, p in enumerate(proposals, 1):
        echo(f"\n[{i}] {p.title}   (evidence: {p.evidence} event(s); {p.status})")
        echo(f"    {p.detail}")
        if p.target == "config":
            echo(f"    → config.toml: [{p.section}] {p.key} = {toml_literal(p.value)}")
        else:
            for ex in p.examples:
                echo(f"    → few_shots.toml: {ex}")

        if do_apply and confirm(f"Apply change [{i}] ({p.title})?"):
            msg = apply_proposal(p, config_path, few_shots_path)
            echo(f"    ✓ applied: {msg}")
            applied.append(p)

    if not do_apply:
        echo("\nDry run — nothing changed. Re-run with --apply to choose changes.")
    elif applied and any(p.section in ("stt", "accessibility") for p in applied):
        echo("\nRestart to pick up changes:  yazses stop && yazses start")
    return applied
