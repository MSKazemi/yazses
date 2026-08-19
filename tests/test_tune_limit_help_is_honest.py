"""`--limit`'s help promised "a full corpus can take an hour". It is 3-4x that.

Measured 2026-08-20 on a real corpus, with `--limit 50`:

    Re-transcribing 50 captured clip(s) with the tune model …
      25/50 clip(s)… — ~4 min left
      50/50 clip(s)…
    ---- wall clock: 510s

9.6 s per clip with `small.en` on a laptop CPU. The corpus was sitting on the product's own
default `max_corpus_mb = 500`, which held **1460 clips** — so a full run is about **3.9
hours**. An earlier interrupted run estimated 2.7 h from its first 25 clips; either way, not
one hour.

The number is the whole point of saying it. The command's own code comment explains why:
*"an hour is a decision (run it overnight, use --limit), while 'a while' is not."* An hour is
something you wait for; four hours is something you schedule. Understating it by 3-4x turns
the help from a decision aid into a reason to be surprised.

Per-clip is the honest unit here, and not by accident: `faster_whisper` calls `pad_or_trim`,
which pads every clip's mel to 3000 frames — 30 s — before the encoder sees it. So decode
cost is near-constant per clip regardless of how long the clip is, and clip *count* predicts
runtime far better than corpus duration does.

This checks the shape of the claim, not a hardcoded string: a total-duration promise cannot
be true for every machine, while a per-clip rate with the machine named can.
"""

from __future__ import annotations

from yazses.cli import app


def _limit_help() -> str:
    from typer.main import get_command

    group = get_command(app)
    tune = group.commands["tune"]  # type: ignore[attr-defined]
    for param in tune.params:
        if param.name == "limit":
            return param.help or ""
    raise AssertionError("`yazses tune` has no --limit option any more")


def test_the_help_no_longer_promises_one_hour() -> None:
    assert "can take an hour" not in _limit_help()


def test_the_help_gives_a_per_clip_rate_rather_than_a_total() -> None:
    """A total cannot be true for every machine; a per-clip rate with the hardware
    named can, and the reader can multiply by a count the command prints."""
    help_text = _limit_help()
    assert "per clip" in help_text
    assert "CPU" in help_text


def test_the_help_says_a_full_run_is_hours() -> None:
    """The decision the number exists to support."""
    assert "hours" in _limit_help()
