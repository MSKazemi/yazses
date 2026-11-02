"""Which XKB layout the Unicode injector resolves keys against, and why.

uinput sends keycodes; the compositor maps them with ITS active layout. These tests pin
the pure parsers on real `localectl` / `gsettings` / sway output shapes, the precedence
between sources, the failure paths of the probes, and the words the user sees when a
character is not on the layout in use. No test spawns a real probe or opens uinput.
"""

from __future__ import annotations

import ctypes
import json
import subprocess

import pytest

import yazses.inject.unicode as unicode_mod
from yazses.config import Config, SttConfig
from yazses.inject.unicode import (
    LayoutDetection,
    UnicodeInjector,
    UnicodeInjectorError,
    detect_layout,
    parse_gsettings_sources,
    parse_localectl_layouts,
    parse_sway_inputs,
)
from yazses.system.doctor import _injection_layout_check

# --- real sample outputs -----------------------------------------------------------

LOCALECTL_US = """\
   System Locale: LANG=en_US.UTF-8
       VC Keymap: (unset)
      X11 Layout: us
       X11 Model: pc105
"""

LOCALECTL_UNSET = """\
   System Locale: LANG=en_US.UTF-8
       VC Keymap: (unset)
      X11 Layout: (unset)
       X11 Model: pc105
"""

LOCALECTL_MULTI = """\
      X11 Layout: us,ir
"""

GSETTINGS_US_IR = "[('xkb', 'us'), ('xkb', 'ir')]\n"
GSETTINGS_IBUS = "[('ibus', 'anthy'), ('xkb', 'ir+pes'), ('xkb', 'us+dvorak')]\n"
GSETTINGS_EMPTY = "@a(ss) []\n"

SWAY_PERSIAN_ACTIVE = json.dumps([
    {"type": "keyboard", "xkb_layout_names": ["English (US)", "Persian"],
     "xkb_active_layout_index": 1},
    {"type": "pointer"},
])
SWAY_UNMAPPED_ACTIVE = json.dumps([
    {"type": "keyboard", "xkb_layout_names": ["English (US)", "Klingon"],
     "xkb_active_layout_index": 1},
])


# --- pure parsers ------------------------------------------------------------------


def test_localectl_reports_the_x11_layout():
    assert parse_localectl_layouts(LOCALECTL_US) == ("us",)


def test_localectl_unset_or_missing_is_no_answer():
    assert parse_localectl_layouts(LOCALECTL_UNSET) == ()
    assert parse_localectl_layouts("System Locale: LANG=C\n") == ()
    assert parse_localectl_layouts("") == ()


def test_localectl_keeps_every_listed_layout_in_order():
    assert parse_localectl_layouts(LOCALECTL_MULTI) == ("us", "ir")


def test_gsettings_reads_only_xkb_entries_and_drops_variants():
    assert parse_gsettings_sources(GSETTINGS_US_IR) == ("us", "ir")
    assert parse_gsettings_sources(GSETTINGS_IBUS) == ("ir", "us")


def test_gsettings_empty_and_garbage_are_no_answer_and_never_raise():
    assert parse_gsettings_sources(GSETTINGS_EMPTY) == ()
    assert parse_gsettings_sources("") == ()
    assert parse_gsettings_sources("__import__('os').system('true')") == ()
    assert parse_gsettings_sources("[(1,") == ()
    assert parse_gsettings_sources("42") == ()


def test_sway_lists_the_active_layout_first():
    assert parse_sway_inputs(SWAY_PERSIAN_ACTIVE) == ("ir", "us")


def test_sway_with_an_unmapped_active_layout_is_no_answer_not_a_guess():
    assert parse_sway_inputs(SWAY_UNMAPPED_ACTIVE) == ()


def test_sway_garbage_is_no_answer():
    assert parse_sway_inputs("not json") == ()
    assert parse_sway_inputs(json.dumps({"type": "keyboard"})) == ()
    assert parse_sway_inputs(json.dumps([{"type": "keyboard"}])) == ()


# --- precedence --------------------------------------------------------------------


