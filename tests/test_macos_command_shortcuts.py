"""Spoken commands send Cmd shortcuts on macOS, and exactly the old Ctrl ones elsewhere.

The dispatcher's keymap was Ctrl-everything on every OS. On a Mac, Ctrl is not the
application-shortcut modifier: "undo", "copy", "save" sent Ctrl+Z/C/S, which most
macOS apps ignore, and "select all" sent Ctrl+A, which in a Cocoa text field moves the
caret to the start of the line. The fix sits behind the platform seam: the macOS bundle
declares `primary_modifier = "cmd"`, and the dispatcher and the editor profiles pick
their macOS tables from it. Nothing branches on `sys.platform`.

Separately, the macOS injector looked up "Return", "BackSpace", "Left"... lower-cased
in a table keyed with capitals, so every named key fell back to keycode 0 -- the "a"
key. That is pinned here too, because the macOS keymap leans on named keys
(Shift+Cmd+Down, Option+Delete, Cmd+Left).

Nothing here has run on a real Mac; the Quartz layer is a recording stand-in.
"""
from __future__ import annotations

import dataclasses
import inspect
import sys
import types

import numpy as np
import pytest

from yazses.commands.dispatch import (
    CMD_DEFAULT_KEYMAP,
    CMD_KEYS,
    DEFAULT_KEYMAP,
    default_keymap,
    dispatch,
    primary_combo,
)
from yazses.commands.grammar import CommandIntent, IntentType
from yazses.commands.profiles import (
    BUILTIN_CMD_PROFILES,
    BUILTIN_PROFILES,
    builtin_profiles,
    load_profiles,
)
from yazses.config import CommandsConfig, Config
from yazses.platform.base import PRIMARY_MODIFIER_CMD, PRIMARY_MODIFIER_CTRL, Platform
from yazses.platform.macos.injector import MacosInjector, resolve_key_combo


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


# ---- Linux / Windows / BSD: byte-identical -----------------------------------

#: What every Ctrl platform sent before this change, written out literally. If this
#: test fails, a Linux or Windows user's spoken command now presses different keys.
_PC_KEYMAP_BEFORE: dict[str, list[str]] = {
    "undo": ["ctrl+z"],
    "undo_n": ["ctrl+z"],
    "save": ["ctrl+s"],
    "copy": ["ctrl+c"],
    "paste": ["ctrl+v"],
    "comment": ["ctrl+slash"],
    "go_to_line": ["ctrl+g"],
    "select_all": ["ctrl+a"],
    "select_to_end": ["ctrl+shift+End"],
    "delete_lines": ["ctrl+shift+k"],
    "delete_words": ["ctrl+BackSpace"],
    "cut": ["ctrl+x"],
    "press_enter": ["Return"],
    "press_tab": ["Tab"],
    "press_escape": ["Escape"],
    "press_backspace": ["BackSpace"],
    "page_up": ["Page_Up"],
    "page_down": ["Page_Down"],
    "line_home": ["Home"],
    "line_end": ["End"],
    "arrow_up": ["Up"],
    "arrow_down": ["Down"],
    "arrow_left": ["Left"],
    "arrow_right": ["Right"],
    "go_to_function": ["ctrl+shift+o"],
    "go_to_class": ["ctrl+shift+o"],
    "go_to_file": ["ctrl+p"],
    "rename_symbol": ["F2"],
    "rename_select": ["ctrl+a"],
    "select_lines": ["ctrl+l"],
}


def test_the_ctrl_keymap_is_byte_identical_to_before():
    assert DEFAULT_KEYMAP == _PC_KEYMAP_BEFORE


@pytest.mark.parametrize("primary", [PRIMARY_MODIFIER_CTRL, "", "super", "CMD "])
def test_anything_but_cmd_gets_the_unchanged_table_itself(primary):
    """The very object, not a copy: the Ctrl path cannot drift from the old table."""
    assert default_keymap(primary) is DEFAULT_KEYMAP
    assert builtin_profiles(primary) is BUILTIN_PROFILES
    assert default_keymap() is DEFAULT_KEYMAP


@pytest.mark.parametrize("action", sorted(DEFAULT_KEYMAP))
def test_dispatch_on_a_ctrl_platform_sends_what_it_sent_without_the_argument(action):
    args = {"n": "2", "name": "user_id"}
    old, new = _Injector(), _Injector()
    dispatch(_intent(action, **args), old)
    dispatch(_intent(action, **args), new, primary_modifier=PRIMARY_MODIFIER_CTRL)
    assert new.calls == old.calls


def test_a_ctrl_platform_still_gets_the_linux_windows_profiles():
    reg = load_profiles(CommandsConfig(profile="jetbrains"), PRIMARY_MODIFIER_CTRL)
    assert reg.keymap("jetbrains")["delete_lines"] == ("ctrl+y",)
    assert load_profiles(CommandsConfig()).keymaps == BUILTIN_PROFILES


