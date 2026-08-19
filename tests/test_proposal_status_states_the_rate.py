"""`yazses tune` called a proposal "validated" on four percent corroboration.

Run against a real 1619-event corpus:

    [1] Upgrade the STT model   (evidence: 189 event(s); validated (9/238 held-out))
    [2] Add vocabulary          (evidence: 44 event(s); unverified — no held-out ...)

Nine out of 238 is under four percent. The bar for the word was `holdout_support > 0`, so
**one** corroborating event out of 238 would have earned it too — and it sat next to a
44-event proposal labelled "unverified", which reads as the weaker of the two.

The label was doing work the number should do, and in the direction that matters most:
these proposals write to `config.toml`, and "validated" invites applying one.

## No threshold was invented

The obvious fix is a minimum count or rate. Any value would have been a guess dressed as a
standard, and this repo has spent several passes learning that a constant chosen to fix
today's example is a constant that will be wrong on the next corpus.

Stating the rate needs no constant at all: a reader tells 4% from 84% without being told
which one counts. The zero case keeps its plain words, because *no* corroboration is a real
distinction rather than a small number.

## The one place a rate is not enough

`1 of 238` rounds to `0%`, and a displayed zero next to a non-zero count reads as a bug — a
reader is entitled to assume zero means zero. Support is non-zero inside that branch by
construction, so the rate is floored to `<1%` rather than rounded through it.

The label is display-only — nothing filters, sorts or gates on it — so wording is the whole
fix. Pinned here, because if that ever stops being true this file is where the assumption
is written down.
"""

from __future__ import annotations

import pytest

from yazses.learning.analysis import Proposal


def _status(support, size: int) -> str:
    return Proposal(
        kind="model", title="t", detail="d", evidence=1,
        holdout_support=support, holdout_size=size,
    ).status


def test_the_verdict_word_is_gone() -> None:
    """The defect: 9/238 and 238/238 got the same word."""
    for support in (1, 9, 100, 238):
        assert "validated (" not in _status(support, 238)


def test_weak_and_strong_corroboration_read_differently() -> None:
    """They read identically before — that is the whole point of the change."""
    weak = _status(9, 238)
    strong = _status(200, 238)
    assert weak != strong
    assert "4%" in weak
    assert "84%" in strong


def test_the_counts_are_still_shown() -> None:
    """The rate alone hides the sample size: 1 of 2 is 50% and means nothing."""
    status = _status(1, 2)
    assert "1 of 2" in status
    assert "50%" in status


@pytest.mark.parametrize(
    "support,size,expected",
    [
        (1, 238, "<1%"),
        (2, 238, "1%"),
        (9, 238, "4%"),
        (238, 238, "100%"),
    ],
)
def test_a_tiny_share_never_displays_as_zero(support, size, expected) -> None:
    """A displayed 0% beside a non-zero count reads as a bug, not as "very small"."""
    assert expected in _status(support, size)
    assert "(0%)" not in _status(support, size)


def test_no_corroboration_keeps_its_plain_words() -> None:
    """Zero is a distinction, not a small number — it must not become "0%"."""
    status = _status(0, 238)
    assert "unverified" in status
    assert "%" not in status


@pytest.mark.parametrize(
    "support,size,fragment",
    [
        (None, 0, "corpus too small"),
        (None, 238, "corpus too small"),
        (5, 0, "no distinct held-out data"),
    ],
)
def test_the_not_evaluated_cases_are_unchanged(support, size, fragment) -> None:
    """`None` means the check never ran, which is different from it finding nothing."""
    assert fragment in _status(support, size)


def test_the_label_is_display_only() -> None:
    """The reason a wording change is a complete fix.

    If anything ever filters or sorts on this string, that is a much larger change and
    this assumption needs revisiting — so it is written down here rather than assumed.
    """
    import subprocess

    out = subprocess.run(
        ["git", "grep", "-l", r"\.status\b", "--", "src/yazses/learning"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    assert all(f.endswith(("analysis.py", "tuner.py")) for f in out), (
        f"a new consumer of Proposal.status appeared in {out} — check it only displays it"
    )
