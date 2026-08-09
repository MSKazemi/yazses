"""The committed asciinema cast is a shipped artifact — keep it valid and clean (issue #23).

`docs/demo/yazses-cli.cast` is linked from the README and the docs home, so a player has
to be able to read it, and it must not carry anything from the machine that recorded it.
Regenerating it is a manual step (`scripts/gen-terminal-demo.py`), which is exactly why
the file itself is worth asserting on rather than the generator alone.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CAST = Path(__file__).resolve().parent.parent / "docs" / "demo" / "yazses-cli.cast"

# Anything that would identify the machine the recording was made on.
_MACHINE_SPECIFIC = (
    re.compile(r"/home/[^\s\"']+"),
    re.compile(r"/Users/[^\s\"']+"),
    re.compile(r"[A-Za-z]:\\\\Users", re.IGNORECASE),
    re.compile(r"AppData"),
)


def _events():
    lines = CAST.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [json.loads(x) for x in lines[1:] if x.strip()]


@pytest.mark.skipif(not CAST.exists(), reason="cast not present in this tree")
def test_cast_header_is_asciicast_v2():
    header, _ = _events()
    assert header["version"] == 2
    assert header["width"] > 0 and header["height"] > 0
    assert header["title"]


@pytest.mark.skipif(not CAST.exists(), reason="cast not present in this tree")
def test_cast_events_are_well_formed_and_monotonic():
    _, events = _events()
    assert events, "a cast with no events plays as a blank screen"
    last = -1.0
    for when, kind, data in events:
        assert kind == "o"
        assert isinstance(data, str)
        assert when >= last, "a player seeks on these timestamps; they must not go backwards"
        last = when


@pytest.mark.skipif(not CAST.exists(), reason="cast not present in this tree")
def test_cast_leaks_no_machine_specific_paths():
    _, events = _events()
    text = "".join(e[2] for e in events)
    for pattern in _MACHINE_SPECIFIC:
        assert not pattern.search(text), f"cast leaks {pattern.pattern}"


@pytest.mark.skipif(not CAST.exists(), reason="cast not present in this tree")
def test_every_recorded_prompt_starts_on_its_own_line():
    # The `features` output is truncated by the generator; without a trailing newline the
    # next prompt was drawn onto the end of the truncation note.
    _, events = _events()
    plain = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", "".join(e[2] for e in events))
    for line in plain.split("\r\n"):
        assert "$ yazses" not in line or line.startswith("$ yazses"), (
            f"a shell prompt is glued to the end of the previous output: {line!r}"
        )
