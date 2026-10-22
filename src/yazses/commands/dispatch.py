"""Command dispatcher — routes CommandIntent to key sequences or text injection."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from yazses.commands.grammar import CommandIntent, IntentType
from yazses.commands.macros import MacroContext, expand
from yazses.platform.base import PRIMARY_MODIFIER_CMD, PRIMARY_MODIFIER_CTRL, InjectorBackend

log = logging.getLogger(__name__)

# Maps action names to key sequences (list of combo strings).
# {n} and {name} are placeholder markers; dispatcher substitutes from args.
ACTION_KEYS: dict[str, list[str]] = {
    "undo":          ["ctrl+z"],
    "undo_n":        ["ctrl+z"],        # repeated N times by dispatcher
    "save":          ["ctrl+s"],
    "copy":          ["ctrl+c"],
    "paste":         ["ctrl+v"],
    "comment":       ["ctrl+slash"],
    "go_to_line":    ["ctrl+g"],        # dispatcher then types the line number + Return
    "select_all":    ["ctrl+a"],
    "select_to_end": ["ctrl+shift+End"],
    "delete_lines":  [],                # dispatcher uses backspace
    "delete_words":  [],                # dispatcher uses ctrl+BackSpace
    # Basic keystrokes.
    "cut":             ["ctrl+x"],
    "press_enter":     ["Return"],
    "press_tab":       ["Tab"],
    "press_escape":    ["Escape"],
    "press_backspace": ["BackSpace"],
    "page_up":         ["Page_Up"],
    "page_down":       ["Page_Down"],
    "line_home":       ["Home"],
    "line_end":        ["End"],
    "arrow_up":        ["Up"],
    "arrow_down":      ["Down"],
    "arrow_left":      ["Left"],
    "arrow_right":     ["Right"],
}

# The keys that OPEN each structured action. The rest of the action -- typing a line
# number or a name, pressing Return, repeating N times -- is the same in every editor;
# this part is not, which is why it is a table an editor profile can override
# (commands/profiles.py) rather than a literal in `_execute` below.
LEAD_KEYS: dict[str, list[str]] = {
    "delete_words":   ["ctrl+BackSpace"],   # sent once per word
    # VS Code / Sublime "delete line"; a JetBrains IDE binds it to ctrl+y.
    "delete_lines":   ["ctrl+shift+k"],     # sent once per line
    "undo_n":         ["ctrl+z"],           # sent once per step
    "go_to_line":     ["ctrl+g"],           # then the number, then Return
    "go_to_function": ["ctrl+shift+o"],     # then the name
    "go_to_class":    ["ctrl+shift+o"],     # then the name
    "go_to_file":     ["ctrl+p"],           # then the name
    "rename_symbol":  ["F2"],               # then rename_select, the name, Return
    "rename_select":  ["ctrl+a"],           # select the old name in the rename box
    "select_lines":   ["ctrl+l"],           # then shift+Down for each further line
}

#: Every action's default keys: what a command sends when no profile overrides it.
#: This is the Linux / Windows / BSD keymap -- a platform whose primary shortcut
#: modifier is Ctrl -- and it is sent exactly as written there.
DEFAULT_KEYMAP: dict[str, list[str]] = {**ACTION_KEYS, **LEAD_KEYS}

# macOS: where the default keymap says something else on a Cmd platform. The tables
# above are Ctrl-everything, and on a Mac Ctrl is not the shortcut modifier: Ctrl+Z,
# Ctrl+C and Ctrl+S do nothing in most apps, and Ctrl+A in a Cocoa text field moves
# the caret to the start of the line rather than selecting anything. Each row is a
# decision, not a blanket Ctrl->Cmd swap -- some Ctrl chords really are Ctrl on a Mac
# (VS Code's and Sublime's Go to Line is Ctrl+G there too), and the word-wise modifier
# is Option, not Cmd. An action not named here sends the same keys on every platform.
# Sources: Apple's "Mac keyboard shortcuts" (document and text editing) and VS Code's
# macOS default keybindings, the keymap DEFAULT_KEYMAP already follows elsewhere.
# None of these has been injected into a running Mac app yet.
CMD_KEYS: dict[str, list[str]] = {
    "undo":           ["cmd+z"],
    "undo_n":         ["cmd+z"],          # sent once per step
    "save":           ["cmd+s"],
    "copy":           ["cmd+c"],
    "paste":          ["cmd+v"],
    "cut":            ["cmd+x"],
    "select_all":     ["cmd+a"],
    "comment":        ["cmd+slash"],
    # Shift+Cmd+Down is "select to end of document" in Cocoa text and in VS Code; a
    # Mac's End key scrolls without moving the caret, and most Mac keyboards lack one.
    "select_to_end":  ["cmd+shift+Down"],
    # Cmd+Left / Cmd+Right are the Mac's line start / line end; Home and End scroll.
    "line_home":      ["cmd+Left"],
    "line_end":       ["cmd+Right"],
    # Option is the Mac's word modifier: Option+Delete deletes the previous word.
    "delete_words":   ["alt+BackSpace"],  # sent once per word
    "delete_lines":   ["cmd+shift+k"],    # VS Code; sent once per line
    "go_to_function": ["cmd+shift+o"],
    "go_to_class":    ["cmd+shift+o"],
    "go_to_file":     ["cmd+p"],
    "rename_select":  ["cmd+a"],
    "select_lines":   ["cmd+l"],
    # Kept as Ctrl on purpose: "go_to_line" is Ctrl+G in VS Code and Sublime on macOS.
}

#: The default keymap on a Cmd platform (macOS).
CMD_DEFAULT_KEYMAP: dict[str, list[str]] = {**DEFAULT_KEYMAP, **CMD_KEYS}


def default_keymap(primary_modifier: str = PRIMARY_MODIFIER_CTRL) -> dict[str, list[str]]:
    """The default keymap for a platform whose shortcut modifier is ``primary_modifier``.

    Anything but Cmd gets `DEFAULT_KEYMAP` itself -- the very object, so the keys Linux,
    Windows and the BSDs send cannot drift from the table they always sent. Pure.
    """
    if primary_modifier == PRIMARY_MODIFIER_CMD:
        return CMD_DEFAULT_KEYMAP
    return DEFAULT_KEYMAP


def primary_combo(combo: str, primary_modifier: str = PRIMARY_MODIFIER_CTRL) -> str:
    """``combo`` with its ``ctrl`` modifier read as the platform's primary modifier.

    For a key list in which every Ctrl *is* the shortcut modifier -- the spoken
    spreadsheet moves ("top of column" is Ctrl+Up on a PC and Cmd+Up on a Mac, where
    Ctrl+Up opens Mission Control). Not for the command keymap above, where some Ctrl
    chords stay Ctrl on a Mac. Unchanged on anything but a Cmd platform. Pure.
    """
    if primary_modifier != PRIMARY_MODIFIER_CMD:
        return combo
    parts = combo.split("+")
    if len(parts) < 2:
        return combo
    mods = [PRIMARY_MODIFIER_CMD if m.lower() in ("ctrl", "control") else m
            for m in parts[:-1]]
    return "+".join([*mods, parts[-1]])


class CommandRefused(Exception):
    """The active editor profile has no safe binding for this action.

    Raised before any key is sent, so a refused command leaves the window untouched.
    """


def _keys(action: str, keymap: Mapping[str, Sequence[str] | None] | None,
          defaults: Mapping[str, list[str]] = DEFAULT_KEYMAP) -> list[str] | None:
    """The keys for ``action``: the profile's override if it has one, else the default.

    ``defaults`` is the platform's default keymap (`default_keymap`).
    ``None`` for an action no table names (the caller's "unknown action" path).
    Raises `CommandRefused` when the profile maps the action to ``None``.
    """
    if keymap is not None and action in keymap:
        override = keymap[action]
        if override is None:
            raise CommandRefused(action)
        return list(override)
    default = defaults.get(action)
    return None if default is None else list(default)


def _send(injector: InjectorBackend, keys: list[str] | None) -> None:
    """Send ``keys`` unless there are none -- a profile may bind a step to nothing."""
    if keys:
        injector.inject_key_sequence(keys)


def dispatch(intent: CommandIntent, injector: InjectorBackend, notify_fn=None,
             macro_table=None, macro_context=None,
             keymap: Mapping[str, Sequence[str] | None] | None = None,
             primary_modifier: str = PRIMARY_MODIFIER_CTRL) -> None:
    """Execute a CommandIntent via the injector.

    For DICTATE, calls injector.inject(raw_text).
    For MACRO, expands the matched macro (via macro_table/macro_context) and injects.
    For all others, dispatches key sequences or shell commands.
    notify_fn(event_name, data) is called if provided (for IPC notifications).

    ``keymap`` is the focused editor's profile (commands/profiles.py): per-action
    overrides of `DEFAULT_KEYMAP`, where ``None`` refuses the action. ``None`` -- the
    default, and all a daemon with `[commands] editor_profiles` off ever passes --
    sends the default keys exactly as before profiles existed.

    ``primary_modifier`` is the platform's (`Platform.primary_modifier`): ``"cmd"``
    picks the macOS default keymap (`CMD_KEYS`); the default, ``"ctrl"``, sends
    `DEFAULT_KEYMAP` unchanged. A profile's ``keymap`` is already the platform's own
    (`commands/profiles.py` builds a Cmd registry on macOS), so it is not translated.
    """
    try:
        _execute(intent, injector, macro_table, macro_context, keymap,
                 default_keymap(primary_modifier))
        if notify_fn and intent.intent != IntentType.DICTATE:
            notify_fn("command_dispatched", {
                "intent": intent.intent.value,
                "action": intent.action,
                "args": intent.args,
            })
    except CommandRefused:
        # Deliberately NOT the raw-text fallback below: the phrase was understood as a
        # command, and typing "rename this to user_id" into the editor is no better
        # than the keys the profile just refused to send.
        log.info("The focused editor's command profile has no binding for %r; "
                 "nothing was sent.", intent.action)
    except Exception as exc:
        log.error("dispatch failed for action %r: %s", intent.action, exc)
        # Fall back to raw text injection on error
        injector.inject(intent.raw_text)


def _execute(intent: CommandIntent, injector: InjectorBackend,
             macro_table=None, macro_context=None,
             keymap: Mapping[str, Sequence[str] | None] | None = None,
             defaults: Mapping[str, list[str]] = DEFAULT_KEYMAP) -> None:
    if intent.intent == IntentType.DICTATE:
        injector.inject(intent.raw_text)
        return

    if intent.intent == IntentType.MACRO:
        _execute_macro(intent, injector, macro_table, macro_context)
        return

    action = intent.action
    args = intent.args
    # Both resolved before anything is sent, so a refused step (CommandRefused) can
    # never leave half an action behind -- rename's selection step included.
    keys = _keys(action, keymap, defaults)
    select = _keys("rename_select", keymap, defaults) if action == "rename_symbol" else None

    if action == "delete_words":
        n = int(args.get("n", "1"))
        # ctrl+BackSpace (Option+Delete on a Mac) deletes one word at a time
        for _ in range(n):
            _send(injector, keys)
        return

    if action == "delete_lines":
        n = int(args.get("n", "1"))
        for _ in range(n):
            # ctrl+shift+k by default (VS Code, Sublime). An editor that binds
            # "delete line" elsewhere overrides it in commands/profiles.py.
            _send(injector, keys)
        return

    if action == "undo_n":
        n = int(args.get("n", "1"))
        for _ in range(n):
            _send(injector, keys)
        return

    if action == "go_to_line":
        _send(injector, keys)
        injector.inject(args.get("n", ""))
        injector.inject_key_sequence(["Return"])
        return

    if action in ("go_to_function", "go_to_class", "go_to_file"):
        _send(injector, keys)
        injector.inject(args.get("name", ""))
        return

    if action == "rename_symbol":
        _send(injector, keys)
        name = args.get("name", "")
        if name:
            _send(injector, select)
            injector.inject(name)
            injector.inject_key_sequence(["Return"])
        return

    if action in ("new_function", "new_class", "new_file"):
        # Insert a skeleton — for now just inject the name
        injector.inject(args.get("name", ""))
        return

    if action in ("run_tests", "run_build", "run_last", "run_command"):
        _run_terminal(action, args, injector)
        return

    if action == "select_lines":
        n = int(args.get("n", "1"))
        _send(injector, keys)
        for _ in range(n - 1):
            injector.inject_key_sequence(["shift+Down"])
        return

    if keys is not None:
        injector.inject_key_sequence(keys)
        return

    # Unknown action — fall back to raw text
    log.warning("No dispatch rule for action %r, injecting raw text", action)
    injector.inject(intent.raw_text)


def _execute_macro(intent: CommandIntent, injector: InjectorBackend,
                   macro_table, macro_context) -> None:
    trigger = intent.args.get("trigger", "")
    macro = macro_table.get(trigger) if macro_table is not None else None
    if macro is None:
        # Table missing or trigger gone — fall back to raw text.
        injector.inject(intent.raw_text)
        return
    if macro.type == "actions":
        # P1: OS/app action chains are parsed but dormant (land in P2).
        log.info("macro %r is an action chain — deferred to P2, not firing", trigger)
        return
    text, cursor_offset = expand(macro, macro_context or MacroContext())
    injector.inject(text)
    if cursor_offset > 0:
        injector.inject_key_sequence(["Left"] * cursor_offset)


def _run_terminal(action: str, args: dict[str, str], injector: InjectorBackend) -> None:
    cmd_map = {
        "run_tests": "pytest",
        "run_build": "make build",
        "run_last": "",
    }
    if action == "run_command":
        cmd = args.get("cmd", "")
    else:
        cmd = cmd_map.get(action, "")
    if cmd:
        injector.inject(cmd)
        injector.inject_key_sequence(["Return"])
    elif action == "run_last":
        injector.inject_key_sequence(["Up", "Return"])
