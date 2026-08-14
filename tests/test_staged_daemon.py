"""Staged dictation wired into the daemon and its IPC (#294).

The pure buffer is covered in `test_staged_buffer.py`. What is tested here is the
promise the feature actually makes: **with staged mode on, a burst does not reach
the application**, and the text a user staged does not go missing.
"""

from __future__ import annotations

from dataclasses import replace

from yazses.config import Config, StagedConfig
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform


def _daemon(mocker, **staged):
    cfg = replace(Config(), staged=StagedConfig(enabled=True, **staged))
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_staged = mocker.MagicMock()
    return d


def _staged(d, action="status"):
    return d._handle_staged(Request(method="staged", params={"action": action}, id=1))


# ---- the promise: nothing types until commit -------------------------------


def test_a_burst_is_staged_rather_than_typed(mocker):
    d = _daemon(mocker)
    event: dict = {}
    assert d._stage_or_commit("rm minus rf slash tmp", event) is None
    assert event["staged_action"] == "stage"
    assert d._staged.text == "rm minus rf slash tmp"


def test_staged_mode_off_leaves_the_pipeline_untouched(mocker):
    """An existing install must not change behaviour when the feature ships."""
    cfg = replace(Config(), staged=StagedConfig())
    assert cfg.staged.enabled is False
    d = Daemon(config=cfg, platform=get_platform())
    assert d._staged.is_empty


def test_a_spoken_commit_returns_the_buffer_not_the_words_that_triggered_it(mocker):
    """Typing "commit that" into the editor would be an easy and absurd bug."""
    d = _daemon(mocker, spoken_commit=True)
    d._stage_or_commit("print hello world", {})
    text = d._stage_or_commit("commit that", {})
    assert text == "print hello world"
    assert d._staged.is_empty


def test_a_spoken_commit_falls_through_so_the_target_guard_still_applies(mocker):
    """Staged mode has no business bypassing the no-text-target guard."""
    import inspect

    source = inspect.getsource(Daemon._on_hold_end)
    staged_at = source.index("_stage_or_commit")
    # Match the CALL, not the bare name. Searching for `_handle_no_target`
    # also matched a comment that merely mentions it — an unrelated change
    # explaining why the command-mode branch does *not* reuse the helper made
    # this fail, because `index()` returns the first hit anywhere in the
    # source, comments included.
    guard_at = source.index("self._handle_no_target(")
    assert staged_at < guard_at, "the commit must reach the guard, not skip it"


def test_commit_words_inside_a_sentence_are_staged(mocker):
    d = _daemon(mocker, spoken_commit=True)
    assert d._stage_or_commit("git commit minus m fix the parser", {}) is None
    assert "git commit" in d._staged.text


def test_an_empty_spoken_commit_says_so_rather_than_typing_nothing(mocker):
    d = _daemon(mocker, spoken_commit=True)
    assert d._stage_or_commit("commit that", {}) is None
    assert d._notify_staged.call_count == 1
    assert "Nothing staged" in d._notify_staged.call_args[0][0]


def test_a_runaway_buffer_is_refused_rather_than_growing_without_bound(mocker):
    d = _daemon(mocker, max_chunks=3)
    for i in range(3):
        d._stage_or_commit(f"burst {i}", {})
    event: dict = {}
    assert d._stage_or_commit("one too many", event) is None
    assert event["staged_action"] == "full"
    assert len(d._staged.chunks) == 3, "the burst is refused, not silently dropped in"


def test_spoken_undo_removes_the_last_burst(mocker):
    d = _daemon(mocker)
    d._stage_or_commit("keep this", {})
    d._stage_or_commit("but not this", {})
    assert d._stage_or_commit("scratch that", {}) is None
    assert d._staged.text == "keep this"


# ---- IPC: the deterministic path -------------------------------------------


def test_ipc_commit_injects_the_buffer_once(mocker):
    d = _daemon(mocker)
    injector = mocker.MagicMock()
    d._injector = injector
    d._stage_or_commit("hello world", {})

    result = _staged(d, "commit")

    assert result["committed"] is True
    injector.inject.assert_called_once_with("hello world")
    assert d._staged.is_empty
    assert _staged(d, "commit")["committed"] is False, "a second commit must not retype"


def test_a_failing_injector_puts_the_text_back_rather_than_losing_it(mocker):
    """Losing dictation the user already reviewed is the worst outcome here."""
    d = _daemon(mocker)
    d._injector = mocker.MagicMock()
    d._injector.inject.side_effect = RuntimeError("ydotool is not running")
    d._stage_or_commit("carefully dictated text", {})

    result = _staged(d, "commit")

    assert result["committed"] is False
    assert "ydotool is not running" in result["detail"]
    assert d._staged.text == "carefully dictated text", "still recoverable"


def test_no_injector_at_all_also_keeps_the_text(mocker):
    d = _daemon(mocker)
    d._injector = None
    d._stage_or_commit("still mine", {})
    result = _staged(d, "commit")
    assert result["committed"] is False
    assert d._staged.text == "still mine"


def test_ipc_discard_reports_how_much_it_dropped(mocker):
    d = _daemon(mocker)
    d._stage_or_commit("three whole words", {})
    result = _staged(d, "discard")
    assert result["discarded_words"] == 3
    assert d._staged.is_empty


def test_ipc_undo_reports_whether_it_did_anything(mocker):
    d = _daemon(mocker)
    assert _staged(d, "undo")["ok"] is False
    d._stage_or_commit("something", {})
    assert _staged(d, "undo")["ok"] is True


def test_ipc_status_answers_even_with_the_feature_off(mocker):
    """So `yazses staged status` can say "it is off" instead of erroring."""
    cfg = replace(Config(), staged=StagedConfig(enabled=False))
    d = Daemon(config=cfg, platform=get_platform())
    pending = _staged(d, "status")["pending"]
    assert pending["enabled"] is False
    assert pending["words"] == 0


def test_an_unknown_action_reports_status_rather_than_raising(mocker):
    d = _daemon(mocker)
    assert _staged(d, "nonsense")["ok"] is True


def test_daemon_status_carries_the_pending_buffer(mocker):
    d = _daemon(mocker)
    d._stage_or_commit("pending text here", {})
    status = d._handle_status(Request(method="status", params={}, id=1))
    assert status["staged"]["words"] == 3
    assert status["staged"]["preview"] == "pending text here"


def test_the_staged_method_is_registered_on_the_ipc_server():
    import inspect

    source = inspect.getsource(Daemon._start_ipc_server)
    assert 'server.register("staged"' in source
