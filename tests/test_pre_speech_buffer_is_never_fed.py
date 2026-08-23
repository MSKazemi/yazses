"""The pre-speech ring buffer is never filled, and that is load-bearing.

`audio/padding.py` describes a ring buffer that "retains the last N ms of audio and
prepends it to each recording", for people whose voice onset is delayed — the
docstring names ALS and Parkinson's. The daemon constructs it (`core/daemon.py`) and
reads it at hold-start to seed the streaming engine.

**Nothing ever pushes into it.** Grepped and confirmed: the only references are the
two constructions and one `.get()`. An unfed buffer returns an array of size 0, and
the caller guards on `padding.size > 0`, so the seeding is a no-op.

## Why this is a guard and not a bug fix

Its own docstring says how it is meant to be fed: *"During idle: call `buf.push(chunk)`
with each audio chunk."* Doing that means **capturing audio continuously while the key
is up** — which contradicts the single loudest promise this project makes, restated on
the comparison page as *"Nothing is listening when the key is up."* That sentence is
true **because** this buffer is never fed.

So the obvious fix is the dangerous one. Someone tidying up a component that is
constructed and read but never written would, in one plausible commit, turn a
hold-to-talk dictation tool into one that records the room. This test makes that
commit fail and forces the trade to be made deliberately rather than as cleanup.

## What the surviving path does and does not do

`[accessibility] pre_speech_padding_ms` still has a second, live effect:
`core/daemon.py` prepends `np.zeros(...)` — synthetic silence, not captured audio —
before decode. That half was measured on 200 LibriSpeech utterances (see
`docs/benchmarks.md`, "The 300 ms of silence before every decode") and it is much
narrower than the note beside it claimed:

* onset intact — no effect at all, every lead from 0 to 1000 ms inside the
  run-to-run noise band;
* 40 ms of speech missing — the lead-in buys back 6 opening words in 200;
* 120 ms missing — it *costs* 11, and 240 ms missing costs 4.

So the setting is not a fix for a clipped onset; it is a small win in the mildest
case and a small loss past that. Prepended silence cannot reconstruct audio that was
never captured, which is precisely why the retained-audio variant is the one that
would work — and why it is not wired.

Whether the accessibility case (a genuinely delayed onset, where the quiet speech
happened before the key went down) is worth the privacy cost is the owner's call, not
a cleanup decision.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from yazses.audio.padding import PreSpeechRingBuffer

SRC = Path(__file__).resolve().parents[1] / "src" / "yazses"


def _push_calls_on_the_padding_buffer() -> list[str]:
    """Every `<something padding-ish>.push(...)` in the package."""
    hits: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - fails loudly elsewhere
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "push":
                continue
            target = ast.unparse(node.func.value)
            if "padding" in target.lower():
                hits.append(f"{path.relative_to(SRC.parent.parent)}:{node.lineno}: {target}.push(...)")
    return hits


def test_the_scan_can_see_push_calls_at_all() -> None:
    """Guard the guard: if `.push(` matched nothing anywhere, the check below would
    pass vacuously. The streaming engine is pushed to on the same hot path."""
    source = (SRC / "core" / "daemon.py").read_text(encoding="utf-8")
    assert ".push(" in source, "no push call found in daemon.py — the matcher is broken"


def test_nothing_feeds_the_pre_speech_ring_buffer() -> None:
    """Feeding it means capturing while idle. That is the whole point of this file."""
    hits = _push_calls_on_the_padding_buffer()
    assert not hits, (
        "something now pushes audio into the pre-speech ring buffer:\n  "
        + "\n  ".join(hits)
        + "\n\nIts docstring says to feed it 'during idle', which means capturing "
        "audio while the hotkey is UP. YazSes promises the opposite, and the public "
        "comparison page states it outright: 'Nothing is listening when the key is "
        "up.' If continuous capture is genuinely wanted for delayed voice onset, "
        "that is a product decision with a privacy cost — make it deliberately, "
        "update the promise, and change this test on purpose."
    )


def test_an_unfed_buffer_contributes_nothing() -> None:
    """So the seeding call at hold-start is a no-op rather than silent zeros."""
    buf = PreSpeechRingBuffer(padding_ms=300, sample_rate=16000)
    assert buf.get().size == 0


def test_the_buffer_would_work_if_it_were_fed() -> None:
    """The component is correct; it is uncalled. Worth pinning so a future decision
    to wire it starts from a working part rather than a rewrite."""
    buf = PreSpeechRingBuffer(padding_ms=100, sample_rate=16000)
    buf.push(np.ones(1600, dtype=np.float32))
    assert buf.get().size == 1600


def test_the_documented_silence_lead_in_is_a_different_mechanism() -> None:
    """`pre_speech_padding_ms` still works — through synthetic silence, not capture.

    Pinned because the two are easy to conflate, and conflating them is what would
    make "the padding does nothing" look true and invite the dangerous fix.
    """
    source = (SRC / "core" / "daemon.py").read_text(encoding="utf-8")
    assert "np.zeros(" in source
    assert "pre_speech_padding_ms" in source
