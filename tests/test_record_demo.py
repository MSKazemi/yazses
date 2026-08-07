"""Tests for the pure parts of scripts/record-demo.py.

The script is a contributor tool, not shipped code, but its two pure functions decide
whether a recording becomes a usable GIF or a silently broken one — a failure you only
notice by opening the file, which is exactly the check a hurried contributor skips.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL", reason="Pillow is a scripts-only dep, not a project dep")
from PIL import Image, ImageDraw, ImageSequence  # noqa: E402


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "record-demo.py"
    spec = importlib.util.spec_from_file_location("record_demo", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rec = _load_script()


def _dictation_frames(n: int = 30, blank_lead: int = 10):
    """Frames shaped like a real dictation demo: a still empty editor, then text."""
    words = "hold a key and speak".split()
    frames = []
    for i in range(n):
        im = Image.new("RGB", (400, 120), (30, 30, 40))
        shown = 0 if i < blank_lead else min(len(words), (i - blank_lead) // 3 + 1)
        ImageDraw.Draw(im).text((14, 50), " ".join(words[:shown]), fill=(230, 230, 240))
        frames.append(im)
    return frames


def test_dedupe_collapses_still_frames_and_conserves_time():
    frames = _dictation_frames()

    kept, durations = rec.dedupe(frames, durations_ms=83)

    assert len(kept) < len(frames), "identical frames were not collapsed"
    assert len(kept) == len(durations)
    assert sum(durations) == len(frames) * 83, "dedupe changed the clip's length"


def test_dedupe_of_all_identical_frames_yields_one():
    frames = [Image.new("RGB", (8, 8), (1, 2, 3)) for _ in range(5)]

    kept, durations = rec.dedupe(frames, durations_ms=100)

    assert len(kept) == 1
    assert durations == [500]


def test_palette_covers_frames_that_appear_later(tmp_path):
    """Regression: the palette must come from the whole clip, not from frame 0.

    A dictation demo opens on an empty editor. Building the palette from the first frame
    gave it almost no entries, so every later frame quantised to a flat block, the frames
    became identical, and the GIF writer collapsed them into a single-frame "animation" —
    a recording that looks fine in the terminal output and is useless in the README.
    """
    kept, durations = rec.dedupe(_dictation_frames(), durations_ms=83)
    palette = rec.build_palette(kept, colors=128)

    quantised = [f.quantize(palette=palette, dither=Image.FLOYDSTEINBERG) for f in kept]
    out = tmp_path / "demo.gif"
    quantised[0].save(
        out, save_all=True, append_images=quantised[1:], duration=durations, loop=0,
        optimize=True,
    )

    read_back = [f.convert("RGB").copy() for f in ImageSequence.Iterator(Image.open(out))]
    assert len(read_back) == len(kept), "frames were lost on write — palette too narrow"
    # The final frame carries the dictated text, so it must not be a flat block.
    assert len(read_back[-1].getcolors(maxcolors=1 << 24) or []) > 2


@pytest.mark.parametrize("spec", ["1,2,3", "a,b,c,d", "0,0,-5,10", "0,0,10,0", ""])
def test_parse_region_rejects_bad_input(spec):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        rec.parse_region(spec)


def test_parse_region_accepts_a_well_formed_region():
    assert rec.parse_region(" 100, 100 ,960,540 ") == (100, 100, 960, 540)


def test_trim_still_removes_dead_air_at_both_ends_only():
    """You start a long recording and perform whenever you're ready; the ends get cut.

    A pause in the *middle* is content — it's the wait while speech is transcribed — so it
    must survive. Only the leading and trailing motionless runs go.
    """
    blank = Image.new("RGB", (40, 20), (0, 0, 0))
    lit = Image.new("RGB", (40, 20), (255, 255, 255))
    # 20 still · 1 move · 8 still (mid-clip pause) · 1 move · 20 still
    frames = [blank] * 20 + [lit] + [blank] * 8 + [lit] + [blank] * 20

    out = rec.trim_still(frames, keep_head=2, keep_tail=4)

    assert len(out) < len(frames), "nothing was trimmed"
    # Both transitions must survive: two runs of `lit` remain.
    assert sum(1 for f in out if f.tobytes() == lit.tobytes()) == 2
    assert len(out) >= 12, "the mid-clip pause was destroyed"


def test_trim_still_on_a_completely_static_clip_is_safe():
    frames = [Image.new("RGB", (8, 8), (7, 7, 7)) for _ in range(10)]

    out = rec.trim_still(frames, keep_head=2, keep_tail=2)

    assert len(out) >= 1, "a static clip must not trim to nothing"


def test_trim_still_handles_no_frames():
    assert rec.trim_still([], keep_head=2, keep_tail=2) == []
