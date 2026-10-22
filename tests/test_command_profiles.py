"""Editor command profiles: the keys a spoken command sends follow the focused editor.

`commands/profiles.py` existed with a registry, a loader and a test, and nothing called
`load_profiles`; `dispatch.py` carried a comment pointing at it and sent VS Code's keys
to every application. So "delete the last line" in a JetBrains IDE sent Ctrl+Shift+K,
and "rename this to user_id" in Sublime Text sent F2 (next bookmark), Ctrl+A (select
the whole buffer) and then typed the name over the file.

These tests pin three things: the pure choice (app class -> profile -> key overrides),
the dispatcher honouring an override or a refusal, and the daemon wiring -- built only
when `[commands] editor_profiles` is on, the focused-app lookup injected, and a missing
lookup degrading to the default keys with its reason logged once.
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

from yazses.commands.dispatch import DEFAULT_KEYMAP, LEAD_KEYS, dispatch
from yazses.commands.grammar import CommandIntent, IntentType
from yazses.commands.profiles import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE,
    NO_FOCUSED_APP_REASON,
    ProfileRegistry,
    load_profiles,
    match_app,
)
from yazses.config import CommandsConfig, Config


class _Injector:
    """Records every call in order: a key sequence as a list, typed text as a str."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        self.calls.append(("backspaces", count))

    def inject_key_sequence(self, keys):
        self.calls.append(list(keys))


def _intent(action: str, **args: str) -> CommandIntent:
    return CommandIntent(intent=IntentType.EDIT, action=action, args=dict(args),
                         raw_text=f"spoken {action}")


# ---- the pure choice -------------------------------------------------------


def test_the_feature_is_off_by_default():
    assert CommandsConfig().editor_profiles is False
    assert CommandsConfig().profile == "auto"


def test_auto_follows_the_focused_application():
    reg = load_profiles(CommandsConfig())
    assert reg.pinned is None
    assert reg.needs_focused_app is True
    assert reg.problems == []


@pytest.mark.parametrize("name", ["jetbrains", "sublime", "vscode", "default", " JetBrains "])
def test_a_profile_name_pins_it_for_every_application(name):
    reg = load_profiles(CommandsConfig(profile=name))
    wanted = name.strip().lower()
    assert reg.pinned == wanted
    assert reg.needs_focused_app is False
    choice = reg.choose("firefox")
    assert (choice.name, choice.reason) == (wanted, "pinned")


def test_an_unknown_profile_name_is_reported_and_uses_the_default_keys():
    """`vim` was in an old example comment; there is no vim profile (it is modal, and
    insert-mode chords do not mean what they mean elsewhere). Say so, never guess."""
    reg = load_profiles(CommandsConfig(profile="vim"))
    assert reg.pinned == DEFAULT_PROFILE
    assert len(reg.problems) == 1
    assert "'vim'" in reg.problems[0] and "jetbrains" in reg.problems[0]
    assert dict(reg.choose("nvim").keymap) == {}


@pytest.mark.parametrize("app_class,profile", [
    ("jetbrains-pycharm-ce", "jetbrains"),   # X11 WM_CLASS
    ("jetbrains-idea", "jetbrains"),
    ("PyCharm", "jetbrains"),                # an AT-SPI application name
    ("Android Studio", "jetbrains"),
    ("sublime_text", "sublime"),
    ("Sublime_text", "sublime"),
    ("Code", "vscode"),
    ("VSCodium", "vscode"),
    ("code-oss", "vscode"),
])
def test_known_editors_are_recognised(app_class, profile):
    assert match_app(app_class) == profile


@pytest.mark.parametrize("app_class", ["", "   ", "firefox", "kitty", "Xcode", "gedit"])
def test_anything_else_is_not_guessed_at(app_class):
    """`code` is matched whole, not as a substring -- `Xcode` is not VS Code."""
    assert match_app(app_class) is None


