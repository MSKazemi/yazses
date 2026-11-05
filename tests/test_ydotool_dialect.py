"""ydotool 1.x and ydotool 0.1.x are different CLIs wearing the same name.

Debian and Ubuntu ship 0.1.8 (24.04 through 26.04). YazSes spoke only 1.x, so on
those machines every dictation was transcribed and then dropped:

    $ ydotool type -d 6 -H 6 -- hello
    ydotool: type: error: unrecognised option '-d'
    $ echo $?
    0

The exit code is the reason it was silent rather than merely broken -- `check=True`
never raised, `LinuxInjector`'s clipboard fallback never fired, nothing reached the
log, and `doctor` reported the backend as fine.

Every 0.1.8 behaviour asserted here was measured on Ubuntu by grabbing the ydotoold
virtual device (EVIOCGRAB) and reading the events it actually emitted.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yazses.inject import ydotool as yd

# `ydotool type --help` on 0.1.8 and on 1.x -- the discriminator is the hold time,
# which 0.1.x does not have at all.
HELP_V0 = (
    "Usage: type [--delay milliseconds] [--key-delay milliseconds] [--args N]"
    "[--file <filepath>] <things to type>\n"
    "  --help                    Show this help.\n"
    "  --delay milliseconds      Delay time before start typing.\n"
    "  --key-delay milliseconds  Delay time between keystrokes. Default 12ms.\n"
)
HELP_V1 = (
    "Usage: ydotool type [OPTION]... [STRINGS]...\n"
    "  -d, --key-delay <ms>   Delay between keystrokes\n"
    "  -H, --key-hold <ms>    Hold time of each keystroke\n"
)


@pytest.fixture(autouse=True)
def _clear_dialect_cache():
    yd.set_ydotool_dialect(None)
    yield
    yd.set_ydotool_dialect(None)


class _Recorder:
    """Stands in for subprocess.run and replays a scripted result per call."""

    def __init__(self, results):
        self.results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.results:
            returncode, stderr = self.results.pop(0)
        else:
            returncode, stderr = 0, ""
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


# --- the exit-0 contract ------------------------------------------------------


def test_an_option_error_is_a_failure_even_though_ydotool_exits_zero(monkeypatch):
    run = _Recorder([(0, "ydotool: type: error: unrecognised option '-d'\n")])
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(yd.YdotoolOptionError):
        yd.run_ydotool(["ydotool", "type", "-d", "6", "--", "hi"], timeout=5)


def test_ordinary_ydotool_chatter_is_not_an_error(monkeypatch):
    # Both lines are what a SUCCESSFUL 0.1.8 run prints, on stderr.
    run = _Recorder([(0, "ydotool: notice: Using ydotoold backend\n"
                         "Key delay was set to 6 milliseconds.\n")])
    monkeypatch.setattr(subprocess, "run", run)
    yd.run_ydotool(["ydotool", "type", "--key-delay", "6", "--", "hi"], timeout=5)


def test_a_nonzero_exit_is_still_a_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _Recorder([(1, "")]))
    with pytest.raises(yd.YdotoolCliError):
        yd.run_ydotool(["ydotool", "type", "--", "hi"], timeout=5)


# --- dialect detection --------------------------------------------------------


@pytest.mark.parametrize(
    ("help_text", "expected"),
    [(HELP_V0, yd.DIALECT_V0), (HELP_V1, yd.DIALECT_V1)],
)
def test_dialect_is_probed_from_type_help(monkeypatch, help_text, expected):
    def fake_run(argv, **kwargs):
        assert argv == ["ydotool", "type", "--help"]
        return SimpleNamespace(returncode=0, stdout=help_text, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert yd.ydotool_dialect() == expected


def test_the_dialect_is_probed_once(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=HELP_V0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    yd.ydotool_dialect()
    yd.ydotool_dialect()
    assert len(calls) == 1


# --- the two command lines ----------------------------------------------------


def test_v0_types_with_key_delay_and_never_d_or_h():
    argv = yd.YdotoolInjector()._type_argv("hello", yd.DIALECT_V0)
    assert argv == ["ydotool", "type", "--key-delay", "6", "--", "hello"]
    assert "-d" not in argv and "-H" not in argv


def test_v1_type_command_is_unchanged():
    argv = yd.YdotoolInjector()._type_argv("hello", yd.DIALECT_V1)
    assert argv == ["ydotool", "type", "-d", "6", "-H", "6", "--", "hello"]


@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("ctrl+v", ["ctrl+v"]),
        ("ctrl+BackSpace", ["ctrl+backspace"]),
        ("shift+Down", ["shift+down"]),
        ("ctrl+shift+k", ["ctrl+shift+k"]),
        # dispatch.py sends "Return" for "new line"; 0.1.8 types the letter r for it.
        ("Return", ["enter"]),
        ("Escape", ["esc"]),
        ("F2", ["f2"]),
        ("Left", ["left"]),
        ("super+a", ["super+a"]),
    ],
)
def test_v0_key_names_are_symbolic(combo, expected):
    assert yd.ydotool_key_args_v0(combo) == expected


def test_v1_key_args_stay_numeric():
    assert yd.ydotool_key_args("ctrl+v") == ["29:1", "47:1", "47:0", "29:0"]


@pytest.mark.parametrize("combo", ["space", "KEY_RIGHTCTRL", "KEY_SEMICOLON", "KEY_DOT"])
def test_v0_refuses_a_key_it_would_mistype(combo):
    """0.1.8 has no error path: an unknown name types its first letter and exits 0.

    Raising here is what routes the keystroke to the clipboard fallback instead of
    putting a wrong character on the screen.
    """
    with pytest.raises(ValueError):
        yd.ydotool_key_args_v0(combo)


def test_key_argv_spells_the_delay_flag_per_dialect():
    assert yd.ydotool_key_argv(["ctrl+v"], yd.DIALECT_V0, 40)[:4] == [
        "ydotool", "key", "--key-delay", "40",
    ]
    assert yd.ydotool_key_argv(["ctrl+v"], yd.DIALECT_V1, 40)[:4] == [
        "ydotool", "key", "-d", "40",
    ]


# --- downgrade behaviour ------------------------------------------------------


def test_inject_downgrades_once_and_retypes(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(0, "ydotool: type: error: unrecognised option '-d'\n"), (0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hi")

    assert run.calls[0][:3] == ["ydotool", "type", "-d"]
    assert run.calls[1] == ["ydotool", "type", "--key-delay", "6", "--", "hi"]
    # and the dialect stays downgraded for the next dictation
    assert yd.ydotool_dialect() == yd.DIALECT_V0


def test_a_non_option_failure_is_not_retyped(monkeypatch):
    """A command that was accepted may have typed half the text already."""
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(1, "ydotool: type: something else went wrong\n")])
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(yd.YdotoolCliError):
        yd.YdotoolInjector().inject("hi")
    # one `type` (never retyped); the only other call is the release-all
    assert [c[1] for c in run.calls] == ["type", "key"]


def test_v0_does_not_send_the_numeric_flood_guard(monkeypatch):
    """The guard is a list of bare key-ups, which 0.1.x's `key` grammar cannot express."""
    yd.set_ydotool_dialect(yd.DIALECT_V0)
    run = _Recorder([(0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hi")

    assert len(run.calls) == 1
    assert run.calls[0][1] == "type"


def test_v1_still_sends_the_flood_guard(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(0, ""), (0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hi")

    assert len(run.calls) == 2
    assert run.calls[1][:2] == ["ydotool", "key"]
    assert "42:0" in run.calls[1]


# --- the bare key-up guard ----------------------------------------------------


def test_the_stuck_modifier_guard_is_a_no_op_on_v0(monkeypatch):
    """`ydotool key 97:0` types the digit 9 on 0.1.8 -- measured, not assumed.

    The daemon runs this guard on every hold-end, so a pass-through put a stray
    digit into the document on every single dictation.
    """
    yd.set_ydotool_dialect(yd.DIALECT_V0)
    run = _Recorder([])
    monkeypatch.setattr(subprocess, "run", run)

    yd.release_keycodes({97, 100})

    assert run.calls == []


def test_the_stuck_modifier_guard_still_runs_on_v1(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    yd.release_keycodes({100, 97})

    assert run.calls == [["ydotool", "key", "97:0", "100:0"]]


# --- the fallback is no longer silent -----------------------------------------


def test_falling_back_to_the_clipboard_is_logged(caplog):
    """The whole failure was invisible; a fallback that says nothing is how."""
    import logging

    from yazses.platform.linux.injector import LinuxInjector

    injector = LinuxInjector.__new__(LinuxInjector)

    class _Broken:
        def inject(self, text):
            raise yd.YdotoolCliError("unrecognised option '-d'")

    class _Fallback:
        def __init__(self):
            self.got = []

        def inject(self, text):
            self.got.append(text)

    injector._primary = _Broken()
    injector._fallback = _Fallback()

    with caplog.at_level(logging.WARNING):
        injector.inject("hello")

    assert injector._fallback.got == ["hello"]
    assert "clipboard fallback" in caplog.text
    assert "unrecognised option" in caplog.text


# --- the probe defaults in the SAFE direction ---------------------------------


@pytest.mark.parametrize(
    "help_text",
    [
        "",  # no answer at all
        "Usage: ydotool type [OPTION]... [STRINGS]...\n",  # options not listed
        "some future ydotool 2.x help we have never seen\n",
    ],
)
def test_an_unrecognised_help_text_assumes_v1(monkeypatch, help_text):
    """Only one of the two wrong guesses can correct itself.

    Guessing v1 on a 0.1.x machine raises `unrecognised option`, which `inject`
    catches and downgrades. Guessing v0 on a 1.x machine is SILENT -- 1.x's `key`
    ignores symbolic names and emits nothing -- so v1 must be the default.
    """

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=help_text, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert yd.ydotool_dialect() == yd.DIALECT_V1


def test_real_upstream_v1_help_is_recognised(monkeypatch):
    """Verbatim from upstream v1.0.4 `Client/tool_type.c`."""
    upstream = (
        "Usage: ydotool type [OPTION]... [STRINGS]...\n"
        "  -d, --key-delay=N          Delay N milliseconds between keys "
        "(the delay between every key down/up pair) (default: 20)\n"
        "  -H, --key-hold=N           Hold each key for N milliseconds "
        "(the delay between key down and up) (default: 20)\n"
        "  -D, --next-delay=N         Delay N milliseconds between command line strings\n"
    )

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=upstream, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert yd.ydotool_dialect() == yd.DIALECT_V1


# --- the two fixes compose -----------------------------------------------------


def test_mixed_text_on_an_0_1_x_machine_uses_both_paths(monkeypatch):
    """#329's Unicode routing and the 0.1.x dialect are independent, and must compose.

    On Debian/Ubuntu (0.1.x) dictating "hej å då" has to do BOTH things at once: the
    ASCII runs need 0.1.x's `--key-delay` command line, and the non-ASCII run must
    bypass ydotool entirely. Either fix alone leaves that sentence wrong.
    """
    import yazses.inject.unicode as unicode_mod

    yd.set_ydotool_dialect(yd.DIALECT_V0)
    typed: list[str] = []

    class _RecordingUnicodeInjector:
        closed = False

        def ensure_producible(self, text):
            pass

        def inject(self, text):
            typed.append(("unicode", text))

        def close(self):
            type(self).closed = True

    monkeypatch.setattr(unicode_mod, "UnicodeInjector", _RecordingUnicodeInjector)

    run = _Recorder([])
    original = run.__call__

    def recording(argv, **kwargs):
        if argv[1] == "type":
            typed.append(("ydotool", argv[-1]))
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording)

    yd.YdotoolInjector().inject("hej å då")

    assert typed == [
        ("ydotool", "hej "),
        ("unicode", "å"),
        ("ydotool", " d"),
        ("unicode", "å"),
    ]
    # every ASCII run went out in the 0.1.x dialect, never with -d/-H
    type_calls = [c for c in run.calls if c[1] == "type"]
    assert type_calls and all("--key-delay" in c and "-d" not in c for c in type_calls)
    # and the uinput device was closed rather than leaked
    assert _RecordingUnicodeInjector.closed
    # 0.1.x cannot express a bare key-up, so no flood guard was attempted
    assert not any(c[1] == "key" for c in run.calls)


# --- release-all on a failed type (v1 flood guard) ----------------------------

_RELEASE_ALL = ["ydotool", "key", *yd._RELEASE_ALL_TYPED_KEYS]


class _FailingType:
    """subprocess.run stand-in: `type` raises *type_exc*, `key` raises *key_exc* or succeeds."""

    def __init__(self, type_exc=None, key_exc=None):
        self.type_exc = type_exc
        self.key_exc = key_exc
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        exc = self.type_exc if argv[1] == "type" else self.key_exc
        if exc is not None:
            raise exc
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    @property
    def argvs(self):
        return [c[0] for c in self.calls]


def test_a_failed_type_still_releases_all_keys_on_v1(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    boom = subprocess.CalledProcessError(1, ["ydotool", "type"], stderr="boom")
    run = _FailingType(type_exc=boom)
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        yd.YdotoolInjector().inject("hello")

    assert caught.value is boom  # same object: neither replaced nor wrapped
    assert [a[1] for a in run.argvs] == ["type", "key"]
    assert run.argvs.count(_RELEASE_ALL) == 1


def test_a_cli_failure_from_type_releases_and_propagates_unchanged(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _Recorder([(1, "ydotool: type: something else went wrong\n"), (0, "")])
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(yd.YdotoolCliError) as caught:
        yd.YdotoolInjector().inject("hello")

    assert type(caught.value) is yd.YdotoolCliError
    assert "exit 1" in str(caught.value)
    assert [c[1] for c in run.calls] == ["type", "key"]
    assert run.calls[1] == _RELEASE_ALL


def test_a_timed_out_type_releases_with_its_own_short_timeout(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    timeout = subprocess.TimeoutExpired(["ydotool", "type"], 10.0)
    run = _FailingType(type_exc=timeout)
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        yd.YdotoolInjector().inject("hello")

    assert caught.value is timeout
    (type_argv, type_kw), (key_argv, key_kw) = run.calls
    assert type_argv[1] == "type" and key_argv == _RELEASE_ALL
    assert key_kw["timeout"] == 5  # its own short budget, not the (already spent) type one
    assert key_kw["timeout"] < type_kw["timeout"]


def test_a_failing_release_does_not_replace_the_typing_error(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    original = subprocess.TimeoutExpired(["ydotool", "type"], 10.0)
    run = _FailingType(
        type_exc=original,
        key_exc=subprocess.TimeoutExpired(["ydotool", "key"], 5),
    )
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        yd.YdotoolInjector().inject("hello")

    assert caught.value is original
    assert run.argvs.count(_RELEASE_ALL) == 1  # attempted exactly once, no retry


def test_a_release_that_cannot_even_start_does_not_replace_the_typing_error(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    original = yd.YdotoolCliError("type failed")

    def run(argv, **kwargs):
        if argv[1] == "type":
            raise original
        raise OSError("ydotoold is gone")

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(yd.YdotoolCliError) as caught:
        yd.YdotoolInjector().inject("hello")
    assert caught.value is original


def test_a_failed_mixed_inject_releases_too(monkeypatch):
    """The non-ASCII path goes through the same guard."""
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    from yazses.inject import unicode as unicode_mod

    class _Uni:
        def __init__(self, *a, **k):
            pass

        def ensure_producible(self, text):
            pass

        def inject(self, text):
            pass

        def close(self):
            pass

    monkeypatch.setattr(unicode_mod, "UnicodeInjector", _Uni)
    timeout = subprocess.TimeoutExpired(["ydotool", "type"], 10.0)
    run = _FailingType(type_exc=timeout)
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired):
        yd.YdotoolInjector().inject("hej å då")

    assert run.argvs.count(_RELEASE_ALL) == 1


def test_v0_sends_nothing_after_a_failed_type(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V0)
    boom = subprocess.TimeoutExpired(["ydotool", "type"], 10.0)
    run = _FailingType(type_exc=boom)
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        yd.YdotoolInjector().inject("hello")

    assert caught.value is boom
    assert [a[1] for a in run.argvs] == ["type"]


def test_the_v1_success_sequence_is_exactly_type_then_one_release(monkeypatch):
    """Golden: the call sequence the base produced, byte for byte."""
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _FailingType()
    monkeypatch.setattr(subprocess, "run", run)

    yd.YdotoolInjector().inject("hello")

    assert run.argvs == [
        ["ydotool", "type", "-d", "6", "-H", "6", "--", "hello"],
        _RELEASE_ALL,
    ]
    assert run.calls[1][1]["timeout"] == 5


def test_a_failing_release_after_a_successful_type_still_surfaces(monkeypatch):
    """Success path is unchanged: only an already-propagating error is protected."""
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    run = _FailingType(key_exc=subprocess.TimeoutExpired(["ydotool", "key"], 5))
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired):
        yd.YdotoolInjector().inject("hello")


def test_a_failing_release_surfaces_even_when_inject_runs_inside_an_except_block(monkeypatch):
    """Whether typing failed is the typing's own outcome, not 'is any exception in flight'.

    The release used to be told `typing_failed=sys.exc_info()[0] is not None`, so a caller
    that invoked `inject()` while handling some unrelated exception had a failing
    release-all swallowed on a perfectly good type.
    """
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    release_error = yd.YdotoolCliError("release failed")
    run = _FailingType(key_exc=release_error)
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(yd.YdotoolCliError) as caught:
        try:
            raise ValueError("an unrelated error being handled")
        except ValueError:
            yd.YdotoolInjector().inject("hello")

    assert caught.value is release_error
    assert [a[1] for a in run.argvs] == ["type", "key"]


def test_a_typing_error_still_wins_when_inject_runs_inside_an_except_block(monkeypatch):
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    original = subprocess.TimeoutExpired(["ydotool", "type"], 10.0)
    run = _FailingType(type_exc=original, key_exc=subprocess.TimeoutExpired(["ydotool", "key"], 5))
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        try:
            raise ValueError("an unrelated error being handled")
        except ValueError:
            yd.YdotoolInjector().inject("hello")

    assert caught.value is original
