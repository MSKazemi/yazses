"""set_clipboard argv shape + graceful degradation."""
from yazses.system.clipboard import set_clipboard


def test_empty_text_is_noop():
    calls = []
    # Keep the call out of the assert: an assert with a side effect vanishes
    # under `python -O` (CodeQL py/side-effect-in-assert).
    result = set_clipboard("", runner=lambda *a, **k: calls.append(a))
    assert result is False
    assert calls == []


def test_wl_copy_passes_text_as_arg(mocker):
    runner = mocker.MagicMock()
    ok = set_clipboard("hi", runner=runner, candidates=[["wl-copy", "--"]])
    assert ok is True
    assert runner.call_args.args[0] == ["wl-copy", "--", "hi"]


def test_xclip_passes_text_on_stdin(mocker):
    runner = mocker.MagicMock()
    ok = set_clipboard("hi", runner=runner, candidates=[["xclip", "-selection", "clipboard"]])
    assert ok is True
    assert runner.call_args.args[0] == ["xclip", "-selection", "clipboard"]
    assert runner.call_args.kwargs["input"] == b"hi"


def test_falls_through_to_next_tool(mocker):
    def runner(cmd, *a, **k):
        if cmd[0] == "xclip":
            raise RuntimeError("no display")
        return mocker.MagicMock()

    ok = set_clipboard(
        "hi", runner=runner,
        candidates=[["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]],
    )
    assert ok is True


def test_no_tools_returns_false():
    assert set_clipboard("hi", candidates=[]) is False


def test_never_raises():
    def boom(*a, **k):
        raise OSError("nope")

    assert set_clipboard("hi", runner=boom, candidates=[["wl-copy", "--"]]) is False
