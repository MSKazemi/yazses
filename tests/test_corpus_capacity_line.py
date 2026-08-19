"""`yazses corpus status` printed a size with nothing to compare it against.

Found on a real corpus:

      events:    1619 (200 discarded, 0 flagged wrong)
      size:      500.0 MB
      range:     2026-08-07T13:08:31 → 2026-08-19T03:35:24

500.0 MB is exactly `[learning] max_corpus_mb`. The corpus was sitting *on* its cap, and
`Store.prune()` was evicting the oldest events on every capture to hold it there — which is
the one fact that line failed to convey. It read identically to a corpus with room to spare.

That matters beyond tidiness: `yazses tune` learns from what survives, so a silently
evicting corpus quietly changes what the product can learn about you, and the date range
gives no hint — a corpus that starts twelve days ago looks the same whether you enabled
capture twelve days ago or the cap deleted everything before it.

## Both limits are named, because they are not interchangeable

`prune(retention_days, max_mb)` applies age first, then size. Either can be the binding
one, and they discard different things: age eviction drops what is stale, size eviction
drops what is oldest *regardless of how recent that is*. On a busy corpus the size cap can
bind at a fraction of the retention window, so naming only one would mislead.

## The 95% line is a display choice, and is labelled as one

`prune` evicts while `disk_size > max_bytes`, so a corpus held at the cap always measures a
hair *under* it — "500.0 of 500 MB" would otherwise read as headroom. Nothing in the store
consults `_NEARLY_FULL`; it decides only what the CLI calls full.
"""

from __future__ import annotations

import pytest

from yazses.learning.store import capacity_line

MB = 1_048_576


def test_a_corpus_on_its_cap_says_so() -> None:
    """The case that prompted this: 500.0 MB against a 500 MB cap, reading as fine."""
    text, warning = capacity_line(500 * MB, 500, 30)
    assert "500 MB" in text
    assert warning is not None
    assert "full" in warning
    assert "evicted" in warning


def test_the_warning_names_both_limits_and_the_knob() -> None:
    _text, warning = capacity_line(500 * MB, 500, 30)
    assert "30 days" in warning
    assert "500 MB" in warning
    assert "max_corpus_mb" in warning, "a user told the corpus is full needs the setting"


def test_a_corpus_with_room_is_not_warned_about() -> None:
    """The opposite failure: a warning on every corpus is a warning on none."""
    text, warning = capacity_line(12 * MB, 500, 30)
    assert warning is None
    assert "12.0 MB of 500 MB" == text


def test_the_size_is_always_shown_against_the_cap() -> None:
    """Even below the line, the bare number was the original defect."""
    for size_mb in (1, 100, 400):
        text, _warning = capacity_line(size_mb * MB, 500, 30)
        assert "of 500 MB" in text


@pytest.mark.parametrize("size_mb,warned", [(474, False), (475, True), (500, True)])
def test_the_display_threshold_is_where_it_says_it_is(size_mb: int, warned: bool) -> None:
    """95% of 500 MB is 475. Pinned so moving it is a decision, not a drift."""
    _text, warning = capacity_line(size_mb * MB, 500, 30)
    assert (warning is not None) is warned


def test_no_cap_is_reported_as_no_cap_rather_than_as_full() -> None:
    """`max_corpus_mb = 0` disables the size limit; dividing by it would warn on
    every corpus, which is the loudest possible way to be wrong."""
    text, warning = capacity_line(9000 * MB, 0, 30)
    assert warning is None
    assert "no size cap" in text


def test_no_age_limit_is_described_honestly() -> None:
    """`retention_days = 0` disables age eviction — saying "0 days" would be false."""
    _text, warning = capacity_line(500 * MB, 500, 0)
    assert warning is not None
    assert "no age limit" in warning
    assert "0 days" not in warning


def test_an_empty_corpus_does_not_warn() -> None:
    text, warning = capacity_line(0, 500, 30)
    assert warning is None
    assert text.startswith("0.0 MB")


def test_it_is_pure() -> None:
    """No store, no config object, no filesystem — so a check can call it too."""
    import inspect

    source = inspect.getsource(capacity_line)
    for forbidden in ("open(", "Path(", "load_config", "sqlite3"):
        assert forbidden not in source