def _fake_run(answers: dict[str, str | None]):
    """A probe runner answering from *answers*, keyed by the tool name; records calls."""
    calls: list[list[str]] = []

    def run(argv: list[str]) -> str | None:
        calls.append(argv)
        return answers.get(argv[0])

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _everything_installed(_name: str) -> str:
    return f"/usr/bin/{_name}"


def test_english_machine_with_no_hints_resolves_us_and_runs_no_probe():
    run = _fake_run({})
    found = detect_layout(environ={}, run=run, which=lambda name: None)
    assert found == LayoutDetection("us", (), "default")
    assert run.calls == []


def test_english_machine_reported_by_localectl_is_us_as_before():
    run = _fake_run({"localectl": LOCALECTL_US})
    found = detect_layout(environ={}, run=run, which=_everything_installed)
    assert found.active == "us"
    assert found.source == "localectl"


def test_environment_variable_still_wins_over_every_probe():
    run = _fake_run({"localectl": LOCALECTL_US, "gsettings": GSETTINGS_US_IR})
    found = detect_layout(
        environ={"XKB_DEFAULT_LAYOUT": "ir,us"}, run=run, which=_everything_installed
    )
    assert found == LayoutDetection("ir", ("ir", "us"), "XKB_DEFAULT_LAYOUT")
    assert run.calls == []


def test_xkb_layout_variable_is_the_second_environment_source():
    found = detect_layout(environ={"XKB_LAYOUT": "de"}, run=_fake_run({}), which=lambda n: None)
    assert found == LayoutDetection("de", ("de",), "XKB_LAYOUT")


def test_the_session_beats_the_system_default_for_a_persian_user():
    """localectl says us (the install default); gsettings says the user is on ir."""
    run = _fake_run({
        "localectl": LOCALECTL_US,
        "gsettings": "[('xkb', 'ir'), ('xkb', 'us')]",
    })
    found = detect_layout(environ={}, run=run, which=_everything_installed)
    assert found.active == "ir"
    assert found.source == "gsettings mru-sources"
    assert found.listed == ("ir", "us")


def test_gsettings_falls_back_to_sources_when_mru_is_empty():
    def run(argv):
        if argv[-1] == "mru-sources":
            return GSETTINGS_EMPTY
        if argv[-1] == "sources":
            return GSETTINGS_US_IR
        return None

    found = detect_layout(environ={}, run=run, which=_everything_installed)
    assert found == LayoutDetection("us", ("us", "ir"), "gsettings sources")


def test_mru_names_the_active_layout_but_the_listed_set_is_the_configured_one():
    """On a real GNOME box: mru-sources is ('us',), sources is us and ir."""

    def run(argv):
        if argv[-1] == "mru-sources":
            return "[('xkb', 'us')]"
        if argv[-1] == "sources":
            return GSETTINGS_US_IR
        return None

    found = detect_layout(environ={}, run=run, which=_everything_installed)
    assert found == LayoutDetection("us", ("us", "ir"), "gsettings mru-sources")


def test_sway_is_asked_before_gsettings_and_localectl():
    run = _fake_run({
        "swaymsg": SWAY_PERSIAN_ACTIVE,
        "gsettings": GSETTINGS_US_IR,
        "localectl": LOCALECTL_US,
    })
    found = detect_layout(environ={}, run=run, which=_everything_installed)
    assert found == LayoutDetection("ir", ("ir", "us"), "sway")
    assert [call[0] for call in run.calls] == ["swaymsg"]


def test_a_probe_tool_that_is_not_installed_is_never_run():
    run = _fake_run({"localectl": LOCALECTL_US})
    found = detect_layout(
        environ={}, run=run, which=lambda name: None if name != "localectl" else "/x"
    )
    assert found.source == "localectl"
    assert [call[0] for call in run.calls] == ["localectl"]


def test_every_probe_silent_falls_back_to_us_without_raising():
    run = _fake_run({"localectl": None, "gsettings": None, "swaymsg": None})
    found = detect_layout(environ={}, run=run, which=_everything_installed)
    assert found == LayoutDetection("us", (), "default")


