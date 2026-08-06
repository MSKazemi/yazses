"""Structured-Markup Dictation (ADR-v2-067) + Document Find-and-Replace (ADR-v2-068) — pure cores."""
from __future__ import annotations

from yazses.findreplace.parse import ReplaceOp, apply_replace, parse_replace_command
from yazses.markup.render import parse_structure, render_markup, spoken_to_markup

# ---- structured markup -----------------------------------------------------

def test_bullet_list():
    assert spoken_to_markup("bullet list: apples; oranges; pears") == "- apples\n- oranges\n- pears"


def test_numbered_and_checklist():
    assert spoken_to_markup("numbered list: first; second") == "1. first\n2. second"
    assert spoken_to_markup("todo list: buy milk; call Sam") == "- [ ] buy milk\n- [ ] call Sam"


def test_table():
    out = spoken_to_markup("table columns Name, Age; row Alice, 30; row Bob, 25")
    assert out == (
        "| Name | Age |\n"
        "| --- | --- |\n"
        "| Alice | 30 |\n"
        "| Bob | 25 |"
    )


def test_table_short_row_padded():
    struct = parse_structure("table columns A, B, C; row x, y")
    out = render_markup(struct)
    assert out.endswith("| x | y |  |")


def test_markup_none_and_empty_items():
    assert spoken_to_markup("just some prose") is None
    assert parse_structure("bullet list:") is None


# ---- find and replace ------------------------------------------------------

def test_parse_replace_every():
    op = parse_replace_command("replace every utilise with use")
    assert op == ReplaceOp(find="utilise", replace="use", all=True, case_sensitive=False)


def test_parse_replace_first_and_synonyms():
    assert parse_replace_command("change the first foo to bar").all is False
    assert parse_replace_command("substitute cat with dog").find == "cat"
    assert parse_replace_command("swap red for blue").replace == "blue"


def test_parse_replace_case_sensitive_and_quotes():
    op = parse_replace_command('replace "API" with "api" case sensitive')
    assert op.find == "API" and op.replace == "api" and op.case_sensitive is True


def test_parse_replace_none():
    assert parse_replace_command("hello there") is None
    assert parse_replace_command("replace with use") is None
    assert parse_replace_command('replace "" with use') is None   # empty find after quote strip


def test_apply_replace():
    op = parse_replace_command("replace every cat with dog")
    assert apply_replace(op, "cat CAT cat") == "dog dog dog"       # case-insensitive, all
    first = parse_replace_command("replace the first cat with dog")
    assert apply_replace(first, "cat cat") == "dog cat"            # only first


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "markup" in slugs and "findreplace" in slugs
    assert Config().markup.enabled is False and Config().findreplace.enabled is False