def test_choose_says_why():
    reg = load_profiles(CommandsConfig())
    assert (reg.choose("").name, reg.choose("").reason) == (DEFAULT_PROFILE, "no_app")
    assert (reg.choose("firefox").name, reg.choose("firefox").reason) == (DEFAULT_PROFILE,
                                                                          "no_match")
    jb = reg.choose("jetbrains-goland")
    assert (jb.name, jb.reason) == ("jetbrains", "matched")
    assert jb.keymap["delete_lines"] == ("ctrl+y",)


def test_an_exact_mapping_still_wins_over_the_matcher():
    """The registry's original contract (`profiles` is checked first) is kept."""
    reg = ProfileRegistry(profiles={"jetbrains-idea": "sublime"})
    assert reg.resolve("jetbrains-idea") == "sublime"


def test_the_keymap_handed_out_cannot_rewrite_the_builtin_table():
    """Every registry shares `BUILTIN_PROFILES`; a caller mutating its copy must not
    change the keys the next command, or the next daemon, sends."""
    keymap = load_profiles(CommandsConfig()).keymap("jetbrains")
    with pytest.raises(TypeError):
        keymap["delete_lines"] = ("ctrl+d",)  # type: ignore[index]
    assert BUILTIN_PROFILES["jetbrains"]["delete_lines"] == ("ctrl+y",)


def test_every_profile_names_only_actions_the_dispatcher_has():
    """A misspelt action would be an override nothing ever reads."""
    for name, overrides in BUILTIN_PROFILES.items():
        unknown = set(overrides) - set(DEFAULT_KEYMAP)
        assert not unknown, f"profile {name!r} overrides unknown actions {sorted(unknown)}"


def _profile_tokens() -> set[str]:
    tokens = {
        combo
        for overrides in BUILTIN_PROFILES.values()
        for keys in overrides.values()
        if keys is not None
        for combo in keys
    }
    assert tokens, "found no profile keys -- this test is not looking at anything"
    return tokens


def test_every_profile_key_is_injectable_on_windows():
    """The dispatcher's own tables are walked by
    `test_platform_windows_hardening::test_every_dispatcher_key_token_resolves`; the
    profiles live in another module and need the same check, or a binding Windows
    cannot express would silently do nothing there."""
    from yazses.platform.windows.injector import resolve_key_combo

    assert not sorted(t for t in _profile_tokens() if resolve_key_combo(t) is None)


def test_every_profile_key_is_expressible_to_ydotool():
    """ydotool 1.x takes numeric keycodes and raises on a name it cannot map."""
    from yazses.inject.ydotool import ydotool_key_args

    for combo in sorted(_profile_tokens()):
        assert ydotool_key_args(combo), combo


def test_the_reason_logged_without_an_app_names_the_sources_and_the_way_out():
    assert "AT-SPI" in NO_FOCUSED_APP_REASON and "xdotool" in NO_FOCUSED_APP_REASON
    assert "[commands] profile" in NO_FOCUSED_APP_REASON


# ---- the dispatcher ---------------------------------------------------------


@pytest.mark.parametrize("intent,expected", [
    (_intent("delete_lines", n="2"), [["ctrl+shift+k"], ["ctrl+shift+k"]]),
    (_intent("delete_words", n="2"), [["ctrl+BackSpace"], ["ctrl+BackSpace"]]),
    (_intent("undo_n", n="2"), [["ctrl+z"], ["ctrl+z"]]),
    (_intent("go_to_line", n="42"), [["ctrl+g"], "42", ["Return"]]),
    (_intent("go_to_function", name="parse"), [["ctrl+shift+o"], "parse"]),
    (_intent("go_to_class", name="Daemon"), [["ctrl+shift+o"], "Daemon"]),
    (_intent("go_to_file", name="cli"), [["ctrl+p"], "cli"]),
    (_intent("rename_symbol", name="user_id"), [["F2"], ["ctrl+a"], "user_id", ["Return"]]),
    (_intent("rename_symbol"), [["F2"]]),
    (_intent("select_lines", n="3"), [["ctrl+l"], ["shift+Down"], ["shift+Down"]]),
    (_intent("save"), [["ctrl+s"]]),
])
def test_without_a_profile_the_keys_are_exactly_the_old_ones(intent, expected):
    """What every install with `editor_profiles` off keeps sending, pinned literally."""
    inj = _Injector()
    dispatch(intent, inj)
    assert inj.calls == expected