# --- probe failure paths -----------------------------------------------------------


def test_run_probe_returns_stdout_on_success(monkeypatch):
    def fake_run(argv, **kwargs):
        assert kwargs["timeout"] <= 1.0  # the probe budget is under a second
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(argv, 0, stdout="X11 Layout: us\n", stderr="")

    monkeypatch.setattr(unicode_mod.subprocess, "run", fake_run)
    assert unicode_mod._run_probe(["localectl", "status"]) == "X11 Layout: us\n"


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("localectl"),
        PermissionError("denied"),
        subprocess.TimeoutExpired(cmd="gsettings", timeout=0.8),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
    ],
)
def test_run_probe_treats_absent_slow_or_undecodable_as_no_answer(monkeypatch, error):
    def fake_run(argv, **kwargs):
        raise error

    monkeypatch.setattr(unicode_mod.subprocess, "run", fake_run)
    assert unicode_mod._run_probe(["gsettings", "get", "x", "y"]) is None


def test_run_probe_treats_a_nonzero_exit_as_no_answer(monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="partial", stderr="no schema")

    monkeypatch.setattr(unicode_mod.subprocess, "run", fake_run)
    assert unicode_mod._run_probe(["gsettings", "get", "x", "y"]) is None


def test_a_probe_that_raises_does_not_stop_detection(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=0.8)

    monkeypatch.setattr(unicode_mod.subprocess, "run", fake_run)
    found = detect_layout(environ={}, which=_everything_installed)
    assert found == LayoutDetection("us", (), "default")


# --- the failure a user sees --------------------------------------------------------


class _LayoutFake:
    """A fake XKB session that knows its layout and maps only the given characters."""

    def __init__(self, layout: str, mapping: dict[str, int]):
        self.layout = layout
        self._mapping = mapping
        self._reverse = {code: char for char, code in mapping.items()}

    def update(self, keycode: int, direction: int) -> None:
        pass

    def key_text(self, keycode: int) -> str:
        return self._reverse.get(keycode, "")

    def close(self) -> None:
        pass


def test_missing_character_error_names_the_layout_that_was_consulted():
    xkb = _LayoutFake("us", {"a": 30})
    with pytest.raises(UnicodeInjectorError) as info:
        UnicodeInjector._plan(xkb, "aس")
    message = str(info.value)
    assert "'us'" in message
    assert "cannot produce 'س'" in message
    assert "Persian and Arabic" in message  # the arabic-script hint names the layout to use


def test_latin_missing_character_gets_no_persian_hint():
    xkb = _LayoutFake("us", {"a": 30})
    with pytest.raises(UnicodeInjectorError) as info:
        UnicodeInjector._plan(xkb, "aé")
    assert "'us'" in str(info.value)
    assert "Persian" not in str(info.value)


def test_ensure_producible_types_nothing_and_raises_before_any_key(monkeypatch):
    xkb = _LayoutFake("us", {"a": 30})
    monkeypatch.setattr(unicode_mod._XkbSession, "create", lambda: xkb)
    with pytest.raises(UnicodeInjectorError, match="cannot produce"):
        UnicodeInjector().ensure_producible("aس")


# --- the real libxkbcommon, when this machine has it ---------------------------------

_PERSIAN_SENTENCE = "سلام، این یک متن فارسی است. ۱۲۳"


def _real_resolution(layout: str) -> set[str] | None:
    """Characters of the Persian sentence that *layout* can produce, or None if unavailable."""
    try:
        lib = unicode_mod._load_xkb_library()
    except UnicodeInjectorError:
        return None
    unicode_mod._configure_xkb(lib)
    context = lib.xkb_context_new(0)
    names = unicode_mod._XkbRuleNames(
        rules=b"evdev", model=b"pc105", layout=layout.encode(), variant=None, options=None
    )
    keymap = lib.xkb_keymap_new_from_names(context, ctypes.byref(names), 0)
    if not keymap:
        return None  # libxkbcommon without xkeyboard-config data
    state = lib.xkb_state_new(keymap)
    session = unicode_mod._XkbSession(lib, context, keymap, state, layout)
    try:
        return {
            ch
            for ch in set(_PERSIAN_SENTENCE) - {" "}
            if unicode_mod._find_key_for_character(session, ch) is not None
        }
    finally:
        session.close()


