"""Tests for Say-Macro — user-programmable voice macro expansion.

Spec: design/specs/say-macro.md. All offline, no models/audio/desktop.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from yazses.commands.dispatch import dispatch
from yazses.commands.grammar import CommandIntent, IntentType, classify
from yazses.commands.macros import (
    Macro,
    MacroContext,
    MacroTable,
    build_macro_table,
    expand,
    load_macros,
    normalize,
)
from yazses.config import load_config

# --- normalize -------------------------------------------------------------

def test_normalize_lowercases_collapses_ws_and_strips_trailing_punct():
    assert normalize("  Save   File.  ") == "save file"
    assert normalize("License Header!") == "license header"
    assert normalize("try   except") == "try except"


# --- MacroTable.match ------------------------------------------------------

def _table(*macros: Macro) -> MacroTable:
    return MacroTable({m.trigger: m for m in macros})


def test_match_exact_whole_utterance_returns_macro():
    m = Macro(trigger="license header", type="text", template="X")
    table = _table(m)
    assert table.match("license header") is m
    assert table.match("License Header.") is m  # normalized


def test_match_trigger_inside_sentence_returns_none():
    m = Macro(trigger="license header", type="text", template="X")
    table = _table(m)
    assert table.match("add the license header here") is None


# --- expand ----------------------------------------------------------------

def test_expand_text_resolves_fixed_placeholders():
    m = Macro(trigger="hdr", type="text",
              template="(c) ${date} ${author} ${time} ${clipboard}")
    ctx = MacroContext(clipboard="CB", date="2026-06-14", time="09:30", author="Mo")
    text, offset = expand(m, ctx)
    assert text == "(c) 2026-06-14 Mo 09:30 CB"
    assert offset == 0


def test_expand_leaves_unknown_token_literal():
    m = Macro(trigger="x", type="text", template="a ${nope} b")
    text, offset = expand(m, MacroContext())
    assert text == "a ${nope} b"
    assert offset == 0


def test_expand_snippet_cursor_marks_caret_offset():
    m = Macro(trigger="te", type="snippet",
              template="try:\n    ${cursor}\nexcept Exception:\n    raise")
    text, offset = expand(m, MacroContext())
    assert "${cursor}" not in text
    assert text == "try:\n    \nexcept Exception:\n    raise"
    # caret must land where ${cursor} was: count chars after the marker
    assert offset == len("\nexcept Exception:\n    raise")


def test_expand_snippet_without_cursor_has_zero_offset():
    m = Macro(trigger="p", type="snippet", template="print()")
    text, offset = expand(m, MacroContext())
    assert text == "print()"
    assert offset == 0


# --- load_macros -----------------------------------------------------------

def test_load_macros_missing_file_is_empty(tmp_path):
    table = load_macros(tmp_path / "nope.toml")
    assert len(table) == 0


def test_load_macros_parses_text_and_snippet(tmp_path):
    p = tmp_path / "macros.toml"
    p.write_text(
        '[[macro]]\ntrigger = "license header"\ntype = "text"\ntext = "HEADER"\n\n'
        '[[macro]]\ntrigger = "try except"\ntype = "snippet"\n'
        'snippet = "try:\\n    ${cursor}\\nexcept:\\n    raise"\n'
    )
    table = load_macros(p)
    assert len(table) == 2
    assert table.match("license header").template == "HEADER"
    assert table.match("try except").type == "snippet"


def test_load_macros_rejects_duplicate_trigger_first_wins(tmp_path):
    p = tmp_path / "macros.toml"
    p.write_text(
        '[[macro]]\ntrigger = "dup"\ntype = "text"\ntext = "FIRST"\n\n'
        '[[macro]]\ntrigger = "Dup."\ntype = "text"\ntext = "SECOND"\n'
    )
    table = load_macros(p)
    assert len(table) == 1
    assert table.match("dup").template == "FIRST"


def test_load_macros_skips_invalid_entry_without_raising(tmp_path):
    p = tmp_path / "macros.toml"
    p.write_text(
        '[[macro]]\ntype = "text"\ntext = "no trigger"\n\n'        # missing trigger
        '[[macro]]\ntrigger = "bad"\ntype = "wat"\ntext = "x"\n\n'  # bad type
        '[[macro]]\ntrigger = "good"\ntype = "text"\ntext = "OK"\n'
    )
    table = load_macros(p)
    assert len(table) == 1
    assert table.match("good").template == "OK"


def test_load_macros_unparseable_file_returns_empty(tmp_path):
    p = tmp_path / "macros.toml"
    p.write_text("this is = = not valid toml [[[")
    table = load_macros(p)
    assert len(table) == 0


def test_load_macros_none_path_is_empty():
    assert len(load_macros(None)) == 0


def test_load_macros_skips_punctuation_only_trigger(tmp_path):
    p = tmp_path / "macros.toml"
    p.write_text('[[macro]]\ntrigger = "..."\ntype = "text"\ntext = "x"\n')
    assert len(load_macros(p)) == 0


def test_load_macros_parses_actions_macro_dormant(tmp_path):
    p = tmp_path / "macros.toml"
    p.write_text(
        '[[macro]]\ntrigger = "run my tests"\ntype = "actions"\n'
        'actions = [ { key = "ctrl+grave" }, { text = "pytest" }, { key = "Return" } ]\n'
    )
    table = load_macros(p)
    macro = table.match("run my tests")
    assert macro.type == "actions"
    assert macro.actions == (("key", "ctrl+grave"), ("text", "pytest"), ("key", "Return"))


# --- build_macro_table -----------------------------------------------------

def test_build_macro_table_dormant_when_disabled(tmp_path):
    cfg = load_config()  # defaults: macros.enabled is False
    assert build_macro_table(cfg, tmp_path) is None


def test_build_macro_table_loads_when_enabled(tmp_path):
    (tmp_path / "macros.toml").write_text(
        '[[macro]]\ntrigger = "hi"\ntype = "text"\ntext = "hello"\n'
    )
    cfg = load_config()
    cfg.macros.enabled = True
    table = build_macro_table(cfg, tmp_path)
    assert table is not None and len(table) == 1


# --- classify integration --------------------------------------------------

def test_classify_dormant_when_table_none_is_unchanged():
    # Regression: existing behavior when no macro table is passed.
    assert classify("save").intent is IntentType.EDIT
    assert classify("hello world").intent is IntentType.DICTATE


def test_classify_macro_match_returns_macro_intent():
    table = _table(Macro(trigger="license header", type="text", template="H"))
    intent = classify("license header", macro_table=table)
    assert intent.intent is IntentType.MACRO
    assert intent.args["trigger"] == "license header"


def test_classify_macro_precedes_regex_grammar():
    # "save" is a built-in EDIT command; a macro of the same trigger wins.
    table = _table(Macro(trigger="save", type="text", template="SAVED"))
    intent = classify("save", macro_table=table)
    assert intent.intent is IntentType.MACRO


def test_classify_non_macro_falls_through_to_regex():
    table = _table(Macro(trigger="license header", type="text", template="H"))
    assert classify("save", macro_table=table).intent is IntentType.EDIT
    assert classify("just dictating", macro_table=table).intent is IntentType.DICTATE


# --- dispatch integration --------------------------------------------------

def _macro_intent(trigger: str) -> CommandIntent:
    return CommandIntent(intent=IntentType.MACRO, action="expand",
                         args={"trigger": trigger}, raw_text=trigger)


def test_dispatch_macro_injects_resolved_text():
    inj = MagicMock()
    table = _table(Macro(trigger="hdr", type="text", template="(c) ${author}"))
    ctx = MacroContext(author="Mo")
    dispatch(_macro_intent("hdr"), inj, macro_table=table, macro_context=ctx)
    inj.inject.assert_called_once_with("(c) Mo")
    inj.inject_key_sequence.assert_not_called()


def test_dispatch_snippet_moves_caret_left_by_offset():
    inj = MagicMock()
    table = _table(Macro(trigger="te", type="snippet", template="a${cursor}bc"))
    dispatch(_macro_intent("te"), inj, macro_table=table, macro_context=MacroContext())
    inj.inject.assert_called_once_with("abc")
    inj.inject_key_sequence.assert_called_once_with(["Left", "Left"])  # 2 chars after cursor


def test_dispatch_actions_macro_is_noop_in_p1():
    inj = MagicMock()
    table = _table(Macro(trigger="rt", type="actions", template="",
                         actions=(("key", "Return"),)))
    dispatch(_macro_intent("rt"), inj, macro_table=table, macro_context=MacroContext())
    inj.inject.assert_not_called()
    inj.inject_key_sequence.assert_not_called()


def test_dispatch_unknown_trigger_falls_back_to_raw_text():
    inj = MagicMock()
    table = _table(Macro(trigger="known", type="text", template="X"))
    dispatch(_macro_intent("missing"), inj, macro_table=table, macro_context=MacroContext())
    inj.inject.assert_called_once_with("missing")  # raw_text fallback


# --- config ----------------------------------------------------------------

def test_config_macros_defaults_off():
    cfg = load_config()
    assert cfg.macros.enabled is False
    assert cfg.macros.path == "macros.toml"
    assert cfg.macros.author == ""


def test_config_loads_macros_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[macros]\nenabled = true\nauthor = "Mo"\npath = "m.toml"\n')
    cfg = load_config(p)
    assert cfg.macros.enabled is True
    assert cfg.macros.author == "Mo"
    assert cfg.macros.path == "m.toml"