def test_only_the_macos_bundle_declares_cmd():
    """The field's default is Ctrl, and only macOS overrides it -- so the Linux,
    Windows and BSD bundles inherit the value that keeps their keys unchanged."""
    import yazses.platform.bsd as bsd
    import yazses.platform.linux as linux
    import yazses.platform.macos as macos
    import yazses.platform.windows as windows

    default = {f.name: f for f in dataclasses.fields(Platform)}["primary_modifier"].default
    assert default == PRIMARY_MODIFIER_CTRL
    assert "primary_modifier=PRIMARY_MODIFIER_CMD" in inspect.getsource(macos.build_platform)
    for bundle in (linux, windows, bsd):
        assert "primary_modifier" not in inspect.getsource(bundle.build_platform), bundle


# ---- the macOS decision table ------------------------------------------------


@pytest.mark.parametrize("action,keys", [
    ("undo", ["cmd+z"]),
    ("undo_n", ["cmd+z"]),
    ("save", ["cmd+s"]),
    ("copy", ["cmd+c"]),
    ("paste", ["cmd+v"]),
    ("cut", ["cmd+x"]),
    ("select_all", ["cmd+a"]),
    ("comment", ["cmd+slash"]),
    ("select_to_end", ["cmd+shift+Down"]),
    ("line_home", ["cmd+Left"]),
    ("line_end", ["cmd+Right"]),
    ("delete_words", ["alt+BackSpace"]),
    ("delete_lines", ["cmd+shift+k"]),
    ("go_to_function", ["cmd+shift+o"]),
    ("go_to_class", ["cmd+shift+o"]),
    ("go_to_file", ["cmd+p"]),
    ("rename_select", ["cmd+a"]),
    ("select_lines", ["cmd+l"]),
    # Deliberately unchanged on a Mac.
    ("go_to_line", ["ctrl+g"]),        # VS Code and Sublime: Ctrl+G on macOS too
    ("rename_symbol", ["F2"]),
    ("press_enter", ["Return"]),
    ("page_up", ["Page_Up"]),
])
def test_the_macos_default_keymap(action, keys):
    assert default_keymap(PRIMARY_MODIFIER_CMD)[action] == keys


def test_the_macos_keymap_covers_every_action():
    assert set(CMD_DEFAULT_KEYMAP) == set(DEFAULT_KEYMAP)
    assert set(CMD_KEYS) <= set(DEFAULT_KEYMAP), "a macOS row for an action nobody has"


#: The actions whose macOS binding still holds Ctrl, each on purpose. A new Ctrl chord
#: added to the dispatcher fails here until someone decides what it is on a Mac.
_CTRL_ON_PURPOSE_ON_A_MAC = {"go_to_line"}


def test_every_ctrl_left_in_the_macos_keymap_is_a_decision():
    still_ctrl = {
        action for action, keys in CMD_DEFAULT_KEYMAP.items()
        if any("ctrl" in combo.lower().split("+")[:-1] for combo in keys)
    }
    assert still_ctrl == _CTRL_ON_PURPOSE_ON_A_MAC


def test_every_macos_key_is_expressible_by_the_macos_injector():
    tokens = {c for keys in CMD_DEFAULT_KEYMAP.values() for c in keys}
    tokens |= {
        c for profile in BUILTIN_CMD_PROFILES.values()
        for keys in profile.values() if keys is not None for c in keys
    }
    assert tokens, "found no macOS keys -- this test is looking at nothing"
    assert not sorted(t for t in tokens if resolve_key_combo(t) is None)


@pytest.mark.parametrize("intent,expected", [
    (_intent("undo"), [["cmd+z"]]),
    (_intent("undo_n", n="2"), [["cmd+z"], ["cmd+z"]]),
    (_intent("copy"), [["cmd+c"]]),
    (_intent("select_all"), [["cmd+a"]]),
    (_intent("delete_words", n="2"), [["alt+BackSpace"], ["alt+BackSpace"]]),
    (_intent("go_to_line", n="42"), [["ctrl+g"], "42", ["Return"]]),
    (_intent("rename_symbol", name="user_id"), [["F2"], ["cmd+a"], "user_id", ["Return"]]),
    (_intent("select_lines", n="2"), [["cmd+l"], ["shift+Down"]]),
])
def test_dispatch_on_a_cmd_platform(intent, expected):
    inj = _Injector()
    dispatch(intent, inj, primary_modifier=PRIMARY_MODIFIER_CMD)
    assert inj.calls == expected