def test_real_xkb_cannot_produce_persian_on_us_and_can_on_ir():
    us = _real_resolution("us")
    if us is None:
        pytest.skip("libxkbcommon or its xkeyboard-config data is not installed")
    ir = _real_resolution("ir")
    assert ir is not None
    persian_only = set(_PERSIAN_SENTENCE) - set(" .")  # '.' is ASCII and resolves everywhere
    assert not (us & persian_only)  # no Persian character on us
    assert set("سلام") <= ir  # every letter of سلام on ir
    assert "۱" in ir  # Persian digits too
    assert (set(_PERSIAN_SENTENCE) - {" "}) - ir == set()


# --- the doctor row ----------------------------------------------------------------


def _cfg(language: str) -> Config:
    cfg = Config()
    cfg.stt = SttConfig(model="small", language=language)
    return cfg


def _found(active: str, listed: tuple[str, ...], source: str = "gsettings mru-sources"):
    return lambda: LayoutDetection(active, listed, source)


def test_english_dictation_row_is_ok_and_says_nothing_about_persian():
    name, status, message = _injection_layout_check(_cfg("en"), detect=_found("us", ("us",), "localectl"))
    assert (name, status) == ("Injection layout", "OK")
    assert "'us'" in message and "localectl" in message
    assert "Persian" not in message


def test_persian_dictation_on_us_warns_and_names_the_clipboard_fallback():
    _, status, message = _injection_layout_check(
        _cfg("fa"), detect=_found("us", ("us", "ir"), "gsettings mru-sources")
    )
    assert status == "WARN"
    assert "'us'" in message
    assert "active Persian ('ir') layout" in message
    assert "clipboard" in message and "fallback" in message
    # The session lists ir but it is not the active one: say what that means.
    assert "also lists 'ir'" in message and "active layout" in message


def test_persian_dictation_on_ir_is_ok_and_does_not_claim_it_is_verified():
    _, status, message = _injection_layout_check(_cfg("fa"), detect=_found("ir", ("ir",)))
    assert status == "OK"
    assert "Not verified against a live compositor" in message
    assert "verified" not in message.replace("Not verified", "")


def test_a_row_that_cannot_detect_says_so_and_does_not_raise():
    def broken():
        raise OSError("probe exploded")

    name, status, message = _injection_layout_check(_cfg("fa"), detect=broken)
    assert (name, status) == ("Injection layout", "WARN")
    assert "could not be checked" in message


# -- the LANG guess survives as the last resort ------------------------------------------------


def _nothing(_argv):
    return None


@pytest.mark.parametrize(
    ("lang", "layout"),
    [("de_DE.UTF-8", "de"), ("sv_SE.UTF-8", "se"), ("fr_FR.UTF-8", "fr"),
     ("es_ES.UTF-8", "es"), ("it_IT.UTF-8", "it"), ("pt_PT.UTF-8", "pt"), ("en_GB.UTF-8", "gb")],
)
def test_lang_is_still_the_last_resort_when_no_probe_answers(lang, layout):
    got = unicode_mod.detect_layout(environ={"LANG": lang}, run=_nothing, which=lambda _n: "/bin/x")
    assert got.active == layout
    assert got.source.startswith("LANG=")


def test_an_answering_probe_beats_lang():
    def run(argv):
        return "X11 Layout: ir\n" if argv[0] == "localectl" else None

    got = unicode_mod.detect_layout(
        environ={"LANG": "de_DE.UTF-8"}, run=run, which=lambda n: "/bin/x" if n == "localectl" else None
    )
    assert got.active == "ir"


def test_english_with_nothing_reported_stays_us():
    got = unicode_mod.detect_layout(environ={"LANG": "en_US.UTF-8"}, run=_nothing, which=lambda _n: None)
    assert (got.active, got.source) == ("us", "default")
