"""`inject/payload.py`: describe a keystroke tool's payload, never quote it. Pure.

The end-to-end tests are in `test_no_log_record_carries_dictated_text.py`; these pin the
two properties the backends rely on, without running anything.
"""
from __future__ import annotations

import pickle
import subprocess

import pytest

from yazses.inject.payload import describe_argv, hide_payload


def test_everything_after_the_end_of_options_is_described_by_length():
    assert describe_argv(["wtype", "--", "hello"]) == ["wtype", "--", "<5 chars>"]
    assert describe_argv(["ydotool", "type", "-d", "6", "--", "a b", "c"]) == [
        "ydotool", "type", "-d", "6", "--", "<3 chars>", "<1 chars>",
    ]


def test_an_argv_without_a_payload_is_unchanged():
    """Key names and counts are what diagnoses a failure, and nobody said them."""
    argv = ["xdotool", "key", "--repeat", "3", "BackSpace"]
    assert describe_argv(argv) == argv


def test_only_the_first_end_of_options_counts():
    """A transcript that *is* `--` must not switch the description back off."""
    assert describe_argv(["wtype", "--", "--", "secret"]) == [
        "wtype", "--", "<2 chars>", "<6 chars>",
    ]



def _raise(exc: BaseException) -> None:
    """Raise *exc* from a call, as the injectors' subprocess helpers do."""
    raise exc

@pytest.mark.parametrize(
    "exc",
    [
        subprocess.CalledProcessError(1, ["wtype", "--", "my pin is 8812"], stderr="no"),
        subprocess.TimeoutExpired(["xdotool", "type", "--", "my pin is 8812"], 10),
    ],
    ids=["called-process-error", "timeout-expired"],
)
def test_the_same_exception_propagates_without_the_text(exc):
    with pytest.raises(type(exc)) as caught:
        with hide_payload():
            _raise(exc)

    assert caught.value is exc, "a new exception would break `except` clauses and chaining"
    for rendered in (str(exc), repr(exc), repr(exc.args), str(exc.cmd)):
        assert "8812" not in rendered, rendered
    assert "<14 chars>" in str(exc)
    # Still a well-formed exception of its type.
    assert pickle.loads(pickle.dumps(exc)).cmd == exc.cmd


def test_other_exceptions_pass_through_untouched():
    err = FileNotFoundError(2, "No such file or directory", "wtype")
    with pytest.raises(FileNotFoundError) as caught:
        with hide_payload():
            _raise(err)
    assert caught.value is err
    assert caught.value.filename == "wtype"


def test_the_return_code_survives():
    with pytest.raises(subprocess.CalledProcessError) as caught:
        with hide_payload():
            _raise(subprocess.CalledProcessError(3, ["wl-copy", "--", "x"]))
    assert caught.value.returncode == 3
    assert "exit status 3" in str(caught.value)