def test_a_profile_keymap_is_never_translated():
    """A profile's keys are already the platform's own; the dispatcher must not
    rewrite Sublime's macOS Ctrl+Shift+K into Cmd+Shift+K."""
    keymap = load_profiles(CommandsConfig(), PRIMARY_MODIFIER_CMD).choose("sublime_text").keymap
    inj = _Injector()
    dispatch(_intent("delete_lines", n="1"), inj, keymap=keymap,
             primary_modifier=PRIMARY_MODIFIER_CMD)
    assert inj.calls == [["ctrl+shift+k"]]


# ---- editor profiles on macOS ------------------------------------------------


def test_the_macos_profiles_are_the_same_profiles():
    assert set(BUILTIN_CMD_PROFILES) == set(BUILTIN_PROFILES)


def test_every_macos_profile_decides_what_its_linux_windows_twin_overrides():
    """A PC override exists because the default is wrong for that editor; on a Mac the
    default is different, so each such action needs its own macOS decision."""
    for name, overrides in BUILTIN_PROFILES.items():
        missing = set(overrides) - set(BUILTIN_CMD_PROFILES[name])
        assert not missing, f"macOS profile {name!r} has not decided {sorted(missing)}"


def test_every_macos_profile_names_only_actions_the_dispatcher_has():
    for name, overrides in BUILTIN_CMD_PROFILES.items():
        unknown = set(overrides) - set(DEFAULT_KEYMAP)
        assert not unknown, f"macOS profile {name!r} overrides unknown actions {unknown}"


def test_a_cmd_registry_uses_the_editors_macos_keymaps():
    reg = load_profiles(CommandsConfig(), PRIMARY_MODIFIER_CMD)
    jb = reg.choose("jetbrains-pycharm").keymap
    assert jb["delete_lines"] == ("cmd+BackSpace",)
    assert jb["go_to_line"] == ("cmd+l",)
    assert jb["select_lines"] is None, "Cmd+L is Go to Line there; must refuse, not guess"
    sublime = reg.choose("sublime_text").keymap
    assert sublime["go_to_function"] == ("cmd+r",)
    assert sublime["rename_symbol"] is None


def test_a_pinned_profile_name_works_on_macos_too():
    reg = load_profiles(CommandsConfig(profile="jetbrains"), PRIMARY_MODIFIER_CMD)
    assert reg.pinned == "jetbrains" and reg.problems == []
    assert reg.choose("anything").keymap["go_to_class"] == ("cmd+o",)


def test_the_cmd_keymap_handed_out_cannot_rewrite_the_builtin_table():
    keymap = load_profiles(CommandsConfig(), PRIMARY_MODIFIER_CMD).keymap("jetbrains")
    with pytest.raises(TypeError):
        keymap["delete_lines"] = ("cmd+d",)  # type: ignore[index]
    assert BUILTIN_CMD_PROFILES["jetbrains"]["delete_lines"] == ("cmd+BackSpace",)


# ---- spreadsheet moves (the one other Ctrl sender) ---------------------------


@pytest.mark.parametrize("combo,primary,expected", [
    ("ctrl+Up", PRIMARY_MODIFIER_CMD, "cmd+Up"),
    ("ctrl+Down", PRIMARY_MODIFIER_CMD, "cmd+Down"),
    ("shift+Tab", PRIMARY_MODIFIER_CMD, "shift+Tab"),
    ("Tab", PRIMARY_MODIFIER_CMD, "Tab"),
    ("ctrl+Up", PRIMARY_MODIFIER_CTRL, "ctrl+Up"),
    ("ctrl+Up", "", "ctrl+Up"),
])
def test_primary_combo(combo, primary, expected):
    assert primary_combo(combo, primary) == expected


@pytest.mark.parametrize("primary,expected", [
    (PRIMARY_MODIFIER_CMD, [["cmd+Up"]]),
    (PRIMARY_MODIFIER_CTRL, [["ctrl+Up"]]),
])
def test_top_of_column_follows_the_platform(primary, expected):
    """Ctrl+Up on a Mac is Mission Control, not "top of column"."""
    from yazses.core.daemon import Daemon

    keys: list[list[str]] = []
    fake = types.SimpleNamespace(
        _timers=None,
        _active_injector=lambda: types.SimpleNamespace(
            inject=lambda text: None, inject_key_sequence=keys.append
        ),
        _notify_spoken=lambda message: None,
        _primary_modifier=lambda: primary,
    )
    event: dict = {}
    Daemon._run_spoken_action(
        fake, types.SimpleNamespace(action=("keys", ["ctrl+Up"]), message=None), event
    )
    assert keys == expected
    assert event["spoken_action"] == "keys"


# ---- the macOS injector ------------------------------------------------------