def test_the_lead_table_is_the_only_new_default():
    """`DEFAULT_KEYMAP` must not change any key `ACTION_KEYS` already sent."""
    from yazses.commands.dispatch import ACTION_KEYS

    for action, keys in ACTION_KEYS.items():
        if action not in LEAD_KEYS:
            assert DEFAULT_KEYMAP[action] == keys


def test_a_jetbrains_window_gets_jetbrains_keys():
    keymap = load_profiles(CommandsConfig()).choose("jetbrains-pycharm").keymap
    inj = _Injector()
    dispatch(_intent("delete_lines", n="2"), inj, keymap=keymap)
    assert inj.calls == [["ctrl+y"], ["ctrl+y"]]

    inj = _Injector()
    dispatch(_intent("rename_symbol", name="user_id"), inj, keymap=keymap)
    # No Ctrl+A: in-place rename has the old name selected, and Ctrl+A would select
    # the file.
    assert inj.calls == [["shift+F6"], "user_id", ["Return"]]


def test_an_action_the_profile_does_not_name_keeps_the_default_keys():
    keymap = load_profiles(CommandsConfig()).choose("sublime_text").keymap
    inj = _Injector()
    dispatch(_intent("go_to_line", n="7"), inj, keymap=keymap)
    assert inj.calls == [["ctrl+g"], "7", ["Return"]]


def test_a_refused_action_sends_nothing_types_nothing_and_reports_nothing():
    """Sublime has no rename binding. The old fallback on a failed dispatch typed the
    raw phrase; for a refusal that would put "spoken rename_symbol" into the code."""
    keymap = load_profiles(CommandsConfig()).choose("sublime_text").keymap
    inj = _Injector()
    notified: list[str] = []
    dispatch(_intent("rename_symbol", name="user_id"), inj,
             notify_fn=lambda name, data: notified.append(name), keymap=keymap)
    assert inj.calls == []
    assert notified == []


def test_dictation_is_untouched_by_a_profile():
    keymap = load_profiles(CommandsConfig()).choose("sublime_text").keymap
    inj = _Injector()
    dispatch(CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text="hello"),
             inj, keymap=keymap)
    assert inj.calls == ["hello"]


# ---- the daemon --------------------------------------------------------------


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _FakeDetector:
    """Stands in for `inject.target.TargetDetector`; touches no desktop."""

    def __init__(self, app_class: str) -> None:
        self.app_class = app_class

    def get_app_class(self) -> str:
        return self.app_class


def _daemon(*, editor_profiles: bool, profile: str = "auto"):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = True
    cfg.commands.editor_profiles = editor_profiles
    cfg.commands.profile = profile
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    d._state.target_ok = True
    return d, inj


def _burst(d, text, *, command_mode):
    d._command_mode = command_mode
    d._engine.text = text
    d._on_hold_end()


def test_off_builds_nothing_and_dispatches_the_default_keys():
    d, _ = _daemon(editor_profiles=False)
    d._target_detector = _FakeDetector("jetbrains-pycharm")
    assert d._build_command_profiles(d._config) is None
    assert d._focused_app_class is None
    assert d._command_keymap() is None


def test_on_reuses_the_text_target_detector_for_the_focused_app():
    d, _ = _daemon(editor_profiles=True)
    d._target_detector = _FakeDetector("Code")
    reg = d._build_command_profiles(d._config)
    assert reg is not None and reg.needs_focused_app
    assert d._focused_app_class is not None
    assert d._focused_app_class() == "Code"
    assert d._profile_detector is None, "the guard's detector was reused, not duplicated"


def test_a_pinned_profile_never_looks_at_the_desktop():
    d, _ = _daemon(editor_profiles=True, profile="jetbrains")
    d._target_detector = _FakeDetector("Code")
    reg = d._build_command_profiles(d._config)
    assert reg is not None and reg.pinned == "jetbrains"
    assert d._focused_app_class is None


