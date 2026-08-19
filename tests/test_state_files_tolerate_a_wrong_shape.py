"""Two state-file loaders promised tolerance and each missed one exception.

Both docstrings already commit to it — `load_calibration` returns *"None if
absent/unreadable"*, `load_state` returns *"zeros if absent/unreadable"* — and both handled
a missing file, an empty one, unparseable JSON and bad bytes. Both were defeated by the same
input: **valid JSON that is not an object.**

    gaze_calibration.json  containing  "a string"  ->  TypeError: string indices must be integers
    wordgoal.json          containing  "a string"  ->  AttributeError: 'str' object has no attribute 'get'

A well-formed document of the wrong shape is unreadable in exactly the sense those
docstrings mean, and neither `except` tuple listed the exception it produces.

## What each cost

`yazses wordgoal status` answered with a traceback. The gaze one was caught by a blanket
`except Exception` in `_build_gaze_targeter`, so it degraded to "gaze dormant" — correct by
accident, and only because a caller happened to be defensive. Relying on that is how the
other three files in this class (`macros.toml`, `redact_patterns`, `vocabulary.txt`) turned
into daemon failures.

## Scope

Only the exception each loader already meant to catch. Nothing about *which* wrong shapes
are worth reading — a string where a table belongs is not recoverable data, it is a
corrupted file, and the documented answer to that is already "start over from the default".
"""

from __future__ import annotations

import shutil

import pytest

from yazses.gaze.store import calibration_path, load_calibration
from yazses.wordgoal.store import load_state, wordgoal_path

#: JSON that parses cleanly and is not a table.
WRONG_SHAPE = [b'"a string"', b"[1, 2, 3]", b"42", b"true", b"null"]
#: The cases both loaders already handled; kept so a fix cannot regress them.
ALREADY_HANDLED = [b"", b"{not json", b"\xff\xfe"]


@pytest.mark.parametrize("body", WRONG_SHAPE + ALREADY_HANDLED)
def test_gaze_calibration_degrades_to_none(tmp_path, body: bytes) -> None:
    path = calibration_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    assert load_calibration(tmp_path) is None


@pytest.mark.parametrize("body", WRONG_SHAPE + ALREADY_HANDLED)
def test_wordgoal_state_degrades_to_zeros(tmp_path, body: bytes) -> None:
    path = wordgoal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    assert load_state(path) == {"count": 0, "goal": 0}


def test_a_missing_file_is_still_the_default(tmp_path) -> None:
    assert load_calibration(tmp_path) is None
    assert load_state(wordgoal_path(tmp_path)) == {"count": 0, "goal": 0}


def test_a_directory_is_still_the_default(tmp_path) -> None:
    for path in (calibration_path(tmp_path), wordgoal_path(tmp_path)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
    try:
        assert load_calibration(tmp_path) is None
        assert load_state(wordgoal_path(tmp_path)) == {"count": 0, "goal": 0}
    finally:
        for path in (calibration_path(tmp_path), wordgoal_path(tmp_path)):
            shutil.rmtree(path)


def test_a_real_wordgoal_state_still_loads(tmp_path) -> None:
    """The expensive direction: a loader that returned zeros for everything would pass
    every test above and silently discard the user's word count."""
    path = wordgoal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"count": 1200, "goal": 2000}', encoding="utf-8")
    assert load_state(path) == {"count": 1200, "goal": 2000}


def test_a_real_calibration_still_loads(tmp_path) -> None:
    """Same, for gaze: refusing every file would disable look-to-pane for everyone."""
    import json

    path = calibration_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"A": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]}), encoding="utf-8")
    loaded = load_calibration(tmp_path)
    assert loaded is not None
    assert loaded.A.shape == (2, 3)


def test_a_calibration_of_the_wrong_dimensions_is_still_refused(tmp_path) -> None:
    """Pre-existing behaviour, pinned because the widened `except` sits beside it."""
    import json

    path = calibration_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"A": [[1.0, 0.0]]}), encoding="utf-8")
    assert load_calibration(tmp_path) is None


def test_negative_counts_are_still_clamped(tmp_path) -> None:
    """The other pre-existing repair in `load_state`."""
    path = wordgoal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"count": -5, "goal": -1}', encoding="utf-8")
    assert load_state(path) == {"count": 0, "goal": 0}