@pytest.mark.parametrize("combo,expected", [
    ("cmd+z", (0x06, ("cmd",))),
    ("Return", (0x24, ())),               # was keycode 0 ("a"): looked up lower-cased
    ("BackSpace", (0x33, ())),
    ("Left", (0x7B, ())),
    ("cmd+shift+Down", (0x7D, ("cmd", "shift"))),
    ("alt+BackSpace", (0x33, ("alt",))),
    ("shift+F6", (0x61, ("shift",))),
    ("cmd+F12", (0x6F, ("cmd",))),
    ("ctrl+g", (0x05, ("ctrl",))),
    ("meta+a", (0x00, ("cmd",))),
    ("super+a", (0x00, ("cmd",))),
])
def test_resolve_key_combo(combo, expected):
    assert resolve_key_combo(combo) == expected


@pytest.mark.parametrize("combo", ["", "cmd+NotAKey", "hyper+z", "Insert"])
def test_an_unknown_key_resolves_to_nothing_not_to_the_a_key(combo):
    assert resolve_key_combo(combo) is None


def test_every_linux_windows_key_name_is_known_on_macos_too():
    """The named keys the Ctrl keymap shares with macOS (Return, the arrows, Page_Up,
    F2...) must resolve, or a Mac presses nothing where it used to press "a"."""
    shared = {c for keys in DEFAULT_KEYMAP.values() for c in keys}
    assert not sorted(t for t in shared if resolve_key_combo(t) is None)


class _FakeQuartz(types.ModuleType):
    """The CoreGraphics names `MacosInjector.inject_key_sequence` touches."""

    kCGEventFlagMaskAlternate = 1 << 19
    kCGEventFlagMaskCommand = 1 << 20
    kCGEventFlagMaskControl = 1 << 18
    kCGEventFlagMaskShift = 1 << 17
    kCGHIDEventTap = "hid-tap"

    def __init__(self) -> None:
        super().__init__("Quartz")
        self.posted: list[tuple[int, bool, int]] = []

    def CGEventCreateKeyboardEvent(self, source, keycode, is_down):  # noqa: N802
        return {"keycode": keycode, "down": is_down, "flags": 0}

    def CGEventSetFlags(self, event, flags):  # noqa: N802
        event["flags"] = flags

    def CGEventPost(self, tap, event):  # noqa: N802
        self.posted.append((event["keycode"], event["down"], event["flags"]))


@pytest.fixture
def quartz(monkeypatch):
    fake = _FakeQuartz()
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    return fake


def test_cmd_z_posts_z_with_the_command_flag(quartz):
    MacosInjector().inject_key_sequence(["cmd+z"])
    cmd = _FakeQuartz.kCGEventFlagMaskCommand
    assert quartz.posted == [(0x06, True, cmd), (0x06, False, cmd)]


def test_an_unknown_key_posts_nothing(quartz):
    MacosInjector().inject_key_sequence(["cmd+NotAKey", "Return"])
    assert quartz.posted == [(0x24, True, 0), (0x24, False, 0)]


# ---- the daemon on a macOS-platform fake -------------------------------------


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


def _daemon(primary: str, *, editor_profiles: bool = False, profile: str = "auto"):
    """A daemon on this host's real platform bundle with only the modifier swapped --
    the macOS bundle itself cannot be built off a Mac."""
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = True
    cfg.commands.editor_profiles = editor_profiles
    cfg.commands.profile = profile
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    platform = dataclasses.replace(get_platform(), primary_modifier=primary)
    d = Daemon(config=cfg, platform=platform)
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    d._state.target_ok = True
    return d, inj


@pytest.mark.parametrize("primary,expected", [
    (PRIMARY_MODIFIER_CMD, ["cmd+z"]),
    (PRIMARY_MODIFIER_CTRL, ["ctrl+z"]),
])
def test_spoken_undo_follows_the_platform(primary, expected):
    d, inj = _daemon(primary)
    d._command_mode = True
    d._engine.text = "undo"
    d._on_hold_end()
    assert expected in inj.calls
    assert inj.calls.count(expected) == 1


def test_the_daemon_builds_a_macos_profile_registry_on_a_cmd_platform():
    d, _ = _daemon(PRIMARY_MODIFIER_CMD, editor_profiles=True, profile="jetbrains")
    reg = d._build_command_profiles(d._config)
    assert reg is not None
    assert reg.keymap("jetbrains")["delete_lines"] == ("cmd+BackSpace",)


def test_a_stand_in_platform_without_the_field_is_a_ctrl_platform():
    from yazses.core.daemon import Daemon

    rig = Daemon.__new__(Daemon)
    assert rig._primary_modifier() == PRIMARY_MODIFIER_CTRL
    rig._platform = types.SimpleNamespace()
    assert rig._primary_modifier() == PRIMARY_MODIFIER_CTRL
