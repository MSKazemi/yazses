"""An invalid redaction pattern stopped the daemon starting — the one thing config cannot do.

`[learning] redact_patterns` is a list of regexes scrubbed from text before it reaches the
encrypted corpus. `CorpusStore.__init__` compiles them, and `Daemon.__init__` calls
`build_writer` unguarded. Type coercion accepts any string for a `list[str]`, so:

    [learning]
    enabled = true
    redact_patterns = ["[unclosed", "\\d{4}"]

...loaded with **zero** `ConfigProblem`s, and then raised `re.PatternError` out of daemon
startup. The daemon did not start at all.

That is precisely what `configcheck` exists to prevent. Its own promise, from issue #52, is
that loading is total: *"no config file can stop the daemon starting"*. It repairs what it
can, falls back otherwise, and reports every decision. A regex it never compiles is a gap in
that guarantee, not an exception to it.

## Why capture is disabled rather than the pattern dropped

Dropping the bad pattern and capturing anyway is the obvious repair and it is the wrong one.
A pattern the user wrote to scrub secrets would be silently skipped, and the text it was
meant to remove would be written to the corpus. That is a worse outcome than either the
crash or the dormancy.

So `build_writer` fails **closed**: capture stays off, the log says why, and `configcheck`
reports the pattern so `yazses doctor` names it under Config validity. Both project promises
hold at once — the daemon starts, and nothing the user asked to scrub is stored unscrubbed.

## The two halves are independent on purpose

`configcheck` reports; `capture` decides. Neither depends on the other having run, so a
caller that builds a `LearningConfig` in code — a test, the settings window — is protected
by the same check.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from yazses.config import Config, load_config_checked
from yazses.configcheck import invalid_regexes
from yazses.learning.capture import build_writer

BAD = "[unclosed"
GOOD = r"\d{4}"


def _load(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return load_config_checked(path)


def test_the_premise_that_an_invalid_pattern_would_raise() -> None:
    """Without this the rest is theatre: the pattern must genuinely not compile."""
    with pytest.raises(re.error):
        re.compile(BAD)


def test_an_invalid_pattern_is_reported(tmp_path) -> None:
    result = _load(tmp_path, f'[learning]\nredact_patterns = ["{BAD}", "\\\\d{{4}}"]\n')
    problem = next(
        (p for p in result.problems if p.key == "redact_patterns"), None
    )
    assert problem is not None, "an uncompilable regex was accepted silently"
    assert BAD in str(problem), "the message must name the offending pattern"


def test_valid_patterns_are_not_reported(tmp_path) -> None:
    """The expensive direction: flagging a working pattern would disable capture."""
    result = _load(tmp_path, '[learning]\nredact_patterns = ["\\\\d{4}", "secret-\\\\w+"]\n')
    assert not [p for p in result.problems if p.key == "redact_patterns"]


def test_capture_is_disabled_rather_than_run_unredacted() -> None:
    """The decision this file exists to record.

    Dropping the pattern and capturing anyway would store text the user asked to scrub.
    """
    cfg = Config().learning
    cfg.enabled = True
    cfg.redact_patterns = [BAD, GOOD]
    assert build_writer(Path(tempfile.mkdtemp()), cfg) is None


def test_capture_still_works_with_valid_patterns() -> None:
    """A check that disabled capture outright would pass the test above."""
    cfg = Config().learning
    cfg.enabled = True
    cfg.redact_patterns = [GOOD]
    assert build_writer(Path(tempfile.mkdtemp()), cfg) is not None


def test_capture_stays_dormant_when_learning_is_off() -> None:
    """Unchanged behaviour; the new check must not resurrect a disabled feature."""
    cfg = Config().learning
    cfg.enabled = False
    cfg.redact_patterns = [GOOD]
    assert build_writer(Path(tempfile.mkdtemp()), cfg) is None


def test_the_daemon_can_still_be_constructed_past_this_point() -> None:
    """The guarantee: no config file stops the daemon starting.

    `Daemon.__init__` calls `build_writer` unguarded, so a raise there is fatal. Asserted
    on the call site, since constructing a daemon loads a speech model.
    """
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon)
    assert "build_writer(self._platform.paths.data_dir, cfg.learning)" in source, (
        "the corpus writer call site moved — re-check that an invalid redaction pattern "
        "still cannot raise out of startup"
    )


@pytest.mark.parametrize(
    "value,expected_bad",
    [
        ([BAD], [BAD]),
        ([GOOD], []),
        ([GOOD, BAD], [BAD]),
        ([], []),
        ("not a list", []),
    ],
)
def test_the_pure_checker(value, expected_bad) -> None:
    assert invalid_regexes("learning", "redact_patterns", value) == expected_bad


def test_only_the_regex_settings_are_checked() -> None:
    """A list of ordinary strings must not be required to compile."""
    assert invalid_regexes("filters.disfluency", "filler_words", ["um", "["]) == []
