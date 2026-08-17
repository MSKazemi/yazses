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
) -> list[Proposal]:
    """Run the tuning flow. Returns the proposals that were applied."""
    if do_retranscribe and transcribe_fn is not None:
        # Announce the scale, then show movement. This is the slow step by a wide
        # margin -- on a real 3683-event corpus it ran for over eight minutes with
        # the model already cached and printed nothing at all, which is
        # indistinguishable from a hang. The count is a metadata query.
        def _progress(done: int, total: int) -> None:
            if total == 0:
                return
            if done == 0:
                echo(
                    f"Re-transcribing {total} captured clip(s) with the tune model — "
                    "the slow step; a large corpus can take a while."
                )
            elif done == total or done % 25 == 0:
                echo(f"  {done}/{total} clip(s)…")

        n = retranscribe(store, transcribe_fn, progress=_progress)
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
