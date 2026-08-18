"""No page may name a model other than the shipped default as "the default".

`docs/faq.md` said **twice** that the default model is `small.en`. It is `base.en` —
in `SttConfig`, on a running daemon, and in `models.md` and `benchmarks.md`, which
mark `base.en` **(default)** four times between them.

The FAQ is not an incidental page: it is written for search and answer engines, so it
is one of the first things a stranger reads, and one of the answers it got wrong was
the hardware question — *"4 GB RAM minimum … the default model is `small.en`"*. The
project's own table puts `small.en` at **1,340 MB** of RAM and a **5.05 s** median
decode against `base.en`'s **874 MB** and **1.56 s**, so the answer paired a memory
figure with a model that does not fit behind it.

## Why only two patterns

"the default `X`" is deliberately not matched. It legitimately describes the default
*engine* (`faster-whisper`), and in `models.md` that phrase even spans a line break —
so a generic matcher both cries wolf and is hard to read. The two forms below are the
ones that assert a **model** default, and they are the two the docs actually use.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.config import SttConfig
from yazses.stt.download import WHISPER_MODELS

DOCS = Path(__file__).resolve().parents[1] / "docs"
SKIP_TREES = {"releases", "research"}

#: "The default model is `base.en`" — optionally "(English)" in between, as the FAQ
#: phrases it.
_PROSE = re.compile(r"default model is\s+(?:English\s*\()?`([\w.\-/]+)`", re.IGNORECASE)
#: "| `base.en` **(default)** |" — the table form used by models.md and benchmarks.md.
_TABLE = re.compile(r"`([\w.\-/]+)`\s*\*\*\(default\)\*\*")


def _claims() -> list[tuple[str, str]]:
    """`(page, model)` for every place a page names the default model."""
    found: list[tuple[str, str]] = []
    for path in sorted(DOCS.rglob("*.md")):
        if SKIP_TREES & set(path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        found.extend((path.name, m) for m in _PROSE.findall(text))
        # The table form marks whatever the table is about. `models.md` uses it for
        # the default *engine* too (`faster-whisper` **(default)**), which is correct
        # and is not a model — so only values the shipped model registry knows are
        # treated as model claims. My synthetic test for this passed while the real
        # page failed: the mismatch was in the table pattern, not the prose one.
        found.extend(
            (path.name, m) for m in _TABLE.findall(text) if m in WHISPER_MODELS
        )
    return found


@pytest.fixture(scope="module")
def claims() -> list[tuple[str, str]]:
    return _claims()


def test_the_scan_finds_the_claims(claims) -> None:
    """A guard over an empty set passes on everything."""
    assert len(claims) >= 6, f"only {len(claims)} default-model claims found"
    assert {"models.md", "benchmarks.md"} <= {page for page, _m in claims}


def test_every_page_names_the_real_default_model(claims) -> None:
    real = SttConfig().model
    wrong = sorted({f"{page}: says {model!r}" for page, model in claims if model != real})
    assert not wrong, (
        f"the default model is {real!r}, but:\n  " + "\n  ".join(wrong)
        + "\n\nThese pages are what a stranger reads first, and the model decides the "
        "download size, the RAM, and the latency they should expect."
    )


def test_the_check_can_fail() -> None:
    """Only worth having if it fires — on the exact sentence that was wrong."""
    assert _PROSE.findall("The default model is English (`small.en`).") == ["small.en"]
    assert _TABLE.findall("| `base.en` **(default)** | 4.07 % |") == ["base.en"]


def test_the_engine_sentence_is_not_mistaken_for_a_model() -> None:
    """`models.md` calls `faster-whisper` the default engine, across a line break.

    A looser matcher flagged it, which would have made this guard wrong on day one
    about a page that is entirely correct.
    """
    assert SttConfig().engine == "faster-whisper"
    assert "faster-whisper" not in WHISPER_MODELS, (
        "the engine/model split this guard relies on has gone"
    )
    # The real page marks the engine with the same table convention as the models.
    # Checked against the actual file rather than a sentence I invented — inventing
    # one is what made this test pass while the guard failed.
    text = (DOCS / "models.md").read_text(encoding="utf-8")
    assert "faster-whisper" in _TABLE.findall(text), "models.md no longer marks it"
    assert ("models.md", "faster-whisper") not in _claims()