def test_with_the_guard_off_a_detector_is_built_for_profiles_alone(monkeypatch):
    """`target_guard = "off"` builds no detector; profiles still need the app. The one
    built here must not become `_target_detector`, whose presence turns the guard on."""
    import yazses.inject.target as target

    class _NoAtspi:
        @staticmethod
        def available():
            return False

        def start(self):  # pragma: no cover - never reached when unavailable
            raise AssertionError("must not start a tracker that is not available")

    monkeypatch.setattr(target, "AtspiFocusTracker", _NoAtspi)
    d, _ = _daemon(editor_profiles=True)
    d._target_detector = None
    d._build_command_profiles(d._config)
    assert d._target_detector is None
    assert isinstance(d._profile_detector, target.TargetDetector)
    assert d._focused_app_class == d._profile_detector.get_app_class


def test_command_keymap_records_the_profile_on_the_event():
    d, _ = _daemon(editor_profiles=True)
    d._command_profiles = load_profiles(d._config.commands)
    d._focused_app_class = lambda: "jetbrains-idea"
    event: dict = {}
    keymap = d._command_keymap(event)
    assert event["command_profile"] == "jetbrains"
    assert keymap is not None and keymap["delete_lines"] == ("ctrl+y",)


@pytest.mark.parametrize("command_mode", [True, False])
def test_a_spoken_command_in_a_jetbrains_ide_sends_its_delete_line(command_mode):
    """The end-to-end wiring: the burst's command is dispatched with the profile of
    the application focused at dispatch time, on both the command key and the shared
    dictation key."""
    d, inj = _daemon(editor_profiles=True)
    d._command_profiles = load_profiles(d._config.commands)
    d._focused_app_class = lambda: "jetbrains-pycharm-ce"

    _burst(d, "delete the last line", command_mode=command_mode)

    assert ["ctrl+y"] in inj.calls
    assert ["ctrl+shift+k"] not in inj.calls


def test_the_same_command_with_profiles_off_sends_what_it_always_did():
    d, inj = _daemon(editor_profiles=False)
    d._focused_app_class = lambda: "jetbrains-pycharm-ce"  # present, and never asked

    _burst(d, "delete the last line", command_mode=True)

    # Ctrl+Shift+K -- Cmd+Shift+K when the suite runs on macOS, a Cmd platform.
    from yazses.commands.dispatch import default_keymap

    assert default_keymap(d._platform.primary_modifier)["delete_lines"] in inj.calls
    assert ["ctrl+y"] not in inj.calls


def test_a_refused_command_in_sublime_types_nothing():
    d, inj = _daemon(editor_profiles=True)
    d._command_profiles = load_profiles(d._config.commands)
    d._focused_app_class = lambda: "sublime_text"

    _burst(d, "rename this to user_id", command_mode=True)

    assert inj.calls == []


def test_no_focused_app_falls_back_to_the_default_keys_and_says_why_once(caplog):
    """macOS, Windows and Wayland-without-AT-SPI have no source; the lookup answers ""."""
    d, _ = _daemon(editor_profiles=True)
    d._command_profiles = load_profiles(d._config.commands)
    d._focused_app_class = lambda: ""

    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        first = d._command_keymap({})
        second = d._command_keymap({})

    assert first is not None and dict(first) == {}
    assert second is not None and dict(second) == {}
    said = [r for r in caplog.records if r.getMessage() == NO_FOCUSED_APP_REASON]
    assert len(said) == 1, "the reason must be logged exactly once, not per command"


def test_a_lookup_that_raises_is_treated_as_no_app():
    d, _ = _daemon(editor_profiles=True)
    d._command_profiles = load_profiles(d._config.commands)

    def _boom() -> str:
        raise RuntimeError("AT-SPI bus went away")

    d._focused_app_class = _boom
    event: dict = {}
    keymap = d._command_keymap(event)
    assert event["command_profile"] == DEFAULT_PROFILE
    assert keymap is not None and dict(keymap) == {}
