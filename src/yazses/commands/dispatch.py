"""Command dispatcher — routes CommandIntent to key sequences or text injection."""
from __future__ import annotations

import logging

from yazses.commands.grammar import CommandIntent, IntentType
from yazses.commands.macros import MacroContext, expand
from yazses.platform.base import InjectorBackend

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


def dispatch(intent: CommandIntent, injector: InjectorBackend, notify_fn=None,
             macro_table=None, macro_context=None) -> None:
    """Execute a CommandIntent via the injector.

    For DICTATE, calls injector.inject(raw_text).
    For MACRO, expands the matched macro (via macro_table/macro_context) and injects.
    For all others, dispatches key sequences or shell commands.
    notify_fn(event_name, data) is called if provided (for IPC notifications).
    """
    try:
        _execute(intent, injector, macro_table, macro_context)
        if notify_fn and intent.intent != IntentType.DICTATE:
            notify_fn("command_dispatched", {
                "intent": intent.intent.value,
                "action": intent.action,
                "args": intent.args,
            })
    except Exception as exc:
        log.error("dispatch failed for action %r: %s", intent.action, exc)
        # Fall back to raw text injection on error
        injector.inject(intent.raw_text)


def _execute(intent: CommandIntent, injector: InjectorBackend,
             macro_table=None, macro_context=None) -> None:
    if intent.intent == IntentType.DICTATE:
        injector.inject(intent.raw_text)
        return

    if intent.intent == IntentType.MACRO:
        _execute_macro(intent, injector, macro_table, macro_context)
        return

    action = intent.action
    args = intent.args
    keys = ACTION_KEYS.get(action)

    if action == "delete_words":
        n = int(args.get("n", "1"))
        # ctrl+BackSpace deletes one word at a time
        for _ in range(n):
            injector.inject_key_sequence(["ctrl+BackSpace"])
        return

    if action == "delete_lines":
        n = int(args.get("n", "1"))
        for _ in range(n):
            # ctrl+shift+k is the VS Code / JetBrains "delete line" binding. A
            # per-editor alternative (e.g. ctrl+d in Sublime) belongs in
            # commands/profiles.py, not in a dead conditional here.
            injector.inject_key_sequence(["ctrl+shift+k"])
        return

    if action == "undo_n":
        n = int(args.get("n", "1"))
        for _ in range(n):
            injector.inject_key_sequence(["ctrl+z"])
        return

    if action == "go_to_line":
        injector.inject_key_sequence(["ctrl+g"])
        injector.inject(args.get("n", ""))
        injector.inject_key_sequence(["Return"])
        return

    if action == "go_to_function":
        injector.inject_key_sequence(["ctrl+shift+o"])
        injector.inject(args.get("name", ""))
        return

    if action == "go_to_class":
        injector.inject_key_sequence(["ctrl+shift+o"])
        injector.inject(args.get("name", ""))
        return

    if action == "go_to_file":
        injector.inject_key_sequence(["ctrl+p"])
        injector.inject(args.get("name", ""))
        return

    if action == "rename_symbol":
        injector.inject_key_sequence(["F2"])
        name = args.get("name", "")
        if name:
            injector.inject_key_sequence(["ctrl+a"])
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
        injector.inject_key_sequence(["ctrl+l"])
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
